"""Test fixtures.

Both nodemanager/config.py (mkdir at import time) and nodemanager/auth.py
(secret-key bootstrap, admin seeding) have import-time side effects driven by
env vars, so those env vars must be set BEFORE `app` (or anything under
nodemanager) is imported anywhere in the test session. Do not import app at
module level in test files - go through the `client`/`admin_client`/
`viewer_client` fixtures below instead.
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
VIEWER_USERNAME = 'viewer'
VIEWER_PASSWORD = 'viewerpass123'


@pytest.fixture(autouse=True)
def reset_users():
    """Reset users.yaml to one known admin + one known viewer before every test.

    _load_users/load_user re-read the file on every request rather than
    caching, so overwriting it here is enough for per-test isolation -
    no monkeypatching or reload gymnastics needed.
    """
    _save_users({
        ADMIN_USERNAME: {
            'password_hash': generate_password_hash(ADMIN_PASSWORD),
            'role': 'admin',
        },
        VIEWER_USERNAME: {
            'password_hash': generate_password_hash(VIEWER_PASSWORD),
            'role': 'viewer',
        },
    })
    yield


@pytest.fixture
def client():
    flask_app_module.app.config['TESTING'] = True
    with flask_app_module.app.test_client() as c:
        yield c


def _login(client, username, password):
    return client.post('/login', data={'username': username, 'password': password})


@pytest.fixture
def admin_client(client):
    _login(client, ADMIN_USERNAME, ADMIN_PASSWORD)
    return client


@pytest.fixture
def viewer_client(client):
    _login(client, VIEWER_USERNAME, VIEWER_PASSWORD)
    return client
