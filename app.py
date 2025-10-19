"""
Vantage6 Node Manager Web Application
A Flask-based web interface for managing vantage6 nodes
"""
import os
import yaml
import docker
import requests
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from pathlib import Path

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Configuration
VANTAGE6_CONFIG_DIR = Path.home() / '.config' / 'vantage6' / 'node'
VANTAGE6_SYSTEM_CONFIG_DIR = Path('/etc/vantage6/node')
APPNAME = 'vantage6'

# Ensure config directory exists
VANTAGE6_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


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
            task_dir = request.form.get('task_dir', '/tmp/vantage6')
            
            # Database configuration
            db_label = request.form.get('db_label', 'default')
            db_uri = request.form.get('db_uri')
            db_type = request.form.get('db_type', 'csv')
            
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
                    'level': 'INFO',
                    'file': f'{name}.log'
                },
                'encryption': {
                    'enabled': False
                }
            }
            
            # Save configuration
            config_file = VANTAGE6_CONFIG_DIR / f'{name}.yaml'
            with open(config_file, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
            
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
    """Start a node"""
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
                existing.start()
                flash(f'Node "{name}" started successfully', 'success')
        except docker.errors.NotFound:
            # Create and start new container
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
                        # Fallback to default if version detection fails
                        image = 'harbor2.vantage6.ai/infrastructure/node:latest'
                        flash(f'Could not detect server version ({error}). Using latest node image.', 'warning')
                else:
                    image = 'harbor2.vantage6.ai/infrastructure/node:latest'
                    flash('No server URL configured. Using latest node image.', 'warning')
            
            # Mount configuration
            volumes = {
                config['path']: {'bind': '/mnt/config.yaml', 'mode': 'ro'}
            }
            
            # Mount databases if they exist
            if config['data'].get('databases'):
                for db in config['data']['databases']:
                    db_path = Path(db['uri'])
                    if db_path.exists() and db_path.is_file():
                        volumes[str(db_path)] = {'bind': f'/mnt/data/{db["label"]}', 'mode': 'ro'}
            
            container = client.containers.run(
                image,
                name=container_name,
                detach=True,
                volumes=volumes,
                environment={
                    'VANTAGE6_CONFIG_FILE': '/mnt/config.yaml'
                },
                labels={
                    'vantage6-type': 'node',
                    'vantage6-name': name
                }
            )
            flash(f'Node "{name}" started successfully', 'success')
    
    except Exception as e:
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
