"""Node configuration CRUD and display: dashboard, list, create/edit/view/delete,
import/export, and log viewing. Docker container start/stop/restart lives in
node_actions.py - the one exception is delete_node()/bulk_delete_nodes(), whose
admin "real delete" also stops/removes the node's container and volumes (see
delete_node()'s docstring for why deleting the config without that would just
orphan the container in the backend).
"""
import os
import re
import io
from itertools import zip_longest
import yaml
import zipfile
import docker
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import current_user
from werkzeug.utils import secure_filename

from nodemanager.config import VANTAGE6_CONFIG_DIR, APPNAME
from nodemanager.docker_utils import (
    get_docker_client, get_node_status, get_running_nodes, remove_node_container_and_volumes,
    get_configured_node_image, get_default_node_image
)
from nodemanager.node_config import (
    get_node_configs, add_node_owner, set_node_owners, remove_node_owner,
    clear_node_owner, filter_visible_configs, can_access_config
)
from nodemanager.server_api import get_running_tasks, get_node_api_session
from nodemanager.auth import admin_required, user_exists, list_assignable_usernames
from nodemanager.audit import log_event

nodes_bp = Blueprint('nodes', __name__)


def _is_valid_image_ref(image):
    """True if `image` looks like a pullable Docker reference (ends in
    ":tag" or "@sha256:digest"), false for things like a stray "/" where a
    ":" belongs - the mistake that produces a cryptic Docker Engine API
    error ("manifest unknown", tag defaulted to "latest") deep in
    node_actions instead of a clear message at save time.
    """
    if '@sha256:' in image:
        return True
    last_segment = image.rsplit('/', 1)[-1]
    return ':' in last_segment


@nodes_bp.route('/')
def index():
    """Dashboard showing overview of all nodes"""
    configs = filter_visible_configs(get_node_configs(), current_user.role, current_user.id)
    running_nodes = get_running_nodes()

    # Enrich configs with running status
    for config in configs:
        status = get_node_status(config['name'], config['type'] == 'system')
        config['status'] = status

    # get_running_nodes() scans Docker directly, independent of the configs
    # list above - without this, it would show every running node container
    # on the host by name, leaking other users' nodes through this widget
    # even though `configs` itself is correctly filtered.
    visible_container_names = {
        f"{APPNAME}-{c['name']}-{'system' if c['type'] == 'system' else 'user'}"
        for c in configs
    }
    running_nodes = [n for n in running_nodes if n['name'] in visible_container_names]

    return render_template('index.html',
                         configs=configs,
                         running_nodes=running_nodes,
                         total_configs=len(configs),
                         running_count=len([c for c in configs if c['status'] == 'running']))


@nodes_bp.route('/nodes')
def list_nodes():
    """List all node configurations"""
    configs = filter_visible_configs(get_node_configs(), current_user.role, current_user.id)

    # Add status to each config
    for config in configs:
        status = get_node_status(config['name'], config['type'] == 'system')
        config['status'] = status

    usernames = list_assignable_usernames() if current_user.role == 'admin' else None
    return render_template('nodes.html', configs=configs, usernames=usernames)


