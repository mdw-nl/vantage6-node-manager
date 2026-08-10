"""Session-based login: user store, secret-key bootstrap, and the app-wide auth gate.

require_login() is registered app-wide via init_app(app) - Blueprint.before_request
only fires for that blueprint's own routes, so it cannot be used here to gate the
other blueprints (nodes, actions, api).
"""
import os
import secrets
import yaml
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

from nodemanager.config import VANTAGE6_CONFIG_DIR, USERS_FILE

auth_bp = Blueprint('auth', __name__)

login_manager = LoginManager()


def _looks_like_placeholder_secret(value):
    # Catches the .env.example / docker-compose.*.yml / previous app.py
    # fallback placeholders (and any future one following this naming) by
    # substance rather than an exact-string allowlist that a new placeholder
    # could silently slip past.
    return 'change' in value.lower() and 'production' in value.lower()


def _get_or_create_secret_key():
    env_key = os.environ.get('SECRET_KEY')
    if env_key and not _looks_like_placeholder_secret(env_key):
        return env_key

    # No real secret was supplied - generate one and persist it next to
    # users.yaml so sessions survive restarts instead of invalidating on
    # every deploy, but never fall back to a value that ships in this repo.
    key_file = VANTAGE6_CONFIG_DIR.parent / '.secret_key'
    if key_file.exists():
        return key_file.read_text().strip()

    key = secrets.token_hex(32)
    key_file.write_text(key)
    os.chmod(str(key_file), 0o600)
    print(f'No usable SECRET_KEY set - generated and persisted a random signing key at {key_file}.')
    return key


class User(UserMixin):
    def __init__(self, username, role):
        self.id = username
        self.role = role


def _load_users():
    if not USERS_FILE.exists():
        return {}
    with open(USERS_FILE, 'r') as f:
        return yaml.safe_load(f) or {}


def _save_users(users):
    with open(USERS_FILE, 'w') as f:
        yaml.dump(users, f, default_flow_style=False)
    os.chmod(str(USERS_FILE), 0o600)


def _seed_admin_user():
    """Create the initial admin account on first run. Never overwrites an
    existing users.yaml, so restarts never reset the admin password."""
    users = _load_users()
    if users:
        return

    username = os.environ.get('ADMIN_USERNAME', 'admin')
    password = os.environ.get('ADMIN_PASSWORD')
    generated = False
    if not password:
        password = secrets.token_urlsafe(12)
        generated = True

    users[username] = {
        'password_hash': generate_password_hash(password),
        'role': 'admin',
    }
    _save_users(users)

    if generated:
        print('=' * 60)
        print('No users.yaml found - created initial admin account.')
        print(f'  username: {username}')
        print(f'  password: {password}')
        print('SAVE THIS PASSWORD - it will not be shown again.')
        print('=' * 60)


@login_manager.user_loader
def load_user(username):
    users = _load_users()
    if username in users:
        return User(username, users[username].get('role', 'admin'))
    return None


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Authentication required'}), 401
    flash('Please log in to access this page.', 'warning')
    return redirect(url_for('auth.login', next=request.path))


PUBLIC_ENDPOINTS = {'auth.login', 'static'}


def require_login():
    # request.endpoint is None for unmatched URLs; falling through here means
    # those get the same login gate instead of an anonymous 404.
    if request.endpoint in PUBLIC_ENDPOINTS or current_user.is_authenticated:
        return None
    return login_manager.unauthorized()


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('nodes.index'))

    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        users = _load_users()
        user_record = users.get(username)

        if user_record and check_password_hash(user_record['password_hash'], password):
            login_user(User(username, user_record.get('role', 'admin')))
            flash(f'Welcome back, {username}!', 'success')
            next_url = request.form.get('next') or request.args.get('next')
            if (next_url and next_url.startswith('/')
                    and not next_url.startswith('//') and '\\' not in next_url):
                return redirect(next_url)
            return redirect(url_for('nodes.index'))

        flash('Invalid username or password.', 'error')

    return render_template('login.html', next=request.args.get('next', ''))


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


def init_app(app):
    login_manager.init_app(app)
    app.before_request(require_login)
    app.secret_key = _get_or_create_secret_key()
    _seed_admin_user()
