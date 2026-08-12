"""Per-user node ownership: who can see/act on which node. Not full coverage -
just the ownership boundary, same "boundary not full coverage" scope as
test_permissions.py.
"""
from unittest.mock import MagicMock, patch

import docker.errors

from nodemanager.node_config import _load_node_owners, get_node_configs
from tests.conftest import (
    ADMIN_USERNAME, ADMIN_PASSWORD, OPERATOR_USERNAME, OPERATOR2_USERNAME,
    create_node,
)


# --- Creating a node records ownership ---

def test_new_node_records_owner(operator_client):
    create_node(operator_client, 'node-a')
    assert _load_node_owners()['node-a'] == [OPERATOR_USERNAME]


def test_import_records_owner(operator_client):
    import io
    yaml_content = b"server_url: https://example.com\napi_key: import-key\n"
    data = {'backup_file': (io.BytesIO(yaml_content), 'node-imported.yaml')}
    operator_client.post('/nodes/import', data=data, content_type='multipart/form-data')
    assert _load_node_owners().get('node-imported') == [OPERATOR_USERNAME]


# --- Prerequisite bug fixes: name collision, api_key collision, path traversal ---

def test_new_node_rejects_duplicate_name(operator_client):
    create_node(operator_client, 'dup-node', server_url='https://first.com')
    create_node(operator_client, 'dup-node', server_url='https://SHOULD-NOT-STICK.com')
    resp = operator_client.get('/nodes/dup-node')
    assert b'first.com' in resp.data
    assert b'SHOULD-NOT-STICK' not in resp.data


def test_new_node_rejects_duplicate_api_key_under_different_name(admin_client, operator_client):
    # Same physical node, same api_key, but a *different* local name - this
    # would spin up a second Docker container authenticating to the real
    # vantage6 server with the same api_key as an existing one, which is a
    # server-side identity conflict, not a harmless duplicate.
    create_node(admin_client, 'real-node', api_key='shared-secret-key')
    create_node(operator_client, 'same-node-different-name', api_key='shared-secret-key')

    assert 'same-node-different-name' not in [c['name'] for c in get_node_configs()]
    assert _load_node_owners().get('same-node-different-name') is None
    assert _load_node_owners()['real-node'] == [ADMIN_USERNAME]


def test_new_node_rejects_path_traversal_name(operator_client, admin_client):
    create_node(operator_client, '../users')
    # users.yaml must be untouched - admin can still log in / list users.
    resp = admin_client.get('/users')
    assert resp.status_code == 200
    assert ADMIN_USERNAME.encode() in resp.data


def test_collision_across_roles_keeps_admins_node(admin_client, operator_client):
    # The exact scenario reported: admin already has a node, an operator
    # tries to create one with the same name - admin's must survive
    # untouched, not get silently overwritten or reassigned to the operator.
    create_node(admin_client, 'shared-name', server_url='https://admins-real-server.com')
    create_node(operator_client, 'shared-name', server_url='https://operators-hijack-attempt.com')

    resp = admin_client.get('/nodes/shared-name')
    assert b'admins-real-server.com' in resp.data
    assert b'operators-hijack-attempt' not in resp.data
    assert _load_node_owners()['shared-name'] == [ADMIN_USERNAME]


# --- operator2 can't reach operator1's node via any route ---

def test_operator2_blocked_from_operator1_node(operator_client, operator2_client):
    create_node(operator_client, 'owned-by-op1')

    assert operator2_client.get('/nodes/owned-by-op1').status_code == 302
    assert operator2_client.post('/nodes/owned-by-op1/edit', data={}).status_code == 302
    assert operator2_client.post('/nodes/owned-by-op1/delete').status_code == 302
    assert operator2_client.get('/nodes/owned-by-op1/export').status_code == 302
    assert operator2_client.post('/nodes/owned-by-op1/start').status_code == 302
    assert operator2_client.post('/nodes/owned-by-op1/stop').status_code == 302
    assert operator2_client.post('/nodes/owned-by-op1/restart').status_code == 302

    # Node must survive all of the above untouched.
    assert _load_node_owners()['owned-by-op1'] == [OPERATOR_USERNAME]


def test_operator2_blocked_via_api_too(operator_client, operator2_client):
    create_node(operator_client, 'api-blocked-node')
    resp = operator2_client.get('/api/nodes/api-blocked-node/health')
    assert resp.status_code == 404


