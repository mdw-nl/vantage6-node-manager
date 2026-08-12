"""Unit tests for nodemanager/server_api.py: talking to the vantage6 server's
own API. `requests` and the Docker client are mocked throughout - no real
network or Docker daemon involved.
"""
from unittest.mock import MagicMock, patch

import pytest
import requests

from nodemanager.server_api import (
    get_server_version, get_node_api_session, get_node_health_status, get_task_history, get_running_tasks,
)


# --- get_server_version: URL construction ---

def test_get_server_version_builds_url_from_server_and_api_path():
    with patch('nodemanager.server_api.requests.get') as mock_get:
        mock_get.return_value = MagicMock(status_code=200, raise_for_status=lambda: None,
                                           json=lambda: {'version': '4.7.0'})
        version, error = get_server_version('https://example.com', '/api')
    mock_get.assert_called_once_with('https://example.com/api/version', timeout=5)
    assert version == '4.7.0'
    assert error is None


def test_get_server_version_strips_trailing_slash_and_inserts_port():
    with patch('nodemanager.server_api.requests.get') as mock_get:
        mock_get.return_value = MagicMock(status_code=200, raise_for_status=lambda: None,
                                           json=lambda: {'version': '4.7.0'})
        get_server_version('https://example.com/', '/api', port='5000')
    mock_get.assert_called_once_with('https://example.com:5000/api/version', timeout=5)


def test_get_server_version_strips_leading_slash_from_api_path():
    with patch('nodemanager.server_api.requests.get') as mock_get:
        mock_get.return_value = MagicMock(status_code=200, raise_for_status=lambda: None,
                                           json=lambda: {'version': '4.7.0'})
        get_server_version('https://example.com', 'api')
    mock_get.assert_called_once_with('https://example.com/api/version', timeout=5)


def test_get_server_version_accepts_v_key_as_fallback():
    with patch('nodemanager.server_api.requests.get') as mock_get:
        mock_get.return_value = MagicMock(status_code=200, raise_for_status=lambda: None,
                                           json=lambda: {'v': '4.9.0'})
        version, error = get_server_version('https://example.com')
    assert version == '4.9.0'


def test_get_server_version_missing_version_field_is_an_error():
    with patch('nodemanager.server_api.requests.get') as mock_get:
        mock_get.return_value = MagicMock(status_code=200, raise_for_status=lambda: None, json=lambda: {})
        version, error = get_server_version('https://example.com')
    assert version is None
    assert 'not found' in error.lower()


# --- get_server_version: error branches ---

def test_get_server_version_timeout():
    with patch('nodemanager.server_api.requests.get', side_effect=requests.exceptions.Timeout()):
        version, error = get_server_version('https://example.com')
    assert version is None
    assert 'timed out' in error.lower()


def test_get_server_version_connection_error():
    with patch('nodemanager.server_api.requests.get', side_effect=requests.exceptions.ConnectionError()):
        version, error = get_server_version('https://example.com')
    assert version is None
    assert 'could not connect' in error.lower()


def test_get_server_version_http_error():
    resp = MagicMock(status_code=500)
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError('500 Server Error', response=resp)
    with patch('nodemanager.server_api.requests.get', return_value=resp):
        version, error = get_server_version('https://example.com')
    assert version is None
    assert 'http error' in error.lower()


# --- get_node_api_session ---

def test_get_node_api_session_missing_config_fields():
    base, headers, node_data, error = get_node_api_session({'data': {}})
    assert base is None
    assert 'missing' in error.lower()


def test_get_node_api_session_token_request_failure_uses_server_message():
    token_resp = MagicMock(ok=False, status_code=401)
    token_resp.json.return_value = {'msg': 'Invalid API key'}
    with patch('nodemanager.server_api.requests.post', return_value=token_resp):
        base, headers, node_data, error = get_node_api_session({
            'data': {'server_url': 'https://example.com', 'api_key': 'bad-key'}
        })
    assert base is None
    assert error == 'Invalid API key'


def test_get_node_api_session_connection_error():
    with patch('nodemanager.server_api.requests.post', side_effect=requests.exceptions.ConnectionError('down')):
        base, headers, node_data, error = get_node_api_session({
            'data': {'server_url': 'https://example.com', 'api_key': 'k'}
        })
    assert base is None
    assert 'could not connect' in error.lower()


