"""Session-based login: user store, secret-key bootstrap, and the app-wide auth gate.

require_login() is registered app-wide via init_app(app) - Blueprint.before_request
only fires for that blueprint's own routes, so it cannot be used here to gate the
other blueprints (nodes, actions, api).
"""
import os
import re
import secrets
import yaml
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

from nodemanager.config import VANTAGE6_CONFIG_DIR, USERS_FILE
from nodemanager.node_config import release_nodes_owned_by
from nodemanager.audit import log_event, read_events, events_to_csv

auth_bp = Blueprint('auth', __name__)

login_manager = LoginManager()

# 'admin' is reserved: it is written only by _seed_admin_user() at first boot
# and is never an option in new_user()/change_user_role() below, so exactly
# one account - whichever was created first - ever holds it. 'operator' can
# act on nodes but not manage users; 'viewer' is read-only.
ROLES = {'admin', 'operator', 'viewer'}
ASSIGNABLE_ROLES = {'operator', 'viewer'}
OPERATOR_ROLES = {'admin', 'operator'}


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
        # Defaults to the least-privileged role: a missing/corrupt role key
        # should fail toward less access, not silently grant admin.
        return User(username, users[username].get('role', 'viewer'))
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


def _forbid(allowed_roles, denied_message):
    # Checking is_authenticated first is a fail-closed backstop, not filler:
    # AnonymousUserMixin has no .role, so without this a route that somehow
    # bypasses require_login would 500 with an AttributeError here instead
    # of cleanly 403/redirecting. require_login (app-wide before_request)
    # always runs before this, so in normal operation current_user is
    # already authenticated by the time this is reached.
    if not current_user.is_authenticated or current_user.role not in allowed_roles:
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': denied_message}), 403
        flash('You do not have permission to perform this action.', 'error')
        return redirect(request.referrer or url_for('nodes.index'))
    return None


def _forbid_non_operator():
    return _forbid(OPERATOR_ROLES, 'Operator access required')


def _forbid_non_admin():
    return _forbid({'admin'}, 'Admin access required')


def require_operator():
    """Blueprint-level before_request gate for blueprints admins and operators can both use."""
    return _forbid_non_operator()


def operator_required(view):
    """Per-route decorator for admin-or-operator routes inside otherwise-mixed blueprints."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        result = _forbid_non_operator()
        return result if result is not None else view(*args, **kwargs)
    return wrapped


def require_admin():
    """Blueprint-level before_request gate for blueprints that are entirely admin-only."""
    return _forbid_non_admin()


def admin_required(view):
    """Per-route decorator for admin-only routes (currently just user management)."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        result = _forbid_non_admin()
        return result if result is not None else view(*args, **kwargs)
    return wrapped


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
            role = user_record.get('role', 'viewer')
            login_user(User(username, role))
            log_event(username, role, 'user.login')
            flash(f'Welcome back, {username}!', 'success')
            next_url = request.form.get('next') or request.args.get('next')
            if (next_url and next_url.startswith('/')
                    and not next_url.startswith('//') and '\\' not in next_url):
                return redirect(next_url)
            return redirect(url_for('nodes.index'))

        # Logged even for a username that doesn't exist at all - the
        # attempted username is recorded as-is (not validated/looked up)
        # so this doubles as a record of scanning/guessing attempts, not
        # just mistyped passwords on real accounts.
        log_event(username, (user_record or {}).get('role'), 'user.login_failed',
                   details='unknown username' if not user_record else 'wrong password')
        flash('Invalid username or password.', 'error')

    return render_template('login.html', next=request.args.get('next', ''))


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


def _count_admins(users):
    return sum(1 for u in users.values() if u.get('role') == 'admin')


