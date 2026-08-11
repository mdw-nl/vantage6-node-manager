"""Integration tests for actions_bp (start/stop/restart, single + bulk): the
Docker-container lifecycle that is this app's core feature. Runs through the
real Flask routes with a mocked `docker` client (no real Docker daemon
needed) so the volume/environment/image-selection logic that node_actions.py
builds is actually exercised, instead of only proving a permission redirect
fires (which every route does identically whether Docker is reachable or not).

`container_path_to_host_path` is patched to identity here rather than
exercised for real - the test tmpdir doesn't live under any of its three
recognized mount prefixes, so with the real function every route would bail
out early with "Cannot mount config directory" before ever reaching
`containers.run`. Its own translation logic is covered separately in
test_docker_utils.py.
"""
from unittest.mock import MagicMock, patch

import docker.errors

from tests.conftest import create_node


def _fake_client(container_get_effect=None):
    """A MagicMock docker client: containers.get() raises NotFound by default
    (fresh container). Volumes are tracked in a dict so behavior matches a
    real daemon - volumes.get() raises NotFound only until volumes.create()
    has been called for that name, since bulk_start_nodes() (unlike
    start_node()) re-fetches each volume by name via volumes.get() right
    after creating it rather than keeping the object returned by create().
    Created volumes carry a real .name (MagicMock's `name` constructor kwarg
    does NOT set the attribute - it names the mock itself)."""
    client = MagicMock()
    client.containers.get.side_effect = (
        container_get_effect if container_get_effect is not None
        else docker.errors.NotFound('no such container')
    )

    volumes = {}

    def _get_volume(name):
        if name not in volumes:
            raise docker.errors.NotFound('no such volume')
        return volumes[name]

    def _create_volume(name):
        vol = MagicMock()
        vol.name = name
        volumes[name] = vol
        return vol

    client.volumes.get.side_effect = _get_volume
    client.volumes.create.side_effect = _create_volume
    return client


def _apply(patches):
    """Apply a {target: value} dict of mock.patch() targets as one context manager."""
    from contextlib import ExitStack
    stack = ExitStack()
    for target, value in patches.items():
        stack.enter_context(patch(target, value))
    return stack


def _docker_patches(client, **extra):
    """The base patch set every actions_bp test needs.

    `get_docker_client` is imported separately into four modules
    (node_actions, docker_utils itself, nodes, server_api) via `from
    nodemanager.docker_utils import get_docker_client` - each is its own
    binding, resolved from that module's own globals at call time, so
    patching one has no effect on the others. All four must be patched
    together, or whichever one is missed falls through to the real,
    unmocked docker.from_env():
    - docker_utils: get_node_status()/get_running_nodes() (used by
      bulk_start_nodes()'s "already running" pre-check).
    - nodes: view_node()'s container_info block, reached whenever a test
      follows the post-action redirect there.
    - server_api: get_running_tasks()/get_node_health_status(), also reached
      via that same redirect.
    """
    patches = {
        'nodemanager.node_actions.get_docker_client': MagicMock(return_value=client),
        'nodemanager.docker_utils.get_docker_client': MagicMock(return_value=client),
        'nodemanager.nodes.get_docker_client': MagicMock(return_value=client),
        'nodemanager.server_api.get_docker_client': MagicMock(return_value=client),
        'nodemanager.node_actions.container_path_to_host_path': lambda p: p,
    }
    patches.update(extra)
    return patches


def _run_image(client):
    """The image `containers.run()` was called with - passed positionally by
    start_node()/bulk_start_nodes() rather than as a kwarg."""
    args, kwargs = client.containers.run.call_args
    return args[0] if args else kwargs.get('image')


# --- start_node: fresh container, explicit image, no encryption ---

