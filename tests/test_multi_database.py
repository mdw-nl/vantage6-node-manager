"""A node's config can list more than one database, each with its own label
(see docker_utils.build_database_env_and_volumes(), which already loops over
the whole list) - these tests cover the create/edit form side of that:
_parse_databases_from_form() in nodemanager/nodes.py, and the multi-row
database section in new_node.html/edit_node.html that feeds it.
"""
import yaml

from nodemanager.node_config import get_node_configs
from nodemanager.config import VANTAGE6_CONFIG_DIR
from tests.conftest import create_node


def _databases_of(name):
    config = next(c for c in get_node_configs() if c['name'] == name)
    return config['data']['databases']


# --- new_node(): multiple database rows ---

def test_new_node_saves_multiple_databases(operator_client):
    create_node(
        operator_client, 'multi-db-node',
        db_label=['patients', 'images'],
        db_uri=['/data/patients.csv', '/data/images'],
        db_type=['csv', 'folder'],
    )

    databases = _databases_of('multi-db-node')
    assert databases == [
        {'label': 'patients', 'uri': '/data/patients.csv', 'type': 'csv'},
        {'label': 'images', 'uri': '/data/images', 'type': 'folder'},
    ]


def test_new_node_rejects_duplicate_database_labels(operator_client):
    resp = operator_client.post('/nodes/new', data={
        'name': 'dup-label-node',
        'server_url': 'https://example.com',
        'api_key': 'test-api-key-dup-label-node',
        'db_label': ['default', 'default'],
        'db_uri': ['/tmp/a.csv', '/tmp/b.csv'],
        'db_type': ['csv', 'csv'],
    })

    assert b'used more than once' in resp.data.lower()
    assert 'dup-label-node' not in [c['name'] for c in get_node_configs()]


def test_new_node_requires_at_least_one_database(operator_client):
    resp = operator_client.post('/nodes/new', data={
        'name': 'no-db-node',
        'server_url': 'https://example.com',
        'api_key': 'test-api-key-no-db-node',
        'db_uri': [''],
        'db_type': ['csv'],
    })

    assert b'at least one database' in resp.data.lower()
    assert 'no-db-node' not in [c['name'] for c in get_node_configs()]


def test_new_node_defaults_label_when_field_omitted_entirely(operator_client):
    # Matches the pre-multi-database behaviour: a form post with no db_label
    # field at all (not just an empty one) still gets a usable config.
    create_node(operator_client, 'no-label-field-node')
    assert _databases_of('no-label-field-node')[0]['label'] == 'default'


# --- edit_node(): the form fully replaces the databases list ---

def test_edit_node_can_add_a_second_database(operator_client):
    create_node(operator_client, 'grow-db-node')

    operator_client.post('/nodes/grow-db-node/edit', data={
        'server_url': 'https://example.com',
        'db_label': ['default', 'extra'],
        'db_uri': ['/tmp/test.csv', '/tmp/extra.csv'],
        'db_type': ['csv', 'csv'],
    })

    databases = _databases_of('grow-db-node')
    assert [db['label'] for db in databases] == ['default', 'extra']


def test_edit_node_can_remove_a_database(operator_client):
    create_node(
        operator_client, 'shrink-db-node',
        db_label=['default', 'extra'],
        db_uri=['/tmp/test.csv', '/tmp/extra.csv'],
        db_type=['csv', 'csv'],
    )
    assert len(_databases_of('shrink-db-node')) == 2

    operator_client.post('/nodes/shrink-db-node/edit', data={
        'server_url': 'https://example.com',
        'db_label': ['default'],
        'db_uri': ['/tmp/test.csv'],
        'db_type': ['csv'],
    })

    databases = _databases_of('shrink-db-node')
    assert len(databases) == 1
    assert databases[0]['label'] == 'default'


def test_edit_node_rejects_duplicate_database_labels(operator_client):
    create_node(operator_client, 'edit-dup-label-node')

    resp = operator_client.post('/nodes/edit-dup-label-node/edit', data={
        'server_url': 'https://example.com',
        'db_label': ['default', 'default'],
        'db_uri': ['/tmp/a.csv', '/tmp/b.csv'],
        'db_type': ['csv', 'csv'],
    })

    assert b'used more than once' in resp.data.lower()
    # Original single database survives untouched - the edit was rejected.
    assert len(_databases_of('edit-dup-label-node')) == 1


def test_edit_node_preserves_hand_authored_keys_the_form_does_not_manage(operator_client):
    # mount_mode isn't a form field - it only ever arrives via import/hand
    # editing (see build_database_env_and_volumes()). A same-label edit must
    # not silently drop it.
    create_node(operator_client, 'mount-mode-node')
    config_path = VANTAGE6_CONFIG_DIR / 'mount-mode-node.yaml'
    with open(config_path) as f:
        data = yaml.safe_load(f)
    data['databases'][0]['mount_mode'] = 'ro'
    with open(config_path, 'w') as f:
        yaml.dump(data, f)

    operator_client.post('/nodes/mount-mode-node/edit', data={
        'server_url': 'https://updated.example.com',
        'db_label': 'default',
        'db_uri': '/tmp/test.csv',
        'db_type': 'csv',
    })

    databases = _databases_of('mount-mode-node')
    assert databases[0]['mount_mode'] == 'ro'


def test_edit_node_drops_preserved_keys_when_label_changes(operator_client):
    # A relabel has no old entry to match against - same as remove+add.
    create_node(operator_client, 'relabel-node')
    config_path = VANTAGE6_CONFIG_DIR / 'relabel-node.yaml'
    with open(config_path) as f:
        data = yaml.safe_load(f)
    data['databases'][0]['mount_mode'] = 'ro'
    with open(config_path, 'w') as f:
        yaml.dump(data, f)

    operator_client.post('/nodes/relabel-node/edit', data={
        'server_url': 'https://updated.example.com',
        'db_label': 'renamed',
        'db_uri': '/tmp/test.csv',
        'db_type': 'csv',
    })

    databases = _databases_of('relabel-node')
    assert databases[0]['label'] == 'renamed'
    assert 'mount_mode' not in databases[0]