def test_get_node_api_session_success_returns_headers_and_node_record():
    token_resp = MagicMock(ok=True)
    token_resp.json.return_value = {'access_token': 'jwt-token'}
    me_resp = MagicMock()
    me_resp.raise_for_status.return_value = None
    me_resp.json.return_value = {'data': [{'id': 42, 'status': 'online'}]}

    with patch('nodemanager.server_api.requests.post', return_value=token_resp), \
         patch('nodemanager.server_api.requests.get', return_value=me_resp):
        base, headers, node_data, error = get_node_api_session({
            'data': {'server_url': 'https://example.com', 'api_key': 'k', 'port': '5000'}
        })

    assert error is None
    assert base == 'https://example.com:5000/api'
    assert headers == {'Authorization': 'Bearer jwt-token'}
    assert node_data == {'id': 42, 'status': 'online'}


# --- get_node_health_status ---

def _config(name='mynode', node_type='user'):
    return {'name': name, 'type': node_type, 'data': {'server_url': 'https://example.com', 'api_key': 'k'}}


def test_health_docker_unavailable(monkeypatch):
    monkeypatch.setattr('nodemanager.server_api.get_docker_client', lambda: None)
    result = get_node_health_status(_config())
    assert result['status'] == 'unknown'


def test_health_container_not_found_is_stopped(monkeypatch):
    import docker.errors
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound('nope')
    monkeypatch.setattr('nodemanager.server_api.get_docker_client', lambda: client)
    result = get_node_health_status(_config())
    assert result['status'] == 'stopped'


def test_health_container_stopped_state():
    with patch('nodemanager.server_api.get_docker_client') as mock_get_client:
        client = MagicMock()
        client.containers.get.return_value = MagicMock(status='exited')
        mock_get_client.return_value = client
        result = get_node_health_status(_config())
    assert result['status'] == 'stopped'


def test_health_running_and_online(monkeypatch):
    container = MagicMock(status='running')
    client = MagicMock()
    client.containers.get.return_value = container
    monkeypatch.setattr('nodemanager.server_api.get_docker_client', lambda: client)
    monkeypatch.setattr('nodemanager.server_api.get_node_api_session',
                         lambda config: ('base', {}, {'status': 'online', 'last_seen': '2026-01-01T00:00:00'}, None))
    result = get_node_health_status(_config())
    assert result['status'] == 'online'
    assert '2026-01-01T00:00:00' in result['message']


def test_health_running_but_server_call_fails(monkeypatch):
    container = MagicMock(status='running')
    client = MagicMock()
    client.containers.get.return_value = container
    monkeypatch.setattr('nodemanager.server_api.get_docker_client', lambda: client)
    monkeypatch.setattr('nodemanager.server_api.get_node_api_session',
                         lambda config: (None, None, None, 'Could not connect to server'))
    result = get_node_health_status(_config())
    assert result['status'] == 'error'
    assert result['message'] == 'Could not connect to server'


