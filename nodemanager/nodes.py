"""Node configuration CRUD and display: dashboard, list, create/edit/view/delete,
import/export, and log viewing. Everything here reads/writes config YAML files or
displays state - Docker container start/stop/restart lives in node_actions.py.
"""
import os
import re
import io
import yaml
import zipfile
import docker
from pathlib import Path
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import current_user
from werkzeug.utils import secure_filename

from nodemanager.config import VANTAGE6_CONFIG_DIR, APPNAME
from nodemanager.docker_utils import get_docker_client, get_node_status, get_running_nodes
from nodemanager.node_config import (
    get_node_configs, add_node_owner, set_node_owners, remove_node_owner,
    clear_node_owner, filter_visible_configs, can_access_config
)
from nodemanager.server_api import get_running_tasks
from nodemanager.auth import admin_required, user_exists, list_assignable_usernames
from nodemanager.audit import log_event

nodes_bp = Blueprint('nodes', __name__)


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
                return render_template('new_node.html')

            server_url = request.form.get('server_url')
            port = request.form.get('port')
            api_path = request.form.get('api_path', '/api')
            # Use persistent data directory instead of /tmp for container environments
            task_dir = request.form.get('task_dir', '/mnt/data/tasks')

            # Database configuration
            db_label = request.form.get('db_label', 'default')
            db_uri = request.form.get('db_uri')
            db_type = request.form.get('db_type', 'csv')

            # Whether the node may run algorithm images that aren't pullable from a
            # registry (e.g. local `docker build` images used in development)
            allow_local_images = request.form.get('allow_local_images') == 'on'

            # Encryption configuration
            encryption_enabled, private_key_path = _process_encryption_form(name)

            # Build configuration
            config = {
                'api_key': api_key,
                'server_url': server_url,
                'port': int(port) if port else None,
                'api_path': api_path,
                'task_dir': task_dir,
                'databases': [{
                    'label': db_label,
                    'uri': db_uri,
                    'type': db_type
                }],
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
            return redirect(url_for('nodes.list_nodes'))

        except Exception as e:
            flash(f'Error creating configuration: {str(e)}', 'error')

    return render_template('new_node.html')


@nodes_bp.route('/nodes/<name>/edit', methods=['GET', 'POST'])
def edit_node(name):
    """
    Edit an existing node's configuration in place.

    Unlike new_node(), this loads the node's current YAML and only
    overwrites the specific fields the form covers - anything else already
    in the file (e.g. images, node_extra_hosts, extra databases beyond the
    first, or fields added by hand-editing/importing) survives untouched.
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

            api_key = request.form.get('api_key')
            if api_key:
                conflict_error = _api_key_conflict_error(name, api_key, configs)
                if conflict_error:
                    flash(conflict_error, 'error')
                    return render_template('edit_node.html', config=config)
                data['api_key'] = api_key

            db_label = request.form.get('db_label', 'default')
            db_uri = request.form.get('db_uri')
            db_type = request.form.get('db_type', 'csv')
            databases = data.get('databases') or [{}]
            databases[0] = {'label': db_label, 'uri': db_uri, 'type': db_type}
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
            return redirect(url_for('nodes.view_node', name=name))

        except Exception as e:
            flash(f'Error updating configuration: {str(e)}', 'error')

    return render_template('edit_node.html', config=config)


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
    return render_template('view_node.html', config=config, container_info=container_info,
                            running_tasks=running_tasks)


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

    admin: a real, permanent delete - removes the config file itself and
    clears every owner. admin is the only role whose "delete" can affect
    other people's access, since it's the one role responsible for the
    underlying node's lifecycle.

    Everyone else: removes only the current user from the owner list, same
    as admin unchecking them in the Access picker. The config file and
    every other owner's access are untouched - this holds even for a node
    the current user originally created, since once a node is shared,
    nobody's personal "delete" should be able to yank it out from under
    someone else who was granted access to the same physical node.
    """
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    if current_user.role == 'admin':
        try:
            # This only removes the config from the node manager - if the
            # node's container is still running, it is left untouched and
            # keeps running unmanaged.
            _delete_node_files(config)
            clear_node_owner(name)
            log_event(current_user.id, current_user.role, 'node.delete', node_name=name)
            flash(f'Node configuration "{name}" deleted successfully', 'success')
        except Exception as e:
            flash(f'Error deleting configuration: {str(e)}', 'error')
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
            try:
                _delete_node_files(config)
                clear_node_owner(name)
                log_event(current_user.id, current_user.role, 'node.delete', node_name=name, details='bulk')
                deleted.append(name)
            except Exception as e:
                errors.append(f'{name}: {str(e)}')
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
