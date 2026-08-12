"""Tests for the dashboard (`/`, nodes.index()) - previously untested entirely.
Covers both the "Configured Nodes" table (must respect ownership, same as
/nodes) and the separate "Running Containers" widget, which scans Docker
directly and must be cross-referenced against visible configs rather than
showing every running container on the host - see index()'s own comment on
why that cross-reference exists.
"""
from unittest.mock import MagicMock, patch

import docker.errors

from tests.conftest import create_node


def _fake_client_with_running(container_names):
    """A MagicMock docker client where exactly `container_names` are
    running - both containers.get() (get_node_status(), per visible config)
    and containers.list() (get_running_nodes(), unfiltered by ownership -
    scans every container on the host) agree on the same set."""
    client = MagicMock()

    def _make_container(name):
        c = MagicMock()
        c.name = name
        c.id = 'a' * 64
        c.status = 'running'
        c.image.tags = ['harbor2.vantage6.ai/infrastructure/node:4.9.0']
        c.attrs = {'Created': '2024-01-01T00:00:00Z'}
        return c

    containers = {name: _make_container(name) for name in container_names}

    def _get(name):
        if name in containers:
            return containers[name]
        raise docker.errors.NotFound('no such container')

    client.containers.get.side_effect = _get
    client.containers.list.return_value = list(containers.values())
    return client


def test_dashboard_empty_state(viewer_client):
    with patch('nodemanager.docker_utils.get_docker_client', return_value=None):
        resp = viewer_client.get('/')
    assert resp.status_code == 200
    assert b'No nodes configured yet' in resp.data


def test_dashboard_configured_nodes_table_respects_ownership(operator_client, operator2_client):
    create_node(operator_client, 'op-node-a')
    create_node(operator2_client, 'op-node-b')

    with patch('nodemanager.docker_utils.get_docker_client', return_value=None):
        resp = operator_client.get('/')

    assert resp.status_code == 200
    assert b'op-node-a' in resp.data
    assert b'op-node-b' not in resp.data


def test_dashboard_admin_sees_every_configured_node(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'op-node-a')
    create_node(operator2_client, 'op-node-b')

    with patch('nodemanager.docker_utils.get_docker_client', return_value=None):
        resp = admin_client.get('/')

    assert resp.status_code == 200
    assert b'op-node-a' in resp.data
    assert b'op-node-b' in resp.data


def test_dashboard_running_widget_only_shows_visible_containers(operator_client, operator2_client):
    # The exact scenario the cross-reference fix guards against: both
    # containers are genuinely running on the host, but operator only owns
    # one of the two configs - the widget must not leak the other one.
    create_node(operator_client, 'op-node')
    create_node(operator2_client, 'op2-node')

    client = _fake_client_with_running(['vantage6-op-node-user', 'vantage6-op2-node-user'])

    with patch('nodemanager.docker_utils.get_docker_client', return_value=client):
        resp = operator_client.get('/')

    assert resp.status_code == 200
    assert b'vantage6-op-node-user' in resp.data
    assert b'vantage6-op2-node-user' not in resp.data


def test_dashboard_running_widget_hidden_when_nothing_visible_is_running(operator_client, operator2_client):
    create_node(operator_client, 'idle-node')
    create_node(operator2_client, 'op2-only-running-node')

    # Only operator2's node is actually running - operator's own dashboard
    # should show no "Running Containers" widget at all.
    client = _fake_client_with_running(['vantage6-op2-only-running-node-user'])

    with patch('nodemanager.docker_utils.get_docker_client', return_value=client):
        resp = operator_client.get('/')

    assert resp.status_code == 200
    assert b'Running Containers' not in resp.data


def test_dashboard_admin_sees_all_running_containers(operator_client, operator2_client, admin_client):
    create_node(operator_client, 'op-node-c')
    create_node(operator2_client, 'op2-node-c')

    client = _fake_client_with_running(['vantage6-op-node-c-user', 'vantage6-op2-node-c-user'])

    with patch('nodemanager.docker_utils.get_docker_client', return_value=client):
        resp = admin_client.get('/')

    assert resp.status_code == 200
    assert b'vantage6-op-node-c-user' in resp.data
    assert b'vantage6-op2-node-c-user' in resp.data