# --- admin bypasses ownership entirely ---

def test_admin_can_act_on_any_operators_node(operator_client, admin_client):
    create_node(operator_client, 'op-owned-node')
    assert admin_client.get('/nodes/op-owned-node').status_code == 200
    assert admin_client.get('/nodes/op-owned-node/edit').status_code == 200
    assert admin_client.get('/nodes/op-owned-node/export').status_code == 200


def test_viewer_manages_own_node_but_never_controls_container(viewer_client):
    # Config-CRUD is open to viewer (ownership-scoped, same as operator);
    # container control (start/stop/restart) never is, even on its own node -
    # that's the one thing that still distinguishes viewer from operator.
    create_node(viewer_client, 'viewer-owned-node')
    assert viewer_client.get('/nodes/viewer-owned-node').status_code == 200
    assert viewer_client.get('/nodes/viewer-owned-node/edit').status_code == 200
    assert viewer_client.get('/nodes/viewer-owned-node/export').status_code == 200
    assert viewer_client.post('/nodes/viewer-owned-node/start').status_code == 302
    assert viewer_client.post('/nodes/viewer-owned-node/stop').status_code == 302
    assert viewer_client.post('/nodes/viewer-owned-node/restart').status_code == 302


def test_viewer_blocked_from_operators_node(operator_client, viewer_client):
    # Viewer is scoped to its own nodes exactly like operator now - no more
    # blanket "viewer sees everything" bypass.
    create_node(operator_client, 'not-the-viewers-node')
    assert viewer_client.get('/nodes/not-the-viewers-node').status_code == 302
    assert viewer_client.post('/nodes/not-the-viewers-node/delete').status_code == 302


# --- List/dashboard/API filtering ---

def test_list_nodes_excludes_other_operators_nodes(operator_client, operator2_client):
    create_node(operator_client, 'op1-node')
    create_node(operator2_client, 'op2-node')

    resp = operator_client.get('/api/nodes')
    names = [n['name'] for n in resp.get_json()]
    assert 'op1-node' in names
    assert 'op2-node' not in names


def test_unclaimed_node_not_visible_to_operators(operator_client, operator2_client, admin_client):
    # No grandfather clause: releasing a node (or it never having an owner
    # in the first place - e.g. pre-existing on upgrade) makes it admin-only,
    # not shared with every operator.
    create_node(operator_client, 'to-be-released')
    admin_client.post('/nodes/to-be-released/owners', data={'owners': []})

    resp = operator2_client.get('/api/nodes')
    names = [n['name'] for n in resp.get_json()]
    assert 'to-be-released' not in names

    admin_names = [n['name'] for n in admin_client.get('/api/nodes').get_json()]
    assert 'to-be-released' in admin_names


# --- Multiple owners on one node ---

def test_node_visible_to_all_of_its_owners(operator_client, operator2_client, admin_client):
    # The reported use case: two different accounts both watching the same
    # physical node, granted by admin rather than each creating their own
    # conflicting config.
    create_node(operator_client, 'shared-watch-node')
    admin_client.post('/nodes/shared-watch-node/owners',
                       data={'owners': [OPERATOR_USERNAME, OPERATOR2_USERNAME]})

    assert _load_node_owners()['shared-watch-node'] == [OPERATOR_USERNAME, OPERATOR2_USERNAME]
    assert operator_client.get('/nodes/shared-watch-node').status_code == 200
    assert operator2_client.get('/nodes/shared-watch-node').status_code == 200

    op1_names = [n['name'] for n in operator_client.get('/api/nodes').get_json()]
    op2_names = [n['name'] for n in operator2_client.get('/api/nodes').get_json()]
    assert 'shared-watch-node' in op1_names
    assert 'shared-watch-node' in op2_names


def test_removing_one_of_several_owners_keeps_the_others(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'multi-owner-node')
    admin_client.post('/nodes/multi-owner-node/owners',
                       data={'owners': [OPERATOR_USERNAME, OPERATOR2_USERNAME]})
    # Drop operator2, keep operator.
    admin_client.post('/nodes/multi-owner-node/owners', data={'owners': [OPERATOR_USERNAME]})

    assert _load_node_owners()['multi-owner-node'] == [OPERATOR_USERNAME]
    assert operator_client.get('/nodes/multi-owner-node').status_code == 200
    assert operator2_client.get('/nodes/multi-owner-node').status_code == 302