def _process_encryption_form(name, current_private_key=None):
    """
    Handle the encryption section of the create/edit node form: saves an
    uploaded or generated private key to disk. Shared by new_node() and
    edit_node() so both save keys the same way.

    current_private_key is the node's existing config['encryption']['private_key']
    (edit_node() only) - when encryption is already enabled and the user
    doesn't upload/generate a replacement, the existing key is kept rather
    than being wiped.

    Returns (encryption_enabled, private_key_path).
    """
    encryption_enabled = request.form.get('encryption_enabled') == 'on'
    if not encryption_enabled:
        return False, None

    key_source = request.form.get('key_source', 'upload')
    keys_dir = VANTAGE6_CONFIG_DIR / 'private_keys'

    if key_source == 'generate':
        generated_private_key = request.form.get('generated_private_key')
        if generated_private_key:
            keys_dir.mkdir(parents=True, exist_ok=True)
            private_key_path = keys_dir / f"{name}_private_key.pem"
            with open(private_key_path, 'w') as f:
                f.write(generated_private_key)
            os.chmod(str(private_key_path), 0o600)
            flash('Generated private key saved securely', 'success')
            return True, str(private_key_path.relative_to(VANTAGE6_CONFIG_DIR.parent))
        if current_private_key:
            return True, current_private_key
        flash('Encryption enabled but no private key was generated', 'error')
        return False, None

    # key_source == 'upload'
    private_key_file = request.files.get('private_key_file')
    if private_key_file and private_key_file.filename:
        filename = secure_filename(private_key_file.filename)
        keys_dir.mkdir(parents=True, exist_ok=True)
        private_key_path = keys_dir / f"{name}_{filename}"
        private_key_file.save(str(private_key_path))
        os.chmod(str(private_key_path), 0o600)
        flash('Private key uploaded and saved securely', 'success')
        return True, str(private_key_path.relative_to(VANTAGE6_CONFIG_DIR.parent))
    if current_private_key:
        return True, current_private_key
    flash('Encryption enabled but no private key file uploaded', 'error')
    return False, None


def _parse_databases_from_form(existing_databases=None):
    """Parse the database section of the create/edit node form into
    vantage6's `databases` config list.

    A node isn't limited to one database: the vantage6 node config schema
    takes a list, each entry with its own label, and an algorithm task
    picks which one it wants by label at run time (see
    build_database_env_and_volumes(), which already loops over the whole
    list). The form mirrors that with parallel arrays - one db_label/db_uri/
    db_type per row - rather than a single field each, so the UI can offer
    a "+ add another database" row.

    The form only manages label/uri/type - not every key the schema allows
    (e.g. mount_mode: ro/copy, see build_database_env_and_volumes()), so a
    row whose label matches one in `existing_databases` (edit_node() passes
    the node's current list; new_node() has none) has its other keys carried
    over rather than dropped. A label match is the only identity a row has
    across an edit - a renamed database is indistinguishable from
    remove-old-add-new and loses whatever hand-authored keys it had, same as
    it would if actually removed and re-added.

    Returns (databases, error) - error is a user-facing string (e.g. a
    duplicate label, which would otherwise silently collide into the same
    <LABEL>_DATABASE_URI environment variable) or None if the list is valid.
    Rows with a blank URI are dropped rather than rejected, since that's
    what an emptied-out "removed" row looks like once submitted. A row
    whose label was left blank (or omitted entirely, e.g. a hand-built form
    post with just one database and no db_label field at all) falls back to
    "default", matching this form's pre-multi-database behaviour.
    zip_longest (not zip) is deliberate: it's what makes that fallback work
    when db_label is missing outright rather than merely empty - zip would
    silently drop the row instead, since it stops at the shortest list.
    """
    labels = request.form.getlist('db_label')
    uris = request.form.getlist('db_uri')
    types = request.form.getlist('db_type')
    old_by_label = {db.get('label'): db for db in (existing_databases or []) if db.get('label')}

    databases = []
    seen_labels = set()
    for label, uri, db_type in zip_longest(labels, uris, types, fillvalue=''):
        label = (label or '').strip() or 'default'
        uri = (uri or '').strip()
        if not uri:
            continue
        if label in seen_labels:
            return None, (f'Database label "{label}" is used more than once - each database '
                           f'needs a unique label so algorithms can tell them apart.')
        seen_labels.add(label)
        databases.append({**old_by_label.get(label, {}), 'label': label, 'uri': uri, 'type': db_type or 'csv'})

    return databases, None


def _valid_node_name(name):
    return bool(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name or ''))


def _api_key_conflict_error(name, api_key, configs):
    """Shared by _node_conflict_error() (create/import) and edit_node():
    two node-manager entries under *different* names but the same api_key
    would both run as independent Docker containers authenticating to the
    real vantage6 server as the same node identity - the server doesn't
    know or care about this app's local names, only the api_key, so this
    causes connection/task conflicts on the server side. Sharing access to
    one node is an ownership question (see node_config.py's owners list),
    not something a second local config - or a hijacked existing one -
    can safely do. `name` is excluded from the search so a node is always
    allowed to keep (or be edited back to) its own api_key.
    """
    if not api_key:
        return None
    existing = next((c for c in configs
                      if c['name'] != name and (c.get('data') or {}).get('api_key') == api_key), None)
    if existing:
        return (f'This API key is already used by node "{existing["name"]}". Ask an admin to grant you '
                'access to that node instead of creating a second, conflicting connection to it.')
    return None