def test_health_running_just_started_is_starting(monkeypatch):
    from datetime import datetime, timezone
    container = MagicMock(status='running')
    container.attrs = {'State': {'StartedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}}
    client = MagicMock()
    client.containers.get.return_value = container
    monkeypatch.setattr('nodemanager.server_api.get_docker_client', lambda: client)
    monkeypatch.setattr('nodemanager.server_api.get_node_api_session',
                         lambda config: ('base', {}, {'status': 'offline'}, None))
    result = get_node_health_status(_config())
    assert result['status'] == 'starting'


def test_health_running_long_uptime_but_offline_is_reconnecting(monkeypatch):
    from datetime import datetime, timezone, timedelta
    container = MagicMock(status='running')
    started = datetime.now(timezone.utc) - timedelta(minutes=5)
    container.attrs = {'State': {'StartedAt': started.isoformat().replace('+00:00', 'Z')}}
    client = MagicMock()
    client.containers.get.return_value = container
    monkeypatch.setattr('nodemanager.server_api.get_docker_client', lambda: client)
    monkeypatch.setattr('nodemanager.server_api.get_node_api_session',
                         lambda config: ('base', {}, {'status': 'offline', 'last_seen': None}, None))
    result = get_node_health_status(_config())
    assert result['status'] == 'reconnecting'


# --- get_task_history ---

def _run(run_id, task_name='algo', status='completed', started_at='2026-01-01T00:00:00',
         finished_at='2026-01-01T00:01:30', image='algo:latest'):
    return {
        'id': run_id, 'status': status, 'started_at': started_at, 'finished_at': finished_at,
        'task': {'id': run_id * 10, 'name': task_name, 'image': image},
    }


def test_task_history_derives_completed_status_and_formats_duration(monkeypatch):
    monkeypatch.setattr('nodemanager.server_api.get_node_api_session',
                         lambda config: ('base', {}, {'id': 1}, None))
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {'data': [_run(1)]}
    resp.headers = {'total-count': '1'}
    with patch('nodemanager.server_api.requests.get', return_value=resp):
        result = get_task_history(_config(), per_page=10, page=1)

    assert result['total'] == 1
    assert result['tasks'][0]['status'] == 'completed'
    assert result['tasks'][0]['duration_display'] == '1m 30s'


def test_task_history_running_status_when_started_but_not_finished(monkeypatch):
    monkeypatch.setattr('nodemanager.server_api.get_node_api_session',
                         lambda config: ('base', {}, {'id': 1}, None))
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {'data': [_run(2, finished_at=None)]}
    resp.headers = {'total-count': '1'}
    with patch('nodemanager.server_api.requests.get', return_value=resp):
        result = get_task_history(_config())
    assert result['tasks'][0]['status'] == 'running'
    assert result['tasks'][0]['duration_display'] == '—'


def test_task_history_pending_status_when_not_started():
    with patch('nodemanager.server_api.get_node_api_session',
               return_value=('base', {}, {'id': 1}, None)):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {'data': [_run(3, started_at=None, finished_at=None)]}
        resp.headers = {'total-count': '1'}
        with patch('nodemanager.server_api.requests.get', return_value=resp):
            result = get_task_history(_config())
    assert result['tasks'][0]['status'] == 'pending'


def test_task_history_error_status_when_finished_but_not_completed(monkeypatch):
    monkeypatch.setattr('nodemanager.server_api.get_node_api_session',
                         lambda config: ('base', {}, {'id': 1}, None))
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {'data': [_run(4, status='failed')]}
    resp.headers = {'total-count': '1'}
    with patch('nodemanager.server_api.requests.get', return_value=resp):
        result = get_task_history(_config())
    assert result['tasks'][0]['status'] == 'error'


def test_task_history_pagination_math():
    with patch('nodemanager.server_api.get_node_api_session',
               return_value=('base', {}, {'id': 1}, None)):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {'data': []}
        resp.headers = {'total-count': '25'}
        with patch('nodemanager.server_api.requests.get', return_value=resp):
            result = get_task_history(_config(), per_page=10, page=2)
    assert result['total'] == 25
    assert result['total_pages'] == 3
    assert result['page'] == 2


def test_task_history_empty_when_session_fails():
    with patch('nodemanager.server_api.get_node_api_session',
               return_value=(None, None, None, 'auth failed')):
        result = get_task_history(_config())
    assert result == {'tasks': [], 'page': 1, 'per_page': 10, 'total': 0, 'total_pages': 0}


def test_task_history_empty_on_request_exception():
    with patch('nodemanager.server_api.get_node_api_session',
               return_value=('base', {}, {'id': 1}, None)), \
         patch('nodemanager.server_api.requests.get', side_effect=requests.exceptions.RequestException()):
        result = get_task_history(_config())
    assert result['tasks'] == []


# --- get_running_tasks ---

def test_get_running_tasks_filters_by_labels_and_sorts_by_start_time():
    client = MagicMock()

    c1 = MagicMock()
    c1.labels = {'run_id': '2'}
    c1.attrs = {'Config': {'Image': 'algo:v1'}, 'State': {'StartedAt': '2026-01-01T00:02:00'}}
    c1.name = 'algo-container-2'

    c2 = MagicMock()
    c2.labels = {'run_id': '1'}
    c2.attrs = {'Config': {'Image': 'algo:v2'}, 'State': {'StartedAt': '2026-01-01T00:01:00'}}
    c2.name = 'algo-container-1'

    client.containers.list.return_value = [c1, c2]

    with patch('nodemanager.server_api.get_docker_client', return_value=client):
        tasks = get_running_tasks('mynode')

    client.containers.list.assert_called_once_with(
        filters={'label': ['vantage6-type=algorithm', 'node=mynode']})
    assert [t['run_id'] for t in tasks] == ['1', '2']


def test_get_running_tasks_empty_when_docker_unavailable():
    with patch('nodemanager.server_api.get_docker_client', return_value=None):
        assert get_running_tasks('mynode') == []
