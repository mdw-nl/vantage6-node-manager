"""
Vantage6 Node Manager Web Application
A Flask-based web interface for managing vantage6 nodes
"""
import os
import io
import yaml
import docker
import requests
import shutil
import base64
import zipfile
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from pathlib import Path
from werkzeug.utils import secure_filename
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Configuration - use environment variables for container flexibility
VANTAGE6_CONFIG_DIR = Path(os.environ.get('VANTAGE6_CONFIG_DIR', '/root/.config/vantage6/node'))
VANTAGE6_SYSTEM_CONFIG_DIR = Path(os.environ.get('VANTAGE6_SYSTEM_CONFIG_DIR', '/etc/vantage6/node'))
VANTAGE6_DATA_DIR = Path(os.environ.get('VANTAGE6_DATA_DIR', '/data'))
APPNAME = 'vantage6'

# Ensure config directory exists
VANTAGE6_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def container_path_to_host_path(container_path):
    """
    Convert a path inside the Node Manager container to the corresponding host path.
    This is needed when the Node Manager creates volumes for node containers.
    
    Args:
        container_path: Path as seen inside the Node Manager container
    
    Returns:
        Host path that Docker can mount, or None if conversion not possible
    """
    container_path_str = str(container_path)
    
    # Get the actual host HOME directory from environment variable
    # When running in Docker, this should be set to the host's HOME
    host_home = os.environ.get('HOST_HOME', str(Path.home()))
    
    # Check if path is in the user config directory
    if container_path_str.startswith('/root/.config/vantage6'):
        # /root/.config/vantage6 is mounted from ${HOME}/.config/vantage6 on host
        # Convert: /root/.config/vantage6/node/file.yaml -> ${HOME}/.config/vantage6/node/file.yaml
        relative_path = container_path_str.replace('/root/.config/vantage6/', '')
        host_path = Path(host_home) / '.config' / 'vantage6' / relative_path
        return str(host_path)
    
    # Check if path is in the system config directory
    elif container_path_str.startswith('/etc/vantage6/node'):
        # /etc/vantage6/node is mounted from ${HOME}/.config/vantage6-system on host
        relative_path = container_path_str.replace('/etc/vantage6/node/', '')
        host_path = Path(host_home) / '.config' / 'vantage6-system' / relative_path
        return str(host_path)
    
    # Check if path is in the data directory
    elif container_path_str.startswith('/data/'):
        # /data is mounted from ${HOME}/vantage6-data on host
        relative_path = container_path_str.replace('/data/', '')
        host_path = Path(host_home) / 'vantage6-data' / relative_path
        return str(host_path)
    
    # Path is not in a known mounted volume
    else:
        return None


# Database types whose "uri" is a local file/folder rather than a connection
# string (matches vantage6.cli.node.start.FILE_BASED_DATABASE_TYPES)
FILE_BASED_DATABASE_TYPES = {'folder', 'csv', 'parquet', 'excel'}


def build_database_env_and_volumes(databases):
    """
    Build the <LABEL>_DATABASE_URI environment variables and volume mounts for
    a node's configured databases, following the same approach as the official
    `v6 node start` CLI.

    For file-based databases (csv/folder/parquet/excel), the file must be
    bind-mounted into the node container at /mnt/<label><suffix>, with the env
    var set to just the filename. The node resolves the real host path for
    algorithm containers by inspecting its own mount table; if the file is
    never mounted into the node container at all (previously: the raw "uri"
    was passed as the env var with no accompanying mount), algorithm
    containers fail with FileNotFoundError when they try to read it, since
    that "uri" doesn't correspond to anything inside the node container -
    the node's own filesystem view is unaffected by the Node Manager's own
    container mounts.

    The "uri" is used directly as the bind-mount source (a host path), not
    translated via container_path_to_host_path() - unlike the config/log
    dirs, it is not a path derived from paths inside the Node Manager's own
    container, it's an opaque host path supplied by the user for Docker
    itself to resolve.

    Returns:
        (env, volumes): dict of env vars, list of "source:target[:mode]" volume strings
    """
    env = {}
    volumes = []
    for db in databases or []:
        label = db.get('label', '')
        uri = db.get('uri', '')
        db_type = (db.get('type') or '').lower()
        if not label or not uri:
            continue

        label_upper = label.upper()
        if db_type in FILE_BASED_DATABASE_TYPES:
            suffix = Path(uri).suffix
            env[f'{label_upper}_DATABASE_URI'] = f'{label}{suffix}'
            mount_mode = str(db.get('mount_mode', 'copy')).lower()
            mode_suffix = ':ro' if mount_mode == 'ro' else ''
            volumes.append(f'{uri}:/mnt/{label}{suffix}{mode_suffix}')
        else:
            env[f'{label_upper}_DATABASE_URI'] = uri
    return env, volumes


def get_docker_client():
    """Get Docker client instance"""
    try:
        return docker.from_env()
    except Exception as e:
        flash(f'Docker is not running or not accessible: {str(e)}', 'error')
        return None