def _node_conflict_error(name, api_key, configs=None):
    """Shared validation for new_node()/_write_imported_config(): returns an
    error string, or None if safe to proceed.

    Two independent checks:
    - name: also a filesystem-path-safety check. name ends up interpolated
      straight into a path (VANTAGE6_CONFIG_DIR / f'{name}.yaml', and
      private-key filenames derived from it) - without this, a name like
      '../users' resolves outside VANTAGE6_CONFIG_DIR entirely, onto
      USERS_FILE itself.
    - api_key: see _api_key_conflict_error().

    Both point the user at asking an admin for access rather than at
    rename/delete - the fix for "I want to watch a node someone else
    already added" is being granted ownership of the existing entry, not
    creating a second, conflicting one.
    """
    if not _valid_node_name(name):
        return 'Node name must be 1-64 characters: letters, numbers, underscore, hyphen.'
    configs = get_node_configs() if configs is None else configs
    if any(c['name'] == name for c in configs):
        return f'A node named "{name}" already exists. Ask an admin to grant you access to it instead.'
    return _api_key_conflict_error(name, api_key, configs)


def _check_server_connection(data):
    """Best-effort validation of server_url/api_key against the vantage6
    server's own /token/node endpoint - the same call get_node_api_session()
    already makes for the node health-status check, so nothing new is talked
    to here, just a pure HTTP round trip to the server (never Docker, never
    the node container).

    Deliberately never blocks saving: unlike the Docker-host database check,
    the server is an external system that may legitimately be unreachable
    yet (not provisioned, mid-restart) at config time, and hard-blocking on
    a wrong key here would let a typo-driven retry loop trip the server's
    own login-attempt lockout before the node ever gets to connect for real.

    Returns a (message, category) tuple to flash alongside the save
    confirmation.
    """
    _, _, _, error = get_node_api_session({'data': data})
    if error:
        return (f'Could not verify the server connection: {error}. The node may fail to '
                f'start until this is fixed.', 'warning')
    return ('Connected to the vantage6 server and verified the API key.', 'success')


