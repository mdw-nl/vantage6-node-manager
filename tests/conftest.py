"""Test fixtures.

Both nodemanager/config.py (mkdir at import time) and nodemanager/auth.py
(secret-key bootstrap, admin seeding) have import-time side effects driven by
env vars, so those env vars must be set BEFORE `app` (or anything under
nodemanager) is imported anywhere in the test session. Do not import app at
module level in test files - go through the `client`/`admin_client`/
`operator_client`/`operator2_client`/`viewer_client` fixtures below instead.
Each logged-in fixture has its own independent session - see
_new_logged_in_client()'s docstring for why that matters.
"""
import os
import tempfile
from pathlib import Path

import pytest

_TEST_DIR = Path(tempfile.mkdtemp(prefix='v6nm-test-'))
_CONFIG_DIR = _TEST_DIR / 'config' / 'node'
_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

os.environ['VANTAGE6_CONFIG_DIR'] = str(_CONFIG_DIR)
os.environ['VANTAGE6_SYSTEM_CONFIG_DIR'] = str(_TEST_DIR / 'system-config')
os.environ['VANTAGE6_DATA_DIR'] = str(_TEST_DIR / 'data')
os.environ['SECRET_KEY'] = 'test-secret-key-for-pytest'
os.environ['ADMIN_USERNAME'] = 'admin'
os.environ['ADMIN_PASSWORD'] = 'adminpass123'

import app as flask_app_module  # noqa: E402  (must come after the env vars above)
from nodemanager.auth import _save_users  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'adminpass123'
OPERATOR_USERNAME = 'operator'
OPERATOR_PASSWORD = 'operatorpass123'
OPERATOR2_USERNAME = 'operator2'
OPERATOR2_PASSWORD = 'operator2pass123'
VIEWER_USERNAME = 'viewer'
VIEWER_PASSWORD = 'viewerpass123'


@pytest.fixture(autouse=True)
def reset_users():
    """Reset users.yaml to one known admin + two operators + viewer before every test.

    _load_users/load_user re-read the file on every request rather than
    caching, so overwriting it here is enough for per-test isolation -
    no monkeypatching or reload gymnastics needed.
    """
    _save_users({
        ADMIN_USERNAME: {
            'password_hash': generate_password_hash(ADMIN_PASSWORD),
            'role': 'admin',
        },
        OPERATOR_USERNAME: {
            'password_hash': generate_password_hash(OPERATOR_PASSWORD),
            'role': 'operator',
        },
        OPERATOR2_USERNAME: {
            'password_hash': generate_password_hash(OPERATOR2_PASSWORD),
            'role': 'operator',
        },
        VIEWER_USERNAME: {
            'password_hash': generate_password_hash(VIEWER_PASSWORD),
            'role': 'viewer',
        },
    })
    yield


@pytest.fixture(autouse=True)
def reset_nodes():
    """Clear node config files + node_owners.yaml before every test.

    Unlike test_permissions.py (which never writes real node YAML - it only
    ever probes access to a nonexistent name), ownership tests create real
    nodes via POST /nodes/new, so without this they'd leak across tests and
    produce order-dependent failures.
    """
    from nodemanager.config import NODE_OWNERS_FILE
    for f in _CONFIG_DIR.glob('*.yaml'):
        f.unlink()
    if NODE_OWNERS_FILE.exists():
        NODE_OWNERS_FILE.unlink()
    yield


@pytest.fixture(autouse=True)
def reset_audit_log():
    """Clear audit.log before every test - same leak-across-tests reasoning
    as reset_nodes(), so audit tests can assert on exact event counts."""
    from nodemanager.config import AUDIT_LOG_FILE
    if AUDIT_LOG_FILE.exists():
        AUDIT_LOG_FILE.unlink()
    yield


@pytest.fixture(autouse=True)
def stub_server_connection_check(monkeypatch):
    """new_node()/edit_node() ping the vantage6 server's own API to validate
    server_url/api_key at save time (nodes.py's _check_server_connection()).
    Default that to "success" for every test so the suite doesn't make real
    network calls to https://example.com (the placeholder server_url
    create_node() uses) on every single node creation. Tests that
    specifically exercise the check itself override this binding directly.
    """
    monkeypatch.setattr(
        'nodemanager.nodes.get_node_api_session',
        lambda config: ('https://example.com/api', {}, {'id': 1}, None)
    )


@pytest.fixture
def client():
    flask_app_module.app.config['TESTING'] = True
    with flask_app_module.app.test_client() as c:
        yield c


def _login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password})


def create_node(client, name, **overrides):
    """POST a minimal valid /nodes/new form as whichever client is passed in.

    api_key defaults to something derived from `name` - unique per node -
    since new_node() now rejects a second node reusing another's api_key.
    Tests that specifically exercise that collision pass a matching
    api_key explicitly via overrides.
    """
    data = {
        'name': name,
        'server_url': 'https://example.com',
        'api_key': f'test-api-key-{name}',
        'db_uri': '/tmp/test.csv',
        'db_type': 'csv',
    }
    data.update(overrides)
    return client.post('/nodes/new', data=data)


def _new_logged_in_client(username, password):
    # Deliberately NOT built on top of the `client` fixture: fixtures are
    # cached per-name per-test, so if two logged-in fixtures both depended on
    # `client` they'd resolve to the very same object - whichever fixture's
    # _login() runs second would silently overwrite the first's session, and
    # a test requesting both would find them logged in as the same user.
    # Each of these gets its own independent test client/cookie jar instead.
    flask_app_module.app.config['TESTING'] = True
    c = flask_app_module.app.test_client()
    _login(c, username, password)
    return c


@pytest.fixture
def admin_client():
    return _new_logged_in_client(ADMIN_USERNAME, ADMIN_PASSWORD)


@pytest.fixture
def operator_client():
    return _new_logged_in_client(OPERATOR_USERNAME, OPERATOR_PASSWORD)


@pytest.fixture
def operator2_client():
    return _new_logged_in_client(OPERATOR2_USERNAME, OPERATOR2_PASSWORD)


@pytest.fixture
def viewer_client():
    return _new_logged_in_client(VIEWER_USERNAME, VIEWER_PASSWORD)