def get_server_version(server_url, api_path='/api', port=None):
    """
    Get the Vantage6 server version from the server's version endpoint.

    Args:
        server_url: Base URL of the Vantage6 server
        api_path: API path (default: '/api')
        port: Server port (optional). The node config stores this separately
              from server_url, so it must be injected into the URL here.

    Returns:
        tuple: (version_string, error_message)
               Returns (None, error_msg) if version cannot be retrieved
    """
    try:
        # Strip any trailing slash so we can consistently append :port and the path
        base_url = server_url.rstrip('/')

        if port:
            base_url = f"{base_url}:{port}"

        # Remove leading slash from api_path if present
        api_path = api_path.lstrip('/')

        version_url = f"{base_url}/{api_path}/version"
        
        # Make request to version endpoint with timeout
        response = requests.get(version_url, timeout=5)
        response.raise_for_status()
        
        # Parse version from response
        version_data = response.json()
        
        # The response typically contains a 'version' field
        if isinstance(version_data, dict):
            version = version_data.get('version') or version_data.get('v')
        else:
            version = str(version_data)
        
        if version:
            return version, None
        else:
            return None, "Version field not found in server response"
            
    except requests.exceptions.Timeout:
        return None, "Server request timed out"
    except requests.exceptions.ConnectionError:
        return None, f"Could not connect to server at {server_url}"
    except requests.exceptions.HTTPError as e:
        return None, f"HTTP error: {e}"
    except Exception as e:
        return None, f"Error retrieving server version: {str(e)}"


def generate_rsa_key_pair():
    """
    Generate a new RSA key pair for encryption.
    
    Returns:
        tuple: (private_key_pem, public_key_pem) as strings
    """
    try:
        # Generate private key (4096 bits for strong security)
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
            backend=default_backend()
        )
        
        # Serialize private key to PEM format
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')
        
        # Generate public key from private key
        public_key = private_key.public_key()
        
        # Serialize public key to PEM format
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')
        
        return private_key_pem, public_key_pem
    except Exception as e:
        print(f"Error generating RSA key pair: {e}")
        return None, None


def find_local_node_image(client, version=None):
    """
    Find a vantage6 node image that is already pulled on this Docker host.

    Deployments can be pinned to a fork/registry (e.g. ghcr.io/mdw-nl/...) whose
    tags don't line up 1:1 with the server-reported version (pre-release suffixes
    like "-rc8"), and the registry derived from the version string may not even
    be reachable. An image that is already local is known to work in this
    environment, so it's a safer default than guessing a registry/tag.

    Args:
        client: Docker client
        version: Optional server version string to prefer a matching tag

    Returns:
        str or None: a local image tag to use, or None if no node image is local
    """
    try:
        candidates = []
        for img in client.images.list():
            for tag in img.tags:
                if '/infrastructure/node' in tag:
                    candidates.append((img.attrs.get('Created', ''), tag))
    except Exception:
        return None

    if not candidates:
        return None

    if version:
        for _, tag in candidates:
            tag_version = tag.rsplit(':', 1)[-1]
            if tag_version == version or tag_version.startswith(f"{version}-") or tag_version.startswith(f"{version}."):
                return tag

    # No version match (or no version given): use the most recently pulled image
    candidates.sort(reverse=True)
    return candidates[0][1]


def get_node_image_for_version(version):
    """
    Determine the appropriate node Docker image based on server version.
    
    Args:
        version: Server version string (e.g., "4.7.1" or "4.7.0")
    
    Returns:
        str: Docker image name with tag
    """
    try:
        # Extract major.minor from version (e.g., "4.7.1" -> "4.7")
        parts = version.split('.')
        if len(parts) >= 2:
            major_minor = f"{parts[0]}.{parts[1]}"
            # Use the exact version for patch-level compatibility
            return f"harbor2.vantage6.ai/infrastructure/node:{version}"
        else:
            # Fallback if version format is unexpected
            return f"harbor2.vantage6.ai/infrastructure/node:{version}"
    except Exception:
        # If parsing fails, use the provided version as-is
        return f"harbor2.vantage6.ai/infrastructure/node:{version}"


def get_node_configs():
    """Get all available node configurations"""
    configs = []
    
    # User configurations
    if VANTAGE6_CONFIG_DIR.exists():
        for config_file in VANTAGE6_CONFIG_DIR.glob('*.yaml'):
            try:
                with open(config_file, 'r') as f:
                    config_data = yaml.safe_load(f)
                configs.append({
                    'name': config_file.stem,
                    'path': str(config_file),
                    'type': 'user',
                    'data': config_data
                })
            except Exception as e:
                print(f"Error loading {config_file}: {e}")
    
    # System configurations
    if VANTAGE6_SYSTEM_CONFIG_DIR.exists():
        for config_file in VANTAGE6_SYSTEM_CONFIG_DIR.glob('*.yaml'):
            try:
                with open(config_file, 'r') as f:
                    config_data = yaml.safe_load(f)
                configs.append({
                    'name': config_file.stem,
                    'path': str(config_file),
                    'type': 'system',
                    'data': config_data
                })
            except Exception as e:
                print(f"Error loading {config_file}: {e}")
    
    return configs