# --- Bulk routes: defense-in-depth against a hand-crafted request ---

def test_bulk_delete_skips_unowned_node(operator_client, operator2_client):
    create_node(operator_client, 'op1-bulk-node')
    operator2_client.post('/nodes/bulk/delete', data={'names': ['op1-bulk-node']})
    assert _load_node_owners().get('op1-bulk-node') == [OPERATOR_USERNAME]


def test_bulk_start_skips_unowned_node(operator_client, operator2_client):
    create_node(operator_client, 'op1-bulk-start-node')
    resp = operator2_client.post('/nodes/bulk/start', data={'names': ['op1-bulk-start-node']}, follow_redirects=True)
    assert b'not found' in resp.data.lower()


# --- Owner management (admin-only drain for the unclaimed pool) ---

def test_reassignment_moves_visibility(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'reassign-me')
    assert 'reassign-me' not in [n['name'] for n in operator2_client.get('/api/nodes').get_json()]

    admin_client.post('/nodes/reassign-me/owners', data={'owners': [OPERATOR2_USERNAME]})

    assert 'reassign-me' in [n['name'] for n in operator2_client.get('/api/nodes').get_json()]
    assert 'reassign-me' not in [n['name'] for n in operator_client.get('/api/nodes').get_json()]


def test_operator_cannot_reassign_ownership(operator_client, operator2_client):
    create_node(operator_client, 'no-self-service-reassign')
    operator_client.post('/nodes/no-self-service-reassign/owners', data={'owners': [OPERATOR2_USERNAME]})
    # Blocked by @admin_required - ownership must be unchanged.
    assert _load_node_owners()['no-self-service-reassign'] == [OPERATOR_USERNAME]


# --- Deleting a user releases their nodes ---

def test_deleting_user_releases_their_nodes(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'orphaned-on-delete')
    admin_client.post(f'/users/{OPERATOR_USERNAME}/delete')

    # Owner cleared, not left as a dangling reference to a deleted username...
    assert 'orphaned-on-delete' not in _load_node_owners()
    # ...but clearing the owner means "unclaimed" now, which is admin-only,
    # not "visible to every operator" - operator2 must still not see it.
    op2_names = [n['name'] for n in operator2_client.get('/api/nodes').get_json()]
    assert 'orphaned-on-delete' not in op2_names
    admin_names = [n['name'] for n in admin_client.get('/api/nodes').get_json()]
    assert 'orphaned-on-delete' in admin_names


def test_deleting_user_keeps_a_shared_nodes_other_owner(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'shared-then-orphaned')
    admin_client.post('/nodes/shared-then-orphaned/owners',
                       data={'owners': [OPERATOR_USERNAME, OPERATOR2_USERNAME]})
    admin_client.post(f'/users/{OPERATOR_USERNAME}/delete')

    assert _load_node_owners()['shared-then-orphaned'] == [OPERATOR2_USERNAME]
    op2_names = [n['name'] for n in operator2_client.get('/api/nodes').get_json()]
    assert 'shared-then-orphaned' in op2_names


# --- "Delete" means different things depending on role ---
# Non-admin: leaves the node (removes just them from the owner list).
# Admin: a real, permanent delete (removes the config file).

def test_non_admin_delete_only_leaves_file_and_other_owners_untouched(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'shared-leave-node')
    admin_client.post('/nodes/shared-leave-node/owners',
                       data={'owners': [OPERATOR_USERNAME, OPERATOR2_USERNAME]})

    operator_client.post('/nodes/shared-leave-node/delete')

    # operator left - no longer sees it...
    assert 'shared-leave-node' not in [n['name'] for n in operator_client.get('/api/nodes').get_json()]
    # ...operator2's access is untouched...
    assert 'shared-leave-node' in [n['name'] for n in operator2_client.get('/api/nodes').get_json()]
    # ...and the config file itself was never removed - admin still sees it.
    assert 'shared-leave-node' in [n['name'] for n in admin_client.get('/api/nodes').get_json()]
    assert _load_node_owners()['shared-leave-node'] == [OPERATOR2_USERNAME]


