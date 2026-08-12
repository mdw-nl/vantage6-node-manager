"""Unit tests for nodemanager/docker_utils.py: pure path/volume/env-building
logic plus the thin Docker-client wrappers, exercised directly with a mocked
`docker` client rather than through Flask routes.
"""
from unittest.mock import MagicMock

import docker.errors

from nodemanager.docker_utils import (
    container_path_to_host_path, build_database_env_and_volumes,
    get_node_image_for_version, find_local_node_image, get_node_status, get_running_nodes,
)


# --- container_path_to_host_path ---

def test_converts_user_config_path(monkeypatch):
    monkeypatch.setenv('HOST_HOME', '/home/alice')
    result = container_path_to_host_path('/root/.config/vantage6/node/mynode.yaml')
    assert result == '/home/alice/.config/vantage6/node/mynode.yaml'


def test_converts_user_private_key_path(monkeypatch):
    monkeypatch.setenv('HOST_HOME', '/home/alice')
    result = container_path_to_host_path('/root/.config/vantage6/node/private_keys/key.pem')
    assert result == '/home/alice/.config/vantage6/node/private_keys/key.pem'


def test_converts_system_config_file_path(monkeypatch):
    monkeypatch.setenv('HOST_HOME', '/home/alice')
    result = container_path_to_host_path('/etc/vantage6/node/system.yaml')
    assert result == '/home/alice/.config/vantage6-system/system.yaml'


def test_converts_data_dir_path(monkeypatch):
    monkeypatch.setenv('HOST_HOME', '/home/alice')
    result = container_path_to_host_path('/data/mynode/log')
    assert result == '/home/alice/vantage6-data/mynode/log'


def test_unmounted_path_returns_none(monkeypatch):
    monkeypatch.setenv('HOST_HOME', '/home/alice')
    assert container_path_to_host_path('/tmp/something.txt') is None


def test_falls_back_to_actual_home_when_host_home_unset(monkeypatch):
    from pathlib import Path
    monkeypatch.delenv('HOST_HOME', raising=False)
    result = container_path_to_host_path('/data/x.csv')
    assert result == str(Path.home() / 'vantage6-data' / 'x.csv')


def test_system_config_directory_itself_converts_correctly(monkeypatch):
    monkeypatch.setenv('HOST_HOME', '/home/alice')
    result = container_path_to_host_path('/etc/vantage6/node')
    assert result == '/home/alice/.config/vantage6-system'


# --- build_database_env_and_volumes ---

def test_file_based_database_sets_filename_env_and_bind_mount():
    env, volumes = build_database_env_and_volumes([
        {'label': 'default', 'uri': '/host/data/patients.csv', 'type': 'csv'},
    ])
    assert env == {'DEFAULT_DATABASE_URI': 'default.csv'}
    assert volumes == ['/host/data/patients.csv:/mnt/default.csv']


def test_connection_string_database_sets_env_without_volume():
    env, volumes = build_database_env_and_volumes([
        {'label': 'default', 'uri': 'postgresql://user:pass@host/db', 'type': 'postgres'},
    ])
    assert env == {'DEFAULT_DATABASE_URI': 'postgresql://user:pass@host/db'}
    assert volumes == []


def test_readonly_mount_mode_appends_ro_suffix():
    env, volumes = build_database_env_and_volumes([
        {'label': 'default', 'uri': '/host/data.csv', 'type': 'csv', 'mount_mode': 'ro'},
    ])
    assert volumes == ['/host/data.csv:/mnt/default.csv:ro']


def test_copy_mount_mode_has_no_suffix():
    env, volumes = build_database_env_and_volumes([
        {'label': 'default', 'uri': '/host/data.csv', 'type': 'csv', 'mount_mode': 'copy'},
    ])
    assert volumes == ['/host/data.csv:/mnt/default.csv']


def test_entries_missing_label_or_uri_are_skipped():
    env, volumes = build_database_env_and_volumes([
        {'label': '', 'uri': '/host/data.csv', 'type': 'csv'},
        {'label': 'default', 'uri': '', 'type': 'csv'},
    ])
    assert env == {}
    assert volumes == []


def test_multiple_databases_all_included():
    env, volumes = build_database_env_and_volumes([
        {'label': 'main', 'uri': '/host/main.csv', 'type': 'csv'},
        {'label': 'extra', 'uri': 'postgresql://host/db', 'type': 'postgres'},
    ])
    assert env == {
        'MAIN_DATABASE_URI': 'main.csv',
        'EXTRA_DATABASE_URI': 'postgresql://host/db',
    }
    assert volumes == ['/host/main.csv:/mnt/main.csv']


def test_no_databases_returns_empty():
    env, volumes = build_database_env_and_volumes(None)
    assert env == {}
    assert volumes == []


# --- get_node_image_for_version ---