def get_running_nodes():
    """Get all running vantage6 node containers"""
    client = get_docker_client()
    if not client:
        return []
    
    running_nodes = []
    try:
        containers = client.containers.list()
        for container in containers:
            if APPNAME in container.name:
                running_nodes.append({
                    'name': container.name,
                    'id': container.id[:12],
                    'status': container.status,
                    'image': container.image.tags[0] if container.image.tags else 'unknown',
                    'created': container.attrs['Created']
                })
    except Exception as e:
        print(f"Error getting running nodes: {e}")
    
    return running_nodes


def get_node_status(node_name, system_folders=False):
    """Check if a specific node is running"""
    postfix = "system" if system_folders else "user"
    container_name = f"{APPNAME}-{node_name}-{postfix}"

    client = get_docker_client()
    if not client:
        return 'unknown'

    try:
        container = client.containers.get(container_name)
        return 'running' if container.status == 'running' else 'stopped'
    except docker.errors.NotFound:
        return 'stopped'
    except Exception as e:
        print(f"Error checking node status: {e}")
        return 'error'


def get_node_health_status(config):
    """
    Derive node health from the vantage6 server's own record of this node
    (its 'status' and 'last_seen' fields, fetched using the node's own
    api_key) rather than parsing log text.

    The container-running check still covers 'stopped' - there's no point
    asking the server about a node whose container isn't even up. A failed
    server call becomes its own 'error' state (with the server's actual
    error message) instead of a missed log pattern.

    Returns a dict with 'status' and 'message' keys.
    """
    postfix = "system" if config['type'] == 'system' else "user"
    container_name = f"{APPNAME}-{config['name']}-{postfix}"

    client = get_docker_client()
    if not client:
        return {'status': 'unknown', 'message': 'Docker not available'}

    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        return {'status': 'stopped', 'message': 'Container not running'}
    except Exception as e:
        return {'status': 'unknown', 'message': str(e)}

    if container.status != 'running':
        return {'status': 'stopped', 'message': f'Container is {container.status}'}

    base, headers, node_data, error = get_node_api_session(config)
    if not base:
        return {'status': 'error', 'message': error}

    if node_data.get('status') == 'online':
        last_seen = node_data.get('last_seen')
        message = f'Connected to server (last seen {last_seen})' if last_seen else 'Connected to server'
        return {'status': 'online', 'message': message}

    # Container is running but the server doesn't have it marked online.
    # Tell "just booted, hasn't connected yet" apart from "was connected,
    # dropped off" using the container's own uptime rather than log text.
    started_at = container.attrs.get('State', {}).get('StartedAt')
    uptime_seconds = None
    if started_at:
        try:
            started_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            uptime_seconds = (datetime.now(started_dt.tzinfo) - started_dt).total_seconds()
        except ValueError:
            pass

    if uptime_seconds is not None and uptime_seconds < 30:
        return {'status': 'starting', 'message': 'Node is starting up'}

    last_seen = node_data.get('last_seen')
    message = f'Disconnected from server (last seen {last_seen})' if last_seen else 'Disconnected from server'
    return {'status': 'reconnecting', 'message': message}


def get_running_tasks(node_name):
    """
    List algorithm containers this node is currently executing.

    When a vantage6 node runs a task it spawns a sibling container on the
    same docker host (not nested inside the node container) labelled
    vantage6-type=algorithm, node=<name>, run_id=<run id>. Those labels are
    set by the node software itself, so this works regardless of whether
    the node was started through this manager or elsewhere.
    """
    client = get_docker_client()
    if not client:
        return []

    try:
        containers = client.containers.list(filters={
            'label': ['vantage6-type=algorithm', f'node={node_name}']
        })
    except Exception:
        return []

    tasks = []
    for container in containers:
        labels = container.labels
        image = container.attrs.get('Config', {}).get('Image', 'unknown')
        tasks.append({
            'run_id': labels.get('run_id', '?'),
            'image': image,
            'container_name': container.name,
            'started_at': container.attrs.get('State', {}).get('StartedAt'),
        })

    tasks.sort(key=lambda t: t['started_at'] or '')
    return tasks


def get_node_api_session(config):
    """
    Authenticate to this node's vantage6 server using the node's own
    api_key - the same credential the node itself uses to connect.

    Returns (base_url, headers, node_data, error). node_data is the
    server's own record for this node (id, status, last_seen, ...). On
    failure base_url/headers/node_data are None and error holds a short,
    server-provided reason where available.
    """
    data = config.get('data', {})
    server_url = data.get('server_url')
    api_key = data.get('api_key')
    if not server_url or not api_key:
        return None, None, None, 'Node config is missing server_url or api_key'

    api_path = data.get('api_path', '/api')
    port = data.get('port')
    base = f"{server_url}:{port}{api_path}" if port else f"{server_url}{api_path}"

    try:
        token_resp = requests.post(f'{base}/token/node', json={'api_key': api_key}, timeout=5)
    except requests.exceptions.RequestException as e:
        return None, None, None, f'Could not connect to server: {e}'

    if not token_resp.ok:
        try:
            reason = token_resp.json().get('msg', token_resp.text)
        except ValueError:
            reason = token_resp.text
        return None, None, None, reason or f'Server returned {token_resp.status_code}'

    headers = {'Authorization': f'Bearer {token_resp.json()["access_token"]}'}

    try:
        me = requests.get(f'{base}/node', headers=headers, timeout=5)
        me.raise_for_status()
        node_data = me.json()['data'][0]
    except Exception as e:
        return None, None, None, f'Could not read node record from server: {e}'

    return base, headers, node_data, None