def test_non_admin_delete_of_own_created_node_does_not_remove_config(operator_client, admin_client):
    # Even the node's original creator only "leaves" - doesn't destroy the
    # config - since a node they created may since have been shared.
    create_node(operator_client, 'creator-leaves')
    operator_client.post('/nodes/creator-leaves/delete')

    assert 'creator-leaves' not in [n['name'] for n in operator_client.get('/api/nodes').get_json()]
    # Becomes admin-only (unclaimed), not gone.
    admin_names = [n['name'] for n in admin_client.get('/api/nodes').get_json()]
    assert 'creator-leaves' in admin_names
    assert _load_node_owners().get('creator-leaves') is None


def test_viewer_delete_also_just_leaves(viewer_client, admin_client):
    create_node(viewer_client, 'viewer-leaves')
    viewer_client.post('/nodes/viewer-leaves/delete')

    assert 'viewer-leaves' not in [n['name'] for n in viewer_client.get('/api/nodes').get_json()]
    assert 'viewer-leaves' in [n['name'] for n in admin_client.get('/api/nodes').get_json()]


def test_admin_delete_is_permanent(operator_client, admin_client):
    create_node(operator_client, 'admin-deletes-me')
    admin_client.post('/nodes/admin-deletes-me/delete')

    admin_names = [n['name'] for n in admin_client.get('/api/nodes').get_json()]
    assert 'admin-deletes-me' not in admin_names
    assert 'admin-deletes-me' not in _load_node_owners()


def test_non_admin_bulk_delete_only_removes_self(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'bulk-leave-node')
    admin_client.post('/nodes/bulk-leave-node/owners',
                       data={'owners': [OPERATOR_USERNAME, OPERATOR2_USERNAME]})

    operator_client.post('/nodes/bulk/delete', data={'names': ['bulk-leave-node']})

    assert 'bulk-leave-node' not in [n['name'] for n in operator_client.get('/api/nodes').get_json()]
    assert 'bulk-leave-node' in [n['name'] for n in operator2_client.get('/api/nodes').get_json()]
    assert _load_node_owners()['bulk-leave-node'] == [OPERATOR2_USERNAME]


def test_admin_bulk_delete_is_permanent(operator_client, admin_client):
    create_node(operator_client, 'admin-bulk-deletes-me')
    admin_client.post('/nodes/bulk/delete', data={'names': ['admin-bulk-deletes-me']})

    admin_names = [n['name'] for n in admin_client.get('/api/nodes').get_json()]
    assert 'admin-bulk-deletes-me' not in admin_names
    assert 'admin-bulk-deletes-me' not in _load_node_owners()


# --- edit_node() must re-check the api_key collision, same as creation ---

def test_edit_node_rejects_api_key_collision_with_other_node(operator_client):
    create_node(operator_client, 'node-one', api_key='key-one')
    create_node(operator_client, 'node-two', api_key='key-two')

    operator_client.post('/nodes/node-two/edit', data={
        'server_url': 'https://hijack-attempt.com',
        'api_key': 'key-one',
        'db_uri': '/tmp/test.csv',
        'db_type': 'csv',
    })

    # node-two must keep its own api_key/server_url - the edit was rejected,
    # not silently applied.
    config = next(c for c in get_node_configs() if c['name'] == 'node-two')
    assert config['data']['api_key'] == 'key-two'
    assert config['data']['server_url'] != 'https://hijack-attempt.com'


def test_edit_node_allows_keeping_its_own_api_key(operator_client):
    # The collision check must exclude the node being edited itself -
    # otherwise every edit that doesn't change api_key would reject itself.
    create_node(operator_client, 'self-edit-node', api_key='self-key')

    resp = operator_client.post('/nodes/self-edit-node/edit', data={
        'server_url': 'https://updated.example.com',
        'api_key': 'self-key',
        'db_uri': '/tmp/test.csv',
        'db_type': 'csv',
    }, follow_redirects=True)

    config = next(c for c in get_node_configs() if c['name'] == 'self-edit-node')
    assert config['data']['server_url'] == 'https://updated.example.com'


# --- Admin's real delete must also clean up the node's private key file ---

