"""Routes with no prior coverage at all beyond an occasional incidental
status-code check: nodes.py's view_logs(), and api.py's task-history and
server-version endpoints. The underlying logic each of these calls into
(get_task_history(), get_server_version()) is already unit-tested in
test_server_api.py - these tests are about the route wiring itself: the
ownership gate, parameter parsing/clamping, and response shape.
"""
from unittest.mock import MagicMock, patch

import docker.errors

from tests.conftest import create_node


# --- view_logs ---

def test_view_logs_not_found_for_nonexistent_node(operator_client):
    resp = operator_client.get('/nodes/does-not-exist/logs')
    assert resp.status_code == 404
    assert resp.get_json()['error'] == 'Node not found'


def test_view_logs_blocked_for_unowned_node(operator_client, operator2_client):
    create_node(operator_client, 'op1-logs-node')
    resp = operator2_client.get('/nodes/op1-logs-node/logs')
    assert resp.status_code == 404


def test_view_logs_docker_unavailable(operator_client):
    create_node(operator_client, 'logs-node-nodocker')
    with patch('nodemanager.nodes.get_docker_client', return_value=None):
        resp = operator_client.get('/nodes/logs-node-nodocker/logs')
    assert resp.status_code == 500
    assert resp.get_json()['error'] == 'Docker not available'


def test_view_logs_container_not_running(operator_client):
    create_node(operator_client, 'logs-node-stopped')
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound('no such container')
    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        resp = operator_client.get('/nodes/logs-node-stopped/logs')
    assert resp.status_code == 404
    assert resp.get_json()['error'] == 'Container not running'


def test_view_logs_returns_container_logs_with_default_tail(operator_client):
    create_node(operator_client, 'logs-node-running')
    container = MagicMock()
    container.logs.return_value = b'line1\nline2\n'
    client = MagicMock()
    client.containers.get.return_value = container
    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        resp = operator_client.get('/nodes/logs-node-running/logs')
    assert resp.status_code == 200
    assert resp.get_json()['logs'] == 'line1\nline2\n'
    container.logs.assert_called_once_with(tail=100)


def test_view_logs_tail_all_param(operator_client):
    create_node(operator_client, 'logs-node-tail-all')
    container = MagicMock()
    container.logs.return_value = b'everything'
    client = MagicMock()
    client.containers.get.return_value = container
    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        operator_client.get('/nodes/logs-node-tail-all/logs?tail=all')
    container.logs.assert_called_once_with(tail='all')


def test_view_logs_tail_numeric_param(operator_client):
    create_node(operator_client, 'logs-node-tail-num')
    container = MagicMock()
    container.logs.return_value = b'x'
    client = MagicMock()
    client.containers.get.return_value = container
    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        operator_client.get('/nodes/logs-node-tail-num/logs?tail=50')
    container.logs.assert_called_once_with(tail=50)


def test_view_logs_invalid_tail_param_falls_back_to_default(operator_client):
    create_node(operator_client, 'logs-node-tail-bad')
    container = MagicMock()
    container.logs.return_value = b'x'
    client = MagicMock()
    client.containers.get.return_value = container
    with patch('nodemanager.nodes.get_docker_client', return_value=client):
        operator_client.get('/nodes/logs-node-tail-bad/logs?tail=notanumber')
    container.logs.assert_called_once_with(tail=100)


# --- /api/nodes/<name>/tasks ---

def test_api_node_tasks_not_found(operator_client):
    resp = operator_client.get('/api/nodes/nope/tasks')
    assert resp.status_code == 404


def test_api_node_tasks_blocked_for_unowned_node(operator_client, operator2_client):
    create_node(operator_client, 'op1-tasks-node')
    resp = operator2_client.get('/api/nodes/op1-tasks-node/tasks')
    assert resp.status_code == 404


def test_api_node_tasks_returns_history_shape(operator_client):
    create_node(operator_client, 'tasks-node')
    fake_history = {
        'tasks': [{'run_id': 1, 'image': 'algo:latest', 'status': 'completed'}],
        'page': 2, 'per_page': 5, 'total': 11, 'total_pages': 3,
    }
    with patch('nodemanager.api.get_task_history', return_value=fake_history) as mock_hist:
        resp = operator_client.get('/api/nodes/tasks-node/tasks?limit=5&page=2')

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['history'] == fake_history['tasks']
    assert body['page'] == 2
    assert body['per_page'] == 5
    assert body['total'] == 11
    assert body['total_pages'] == 3

    _, kwargs = mock_hist.call_args
    assert kwargs['per_page'] == 5
    assert kwargs['page'] == 2


def test_api_node_tasks_clamps_out_of_range_params(operator_client):
    create_node(operator_client, 'tasks-node-clamp')
    empty = {'tasks': [], 'page': 1, 'per_page': 100, 'total': 0, 'total_pages': 0}
    with patch('nodemanager.api.get_task_history', return_value=empty) as mock_hist:
        operator_client.get('/api/nodes/tasks-node-clamp/tasks?limit=99999&page=0')

    _, kwargs = mock_hist.call_args
    assert kwargs['per_page'] == 100  # clamped to the max
    assert kwargs['page'] == 1        # clamped to the min


# --- /api/server/version ---

def test_api_server_version_requires_server_url(operator_client):
    resp = operator_client.get('/api/server/version')
    assert resp.status_code == 400
    assert resp.get_json()['error'] == 'server_url parameter is required'


def test_api_server_version_success(operator_client):
    with patch('nodemanager.api.get_server_version', return_value=('4.9.0', None)):
        resp = operator_client.get('/api/server/version?server_url=https://example.com')

    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is True
    assert body['version'] == '4.9.0'
    assert body['recommended_image'] == 'harbor2.vantage6.ai/infrastructure/node:4.9.0'


def test_api_server_version_error_from_server(operator_client):
    with patch('nodemanager.api.get_server_version', return_value=(None, 'Connection refused')):
        resp = operator_client.get('/api/server/version?server_url=https://unreachable.example.com')

    # Errors are reported as a 200 with success: False, not an HTTP error
    # status - this is the frontend's own version-check form, not a strict API.
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['success'] is False
    assert body['error'] == 'Connection refused'


def test_api_server_version_requires_login(client):
    resp = client.get('/api/server/version?server_url=https://example.com')
    assert resp.status_code == 401
    assert resp.get_json()['success'] is False