def _valid_username(username):
    return bool(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', username or ''))


def user_exists(username):
    """Public check for other modules (e.g. node-owner reassignment) that
    need to validate a username without reaching into _load_users() directly."""
    return username in _load_users()


def list_assignable_usernames():
    """Public: sorted usernames of non-admin accounts, for building the node
    access-picker UI - admin already sees/manages every node regardless of
    who else has access, so offering it as a checkbox would be meaningless
    (and unchecking it could misleadingly suggest admin loses access)."""
    users = _load_users()
    return sorted(u for u, info in users.items() if info.get('role') in ASSIGNABLE_ROLES)


@auth_bp.route('/users')
@admin_required
def list_users():
    users = _load_users()
    return render_template('users.html', users=users)


@auth_bp.route('/users/new', methods=['GET', 'POST'])
@admin_required
def new_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')
        role = request.form.get('role', '')

        if not _valid_username(username):
            flash('Username must be 1-64 characters: letters, numbers, underscore, hyphen.', 'error')
            return render_template('new_user.html')
        if role not in ASSIGNABLE_ROLES:
            flash('Invalid role.', 'error')
            return render_template('new_user.html')
        if len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
            return render_template('new_user.html')

        users = _load_users()
        if username in users:
            flash(f'User "{username}" already exists.', 'error')
            return render_template('new_user.html')

        users[username] = {'password_hash': generate_password_hash(password), 'role': role}
        _save_users(users)
        log_event(current_user.id, current_user.role, 'user.create', target_user=username, details=f'role={role}')
        flash(f'User "{username}" created.', 'success')
        return redirect(url_for('auth.list_users'))

    return render_template('new_user.html')


@auth_bp.route('/users/<username>/delete', methods=['POST'])
@admin_required
def delete_user(username):
    if username == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('auth.list_users'))

    users = _load_users()
    if username not in users:
        flash(f'User "{username}" not found.', 'error')
        return redirect(url_for('auth.list_users'))

    if users[username].get('role') == 'admin' and _count_admins(users) <= 1:
        flash('Cannot delete the last remaining admin account.', 'error')
        return redirect(url_for('auth.list_users'))

    del users[username]
    _save_users(users)
    release_nodes_owned_by(username)
    log_event(current_user.id, current_user.role, 'user.delete', target_user=username)
    flash(f'User "{username}" deleted.', 'success')
    return redirect(url_for('auth.list_users'))


@auth_bp.route('/users/<username>/role', methods=['POST'])
@admin_required
def change_user_role(username):
    if username == current_user.id:
        flash('You cannot change your own role.', 'error')
        return redirect(url_for('auth.list_users'))

    new_role = request.form.get('role', '')
    if new_role not in ASSIGNABLE_ROLES:
        flash('Invalid role.', 'error')
        return redirect(url_for('auth.list_users'))

    users = _load_users()
    if username not in users:
        flash(f'User "{username}" not found.', 'error')
        return redirect(url_for('auth.list_users'))

    if users[username].get('role') == 'admin' and _count_admins(users) <= 1:
        # Redundant with 'admin' being unassignable above (new_role can never
        # be 'admin'), but kept as defense-in-depth in case that ever changes.
        flash('Cannot demote the last remaining admin account.', 'error')
        return redirect(url_for('auth.list_users'))

    users[username]['role'] = new_role
    _save_users(users)
    log_event(current_user.id, current_user.role, 'user.role_change', target_user=username, details=f'role={new_role}')
    flash(f'Updated role for "{username}".', 'success')
    return redirect(url_for('auth.list_users'))


@auth_bp.route('/users/<username>/password', methods=['POST'])
@admin_required
def reset_user_password(username):
    users = _load_users()
    if username not in users:
        flash(f'User "{username}" not found.', 'error')
        return redirect(url_for('auth.list_users'))

    new_password = request.form.get('password', '')
    if len(new_password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('auth.list_users'))

    users[username]['password_hash'] = generate_password_hash(new_password)
    _save_users(users)
    log_event(current_user.id, current_user.role, 'user.password_reset', target_user=username)
    flash(f'Password updated for "{username}".', 'success')
    return redirect(url_for('auth.list_users'))


# How many recent events the /audit page renders. The full history is always
# available via /audit/export.csv - this cap just keeps a page load cheap
# once the log has been accumulating for a while.
AUDIT_PAGE_LIMIT = 300


@auth_bp.route('/audit')
@admin_required
def audit_log():
    events = read_events()
    return render_template('audit.html', events=events[:AUDIT_PAGE_LIMIT], total=len(events),
                            limit=AUDIT_PAGE_LIMIT)


@auth_bp.route('/audit/export.csv')
@admin_required
def audit_export():
    csv_data = events_to_csv(read_events())
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=audit_log.csv'}
    )


def init_app(app):
    login_manager.init_app(app)
    app.before_request(require_login)
    app.secret_key = _get_or_create_secret_key()
    _seed_admin_user()