def test_start_fresh_node_builds_expected_container(operator_client):
    create_node(operator_client, 'fresh-node', server_url='https://example.com')
    client = _fake_client()

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/fresh-node/start',
                                     data={'image': 'harbor2.vantage6.ai/infrastructure/node:4.7.0'})
    assert resp.status_code == 302

    client.containers.run.assert_called_once()
    assert _run_image(client) == 'harbor2.vantage6.ai/infrastructure/node:4.7.0'
    _, kwargs = client.containers.run.call_args
    assert kwargs['name'] == 'vantage6-fresh-node-user'
    assert '--name fresh-node' in kwargs['command']
    assert '--dockerized --user' in kwargs['command']
    assert kwargs['labels']['name'] == 'fresh-node'
    assert kwargs['extra_hosts'] == {"host.docker.internal": "host-gateway"}

    volumes = kwargs['volumes']
    assert any(v.endswith(':/mnt/data') for v in volumes)
    assert any(v.endswith(':/mnt/vpn') for v in volumes)
    assert any(v.endswith(':/mnt/ssh') for v in volumes)
    assert any(v.endswith(':/mnt/squid') for v in volumes)
    assert any(v.endswith(':/mnt/config') for v in volumes)
    assert '/var/run/docker.sock:/var/run/docker.sock' in volumes
    # No encryption configured - no private key mount, no PRIVATE_KEY env.
    assert not any('private_key.pem' in v for v in volumes)
    assert 'PRIVATE_KEY' not in kwargs['environment']

    # DB config from create_node()'s defaults (label "default", csv db, /tmp/test.csv).
    assert kwargs['environment'].get('DEFAULT_DATABASE_URI') == 'default.csv'


def test_start_node_with_encryption_mounts_private_key(operator_client):
    create_node(operator_client, 'crypto-node', server_url='https://example.com', **{
        'encryption_enabled': 'on',
        'key_source': 'generate',
        'generated_private_key': '-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----',
    })
    client = _fake_client()

    with _apply(_docker_patches(client)):
        operator_client.post('/nodes/crypto-node/start', data={'image': 'some/image:tag'})

    _, kwargs = client.containers.run.call_args
    assert any(v.endswith(':/mnt/private_key.pem') for v in kwargs['volumes'])
    assert kwargs['environment']['PRIVATE_KEY'] == '/mnt/private_key.pem'


def test_start_already_running_node_does_not_recreate_container(operator_client):
    create_node(operator_client, 'already-running')
    running = MagicMock(status='running')
    client = _fake_client(container_get_effect=lambda name: running)

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/already-running/start', follow_redirects=True)

    assert b'already running' in resp.data.lower()
    client.containers.run.assert_not_called()
    running.remove.assert_not_called()


def test_start_reuses_previous_image_and_removes_stopped_container(operator_client):
    create_node(operator_client, 'stopped-node')
    stopped = MagicMock(status='exited')
    stopped.image.tags = ['harbor2.vantage6.ai/infrastructure/node:4.6.0']
    client = _fake_client(container_get_effect=lambda name: stopped)

    with _apply(_docker_patches(client)):
        # No image supplied - must fall back to the stopped container's own image,
        # not go through server-version detection at all.
        operator_client.post('/nodes/stopped-node/start')

    stopped.remove.assert_called_once()
    assert _run_image(client) == 'harbor2.vantage6.ai/infrastructure/node:4.6.0'


def test_start_with_no_image_and_no_history_falls_back_through_version_chain(operator_client):
    create_node(operator_client, 'no-image-node', server_url='https://example.com')
    client = _fake_client()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': MagicMock(return_value=('4.9.0', None)),
        'nodemanager.node_actions.find_local_node_image': MagicMock(return_value=None),
    })):
        operator_client.post('/nodes/no-image-node/start')

    assert _run_image(client) == 'harbor2.vantage6.ai/infrastructure/node:4.9.0'


def test_start_falls_back_to_latest_when_server_unreachable(operator_client):
    create_node(operator_client, 'unreachable-node', server_url='https://example.com')
    client = _fake_client()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': MagicMock(return_value=(None, 'Could not connect to server')),
        'nodemanager.node_actions.find_local_node_image': MagicMock(return_value=None),
    })):
        resp = operator_client.post('/nodes/unreachable-node/start', follow_redirects=True)

    assert _run_image(client) == 'harbor2.vantage6.ai/infrastructure/node:latest'
    assert b'could not detect server version' in resp.data.lower()


def test_start_node_when_docker_unavailable_does_not_crash(operator_client):
    create_node(operator_client, 'no-docker-node')
    with patch('nodemanager.node_actions.get_docker_client', return_value=None):
        resp = operator_client.post('/nodes/no-docker-node/start')
    assert resp.status_code == 302


# --- stop_node / restart_node ---

def test_stop_running_node(operator_client):
    create_node(operator_client, 'stop-me')
    container = MagicMock()
    client = _fake_client(container_get_effect=lambda name: container)

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/stop-me/stop', follow_redirects=True)

    container.stop.assert_called_once()
    assert b'stopped successfully' in resp.data.lower()


def test_stop_node_not_running_is_handled_gracefully(operator_client):
    create_node(operator_client, 'not-running-node')
    client = _fake_client()  # containers.get raises NotFound

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/not-running-node/stop', follow_redirects=True)

    assert b'is not running' in resp.data.lower()