def get_task_history(config, per_page=10, page=1):
    """
    Fetch a page of this node's task-execution history from the vantage6
    server's own records, rather than inferring it from log text. The
    server tracks each run's status and timestamps in its database
    regardless of what the node's local logs say or how long they're kept,
    so this reflects the server's ground truth and isn't tied to any
    particular wording the node software happens to log.

    Returns {'tasks': [...], 'page': int, 'per_page': int, 'total': int,
    'total_pages': int}.
    """
    empty = {'tasks': [], 'page': page, 'per_page': per_page, 'total': 0, 'total_pages': 0}

    base, headers, node_data, error = get_node_api_session(config)
    if not base:
        return empty

    try:
        resp = requests.get(f'{base}/run', headers=headers, params={
            'node_id': node_data['id'],
            'include': 'task',
            'sort': '-id',
            'per_page': per_page,
            'page': page,
        }, timeout=5)
        resp.raise_for_status()
        runs = resp.json().get('data', [])
        total = int(resp.headers.get('total-count', len(runs)))
    except Exception:
        return empty

    history = []
    for run in runs:
        task = run.get('task') or {}
        started_at = run.get('started_at')
        finished_at = run.get('finished_at')

        if finished_at:
            status = 'completed' if run.get('status') == 'completed' else 'error'
        elif started_at:
            status = 'running'
        else:
            status = 'pending'

        duration_seconds = None
        if started_at and finished_at:
            try:
                duration_seconds = max(0, int(
                    (datetime.fromisoformat(finished_at) - datetime.fromisoformat(started_at)).total_seconds()
                ))
            except ValueError:
                pass

        if duration_seconds is None:
            duration_display = '—'
        elif duration_seconds >= 60:
            duration_display = f'{duration_seconds // 60}m {duration_seconds % 60}s'
        else:
            duration_display = f'{duration_seconds}s'

        history.append({
            'task_id': task.get('id'),
            'run_id': run.get('id'),
            'name': task.get('name') or '—',
            'image': task.get('image') or '—',
            'started_at': started_at,
            'finished_at': finished_at,
            'duration_display': duration_display,
            'status': status,
        })

    total_pages = max(1, (total + per_page - 1) // per_page)
    return {'tasks': history, 'page': page, 'per_page': per_page, 'total': total, 'total_pages': total_pages}


@app.route('/')
def index():
    """Dashboard showing overview of all nodes"""
    configs = get_node_configs()
    running_nodes = get_running_nodes()
    
    # Enrich configs with running status
    for config in configs:
        status = get_node_status(config['name'], config['type'] == 'system')
        config['status'] = status
    
    return render_template('index.html', 
                         configs=configs, 
                         running_nodes=running_nodes,
                         total_configs=len(configs),
                         running_count=len([c for c in configs if c['status'] == 'running']))


@app.route('/nodes')
def list_nodes():
    """List all node configurations"""
    configs = get_node_configs()
    
    # Add status to each config
    for config in configs:
        status = get_node_status(config['name'], config['type'] == 'system')
        config['status'] = status
    
    return render_template('nodes.html', configs=configs)


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


@app.route('/nodes/new', methods=['GET', 'POST'])
def new_node():
    """Create a new node configuration"""
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            server_url = request.form.get('server_url')
            api_key = request.form.get('api_key')
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
            
            if encryption_enabled:
                flash(f'Node configuration "{name}" created successfully with encryption enabled!', 'success')
            else:
                flash(f'Node configuration "{name}" created successfully!', 'success')
            return redirect(url_for('list_nodes'))
            
        except Exception as e:
            flash(f'Error creating configuration: {str(e)}', 'error')
    
    return render_template('new_node.html')


@app.route('/nodes/<name>/edit', methods=['GET', 'POST'])
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

    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('list_nodes'))

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

            if get_node_status(name, config['type'] == 'system') == 'running':
                flash(f'Node configuration "{name}" updated. Restart the node for the changes to take effect.', 'success')
            else:
                flash(f'Node configuration "{name}" updated.', 'success')
            return redirect(url_for('view_node', name=name))

        except Exception as e:
            flash(f'Error updating configuration: {str(e)}', 'error')

    return render_template('edit_node.html', config=config)


