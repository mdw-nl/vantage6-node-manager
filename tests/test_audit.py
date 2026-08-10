"""Admin-only audit log: who did what to nodes and user accounts. Not full
coverage - checks that the key node/user lifecycle events get recorded with
the right actor and target, and that the log page/export are admin-only.
Docker-dependent events (start/stop/restart) aren't exercised here since
this suite has no real Docker daemon to act against - see test_permissions.py/
test_ownership.py for how those routes are reached without one.
"""
from nodemanager.audit import read_events
from tests import conftest as conftest_module
from tests.conftest import (
    ADMIN_USERNAME, ADMIN_PASSWORD, OPERATOR_USERNAME, OPERATOR2_USERNAME,
    create_node, _login,
)

flask_app_module = conftest_module.flask_app_module


def test_node_create_is_logged(operator_client):
    create_node(operator_client, 'audit-node')

    matching = [e for e in read_events() if e['action'] == 'node.create' and e['node_name'] == 'audit-node']
    assert len(matching) == 1
    assert matching[0]['username'] == OPERATOR_USERNAME
    assert matching[0]['role'] == 'operator'


def test_node_leave_vs_delete_are_logged_distinctly(operator_client, admin_client):
    create_node(operator_client, 'leave-me')
    operator_client.post('/nodes/leave-me/delete')   # leave - config survives
    admin_client.post('/nodes/leave-me/delete')       # admin - real delete

    actions = [e['action'] for e in read_events() if e['node_name'] == 'leave-me']
    assert 'node.create' in actions
    assert 'node.leave' in actions
    assert 'node.delete' in actions


def test_owner_grant_is_logged_with_diff(operator_client, admin_client):
    create_node(operator_client, 'shared-audit-node')
    admin_client.post('/nodes/shared-audit-node/owners',
                       data={'owners': [OPERATOR_USERNAME, OPERATOR2_USERNAME]})

    events = [e for e in read_events() if e['action'] == 'node.access.update']
    assert len(events) == 1
    assert 'added' in events[0]['details']
    assert OPERATOR2_USERNAME in events[0]['details']
    assert events[0]['username'] == 'admin'


def test_user_management_events_are_logged(admin_client):
    admin_client.post('/users/new', data={'username': 'audituser', 'password': 'auditpass123', 'role': 'viewer'})
    admin_client.post('/users/audituser/role', data={'role': 'operator'})
    admin_client.post('/users/audituser/delete')

    actions = [e['action'] for e in read_events() if e.get('target_user') == 'audituser']
    assert actions.count('user.create') == 1
    assert actions.count('user.role_change') == 1
    assert actions.count('user.delete') == 1


def test_audit_page_is_admin_only(operator_client, viewer_client, admin_client):
    assert operator_client.get('/audit').status_code == 302
    assert viewer_client.get('/audit').status_code == 302
    assert admin_client.get('/audit').status_code == 200


def test_audit_export_is_admin_only_and_returns_csv(operator_client, admin_client):
    create_node(admin_client, 'csv-node')

    assert operator_client.get('/audit/export.csv').status_code == 302

    resp = admin_client.get('/audit/export.csv')
    assert resp.status_code == 200
    assert resp.mimetype == 'text/csv'
    assert b'node.create' in resp.data
    assert b'csv-node' in resp.data


# --- Login attempts, success and failure ---

def test_successful_login_is_logged(client):
    _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)

    matching = [e for e in read_events() if e['action'] == 'user.login']
    assert len(matching) == 1
    assert matching[0]['username'] == ADMIN_USERNAME
    assert matching[0]['role'] == 'admin'


def test_failed_login_wrong_password_is_logged(client):
    _login(client, ADMIN_USERNAME, 'not-the-right-password')

    matching = [e for e in read_events() if e['action'] == 'user.login_failed']
    assert len(matching) == 1
    assert matching[0]['username'] == ADMIN_USERNAME
    assert matching[0]['role'] == 'admin'
    assert matching[0]['details'] == 'wrong password'


def test_failed_login_unknown_username_is_logged(client):
    # The submitted username is recorded as-is (not validated/looked up) so
    # this doubles as a record of scanning/guessing attempts.
    _login(client, 'nobody-such-user', 'whatever123')

    matching = [e for e in read_events() if e['action'] == 'user.login_failed']
    assert len(matching) == 1
    assert matching[0]['username'] == 'nobody-such-user'
    assert matching[0]['role'] is None
    assert matching[0]['details'] == 'unknown username'


def test_successful_login_does_not_log_as_failed(client):
    _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    assert not [e for e in read_events() if e['action'] == 'user.login_failed']


# --- CSV export must neutralize formula injection from an attacker-chosen
#     (i.e. completely unvalidated) failed-login username ---

def test_csv_export_neutralizes_formula_injection_in_failed_login_username(admin_client):
    # A plain, independent test_client() rather than the `client` fixture -
    # mixing `client` (which stays open via `with`) and a separately-created
    # client like admin_client in the same test confuses Flask's
    # request-context teardown when their requests interleave. See
    # test_permissions.py::test_demoted_admin_is_blocked_on_next_request for
    # the same pattern/reasoning.
    attacker = flask_app_module.app.test_client()
    _login(attacker, '=cmd|calc!A1', 'whatever123')

    resp = admin_client.get('/audit/export.csv')
    assert b"'=cmd|calc!A1" in resp.data
