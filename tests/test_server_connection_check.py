"""Tests for the non-blocking server/API-key check that new_node()/edit_node()
run at save time (nodes.py's _check_server_connection()).

It's deliberately advisory, not a gate: unlike the Docker-host database check
(node_actions.py's verify_database_mounts()), the vantage6 server is an
external system that may legitimately be unreachable at config-save time, and
hard-blocking on a wrong key risks tripping the server's own login-lockout
policy before the real node ever gets to connect. So a failed check must
still let the save go through - it only changes what gets flashed.
"""
from unittest.mock import patch

from nodemanager.nodes import _check_server_connection
from tests.conftest import create_node


# --- _check_server_connection unit tests ---

def test_check_server_connection_success_message():
    with patch('nodemanager.nodes.get_node_api_session',
               return_value=('https://example.com/api', {}, {'id': 1}, None)):
        message, category = _check_server_connection({'server_url': 'https://example.com', 'api_key': 'k'})
    assert category == 'success'
    assert 'Connected' in message


def test_check_server_connection_failure_message():
    with patch('nodemanager.nodes.get_node_api_session',
               return_value=(None, None, None, 'Invalid API key')):
        message, category = _check_server_connection({'server_url': 'https://example.com', 'api_key': 'wrong'})
    assert category == 'warning'
    assert 'Invalid API key' in message
    assert 'may fail to start' in message


# --- new_node()/edit_node() never block on a failed check ---

def test_new_node_saves_even_when_server_check_fails(operator_client):
    with patch('nodemanager.nodes.get_node_api_session',
               return_value=(None, None, None, 'Could not connect to server')):
        resp = operator_client.post('/nodes/new', data={
            'name': 'unreachable-node',
            'server_url': 'https://not-a-real-server.example',
            'api_key': 'some-key',
            'db_uri': '/tmp/test.csv',
            'db_type': 'csv',
        }, follow_redirects=True)

    assert b'created successfully' in resp.data.lower()
    assert b'could not verify the server connection' in resp.data.lower()
    from nodemanager.node_config import get_node_configs
    assert any(c['name'] == 'unreachable-node' for c in get_node_configs())


def test_new_node_shows_success_when_server_check_passes(operator_client):
    with patch('nodemanager.nodes.get_node_api_session',
               return_value=('https://example.com/api', {}, {'id': 1}, None)):
        resp = operator_client.post('/nodes/new', data={
            'name': 'reachable-node',
            'server_url': 'https://example.com',
            'api_key': 'some-key',
            'db_uri': '/tmp/test.csv',
            'db_type': 'csv',
        }, follow_redirects=True)

    assert b'created successfully' in resp.data.lower()
    assert b'connected to the vantage6 server' in resp.data.lower()


def test_edit_node_saves_even_when_server_check_fails(operator_client):
    create_node(operator_client, 'edit-me', server_url='https://example.com')

    with patch('nodemanager.nodes.get_node_api_session',
               return_value=(None, None, None, 'Invalid API key')):
        resp = operator_client.post('/nodes/edit-me/edit', data={
            'server_url': 'https://example.com',
            'api_key': 'a-different-key',
            'db_uri': '/tmp/test.csv',
            'db_type': 'csv',
        }, follow_redirects=True)

    assert b'updated' in resp.data.lower()
    assert b'could not verify the server connection' in resp.data.lower()