@app.route('/nodes/<name>')
def view_node(name):
    """View details of a specific node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    
    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('list_nodes'))
    
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


@app.route('/nodes/<name>/start', methods=['POST'])
def start_node(name):
    """Start a node container following official vantage6 implementation"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    
    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('list_nodes'))
    
    client = get_docker_client()
    if not client:
        return redirect(url_for('view_node', name=name))
    
    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"
        
        # Check if already running
        previous_image = None
        try:
            existing = client.containers.get(container_name)
            if existing.status == 'running':
                flash(f'Node "{name}" is already running', 'warning')
                return redirect(url_for('view_node', name=name))
            else:
                # Remember the image this node was last running, so a restart
                # doesn't depend on re-detecting/re-pulling an image (which may
                # live in a registry that isn't reachable from this host)
                if existing.image and existing.image.tags:
                    previous_image = existing.image.tags[0]
                # Remove the existing stopped container and recreate it
                existing.remove()
                flash(f'Removed existing stopped container, creating new one...', 'info')
        except docker.errors.NotFound:
            # Container doesn't exist, will create below
            pass

        # Determine image version from server if not specified
        image = request.form.get('image') or previous_image
        if image and image == previous_image:
            flash(f'Reusing previously used node image: {image}', 'info')

        if not image:
            # Get server version to determine appropriate node image
            server_url = config['data'].get('server_url')
            api_path = config['data'].get('api_path', '/api')
            port = config['data'].get('port')

            version, error = (None, 'No server URL configured')
            if server_url:
                version, error = get_server_version(server_url, api_path, port)

            if version:
                image = find_local_node_image(client, version)
                if image:
                    flash(f'Using locally available node image matching server version {version}: {image}', 'info')
                else:
                    image = get_node_image_for_version(version)
                    flash(f'Using node image for server version {version}', 'info')
            else:
                image = find_local_node_image(client)
                if image:
                    flash(f'Could not detect server version ({error}). Using locally available node image: {image}', 'warning')
                else:
                    image = 'harbor2.vantage6.ai/infrastructure/node:latest'
                    flash(f'Could not detect server version ({error}). Using latest node image.', 'warning')
        
        # Create Docker volumes (similar to official implementation)
        # These volumes persist data, VPN config, SSH config, and Squid proxy config
        data_volume_name = f"{container_name}-vol"
        vpn_volume_name = f"{container_name}-vpn-vol"
        ssh_volume_name = f"{container_name}-ssh-vol"
        squid_volume_name = f"{container_name}-squid-vol"
        
        # Create volumes if they don't exist
        try:
            data_volume = client.volumes.get(data_volume_name)
        except docker.errors.NotFound:
            data_volume = client.volumes.create(data_volume_name)
            flash(f'Created data volume: {data_volume_name}', 'info')
        
        try:
            vpn_volume = client.volumes.get(vpn_volume_name)
        except docker.errors.NotFound:
            vpn_volume = client.volumes.create(vpn_volume_name)
            flash(f'Created VPN volume: {vpn_volume_name}', 'info')
        
        try:
            ssh_volume = client.volumes.get(ssh_volume_name)
        except docker.errors.NotFound:
            ssh_volume = client.volumes.create(ssh_volume_name)
            flash(f'Created SSH volume: {ssh_volume_name}', 'info')
        
        try:
            squid_volume = client.volumes.get(squid_volume_name)
        except docker.errors.NotFound:
            squid_volume = client.volumes.create(squid_volume_name)
            flash(f'Created Squid volume: {squid_volume_name}', 'info')
        
        # Convert container path to host path for config directory
        config_path = Path(config['path'])
        config_dir_host_path = container_path_to_host_path(str(config_path.parent))
        
        if not config_dir_host_path:
            flash(f'Error: Cannot mount config directory - path not in mounted volume', 'error')
            return redirect(url_for('view_node', name=name))
        
        # Get log directory from config
        log_dir_path = config['data'].get('logging', {}).get('file')
        if log_dir_path:
            log_dir = Path(log_dir_path).parent
            log_dir_host_path = container_path_to_host_path(str(log_dir))
        else:
            # Default log directory
            log_dir = VANTAGE6_DATA_DIR / name / 'log'
            log_dir.mkdir(parents=True, exist_ok=True)
            log_dir_host_path = container_path_to_host_path(str(log_dir))
        
        # Build volume mounts similar to official vantage6 implementation
        # Format: host_path:container_path or volume_name:container_path
        volumes = [
            f"{log_dir_host_path}:/mnt/log",
            f"{data_volume.name}:/mnt/data",
            f"{vpn_volume.name}:/mnt/vpn",
            f"{ssh_volume.name}:/mnt/ssh",
            f"{squid_volume.name}:/mnt/squid",
            f"{config_dir_host_path}:/mnt/config",
            "/var/run/docker.sock:/var/run/docker.sock"
        ]
        
        # Mount private key file if encryption is enabled
        encryption_config = config['data'].get('encryption', {})
        if encryption_config.get('enabled') and encryption_config.get('private_key'):
            # The private key path in config is relative to VANTAGE6_CONFIG_DIR.parent
            # e.g. "node/private_keys/mynode_private_key.pem"
            private_key_relative = encryption_config['private_key']
            private_key_config_path = str(VANTAGE6_CONFIG_DIR.parent / private_key_relative)
            private_key_host_path = container_path_to_host_path(private_key_config_path)
            if private_key_host_path:
                volumes.append(f"{private_key_host_path}:/mnt/private_key.pem")
            else:
                flash(f'Warning: Could not resolve host path for private key '
                      f'"{private_key_config_path}". Verify your encryption configuration.', 'warning')
        
        # Build environment variables similar to official implementation
        env = {
            'DATA_VOLUME_NAME': data_volume.name,
            'VPN_VOLUME_NAME': vpn_volume.name,
            'SSH_TUNNEL_VOLUME_NAME': ssh_volume.name,
            'SSH_SQUID_VOLUME_NAME': squid_volume.name,
        }
        
        # Only set PRIVATE_KEY env var when encryption is enabled
        if encryption_config.get('enabled'):
            env['PRIVATE_KEY'] = '/mnt/private_key.pem'

        # Add database URIs as environment variables (required for dockerized nodes).
        # File-based databases also need to be bind-mounted into the node container -
        # see build_database_env_and_volumes() for why.
        db_env, db_volumes = build_database_env_and_volumes(config['data'].get('databases'))
        env.update(db_env)
        volumes.extend(db_volumes)

        # Build the command to run inside the container
        # This is the critical missing piece - the container needs a command!
        system_folders_option = "--system" if config['type'] == 'system' else "--user"
        cmd = f"vnode-local start --name {name} --config /mnt/config/{config_path.name} --dockerized {system_folders_option}"
        
        # Create and start the container
        container = client.containers.run(
            image,
            command=cmd,
            volumes=volumes,
            detach=True,
            labels={
                f'{APPNAME}-type': 'node',
                'system': str(config['type'] == 'system'),
                'name': name
            },
            environment=env,
            name=container_name,
            auto_remove=False,
            tty=True,
            extra_hosts={"host.docker.internal": "host-gateway"}
        )
        
        flash(f'Node "{name}" started successfully', 'success')
    
    except Exception as e:
        import sys
        print(f"ERROR starting node: {str(e)}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        flash(f'Error starting node: {str(e)}', 'error')
    
    return redirect(url_for('view_node', name=name))


@app.route('/nodes/<name>/stop', methods=['POST'])
def stop_node(name):
    """Stop a running node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    
    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('list_nodes'))
    
    client = get_docker_client()
    if not client:
        return redirect(url_for('view_node', name=name))
    
    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"
        
        container = client.containers.get(container_name)
        container.stop()
        flash(f'Node "{name}" stopped successfully', 'success')
    
    except docker.errors.NotFound:
        flash(f'Node "{name}" is not running', 'warning')
    except Exception as e:
        flash(f'Error stopping node: {str(e)}', 'error')
    
    return redirect(url_for('view_node', name=name))


@app.route('/nodes/<name>/restart', methods=['POST'])
def restart_node(name):
    """Restart a node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    
    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('list_nodes'))
    
    client = get_docker_client()
    if not client:
        return redirect(url_for('view_node', name=name))
    
    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"
        
        container = client.containers.get(container_name)
        container.restart()
        flash(f'Node "{name}" restarted successfully', 'success')
    
    except docker.errors.NotFound:
        flash(f'Node "{name}" is not running', 'warning')
    except Exception as e:
        flash(f'Error restarting node: {str(e)}', 'error')
    
    return redirect(url_for('view_node', name=name))


