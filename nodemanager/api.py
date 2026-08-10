"""JSON API endpoints consumed by the frontend's own JS (health polling, task
history, server version lookup, RSA key generation) as well as external tools.
"""
from flask import Blueprint, request, jsonify

from nodemanager.docker_utils import get_node_status, get_node_image_for_version
from nodemanager.node_config import get_node_configs
from nodemanager.server_api import get_server_version, get_node_health_status, get_running_tasks, get_task_history
from nodemanager.crypto import generate_rsa_key_pair
from nodemanager.auth import admin_required

api_bp = Blueprint('api', __name__)


@api_bp.route('/api/nodes')
def api_list_nodes():
    """API endpoint to list all nodes"""
    configs = get_node_configs()
    for config in configs:
        status = get_node_status(config['name'], config['type'] == 'system')
        config['status'] = status
        # api_key is a live credential the node uses to authenticate to the
        # vantage6 server - the browser has no legitimate use for it back,
        # and this endpoint is viewer-accessible, so it must never round-trip.
        if config.get('data'):
            config['data'] = {k: v for k, v in config['data'].items() if k != 'api_key'}
    return jsonify(configs)


@api_bp.route('/api/nodes/<name>/health')
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


@api_bp.route('/api/nodes/<name>/tasks')
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


@api_bp.route('/api/server/version')
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


@api_bp.route('/api/encryption/generate-key', methods=['POST'])
@admin_required
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
