"""Docker-facing helpers: client access, container/image lookups, volume/env construction."""
import os
import docker
from pathlib import Path
from flask import flash

from nodemanager.config import APPNAME

# Database types whose "uri" is a local file/folder rather than a connection
# string (matches vantage6.cli.node.start.FILE_BASED_DATABASE_TYPES)
FILE_BASED_DATABASE_TYPES = {'folder', 'csv', 'parquet', 'excel'}


def container_path_to_host_path(container_path):
    """
    Convert a path inside the Node Manager container to the corresponding host path.
    This is needed when the Node Manager creates volumes for node containers.

    Args:
        container_path: Path as seen inside the Node Manager container

    Returns:
        Host path that Docker can mount, or None if conversion not possible
    """
    # Get the actual host HOME directory from environment variable
    # When running in Docker, this should be set to the host's HOME
    host_home = os.environ.get('HOST_HOME', str(Path.home()))
    path = Path(container_path)

    # Each (container_prefix, host_base) pair below is a mount point: everything
    # under container_prefix inside this container maps to the same relative
    # path under host_base on the real host. Compared as Path objects (not raw
    # string prefixes) so this handles container_path being the prefix directory
    # itself, with no trailing slash and nothing after it - e.g. VANTAGE6_SYSTEM_
    # CONFIG_DIR passed as-is for a *system*-type node. A string .replace() of
    # 'prefix/' never matches that case, leaving relative_path as the original
    # absolute container path - and joining an absolute path onto a pathlib Path
    # resets it entirely, silently producing the unmounted container path back
    # out as if it were a valid host path. Path.relative_to() has no such
    # footgun: relative_to() on an exact match returns '.', which joins onto
    # host_base as a no-op.
    mounts = [
        # /root/.config/vantage6 is mounted from ${HOME}/.config/vantage6 on host
        (Path('/root/.config/vantage6'), Path(host_home) / '.config' / 'vantage6'),
        # /etc/vantage6/node is mounted from ${HOME}/.config/vantage6-system on host
        (Path('/etc/vantage6/node'), Path(host_home) / '.config' / 'vantage6-system'),
        # /data is mounted from ${HOME}/vantage6-data on host
        (Path('/data'), Path(host_home) / 'vantage6-data'),
    ]

    for container_prefix, host_base in mounts:
        if path == container_prefix or container_prefix in path.parents:
            return str(host_base / path.relative_to(container_prefix))

    # Path is not in a known mounted volume
    return None


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