@app.route('/nodes/<name>/logs')
def view_logs(name):
    """View logs of a running node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    
    if not config:
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


@app.route('/nodes/<name>/delete', methods=['POST'])
def delete_node(name):
    """Delete a node configuration"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    
    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('list_nodes'))

    try:
        # Delete configuration file. This only removes the config from the
        # node manager - if the node's container is still running, it is
        # left untouched and keeps running unmanaged.
        os.remove(config['path'])
        flash(f'Node configuration "{name}" deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting configuration: {str(e)}', 'error')

    return redirect(url_for('list_nodes'))


@app.route('/nodes/<name>/export')
def export_node(name):
    """
    Export a node's config as a download. Plain .yaml when there's nothing
    else to bundle; a .zip (config + private key) only when encryption is
    enabled and a key file needs to travel with it.
    """
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config:
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('list_nodes'))

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
    """Shared final step for import_node: refuse name collisions, write the yaml"""
    existing_configs = get_node_configs()
    if any(c['name'] == name for c in existing_configs):
        return f'A node named "{name}" already exists. Rename or delete it first, then retry the import.'

    config_file = VANTAGE6_CONFIG_DIR / f'{name}.yaml'
    with open(config_file, 'w') as f:
        yaml.dump(config_data, f, default_flow_style=False)
    return None


