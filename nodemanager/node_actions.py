"""Routes that mutate a running container's state via the Docker daemon: start,
stop, restart (singly or in bulk). Passive views (logs) live in nodes.py
instead - see the split rationale in the refactor plan. Delete/bulk-delete
also live in nodes.py despite mutating container state, since admin's "real
delete" removes the container/volumes as part of the same config mutation.
"""
import os
import docker
from pathlib import Path
from flask import Blueprint, request, redirect, url_for, flash
from flask_login import current_user

from nodemanager.config import VANTAGE6_CONFIG_DIR, VANTAGE6_DATA_DIR, APPNAME
from nodemanager.docker_utils import (
    get_docker_client, get_node_status, find_local_node_image,
    get_node_image_for_version, build_database_env_and_volumes, container_path_to_host_path
)
from nodemanager.node_config import get_node_configs, can_access_config
from nodemanager.server_api import get_server_version
from nodemanager.auth import require_operator
from nodemanager.audit import log_event

actions_bp = Blueprint('actions', __name__)
# Every route in this blueprint mutates container state via the Docker daemon -
# gate the whole blueprint at once rather than decorating each route. Admin and
# operator can both act here; only /users is admin-only. Registered here (not in
# auth.init_app) to avoid a circular import: auth.py must not import from this module.
actions_bp.before_request(require_operator)


@actions_bp.route('/nodes/<name>/start', methods=['POST'])
def start_node(name):
    """Start a node container following official vantage6 implementation"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    client = get_docker_client()
    if not client:
        return redirect(url_for('nodes.view_node', name=name))

    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"

        # Check if already running
        previous_image = None
        try:
            existing = client.containers.get(container_name)
            if existing.status == 'running':
                flash(f'Node "{name}" is already running', 'warning')
                return redirect(url_for('nodes.view_node', name=name))
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
            return redirect(url_for('nodes.view_node', name=name))

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

        log_event(current_user.id, current_user.role, 'node.start', node_name=name)
        flash(f'Node "{name}" started successfully', 'success')

    except Exception as e:
        import sys
        print(f"ERROR starting node: {str(e)}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc()
        flash(f'Error starting node: {str(e)}', 'error')

    return redirect(url_for('nodes.view_node', name=name))


@actions_bp.route('/nodes/<name>/stop', methods=['POST'])
def stop_node(name):
    """Stop a running node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    client = get_docker_client()
    if not client:
        return redirect(url_for('nodes.view_node', name=name))

    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"

        container = client.containers.get(container_name)
        container.stop()
        log_event(current_user.id, current_user.role, 'node.stop', node_name=name)
        flash(f'Node "{name}" stopped successfully', 'success')

    except docker.errors.NotFound:
        flash(f'Node "{name}" is not running', 'warning')
    except Exception as e:
        flash(f'Error stopping node: {str(e)}', 'error')

    return redirect(url_for('nodes.view_node', name=name))


@actions_bp.route('/nodes/<name>/restart', methods=['POST'])
def restart_node(name):
    """Restart a node"""
    configs = get_node_configs()
    config = next((c for c in configs if c['name'] == name), None)

    if not config or not can_access_config(config, current_user.role, current_user.id):
        flash(f'Node configuration "{name}" not found', 'error')
        return redirect(url_for('nodes.list_nodes'))

    client = get_docker_client()
    if not client:
        return redirect(url_for('nodes.view_node', name=name))

    try:
        postfix = "system" if config['type'] == 'system' else "user"
        container_name = f"{APPNAME}-{name}-{postfix}"

        container = client.containers.get(container_name)
        container.restart()
        log_event(current_user.id, current_user.role, 'node.restart', node_name=name)
        flash(f'Node "{name}" restarted successfully', 'success')

    except docker.errors.NotFound:
        flash(f'Node "{name}" is not running', 'warning')
    except Exception as e:
        flash(f'Error restarting node: {str(e)}', 'error')

    return redirect(url_for('nodes.view_node', name=name))


@actions_bp.route('/nodes/bulk/start', methods=['POST'])
def bulk_start_nodes():
    names = request.form.getlist('names')
    if not names:
        flash('No nodes selected', 'warning')
        return redirect(url_for('nodes.list_nodes'))

    configs = get_node_configs()
    client = get_docker_client()
    if not client:
        return redirect(url_for('nodes.list_nodes'))

    started = []
    errors = []
    for name in names:
        config = next((c for c in configs if c['name'] == name), None)
        if not config or not can_access_config(config, current_user.role, current_user.id):
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

            # Mount private key file if encryption is enabled - same logic as
            # start_node(). Without the matching volume mount, an encrypted
            # node would boot with PRIVATE_KEY pointed at a path that was
            # never actually mounted into the container.
            encryption_config = config['data'].get('encryption', {})
            if encryption_config.get('enabled') and encryption_config.get('private_key'):
                private_key_relative = encryption_config['private_key']
                private_key_config_path = str(VANTAGE6_CONFIG_DIR.parent / private_key_relative)
                private_key_host_path = container_path_to_host_path(private_key_config_path)
                if private_key_host_path:
                    volumes.append(f"{private_key_host_path}:/mnt/private_key.pem")
                else:
                    errors.append(f'{name}: could not resolve host path for private key '
                                   f'"{private_key_config_path}"')
                    continue

            env = {
                'DATA_VOLUME_NAME': data_volume.name,
                'VPN_VOLUME_NAME': vpn_volume.name,
                'SSH_TUNNEL_VOLUME_NAME': ssh_volume.name,
                'SSH_SQUID_VOLUME_NAME': squid_volume.name,
            }

            # Only set PRIVATE_KEY env var when encryption is enabled - same as start_node().
            if encryption_config.get('enabled'):
                env['PRIVATE_KEY'] = '/mnt/private_key.pem'

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
                tty=True,
                extra_hosts={"host.docker.internal": "host-gateway"}
            )
            log_event(current_user.id, current_user.role, 'node.start', node_name=name, details='bulk')
            started.append(name)
        except Exception as e:
            errors.append(f'{name}: {str(e)}')

    if started:
        flash(f'Started {len(started)} node(s): {", ".join(started)}', 'success')
    for err in errors:
        flash(err, 'error')

    return redirect(url_for('nodes.list_nodes'))


@actions_bp.route('/nodes/bulk/stop', methods=['POST'])
def bulk_stop_nodes():
    names = request.form.getlist('names')
    if not names:
        flash('No nodes selected', 'warning')
        return redirect(url_for('nodes.list_nodes'))

    configs = get_node_configs()
    client = get_docker_client()
    if not client:
        return redirect(url_for('nodes.list_nodes'))

    stopped = []
    errors = []
    for name in names:
        config = next((c for c in configs if c['name'] == name), None)
        if not config or not can_access_config(config, current_user.role, current_user.id):
            errors.append(f'{name}: not found')
            continue
        try:
            postfix = "system" if config['type'] == 'system' else "user"
            container_name = f"{APPNAME}-{name}-{postfix}"

            container = client.containers.get(container_name)
            container.stop()
            log_event(current_user.id, current_user.role, 'node.stop', node_name=name, details='bulk')
            stopped.append(name)
        except docker.errors.NotFound:
            errors.append(f'{name}: not running')
        except Exception as e:
            errors.append(f'{name}: {str(e)}')

    if stopped:
        flash(f'Stopped {len(stopped)} node(s): {", ".join(stopped)}', 'success')
    for err in errors:
        flash(err, 'error')

    return redirect(url_for('nodes.list_nodes'))