def test_get_node_image_for_version_builds_harbor_tag():
    assert get_node_image_for_version('4.7.1') == 'harbor2.vantage6.ai/infrastructure/node:4.7.1'


def test_get_node_image_for_version_handles_short_version_string():
    assert get_node_image_for_version('4') == 'harbor2.vantage6.ai/infrastructure/node:4'


# --- find_local_node_image ---

def _image(tags, created=''):
    img = MagicMock()
    img.tags = tags
    img.attrs = {'Created': created}
    return img


def test_find_local_node_image_matches_exact_version():
    client = MagicMock()
    client.images.list.return_value = [
        _image(['harbor2.vantage6.ai/infrastructure/node:4.6.0']),
        _image(['harbor2.vantage6.ai/infrastructure/node:4.7.0']),
    ]
    assert find_local_node_image(client, '4.7.0') == 'harbor2.vantage6.ai/infrastructure/node:4.7.0'


def test_find_local_node_image_matches_prerelease_suffix():
    client = MagicMock()
    client.images.list.return_value = [_image(['ghcr.io/mdw-nl/infrastructure/node:4.14.0-rc8'])]
    assert find_local_node_image(client, '4.14.0') == 'ghcr.io/mdw-nl/infrastructure/node:4.14.0-rc8'


def test_find_local_node_image_falls_back_to_most_recent_when_no_version_match():
    client = MagicMock()
    client.images.list.return_value = [
        _image(['harbor2.vantage6.ai/infrastructure/node:4.6.0'], created='2024-01-01T00:00:00Z'),
        _image(['harbor2.vantage6.ai/infrastructure/node:4.7.0'], created='2024-06-01T00:00:00Z'),
    ]
    assert find_local_node_image(client, '9.9.9') == 'harbor2.vantage6.ai/infrastructure/node:4.7.0'


def test_find_local_node_image_returns_none_when_no_node_images():
    client = MagicMock()
    client.images.list.return_value = [_image(['some/other-image:latest'])]
    assert find_local_node_image(client) is None


def test_find_local_node_image_returns_none_on_exception():
    client = MagicMock()
    client.images.list.side_effect = Exception('docker error')
    assert find_local_node_image(client) is None


# --- get_node_status / get_running_nodes ---

def test_get_node_status_running(monkeypatch):
    client = MagicMock()
    client.containers.get.return_value = MagicMock(status='running')
    monkeypatch.setattr('nodemanager.docker_utils.get_docker_client', lambda: client)
    assert get_node_status('mynode', system_folders=False) == 'running'


def test_get_node_status_stopped_when_not_found(monkeypatch):
    client = MagicMock()
    client.containers.get.side_effect = docker.errors.NotFound('nope')
    monkeypatch.setattr('nodemanager.docker_utils.get_docker_client', lambda: client)
    assert get_node_status('mynode', system_folders=False) == 'stopped'


def test_get_node_status_stopped_when_container_exited(monkeypatch):
    client = MagicMock()
    client.containers.get.return_value = MagicMock(status='exited')
    monkeypatch.setattr('nodemanager.docker_utils.get_docker_client', lambda: client)
    assert get_node_status('mynode', system_folders=False) == 'stopped'


def test_get_node_status_unknown_when_docker_unavailable(monkeypatch):
    monkeypatch.setattr('nodemanager.docker_utils.get_docker_client', lambda: None)
    assert get_node_status('mynode', system_folders=False) == 'unknown'


def test_get_node_status_uses_system_postfix(monkeypatch):
    client = MagicMock()
    client.containers.get.return_value = MagicMock(status='running')
    monkeypatch.setattr('nodemanager.docker_utils.get_docker_client', lambda: client)
    get_node_status('mynode', system_folders=True)
    client.containers.get.assert_called_once_with('vantage6-mynode-system')


def test_get_running_nodes_filters_by_appname(monkeypatch):
    client = MagicMock()
    node_container = MagicMock(name='vantage6-mynode-user')
    node_container.name = 'vantage6-mynode-user'
    node_container.id = 'abc123456789'
    node_container.status = 'running'
    node_container.image.tags = ['harbor2.vantage6.ai/infrastructure/node:4.7.0']
    node_container.attrs = {'Created': '2024-01-01T00:00:00Z'}

    other_container = MagicMock()
    other_container.name = 'some-other-container'

    client.containers.list.return_value = [node_container, other_container]
    monkeypatch.setattr('nodemanager.docker_utils.get_docker_client', lambda: client)

    result = get_running_nodes()
    assert len(result) == 1
    assert result[0]['name'] == 'vantage6-mynode-user'
    assert result[0]['id'] == 'abc123456789'[:12]


def test_get_running_nodes_empty_when_docker_unavailable(monkeypatch):
    monkeypatch.setattr('nodemanager.docker_utils.get_docker_client', lambda: None)
    assert get_running_nodes() == []