@app.route('/nodes/import', methods=['GET', 'POST'])
def import_node():
    """Import a node config from a previously exported .yaml file or .zip backup"""
    if request.method == 'GET':
        return render_template('import_node.html')

    upload = request.files.get('backup_file')
    if not upload or not upload.filename:
        flash('No backup file selected', 'error')
        return redirect(url_for('import_node'))

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
                return redirect(url_for('import_node'))

        elif filename.endswith('.zip'):
            with zipfile.ZipFile(upload.stream) as zf:
                yaml_names = [n for n in zf.namelist() if n.endswith('.yaml')]
                if len(yaml_names) != 1:
                    flash('Backup zip must contain exactly one node config (.yaml) file', 'error')
                    return redirect(url_for('import_node'))

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
                    return redirect(url_for('import_node'))

        else:
            flash('Unsupported file type. Upload a .yaml file or a .zip backup.', 'error')
            return redirect(url_for('import_node'))

        flash(f'Node configuration "{name}" imported successfully', 'success')
        return redirect(url_for('view_node', name=name))

    except zipfile.BadZipFile:
        flash('Uploaded file is not a valid backup zip', 'error')
        return redirect(url_for('import_node'))
    except yaml.YAMLError:
        flash('Uploaded file is not valid YAML', 'error')
        return redirect(url_for('import_node'))
    except Exception as e:
        flash(f'Error importing configuration: {str(e)}', 'error')
        return redirect(url_for('import_node'))


@app.route('/nodes/bulk/start', methods=['POST'])
def bulk_start_nodes():
    names = request.form.getlist('names')
    if not names:
        flash('No nodes selected', 'warning')
        return redirect(url_for('list_nodes'))

    configs = get_node_configs()
    client = get_docker_client()
    if not client:
        return redirect(url_for('list_nodes'))

    started = []
    errors = []
    for name in names:
        config = next((c for c in configs if c['name'] == name), None)
        if not config:
            errors.append(f'{name}: not found')
            continue
        status = get_node_status(name, config['type'] == 'system')
        if status == 'running':
            errors.append(f'{name}: already running')
            continue
        try:
            postfix = "system" if config['type'] == 'system' else "user"
            container_name = f"{APPNAME}-{name}-{postfix}"

            previous_image = None
            try:
                existing = client.containers.get(container_name)
                if existing.image and existing.image.tags:
                    previous_image = existing.image.tags[0]
                existing.remove()
            except docker.errors.NotFound:
                pass

            image = previous_image

            if not image:
                server_url = config['data'].get('server_url')
                api_path = config['data'].get('api_path', '/api')
                port = config['data'].get('port')
                version = None
                if server_url:
                    version, error = get_server_version(server_url, api_path, port)
                image = find_local_node_image(client, version)
                if not image and version:
                    image = get_node_image_for_version(version)
            if not image:
                image = 'harbor2.vantage6.ai/infrastructure/node:latest'

            data_volume_name = f"{container_name}-vol"
            vpn_volume_name = f"{container_name}-vpn-vol"
            ssh_volume_name = f"{container_name}-ssh-vol"
            squid_volume_name = f"{container_name}-squid-vol"

            for vol_name in [data_volume_name, vpn_volume_name, ssh_volume_name, squid_volume_name]:
                try:
                    client.volumes.get(vol_name)
                except docker.errors.NotFound:
                    client.volumes.create(vol_name)

            data_volume = client.volumes.get(data_volume_name)
            vpn_volume = client.volumes.get(vpn_volume_name)
            ssh_volume = client.volumes.get(ssh_volume_name)
            squid_volume = client.volumes.get(squid_volume_name)

            config_path = Path(config['path'])
            config_dir_host_path = container_path_to_host_path(str(config_path.parent))
            if not config_dir_host_path:
                errors.append(f'{name}: cannot mount config directory')
                continue

            log_dir_path = config['data'].get('logging', {}).get('file')
            if log_dir_path:
                log_dir = Path(log_dir_path).parent
                log_dir_host_path = container_path_to_host_path(str(log_dir))
            else:
                log_dir = VANTAGE6_DATA_DIR / name / 'log'
                log_dir.mkdir(parents=True, exist_ok=True)
                log_dir_host_path = container_path_to_host_path(str(log_dir))

            volumes = [
                f"{log_dir_host_path}:/mnt/log",
                f"{data_volume.name}:/mnt/data",
                f"{vpn_volume.name}:/mnt/vpn",
                f"{ssh_volume.name}:/mnt/ssh",
                f"{squid_volume.name}:/mnt/squid",
                f"{config_dir_host_path}:/mnt/config",
                "/var/run/docker.sock:/var/run/docker.sock"
            ]

            env = {
                'DATA_VOLUME_NAME': data_volume.name,
                'VPN_VOLUME_NAME': vpn_volume.name,
                'SSH_TUNNEL_VOLUME_NAME': ssh_volume.name,
                'SSH_SQUID_VOLUME_NAME': squid_volume.name,
                'PRIVATE_KEY': '/mnt/private_key.pem'
            }

            db_env, db_volumes = build_database_env_and_volumes(config['data'].get('databases'))
            env.update(db_env)
            volumes.extend(db_volumes)

            system_folders_option = "--system" if config['type'] == 'system' else "--user"
            cmd = f"vnode-local start --name {name} --config /mnt/config/{config_path.name} --dockerized {system_folders_option}"

            client.containers.run(
                image,
                command=cmd,
                volumes=volumes,
                detach=True,
                labels={
                    f'{APPNAME}-type': 'node',
                    'system': str(config['type'] == 'system'),
                    'name': name
                },
                environment=env,
                name=container_name,
                auto_remove=False,
                tty=True
            )
            started.append(name)
        except Exception as e:
            errors.append(f'{name}: {str(e)}')

    if started:
        flash(f'Started {len(started)} node(s): {", ".join(started)}', 'success')
    for err in errors:
        flash(err, 'error')

    return redirect(url_for('list_nodes'))


