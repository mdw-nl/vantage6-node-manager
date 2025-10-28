"""
Vantage6 Node Manager Web Application
A Flask-based web interface for managing vantage6 nodes
"""
import os
import yaml
import docker
import requests
import shutil
import base64
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
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


def get_docker_client():
    """Get Docker client instance"""
    try:
        return docker.from_env()
    except Exception as e:
        flash(f'Docker is not running or not accessible: {str(e)}', 'error')
        return None


def get_server_version(server_url, api_path='/api'):
    """
    Get the Vantage6 server version from the server's version endpoint.
    
    Args:
        server_url: Base URL of the Vantage6 server
        api_path: API path (default: '/api')
    
    Returns:
        tuple: (version_string, error_message)
               Returns (None, error_msg) if version cannot be retrieved
    """
    try:
        # Construct the version endpoint URL
        if not server_url.endswith('/'):
            server_url += '/'
        
        # Remove leading slash from api_path if present
        api_path = api_path.lstrip('/')
        
        version_url = f"{server_url}{api_path}/version"
        
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
        return container.status
    except docker.errors.NotFound:
        return 'stopped'
    except Exception as e:
        print(f"Error checking node status: {e}")
        return 'error'


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
            
            # Encryption configuration
            encryption_enabled = request.form.get('encryption_enabled') == 'on'
            private_key_path = None
            
            if encryption_enabled:
                # Check if key was generated or uploaded
                key_source = request.form.get('key_source', 'upload')
                
                if key_source == 'generate':
                    # Handle generated private key
                    generated_private_key = request.form.get('generated_private_key')
                    if generated_private_key:
                        # Create a private_keys subdirectory if it doesn't exist
                        keys_dir = VANTAGE6_CONFIG_DIR / 'private_keys'
                        keys_dir.mkdir(parents=True, exist_ok=True)
                        
                        # Save with node name
                        safe_filename = f"{name}_private_key.pem"
                        private_key_path = keys_dir / safe_filename
                        
                        # Write the generated key to file
                        with open(private_key_path, 'w') as f:
                            f.write(generated_private_key)
                        
                        # Set proper permissions (read-only for owner)
                        os.chmod(str(private_key_path), 0o600)
                        
                        # Store relative path in config for portability
                        private_key_path = str(private_key_path.relative_to(VANTAGE6_CONFIG_DIR.parent))
                        
                        flash(f'Generated private key saved securely', 'success')
                    else:
                        flash('Encryption enabled but no private key was generated', 'error')
                        encryption_enabled = False
                else:
                    # Handle private key file upload
                    if 'private_key_file' in request.files:
                        private_key_file = request.files['private_key_file']
                        if private_key_file and private_key_file.filename:
                            # Secure the filename and save to config directory
                            filename = secure_filename(private_key_file.filename)
                            
                            # Create a private_keys subdirectory if it doesn't exist
                            keys_dir = VANTAGE6_CONFIG_DIR / 'private_keys'
                            keys_dir.mkdir(parents=True, exist_ok=True)
                            
                            # Save with node name prefix to avoid conflicts
                            safe_filename = f"{name}_{filename}"
                            private_key_path = keys_dir / safe_filename
                            private_key_file.save(str(private_key_path))
                            
                            # Set proper permissions (read-only for owner)
                            os.chmod(str(private_key_path), 0o600)
                            
                            # Store relative path in config for portability
                            private_key_path = str(private_key_path.relative_to(VANTAGE6_CONFIG_DIR.parent))
                            
                            flash(f'Private key uploaded and saved securely', 'success')
                        else:
                            flash('Encryption enabled but no private key file provided', 'error')
                            encryption_enabled = False
                    else:
                        flash('Encryption enabled but no private key file uploaded', 'error')
                        encryption_enabled = False
            
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
    
    return render_template('view_node.html', config=config, container_info=container_info)


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
        try:
            existing = client.containers.get(container_name)
            if existing.status == 'running':
                flash(f'Node "{name}" is already running', 'warning')
                return redirect(url_for('view_node', name=name))
            else:
                # Remove the existing stopped container and recreate it
                existing.remove()
                flash(f'Removed existing stopped container, creating new one...', 'info')
        except docker.errors.NotFound:
            # Container doesn't exist, will create below
            pass
        
        # Determine image version from server if not specified
        image = request.form.get('image')
        
        if not image:
            # Get server version to determine appropriate node image
            server_url = config['data'].get('server_url')
            api_path = config['data'].get('api_path', '/api')
            
            if server_url:
                version, error = get_server_version(server_url, api_path)
                if version:
                    image = get_node_image_for_version(version)
                    flash(f'Using node image for server version {version}', 'info')
                else:
                    image = 'harbor2.vantage6.ai/infrastructure/node:latest'
                    flash(f'Could not detect server version ({error}). Using latest node image.', 'warning')
            else:
                image = 'harbor2.vantage6.ai/infrastructure/node:latest'
                flash('No server URL configured. Using latest node image.', 'warning')
        
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
        
        # Build environment variables similar to official implementation
        env = {
            'DATA_VOLUME_NAME': data_volume.name,
            'VPN_VOLUME_NAME': vpn_volume.name,
            'SSH_TUNNEL_VOLUME_NAME': ssh_volume.name,
            'SSH_SQUID_VOLUME_NAME': squid_volume.name,
            'PRIVATE_KEY': '/mnt/private_key.pem'
        }
        
        # Add database URIs as environment variables (required for dockerized nodes)
        # The node expects <LABEL>_DATABASE_URI environment variables
        if config['data'].get('databases'):
            for db in config['data'].get('databases'):
                label = db.get('label', '').upper()
                uri = db.get('uri', '')
                if label and uri:
                    env[f'{label}_DATABASE_URI'] = uri
        
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
            tty=True
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
    
    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"
        
        container = client.containers.get(container_name)
        logs = container.logs(tail=100).decode('utf-8')
        
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
    
    # Check if node is running
    status = get_node_status(name, config['type'] == 'system')
    if status == 'running':
        flash(f'Cannot delete running node. Please stop it first.', 'error')
        return redirect(url_for('view_node', name=name))
    
    try:
        # Delete configuration file
        os.remove(config['path'])
        flash(f'Node configuration "{name}" deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting configuration: {str(e)}', 'error')
    
    return redirect(url_for('list_nodes'))


@app.route('/api/nodes')
def api_list_nodes():
    """API endpoint to list all nodes"""
    configs = get_node_configs()
    for config in configs:
        status = get_node_status(config['name'], config['type'] == 'system')
        config['status'] = status
    return jsonify(configs)


@app.route('/api/nodes/<name>/status')
def api_node_status(name):
    """API endpoint to get node status"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)
    
    if not config:
        return jsonify({'error': 'Node not found'}), 404
    
    status = get_node_status(name, config['type'] == 'system')
    return jsonify({'name': name, 'status': status})


@app.route('/api/server/version')
def api_server_version():
    """API endpoint to check a Vantage6 server's version"""
    server_url = request.args.get('server_url')
    api_path = request.args.get('api_path', '/api')
    
    if not server_url:
        return jsonify({'error': 'server_url parameter is required'}), 400
    
    version, error = get_server_version(server_url, api_path)
    
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
