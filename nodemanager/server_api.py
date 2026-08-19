"""Talking to the vantage6 server's own API: version, node auth session, health, task history.

Depends on docker_utils (get_docker_client) - keep this dependency one-directional;
docker_utils must never import from this module.
"""
import docker
import requests
from datetime import datetime

from nodemanager.config import APPNAME
from nodemanager.docker_utils import get_docker_client


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


# The node-manager doesn't depend on the vantage6 package itself, so these
# mirror vantage6.common.task_status.TaskStatus - the raw 'status' strings a
# run can have on the server, and their operator-facing labels. Everything
# NOT in _ACTIVE_STATUSES is treated as a failure (matching that module's own
# has_task_failed()), so a status vantage6 adds in a future release still
# surfaces as an error instead of being silently mislabeled as pending.
_ACTIVE_STATUSES = {'pending', 'initializing', 'active', 'completed'}

_ERROR_LABELS = {
    'failed': 'Failed',
    'start failed': 'Failed to start',
    'non-existing Docker image': 'Algorithm image not found',
    'crashed': 'Crashed',
    'killed by user': 'Killed',
    'not allowed': 'Not allowed by node policy',
    'unknown error': 'Unknown error',
}


def _error_label(raw_status):
    """Operator-facing label for a failed run's raw server status."""
    if raw_status in _ERROR_LABELS:
        return _ERROR_LABELS[raw_status]
    if not raw_status:
        return 'Unknown error'
    return raw_status.replace('_', ' ').capitalize()


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
        raw_status = run.get('status')

        status_label = None
        if raw_status not in _ACTIVE_STATUSES:
            # A failure can happen before the run ever gets a started_at/
            # finished_at (e.g. rejected by node policy, missing image) -
            # check this first so those don't fall through to 'pending'.
            status = 'error'
            status_label = _error_label(raw_status)
        elif finished_at:
            status = 'completed'
        elif started_at:
            status = 'running'
        else:
            status = 'pending'

        if status_label is None:
            status_label = status.capitalize()

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
            'status_label': status_label,
        })

    total_pages = max(1, (total + per_page - 1) // per_page)
    return {'tasks': history, 'page': page, 'per_page': per_page, 'total': total, 'total_pages': total_pages}