def test_restart_running_node(operator_client):
    create_node(operator_client, 'restart-me')
    container = MagicMock()
    client = _fake_client(container_get_effect=lambda name: container)

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/restart-me/restart', follow_redirects=True)

    container.restart.assert_called_once()
    assert b'restarted successfully' in resp.data.lower()


def test_restart_node_not_running_is_handled_gracefully(operator_client):
    create_node(operator_client, 'restart-not-running')
    client = _fake_client()

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/restart-not-running/restart', follow_redirects=True)

    assert b'is not running' in resp.data.lower()


def test_start_stop_restart_are_logged_to_audit(operator_client):
    from nodemanager.audit import read_events

    create_node(operator_client, 'audited-lifecycle-node')
    container = MagicMock(status='exited')
    container.image.tags = []
    client = _fake_client(container_get_effect=lambda name: container)

    with _apply(_docker_patches(client)):
        operator_client.post('/nodes/audited-lifecycle-node/start', data={'image': 'some/image:tag'})

    with patch('nodemanager.node_actions.get_docker_client', return_value=client):
        operator_client.post('/nodes/audited-lifecycle-node/stop')
        operator_client.post('/nodes/audited-lifecycle-node/restart')

    actions = [e['action'] for e in read_events() if e['node_name'] == 'audited-lifecycle-node']
    assert 'node.start' in actions
    assert 'node.stop' in actions
    assert 'node.restart' in actions


# --- bulk start / bulk stop ---

def test_bulk_start_starts_multiple_nodes(operator_client):
    create_node(operator_client, 'bulk-a', server_url='https://example.com')
    create_node(operator_client, 'bulk-b', server_url='https://example.com')
    client = _fake_client()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': MagicMock(return_value=('4.9.0', None)),
        'nodemanager.node_actions.find_local_node_image': MagicMock(return_value=None),
    })):
        resp = operator_client.post('/nodes/bulk/start', data={'names': ['bulk-a', 'bulk-b']},
                                     follow_redirects=True)

    assert client.containers.run.call_count == 2
    assert b'started 2 node' in resp.data.lower()


def test_bulk_start_skips_already_running_node(operator_client):
    create_node(operator_client, 'bulk-running', server_url='https://example.com')
    running = MagicMock(status='running')
    client = _fake_client(container_get_effect=lambda name: running)

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/bulk/start', data={'names': ['bulk-running']},
                                     follow_redirects=True)

    client.containers.run.assert_not_called()
    assert b'already running' in resp.data.lower()


def test_bulk_start_mounts_private_key_for_encrypted_node(operator_client):
    create_node(operator_client, 'bulk-crypto', server_url='https://example.com', **{
        'encryption_enabled': 'on',
        'key_source': 'generate',
        'generated_private_key': '-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----',
    })
    client = _fake_client()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': MagicMock(return_value=('4.9.0', None)),
        'nodemanager.node_actions.find_local_node_image': MagicMock(return_value=None),
    })):
        operator_client.post('/nodes/bulk/start', data={'names': ['bulk-crypto']})

    _, kwargs = client.containers.run.call_args
    assert any(v.endswith(':/mnt/private_key.pem') for v in kwargs['volumes'])


def test_bulk_start_omits_private_key_env_when_encryption_disabled(operator_client):
    create_node(operator_client, 'bulk-no-crypto', server_url='https://example.com')
    client = _fake_client()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': MagicMock(return_value=('4.9.0', None)),
        'nodemanager.node_actions.find_local_node_image': MagicMock(return_value=None),
    })):
        operator_client.post('/nodes/bulk/start', data={'names': ['bulk-no-crypto']})

    _, kwargs = client.containers.run.call_args
    assert 'PRIVATE_KEY' not in kwargs['environment']


def test_bulk_stop_stops_multiple_nodes(operator_client):
    create_node(operator_client, 'bulk-stop-a')
    create_node(operator_client, 'bulk-stop-b')
    container = MagicMock()
    client = _fake_client(container_get_effect=lambda name: container)

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/bulk/stop', data={'names': ['bulk-stop-a', 'bulk-stop-b']},
                                     follow_redirects=True)

    assert container.stop.call_count == 2
    assert b'stopped 2 node' in resp.data.lower()


def test_bulk_stop_reports_not_running_nodes(operator_client):
    create_node(operator_client, 'bulk-stop-none')
    client = _fake_client()  # NotFound for every container

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/bulk/stop', data={'names': ['bulk-stop-none']},
                                     follow_redirects=True)

    assert b'not running' in resp.data.lower()