@nodes_bp.route('/nodes/new', methods=['GET', 'POST'])
def new_node():
    """Create a new node configuration.

    No role decorator: any authenticated role (admin/operator/viewer) can
    create a node, which it then owns. Container control (start/stop/
    restart) stays admin+operator only via actions_bp's own gate - creating
    a config is a viewer-safe, Docker-daemon-free operation.
    """
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            api_key = request.form.get('api_key')
            conflict_error = _node_conflict_error(name, api_key)
            if conflict_error:
                flash(conflict_error, 'error')
                return render_template('new_node.html', default_image=get_default_node_image())

            server_url = request.form.get('server_url')
            port = request.form.get('port')
            api_path = request.form.get('api_path', '/api')
            # Use persistent data directory instead of /tmp for container environments
            task_dir = request.form.get('task_dir', '/mnt/data/tasks')

            # Database configuration - one or more rows, see _parse_databases_from_form()
            databases, db_error = _parse_databases_from_form()
            if db_error:
                flash(db_error, 'error')
                return render_template('new_node.html', default_image=get_default_node_image())
            if not databases:
                flash('At least one database (label + URI) is required.', 'error')
                return render_template('new_node.html', default_image=get_default_node_image())

            # Whether the node may run algorithm images that aren't pullable from a
            # registry (e.g. local `docker build` images used in development)
            allow_local_images = request.form.get('allow_local_images') == 'on'

            # Node image the user confirmed on the form (auto-filled from the
            # server's detected version, but editable for orgs running nodes
            # against servers of different versions). Empty means "let
            # node_actions figure it out at start time" (see get_default_node_image).
            # Stored under images.node - the vantage6 CLI's own schema for
            # pinning this (vantage6.cli.node.start reads config["images"]["node"]),
            # not a node-manager invention, so configs stay usable with `v6 node start` too.
            image = request.form.get('image', '').strip() or None
            if image and not _is_valid_image_ref(image):
                flash(f'Node Image "{image}" doesn\'t look like a valid image reference - '
                      f'it should end in ":tag" (e.g. .../node-lite:4.14.0-rc8). '
                      f'Did you mean a colon instead of the last "/"?', 'error')
                return render_template('new_node.html', default_image=get_default_node_image())

            # Encryption configuration
            encryption_enabled, private_key_path = _process_encryption_form(name)

            # Build configuration
            config = {
                'api_key': api_key,
                'server_url': server_url,
                'port': int(port) if port else None,
                'api_path': api_path,
                'task_dir': task_dir,
                'images': {'node': image} if image else None,
                'databases': databases,
                'logging': {
                    'backup_count': 5,
                    'datefmt': '%Y-%m-%d %H:%M:%S',
                    'file': f'{name}.log',
                    'format': '%(asctime)s - %(name)-14s - %(levelname)-8s - %(message)s',
                    'level': 'INFO',
                    'max_size': 1024,
                    'use_console': True,
                    'loggers': [
                        {'name': 'urllib3', 'level': 'warning'},
                        {'name': 'requests', 'level': 'warning'},
                        {'name': 'engineio.client', 'level': 'warning'},
                        {'name': 'docker.utils.config', 'level': 'warning'},
                        {'name': 'docker.auth', 'level': 'warning'}
                    ]
                },
                'encryption': {
                    'enabled': encryption_enabled,
                    'private_key': private_key_path if encryption_enabled else None
                },
                'policies': {
                    'allowed_algorithms': [],
                    'require_algorithm_pull': not allow_local_images
                }
            }

            # Save configuration
            config_file = VANTAGE6_CONFIG_DIR / f'{name}.yaml'
            with open(config_file, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            add_node_owner(name, current_user.id)
            log_event(current_user.id, current_user.role, 'node.create', node_name=name)

            if encryption_enabled:
                flash(f'Node configuration "{name}" created successfully with encryption enabled!', 'success')
            else:
                flash(f'Node configuration "{name}" created successfully!', 'success')
            flash(*_check_server_connection(config))
            return redirect(url_for('nodes.list_nodes'))

        except Exception as e:
            flash(f'Error creating configuration: {str(e)}', 'error')

    return render_template('new_node.html', default_image=get_default_node_image())


@nodes_bp.route('/nodes/<name>/edit', methods=['GET', 'POST'])
def edit_node(name):
    """
    Edit an existing node's configuration in place.

    Unlike new_node(), this loads the node's current YAML and only
    overwrites the specific fields the form covers (including images.node,
    now that the form exposes it) - anything else already in the file (e.g.
    node_extra_hosts, or fields added by hand-editing/importing) survives
    untouched. `databases` is the one list-valued field the form fully
    replaces rather than merges: the template renders one editable row per
    existing entry (see _parse_databases_from_form()), so nothing is
    silently dropped as long as the submitted form reflects what was shown.
    Renaming isn't supported here: the config filename, container name and
    the server's own record of the node are all tied to the current name.
    """
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    if request.method == 'POST':
        try:
            data = config['data'] or {}

            data['server_url'] = request.form.get('server_url')
            port = request.form.get('port')
            data['port'] = int(port) if port else None
            data['api_path'] = request.form.get('api_path', '/api')
            data['task_dir'] = request.form.get('task_dir') or data.get('task_dir', '/tmp/vantage6')

            image = request.form.get('image', '').strip() or None
            if image and not _is_valid_image_ref(image):
                flash(f'Node Image "{image}" doesn\'t look like a valid image reference - '
                      f'it should end in ":tag" (e.g. .../node-lite:4.14.0-rc8). '
                      f'Did you mean a colon instead of the last "/"?', 'error')
                return render_template(
                    'edit_node.html', config=config,
                    configured_image=get_configured_node_image(config['data'] or {}),
                    default_image=get_default_node_image()
                )
            data['images'] = {'node': image} if image else None

            api_key = request.form.get('api_key')
            if api_key:
                conflict_error = _api_key_conflict_error(name, api_key, configs)
                if conflict_error:
                    flash(conflict_error, 'error')
                    return render_template(
                        'edit_node.html', config=config,
                        configured_image=get_configured_node_image(config['data'] or {}),
                        default_image=get_default_node_image()
                    )
                data['api_key'] = api_key

            databases, db_error = _parse_databases_from_form(data.get('databases'))
            if db_error:
                flash(db_error, 'error')
                return render_template(
                    'edit_node.html', config=config,
                    configured_image=get_configured_node_image(config['data'] or {}),
                    default_image=get_default_node_image()
                )
            if not databases:
                flash('At least one database (label + URI) is required.', 'error')
                return render_template(
                    'edit_node.html', config=config,
                    configured_image=get_configured_node_image(config['data'] or {}),
                    default_image=get_default_node_image()
                )
            data['databases'] = databases

            existing_encryption = data.get('encryption') or {}
            encryption_enabled, private_key_path = _process_encryption_form(
                name, current_private_key=existing_encryption.get('private_key')
            )
            data['encryption'] = {
                'enabled': encryption_enabled,
                'private_key': private_key_path if encryption_enabled else None
            }

            allow_local_images = request.form.get('allow_local_images') == 'on'
            policies = data.get('policies') or {}
            policies['require_algorithm_pull'] = not allow_local_images
            policies.setdefault('allowed_algorithms', [])
            data['policies'] = policies

            with open(config['path'], 'w') as f:
                yaml.dump(data, f, default_flow_style=False)
            log_event(current_user.id, current_user.role, 'node.edit', node_name=name)

            if get_node_status(name, config['type'] == 'system') == 'running':
                flash(f'Node configuration "{name}" updated. Restart the node for the changes to take effect.', 'success')
            else:
                flash(f'Node configuration "{name}" updated.', 'success')
            flash(*_check_server_connection(data))
            return redirect(url_for('nodes.view_node', name=name))

        except Exception as e:
            flash(f'Error updating configuration: {str(e)}', 'error')

    return render_template(
        'edit_node.html', config=config,
        configured_image=get_configured_node_image(config['data'] or {}),
        default_image=get_default_node_image()
    )


@nodes_bp.route('/nodes/<name>')
def view_node(name):
    """View details of a specific node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    # Get node status and logs
    status = get_node_status(name, config['type'] == 'system')
    config['status'] = status

    # Get container details if running
    container_info = None
    if status == 'running':
        client = get_docker_client()
        if client:
            postfix = "system" if config['type'] == 'system' else "user"
            container_name = f"{APPNAME}-{name}-{postfix}"
            try:
                container = client.containers.get(container_name)
                container_info = {
                    'id': container.id[:12],
                    'image': container.image.tags[0] if container.image.tags else 'unknown',
                    'created': container.attrs['Created'],
                    'ports': container.ports,
                    'labels': container.labels
                }
            except Exception as e:
                print(f"Error getting container info: {e}")

    running_tasks = get_running_tasks(name) if status == 'running' else []

    # Task history is fetched client-side (see refreshTaskHistory() in the
    # template) so a slow or unreachable vantage6 server can't stall this
    # page's initial load.
    return render_template(
        'view_node.html', config=config, container_info=container_info,
        running_tasks=running_tasks
    )


@nodes_bp.route('/nodes/<name>/logs')
def view_logs(name):
    """View logs of a running node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        return jsonify({'error': 'Node not found'}), 404

    client = get_docker_client()
    if not client:
        return jsonify({'error': 'Docker not available'}), 500

    tail_param = request.args.get('tail', '100')
    if tail_param == 'all':
        tail = 'all'
    elif tail_param.isdigit():
        tail = int(tail_param)
    else:
        tail = 100

    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"

        container = client.containers.get(container_name)
        logs = container.logs(tail=tail).decode('utf-8')

        return jsonify({'logs': logs})

    except docker.errors.NotFound:
        return jsonify({'error': 'Container not running'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _delete_node_files(config):
    """Admin-only real delete: removes the config file and, if encryption
    was enabled, its private key file too. Without this the .pem lingers
    in private_keys/ forever with nothing left pointing at it - an
    orphaned secret that just accumulates on disk across node deletions.
    """
    encryption_config = (config.get('data') or {}).get('encryption') or {}
    private_key_rel = encryption_config.get('private_key')
    if private_key_rel:
        private_key_path = VANTAGE6_CONFIG_DIR.parent / private_key_rel
        if private_key_path.exists():
            private_key_path.unlink()
    os.remove(config['path'])


@nodes_bp.route('/nodes/<name>/delete', methods=['POST'])
def delete_node(name):
    """"Delete" a node configuration - what this actually does depends on role.

    admin: a real, permanent delete - stops and removes the node's Docker
    container and its data/vpn/ssh/squid volumes, then removes the config
    file itself and clears every owner. admin is the only role whose
    "delete" can affect other people's access (and the underlying
    container/volumes), since it's the one role responsible for the
    underlying node's lifecycle.

    Everyone else: removes only the current user from the owner list, same
    as admin unchecking them in the Access picker. The config file, the
    container, its volumes, and every other owner's access are untouched -
    this holds even for a node the current user originally created, since
    once a node is shared, nobody's personal "delete" should be able to yank
    it out from under someone else who was granted access to the same
    physical node.
    """
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    if current_user.role == 'admin':
        client = get_docker_client()
        if not client:
            flash('Node configuration was not deleted - it could not be removed '
                  'without also cleaning up its container.', 'warning')
            return redirect(url_for('nodes.list_nodes'))

        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"
        try:
            container_removed, volumes_removed, volume_warnings = \
                remove_node_container_and_volumes(client, container_name)
        except Exception as e:
            flash(f'Could not remove container "{container_name}": {str(e)} - '
                  f'node configuration was not deleted', 'error')
            return redirect(url_for('nodes.list_nodes'))

        try:
            _delete_node_files(config)
            clear_node_owner(name)
            log_event(current_user.id, current_user.role, 'node.delete', node_name=name)
            detail = 'its container' if container_removed else 'its container (already gone)'
            flash(f'Node configuration "{name}" deleted successfully, along with '
                  f'{detail} and {len(volumes_removed)} volume(s)', 'success')
            for warning in volume_warnings:
                flash(f'Could not remove volume {warning}', 'warning')
        except Exception as e:
            # The container and volumes above are already gone at this point -
            # a failure here leaves the config behind, but the node's data is
            # not recoverable by starting it again, so say so explicitly
            # rather than letting this read like nothing happened.
            flash(f'Error deleting configuration: {str(e)}. Its container and volumes '
                  f'(including node data) were already removed and cannot be recovered.', 'error')
    else:
        remove_node_owner(name, current_user.id)
        log_event(current_user.id, current_user.role, 'node.leave', node_name=name)
        flash(f'Node "{name}" removed from your list. It is untouched for anyone else with access to it.', 'success')

    return redirect(url_for('nodes.list_nodes'))


@nodes_bp.route('/nodes/<name>/export')
def export_node(name):
    """
    Export a node's config as a download. Plain .yaml when there's nothing
    else to bundle; a .zip (config + private key) only when encryption is
    enabled and a key file needs to travel with it.
    """
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    encryption_config = config['data'].get('encryption', {}) or {}
    private_key_path = None
    if encryption_config.get('enabled') and encryption_config.get('private_key'):
        candidate = VANTAGE6_CONFIG_DIR.parent / encryption_config['private_key']
        if candidate.exists():
            private_key_path = candidate
        else:
            flash(f'Warning: private key file not found at "{candidate}", '
                  f'exported backup does not include it', 'warning')

    if not private_key_path:
        return send_file(
            config['path'],
            mimetype='application/x-yaml',
            as_attachment=True,
            download_name=f'{name}.yaml'
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.write(config['path'], arcname=f'{name}.yaml')
        zf.write(private_key_path, arcname='private_key.pem')

    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'{name}_backup.zip'
    )


def _write_imported_config(name, config_data):
    """Shared final step for import_node: validate the name, refuse collisions, write the yaml.

    name here comes from an uploaded filename (Path(...).stem) - user-controlled,
    same as new_node()'s form field, so it needs the same validation.
    """
    conflict_error = _node_conflict_error(name, config_data.get('api_key'))
    if conflict_error:
        return conflict_error

    imported_image = (config_data.get('images') or {}).get('node')
    if imported_image and not _is_valid_image_ref(imported_image):
        return (f'Node Image "{imported_image}" in the imported config doesn\'t look like a valid '
                f'image reference - it should end in ":tag" (e.g. .../node-lite:4.14.0-rc8).')

    config_file = VANTAGE6_CONFIG_DIR / f'{name}.yaml'
    with open(config_file, 'w') as f:
        yaml.dump(config_data, f, default_flow_style=False)
    add_node_owner(name, current_user.id)
    log_event(current_user.id, current_user.role, 'node.import', node_name=name)
    return None


@nodes_bp.route('/nodes/import', methods=['GET', 'POST'])
def import_node():
    """Import a node config from a previously exported .yaml file or .zip backup"""
    if request.method == 'GET':
        return render_template('import_node.html')

    upload = request.files.get('backup_file')
    if not upload or not upload.filename:
        flash('No backup file selected', 'error')
        return redirect(url_for('nodes.import_node'))

    filename = upload.filename.lower()

    try:
        if filename.endswith('.yaml') or filename.endswith('.yml'):
            name = Path(upload.filename).stem
            config_data = yaml.safe_load(upload.stream.read())

            encryption_config = config_data.get('encryption', {}) or {}
            if encryption_config.get('enabled'):
                flash('Warning: config has encryption enabled but a plain .yaml import has no '
                      'private key to go with it. Encryption has been disabled for the imported '
                      'node - re-export as a .zip backup if a key needs to travel with it.',
                      'warning')
                config_data['encryption'] = {'enabled': False, 'private_key': None}

            error = _write_imported_config(name, config_data)
            if error:
                flash(error, 'error')
                return redirect(url_for('nodes.import_node'))

        elif filename.endswith('.zip'):
            with zipfile.ZipFile(upload.stream) as zf:
                yaml_names = [n for n in zf.namelist() if n.endswith('.yaml')]
                if len(yaml_names) != 1:
                    flash('Backup zip must contain exactly one node config (.yaml) file', 'error')
                    return redirect(url_for('nodes.import_node'))

                yaml_entry = yaml_names[0]
                name = Path(yaml_entry).stem
                config_data = yaml.safe_load(zf.read(yaml_entry))

                encryption_config = config_data.get('encryption', {}) or {}
                if encryption_config.get('enabled') and 'private_key.pem' in zf.namelist():
                    keys_dir = VANTAGE6_CONFIG_DIR / 'private_keys'
                    keys_dir.mkdir(parents=True, exist_ok=True)

                    key_filename = f'{name}_private_key.pem'
                    key_path = keys_dir / key_filename
                    key_path.write_bytes(zf.read('private_key.pem'))
                    os.chmod(str(key_path), 0o600)

                    # Store relative path in config for portability, matching how new_node saves it
                    config_data['encryption']['private_key'] = str(
                        key_path.relative_to(VANTAGE6_CONFIG_DIR.parent)
                    )
                elif encryption_config.get('enabled'):
                    flash('Warning: config has encryption enabled but the backup did not include '
                          'a private key file. Encryption has been disabled for the imported node.',
                          'warning')
                    config_data['encryption'] = {'enabled': False, 'private_key': None}

                error = _write_imported_config(name, config_data)
                if error:
                    flash(error, 'error')
                    return redirect(url_for('nodes.import_node'))

        else:
            flash('Unsupported file type. Upload a .yaml file or a .zip backup.', 'error')
            return redirect(url_for('nodes.import_node'))

        flash(f'Node configuration "{name}" imported successfully', 'success')
        return redirect(url_for('nodes.view_node', name=name))

    except zipfile.BadZipFile:
        flash('Uploaded file is not a valid backup zip', 'error')
        return redirect(url_for('nodes.import_node'))
    except yaml.YAMLError:
        flash('Uploaded file is not valid YAML', 'error')
        return redirect(url_for('nodes.import_node'))
    except Exception as e:
        flash(f'Error importing configuration: {str(e)}', 'error')
        return redirect(url_for('nodes.import_node'))


@nodes_bp.route('/nodes/bulk/delete', methods=['POST'])
def bulk_delete_nodes():
    names = request.form.getlist('names')
    if not names:
        flash('No nodes selected', 'warning')
        return redirect(url_for('nodes.list_nodes'))

    configs = get_node_configs()
    client = get_docker_client() if current_user.role == 'admin' else None

    deleted = []
    removed = []
    errors = []
    for name in names:
        config = next((c for c in configs if c['name'] == name), None)
        if not config or not can_access_config(config, current_user.role, current_user.id):
            # Template only ever offers checkboxes for visible nodes - this
            # guards against a hand-crafted POST body naming someone else's node.
            errors.append(f'{name}: not found')
            continue
        if current_user.role == 'admin':
            # Real delete - see delete_node()'s docstring for why this
            # differs by role.
            if not client:
                errors.append(f'{name}: could not remove without also cleaning up its container')
                continue
            postfix = "system" if config['type'] == 'system' else "user"
            container_name = f"{APPNAME}-{name}-{postfix}"
            try:
                container_removed, volumes_removed, volume_warnings = \
                    remove_node_container_and_volumes(client, container_name)
            except Exception as e:
                errors.append(f'{name}: could not remove container - {str(e)}')
                continue
            try:
                _delete_node_files(config)
                clear_node_owner(name)
                log_event(current_user.id, current_user.role, 'node.delete', node_name=name, details='bulk')
                deleted.append(name)
                for warning in volume_warnings:
                    errors.append(f'{name}: could not remove volume {warning}')
            except Exception as e:
                # Container/volumes above are already gone - the node's data
                # is not recoverable even though the config survives.
                errors.append(f'{name}: {str(e)} (its container and volumes, including '
                               f'node data, were already removed and cannot be recovered)')
        else:
            remove_node_owner(name, current_user.id)
            log_event(current_user.id, current_user.role, 'node.leave', node_name=name, details='bulk')
            removed.append(name)

    if deleted:
        flash(f'Deleted {len(deleted)} node(s): {", ".join(deleted)}', 'success')
    if removed:
        flash(f'Removed {len(removed)} node(s) from your list: {", ".join(removed)}', 'success')
    for err in errors:
        flash(err, 'error')

    return redirect(url_for('nodes.list_nodes'))


@nodes_bp.route('/nodes/<name>/owners', methods=['POST'])
@admin_required
def update_node_owners(name):
    """Admin-only: set the full list of users who own this node. A node can
    have more than one owner (e.g. two people at the same hospital both
    watching the same physical node) - this replaces the entire set in one
    submit rather than adding/removing one at a time. Also the drain for
    the "unclaimed" pool - without this, nodes with no owner recorded
    (created before this feature existed, or released via delete_user())
    would stay admin-only forever with no way to hand them to anyone.
    """
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    new_owners = [u.strip() for u in request.form.getlist('owners') if u.strip()]
    unknown = [u for u in new_owners if not user_exists(u)]
    if unknown:
        flash(f'Unknown user(s): {", ".join(unknown)}.', 'error')
        return redirect(url_for('nodes.list_nodes'))

    old_owners = set(config.get('owners', []))
    set_node_owners(name, new_owners)

    added = sorted(set(new_owners) - old_owners)
    dropped = sorted(old_owners - set(new_owners))
    detail_parts = []
    if added:
        detail_parts.append(f"added: {', '.join(added)}")
    if dropped:
        detail_parts.append(f"removed: {', '.join(dropped)}")
    if detail_parts:
        log_event(current_user.id, current_user.role, 'node.access.update',
                   node_name=name, details='; '.join(detail_parts))

    if new_owners:
        flash(f'Node "{name}" owners set to: {", ".join(new_owners)}.', 'success')
    else:
        flash(f'Node "{name}" has no owners now - only admin can see it.', 'success')

    return redirect(url_for('nodes.list_nodes'))
