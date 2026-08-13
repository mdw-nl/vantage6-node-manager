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
    # verify_database_mounts() execs into the container containers.run() just
    # returned - default that to "file found" so tests not exercising it don't
    # have to know it exists. Individual tests override .exec_run.return_value
    # to simulate a missing/misresolved database mount.
    client.containers.run.return_value.exec_run.return_value = (0, b'')

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


def test_start_fails_fast_when_database_file_missing_on_host(operator_client):
    """If the Database URI resolves to nothing on the Docker host (e.g. a user
    pasted a container-side path like this app's own /data instead of the real
    host path), Docker itself doesn't error - it silently mounts an empty
    directory. start_node() must catch that immediately, tear the container
    back down, and surface an actionable error instead of leaving a node
    "running" with no data."""
    from nodemanager.audit import read_events

    create_node(operator_client, 'missing-db-node', server_url='https://example.com')
    client = _fake_client()
    client.containers.run.return_value.exec_run.return_value = (1, b'')

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/missing-db-node/start',
                                     data={'image': 'harbor2.vantage6.ai/infrastructure/node:4.7.0'},
                                     follow_redirects=True)

    assert b'error starting node' in resp.data.lower()
    assert b'not found' in resp.data.lower()
    client.containers.run.return_value.remove.assert_called_once_with(force=True)

    actions = [e['action'] for e in read_events() if e['node_name'] == 'missing-db-node']
    assert 'node.start' not in actions


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


def test_start_with_no_image_and_no_history_falls_back_to_default_image(operator_client):
    create_node(operator_client, 'no-image-node', server_url='https://example.com')
    client = _fake_client()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': MagicMock(return_value=('4.9.0', None)),
        'nodemanager.node_actions.find_local_node_image': MagicMock(return_value=None),
    })):
        operator_client.post('/nodes/no-image-node/start')

    assert _run_image(client) == 'ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.14.0-rc8'


def test_start_falls_back_to_latest_when_server_unreachable(operator_client):
    create_node(operator_client, 'unreachable-node', server_url='https://example.com')
    client = _fake_client()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': MagicMock(return_value=(None, 'Could not connect to server')),
        'nodemanager.node_actions.find_local_node_image': MagicMock(return_value=None),
    })):
        resp = operator_client.post('/nodes/unreachable-node/start', follow_redirects=True)

    assert _run_image(client) == 'ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.14.0-rc8'
    assert b'could not detect server version' in resp.data.lower()


def test_start_uses_node_configured_image_without_detecting_version(operator_client):
    create_node(operator_client, 'configured-image-node', server_url='https://example.com',
                image='ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.15.0')
    client = _fake_client()
    get_server_version_mock = MagicMock()

    with _apply(_docker_patches(client, **{
        'nodemanager.node_actions.get_server_version': get_server_version_mock,
    })):
        operator_client.post('/nodes/configured-image-node/start')

    assert _run_image(client) == 'ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.15.0'
    # A node-level configured image is a known-good value - no need to pay
    # for a server round-trip just to derive the same answer.
    get_server_version_mock.assert_not_called()


def test_start_prefers_previous_container_image_over_configured_image(operator_client):
    create_node(operator_client, 'stopped-with-configured-image', server_url='https://example.com',
                image='ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.15.0')
    stopped = MagicMock(status='exited')
    stopped.image.tags = ['ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.14.0-rc8']
    client = _fake_client(container_get_effect=lambda name: stopped)

    with _apply(_docker_patches(client)):
        operator_client.post('/nodes/stopped-with-configured-image/start')

    assert _run_image(client) == 'ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.14.0-rc8'


def test_start_translates_docker_pull_failure_into_readable_flash(operator_client):
    # containers.run() pulls the image first if it isn't cached - a bad
    # tag/registry surfaces as a raw Docker Engine API error ("manifest
    # unknown") unless node_actions translates it. Non-technical users need
    # the translated message, not a docker+http:// URL.
    create_node(operator_client, 'bad-image-node', server_url='https://example.com',
                image='ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.14.0-rc8')
    client = _fake_client()
    client.containers.run.side_effect = docker.errors.APIError(
        'manifest unknown', explanation='manifest unknown'
    )

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/bad-image-node/start', follow_redirects=True)

    assert b"edit page" in resp.data.lower()
    assert b'http+docker://' not in resp.data


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
    """restart_node() must fully recreate the container (stop + remove + run
    fresh from the current config) rather than a plain `docker restart` -
    that's the only way a config edit's mount/env changes (database path,
    encryption key, log dir) actually take effect. `container.status` is
    flipped by the stop() side effect to simulate the daemon transitioning
    the same container to 'exited', same as a real stop would."""
    create_node(operator_client, 'restart-me')
    container = MagicMock(status='running')
    container.image.tags = ['harbor2.vantage6.ai/infrastructure/node:4.7.0']

    def _mark_exited():
        container.status = 'exited'
    container.stop.side_effect = _mark_exited

    client = _fake_client(container_get_effect=lambda name: container)

    with _apply(_docker_patches(client)):
        resp = operator_client.post('/nodes/restart-me/restart', follow_redirects=True)

    container.stop.assert_called_once()
    container.remove.assert_called_once()
    client.containers.run.assert_called_once()
    assert _run_image(client) == 'harbor2.vantage6.ai/infrastructure/node:4.7.0'
    assert b'restarted successfully' in resp.data.lower()


def test_restart_picks_up_edited_database_path(operator_client):
    """The bug this fix addresses: editing a running node's config (here, its
    database path) and clicking Restart must actually mount the new path -
    not silently keep the container's original mounts, which a plain `docker
    restart` would have done.
    """
    create_node(operator_client, 'repath-node')
    container = MagicMock(status='running')
    container.image.tags = ['some/image:tag']

    def _mark_exited():
        container.status = 'exited'
    container.stop.side_effect = _mark_exited

    client = _fake_client(container_get_effect=lambda name: container)

    with _apply(_docker_patches(client)):
        operator_client.post('/nodes/repath-node/edit', data={
            'server_url': 'https://example.com',
            'db_label': 'default',
            'db_uri': '/tmp/new-data.csv',
            'db_type': 'csv',
        })
        operator_client.post('/nodes/repath-node/restart')

    _, kwargs = client.containers.run.call_args
    volumes = kwargs['volumes']
    assert any(v.startswith('/tmp/new-data.csv:') for v in volumes)
    assert not any(v.startswith('/tmp/test.csv:') for v in volumes)


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

    # restart_node() now recreates the container the same way start_node()
    # does, so it needs the same full patch set (container_path_to_host_path
    # included) - not just get_docker_client - or it bails out with "Cannot
    # mount config directory" before ever reaching containers.run().
    with _apply(_docker_patches(client)):
        operator_client.post('/nodes/audited-lifecycle-node/start', data={'image': 'some/image:tag'})
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