def test_admin_delete_removes_orphaned_private_key_file(operator_client, admin_client):
    from nodemanager.config import VANTAGE6_CONFIG_DIR

    create_node(operator_client, 'encrypted-node', **{
        'encryption_enabled': 'on',
        'key_source': 'generate',
        'generated_private_key': '-----BEGIN PRIVATE KEY-----\nfake-key-material\n-----END PRIVATE KEY-----',
    })
    key_path = VANTAGE6_CONFIG_DIR / 'private_keys' / 'encrypted-node_private_key.pem'
    assert key_path.exists()

    admin_client.post('/nodes/encrypted-node/delete')

    assert not key_path.exists()


def test_non_admin_leave_does_not_touch_private_key_file(operator_client, admin_client):
    # A non-admin's "delete" is just a leave - it must not remove the key
    # file, since the config (and anyone else's access to it) survives.
    from nodemanager.config import VANTAGE6_CONFIG_DIR

    create_node(operator_client, 'encrypted-leave-node', **{
        'encryption_enabled': 'on',
        'key_source': 'generate',
        'generated_private_key': '-----BEGIN PRIVATE KEY-----\nfake-key-material\n-----END PRIVATE KEY-----',
    })
    key_path = VANTAGE6_CONFIG_DIR / 'private_keys' / 'encrypted-leave-node_private_key.pem'
    assert key_path.exists()

    operator_client.post('/nodes/encrypted-leave-node/delete')

    assert key_path.exists()


# --- edit_node() warns when other owners are also affected ---

def test_edit_node_shows_shared_warning_when_node_has_other_owners(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'shared-edit-node')
    admin_client.post('/nodes/shared-edit-node/owners',
                       data={'owners': [OPERATOR_USERNAME, OPERATOR2_USERNAME]})

    resp = operator_client.get('/nodes/shared-edit-node/edit')
    assert OPERATOR2_USERNAME.encode() in resp.data
    assert b'shared' in resp.data.lower()


def test_edit_node_no_shared_warning_when_sole_owner(operator_client):
    create_node(operator_client, 'solo-edit-node')

    resp = operator_client.get('/nodes/solo-edit-node/edit')
    assert b'also shared with' not in resp.data.lower()


# --- Admin's real delete must also remove the node's Docker container and volumes ---

def _fake_docker_client(container_name=None, volume_names=None):
    """MagicMock docker client for delete-route tests: containers.get(name)
    returns a container mock only when `name` matches `container_name`
    (NotFound otherwise, simulating no running/stopped container left
    behind). volumes.get(name) returns a distinct mock per name in
    `volume_names` (NotFound for anything else).

    Returns (client, container_mock, {volume_name: volume_mock}).
    """
    client = MagicMock()
    container_mock = MagicMock()

    def _get_container(name):
        if container_name is not None and name == container_name:
            return container_mock
        raise docker.errors.NotFound('no such container')
    client.containers.get.side_effect = _get_container

    volume_mocks = {vname: MagicMock() for vname in (volume_names or [])}

    def _get_volume(name):
        if name in volume_mocks:
            return volume_mocks[name]
        raise docker.errors.NotFound('no such volume')
    client.volumes.get.side_effect = _get_volume

    return client, container_mock, volume_mocks


def test_admin_delete_removes_running_container_and_volumes(operator_client, admin_client):
    create_node(operator_client, 'container-cleanup-node')
    container_name = 'vantage6-container-cleanup-node-user'
    volume_names = [f'{container_name}-vol', f'{container_name}-vpn-vol',
                     f'{container_name}-ssh-vol', f'{container_name}-squid-vol']
    client, container_mock, volume_mocks = _fake_docker_client(container_name, volume_names)

    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        admin_client.post('/nodes/container-cleanup-node/delete')

    container_mock.stop.assert_called_once()
    container_mock.remove.assert_called_once()
    for vol in volume_mocks.values():
        vol.remove.assert_called_once()
    assert 'container-cleanup-node' not in [c['name'] for c in get_node_configs()]


def test_admin_delete_of_stopped_node_still_removes_volumes(operator_client, admin_client):
    create_node(operator_client, 'stopped-cleanup-node')
    container_name = 'vantage6-stopped-cleanup-node-user'
    volume_names = [f'{container_name}-vol']
    client, container_mock, volume_mocks = _fake_docker_client(None, volume_names)

    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        admin_client.post('/nodes/stopped-cleanup-node/delete')

    container_mock.stop.assert_not_called()
    volume_mocks[volume_names[0]].remove.assert_called_once()
    assert 'stopped-cleanup-node' not in [c['name'] for c in get_node_configs()]


