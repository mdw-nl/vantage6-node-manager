"""Permission-critical paths: who can reach which routes. Not full coverage -
just the boundary between unauthenticated / viewer / admin, since a regression
here is exactly the kind of bug that's dangerous and easy to miss by clicking
around manually.
"""
from werkzeug.security import generate_password_hash

from nodemanager.auth import _load_users, _save_users
from tests import conftest as conftest_module
from tests.conftest import ADMIN_USERNAME, ADMIN_PASSWORD, VIEWER_USERNAME, VIEWER_PASSWORD, _login

flask_app_module = conftest_module.flask_app_module


# --- Unauthenticated: existing require_login behavior (regression guard) ---

def test_unauthenticated_get_nodes_redirects_to_login(client):
    resp = client.get('/nodes')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_unauthenticated_api_nodes_gets_json_401(client):
    resp = client.get('/api/nodes')
    assert resp.status_code == 401
    assert resp.get_json()['success'] is False


# --- Viewer: blocked from admin-only routes ---

def test_viewer_blocked_from_start_node(viewer_client):
    # actions_bp is gated entirely via before_request - the node doesn't need
    # to exist for this to prove the blueprint-level block fires first.
    resp = viewer_client.post('/nodes/some-node/start')
    assert resp.status_code == 302
    assert '/nodes/some-node/start' not in resp.headers.get('Location', '')


def test_viewer_blocked_from_bulk_stop(viewer_client):
    # A second actions_bp route - proves the gate is blueprint-wide, not
    # accidentally scoped to just one route.
    resp = viewer_client.post('/nodes/bulk/stop')
    assert resp.status_code == 302


def test_viewer_can_list_nodes(viewer_client):
    resp = viewer_client.get('/nodes')
    assert resp.status_code == 200


def test_viewer_blocked_from_new_node_form(viewer_client):
    resp = viewer_client.get('/nodes/new')
    assert resp.status_code == 302


def test_viewer_blocked_from_export(viewer_client):
    resp = viewer_client.get('/nodes/some-node/export')
    assert resp.status_code == 302


def test_viewer_blocked_from_generate_key_with_json_403(viewer_client):
    # Proves the /api/ branch of the shared forbid-helper fires for a route
    # outside nodes/actions too, and that it's a JSON 403, not an HTML redirect.
    resp = viewer_client.post('/api/encryption/generate-key')
    assert resp.status_code == 403
    body = resp.get_json()
    assert body['success'] is False


# --- Admin: unaffected by the new gates ---

def test_admin_can_reach_new_node_form(admin_client):
    resp = admin_client.get('/nodes/new')
    assert resp.status_code == 200


# --- User management: access control ---

def test_viewer_blocked_from_users_list(viewer_client):
    resp = viewer_client.get('/users')
    assert resp.status_code == 302


def test_admin_can_reach_users_list(admin_client):
    resp = admin_client.get('/users')
    assert resp.status_code == 200


# --- Safeguards: last admin can't be removed or demoted ---

def test_cannot_delete_sole_admin(admin_client):
    _save_users({
        ADMIN_USERNAME: {'password_hash': generate_password_hash(ADMIN_PASSWORD), 'role': 'admin'},
    })
    resp = admin_client.post(f'/users/{ADMIN_USERNAME}/delete')
    assert resp.status_code == 302
    assert ADMIN_USERNAME in _load_users()


def test_cannot_demote_sole_admin(admin_client):
    _save_users({
        ADMIN_USERNAME: {'password_hash': generate_password_hash(ADMIN_PASSWORD), 'role': 'admin'},
    })
    resp = admin_client.post(f'/users/{ADMIN_USERNAME}/role', data={'role': 'viewer'})
    assert resp.status_code == 302
    assert _load_users()[ADMIN_USERNAME]['role'] == 'admin'


def test_admin_with_a_second_admin_present_can_be_deleted(admin_client):
    # Sanity check the safeguard is "last admin", not "any admin" - with a
    # second admin present, deleting a (non-self) admin must succeed.
    _save_users({
        ADMIN_USERNAME: {'password_hash': generate_password_hash(ADMIN_PASSWORD), 'role': 'admin'},
        'admin2': {'password_hash': generate_password_hash('admin2pass123'), 'role': 'admin'},
    })
    resp = admin_client.post('/users/admin2/delete')
    assert resp.status_code == 302
    assert 'admin2' not in _load_users()


# --- Safeguards: can't act on your own account ---

def test_cannot_delete_self(admin_client):
    resp = admin_client.post(f'/users/{ADMIN_USERNAME}/delete')
    assert resp.status_code == 302
    assert ADMIN_USERNAME in _load_users()


def test_cannot_change_own_role(admin_client):
    resp = admin_client.post(f'/users/{ADMIN_USERNAME}/role', data={'role': 'viewer'})
    assert resp.status_code == 302
    assert _load_users()[ADMIN_USERNAME]['role'] == 'admin'


# --- Input validation ---

def test_rejects_invalid_username(admin_client):
    resp = admin_client.post('/users/new', data={
        'username': 'a b', 'password': 'validpass123', 'role': 'viewer',
    })
    assert 'a b' not in _load_users()


def test_rejects_invalid_role(admin_client):
    resp = admin_client.post('/users/new', data={
        'username': 'newperson', 'password': 'validpass123', 'role': 'superuser',
    })
    assert 'newperson' not in _load_users()


def test_rejects_duplicate_username(admin_client):
    before = _load_users()[VIEWER_USERNAME]['password_hash']
    admin_client.post('/users/new', data={
        'username': VIEWER_USERNAME, 'password': 'differentpass123', 'role': 'admin',
    })
    users = _load_users()
    # Existing account untouched - not overwritten by the rejected duplicate.
    assert users[VIEWER_USERNAME]['password_hash'] == before
    assert users[VIEWER_USERNAME]['role'] == 'viewer'


# --- Role changes take effect on the target's next request, not by magic ---

def test_demoted_admin_is_blocked_on_next_request():
    # Two independent cookie jars/sessions - admin_client's fixture reuses the
    # `client` fixture's own jar, so it can't stand in for a second session.
    _save_users({
        ADMIN_USERNAME: {'password_hash': generate_password_hash(ADMIN_PASSWORD), 'role': 'admin'},
        'admin2': {'password_hash': generate_password_hash('admin2pass123'), 'role': 'admin'},
    })

    # Plain client objects (no `with`) - each keeps its own cookie jar across
    # calls; nesting two `with app.test_client()` blocks confuses Flask's
    # request-context teardown when requests interleave between them.
    admin1 = flask_app_module.app.test_client()
    admin2 = flask_app_module.app.test_client()
    _login(admin1, ADMIN_USERNAME, ADMIN_PASSWORD)
    _login(admin2, 'admin2', 'admin2pass123')

    assert admin2.get('/nodes/new').status_code == 200  # admin2 starts with access

    # admin1 demotes admin2 out from under it.
    admin1.post('/users/admin2/role', data={'role': 'viewer'})

    # admin2's very next request, same session/cookie, reflects the change.
    resp = admin2.get('/nodes/new')
    assert resp.status_code == 302