@app.route('/nodes/bulk/stop', methods=['POST'])
def bulk_stop_nodes():
    names = request.form.getlist('names')
    if not names:
        flash('No nodes selected', 'warning')
        return redirect(url_for('list_nodes'))

    configs = get_node_configs()
    client = get_docker_client()
    if not client:
        return redirect(url_for('list_nodes'))

    stopped = []
    errors = []
    for name in names:
        config = next((c for c in configs if c['name'] == name), None)
        if not config:
            errors.append(f'{name}: not found')
            continue
        try:
            postfix = "system" if config['type'] == 'system' else "user"
            container_name = f"{APPNAME}-{name}-{postfix}"

            container = client.containers.get(container_name)
            container.stop()
            stopped.append(name)
        except docker.errors.NotFound:
            errors.append(f'{name}: not running')
        except Exception as e:
            errors.append(f'{name}: {str(e)}')

    if stopped:
        flash(f'Stopped {len(stopped)} node(s): {", ".join(stopped)}', 'success')
    for err in errors:
        flash(err, 'error')

    return redirect(url_for('list_nodes'))


@app.route('/nodes/bulk/delete', methods=['POST'])
def bulk_delete_nodes():
    names = request.form.getlist('names')
    if not names:
        flash('No nodes selected', 'warning')
        return redirect(url_for('list_nodes'))

    configs = get_node_configs()
    deleted = []
    errors = []
    for name in names:
        config = next((c for c in configs if c['name'] == name), None)
        if not config:
            errors.append(f'{name}: not found')
            continue
        try:
            os.remove(config['path'])
            deleted.append(name)
        except Exception as e:
            errors.append(f'{name}: {str(e)}')

    if deleted:
        flash(f'Deleted {len(deleted)} node(s): {", ".join(deleted)}', 'success')
    for err in errors:
        flash(err, 'error')

    return redirect(url_for('list_nodes'))


@app.route('/api/nodes')
def api_list_nodes():
    """API endpoint to list all nodes"""
    configs = get_node_configs()
    for config in configs:
        status = get_node_status(config['name'], config['type'] == 'system')
        config['status'] = status
    return jsonify(configs)


@app.route('/api/nodes/<name>/health')
def api_node_health(name):
    """API endpoint to get the node's health status from the vantage6 server"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config:
        return jsonify({'error': 'Node not found'}), 404

    health = get_node_health_status(config)
    health['name'] = name
    health['tasks'] = get_running_tasks(name) if health['status'] != 'stopped' else []
    return jsonify(health)


@app.route('/api/nodes/<name>/tasks')
def api_node_tasks(name):
    """API endpoint to get a node's task execution history from the vantage6 server"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config:
        return jsonify({'error': 'Node not found'}), 404

    per_page = request.args.get('limit', 10, type=int)
    per_page = max(1, min(per_page, 100))
    page = request.args.get('page', 1, type=int)
    page = max(1, page)

    result = get_task_history(config, per_page=per_page, page=page)
    return jsonify({
        'history': result['tasks'],
        'page': result['page'],
        'per_page': result['per_page'],
        'total': result['total'],
        'total_pages': result['total_pages'],
    })


@app.route('/api/server/version')
def api_server_version():
    """API endpoint to check a Vantage6 server's version"""
    server_url = request.args.get('server_url')
    api_path = request.args.get('api_path', '/api')
    port = request.args.get('port')

    if not server_url:
        return jsonify({'error': 'server_url parameter is required'}), 400

    version, error = get_server_version(server_url, api_path, port)
    
    if error:
        return jsonify({
            'success': False,
            'error': error,
            'server_url': server_url
        }), 200
    
    recommended_image = get_node_image_for_version(version)
    
    return jsonify({
        'success': True,
        'version': version,
        'server_url': server_url,
        'recommended_image': recommended_image
    })


@app.route('/api/encryption/generate-key', methods=['POST'])
def api_generate_encryption_key():
    """API endpoint to generate a new RSA key pair for encryption"""
    try:
        private_key_pem, public_key_pem = generate_rsa_key_pair()
        
        if not private_key_pem or not public_key_pem:
            return jsonify({
                'success': False,
                'error': 'Failed to generate RSA key pair'
            }), 500
        
        return jsonify({
            'success': True,
            'private_key': private_key_pem,
            'public_key': public_key_pem,
            'message': 'RSA key pair generated successfully. Please download and save your private key securely!'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error generating key pair: {str(e)}'
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