def test_non_admin_delete_never_touches_docker(operator_client):
    # A "leave" must not affect the underlying container/volumes at all -
    # get_docker_client() shouldn't even be called.
    create_node(operator_client, 'leave-no-docker-node')

    with patch('nodemanager.nodes.get_docker_client') as get_client:
        operator_client.post('/nodes/leave-no-docker-node/delete')

    get_client.assert_not_called()


def test_admin_delete_aborts_config_when_docker_unreachable(operator_client, admin_client):
    # If the container can't be cleaned up, the config must survive too -
    # deleting it anyway would orphan the container with no way left to
    # remove it from the UI.
    create_node(operator_client, 'no-docker-node')

    with patch('nodemanager.nodes.get_docker_client', return_value=None):
        admin_client.post('/nodes/no-docker-node/delete')

    assert 'no-docker-node' in [c['name'] for c in get_node_configs()]


def test_admin_delete_warns_but_continues_when_volume_removal_fails(operator_client, admin_client):
    # A stuck volume (e.g. still in use) shouldn't block the delete - the
    # container and config are already gone by that point.
    create_node(operator_client, 'stuck-volume-node')
    container_name = 'vantage6-stuck-volume-node-user'
    volume_names = [f'{container_name}-vol']
    client, container_mock, volume_mocks = _fake_docker_client(None, volume_names)
    volume_mocks[volume_names[0]].remove.side_effect = docker.errors.APIError('volume in use')

    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        resp = admin_client.post('/nodes/stuck-volume-node/delete', follow_redirects=True)

    assert 'stuck-volume-node' not in [c['name'] for c in get_node_configs()]
    assert b'could not remove volume' in resp.data.lower()


def test_delete_confirm_dialog_mentions_container_and_volumes(operator_client, admin_client):
    # The onsubmit="confirm(...)" attributes are nested-quoted Jinja/JS - a
    # broken escape is a runtime JS error invisible to pytest, so at least
    # confirm the template renders and the new wording made it into the
    # attribute value for both the running and stopped branches, on both
    # the list page and the single-node page.
    create_node(operator_client, 'stopped-confirm-node')
    create_node(operator_client, 'running-confirm-node')
    container_name = 'vantage6-running-confirm-node-user'
    client, container_mock, _ = _fake_docker_client(container_name)
    container_mock.status = 'running'

    with patch('nodemanager.nodes.get_docker_client', return_value=client), \
         patch('nodemanager.docker_utils.get_docker_client', return_value=client):
        list_resp = admin_client.get('/nodes')
        stopped_view_resp = admin_client.get('/nodes/stopped-confirm-node')
        running_view_resp = admin_client.get('/nodes/running-confirm-node')

    # One occurrence per node row's confirm() plus one in the bulk-delete JS.
    assert list_resp.data.count(b'including node data') == 3
    assert b'including node data' in stopped_view_resp.data
    assert b'including node data' in running_view_resp.data
    assert b'keeps running unmanaged' not in list_resp.data


def test_admin_bulk_delete_removes_containers_and_volumes(operator_client, admin_client):
    create_node(operator_client, 'bulk-cleanup-a')
    create_node(operator_client, 'bulk-cleanup-b')
    container_a = 'vantage6-bulk-cleanup-a-user'
    container_b = 'vantage6-bulk-cleanup-b-user'

    client = MagicMock()
    containers = {container_a: MagicMock(), container_b: MagicMock()}

    def _get_container(name):
        if name in containers:
            return containers[name]
        raise docker.errors.NotFound('no such container')
    client.containers.get.side_effect = _get_container
    client.volumes.get.side_effect = docker.errors.NotFound('no such volume')

    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        admin_client.post('/nodes/bulk/delete', data={'names': ['bulk-cleanup-a', 'bulk-cleanup-b']})

    for container in containers.values():
        container.stop.assert_called_once()
        container.remove.assert_called_once()
    names = [c['name'] for c in get_node_configs()]
    assert 'bulk-cleanup-a' not in names
    assert 'bulk-cleanup-b' not in names
