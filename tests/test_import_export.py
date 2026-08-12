"""Tests for the .zip import/export paths - previously untested entirely
(only the plain .yaml import had any coverage). This is the most fiddly
logic in nodes.py: zipfile handling, validating the zip's contents, and
computing/rewriting the private key's path relative to
VANTAGE6_CONFIG_DIR.parent so it's portable across machines - a regression
here would silently corrupt or drop someone's encryption key.
"""
import io
import zipfile

import yaml

from nodemanager.config import VANTAGE6_CONFIG_DIR
from nodemanager.node_config import _load_node_owners, get_node_configs
from tests.conftest import ADMIN_USERNAME, OPERATOR_USERNAME, create_node


def _make_zip(yaml_filename, yaml_content, private_key_content=None, private_key_arcname='private_key.pem'):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr(yaml_filename, yaml_content)
        if private_key_content is not None:
            zf.writestr(private_key_arcname, private_key_content)
    buffer.seek(0)
    return buffer


def _upload_zip(client, buffer, filename='backup.zip'):
    return client.post('/nodes/import', data={'backup_file': (buffer, filename)},
                        content_type='multipart/form-data')


# --- .zip import ---

def test_zip_import_with_key_creates_node_and_key_file(operator_client):
    yaml_content = (
        "server_url: https://example.com\n"
        "api_key: zip-import-key\n"
        "encryption:\n"
        "  enabled: true\n"
        "  private_key: null\n"
    )
    zbuf = _make_zip('crypto-imported.yaml', yaml_content, private_key_content=b'FAKE-PEM-CONTENT')

    resp = _upload_zip(operator_client, zbuf, filename='crypto-imported_backup.zip')
    assert resp.status_code == 302

    # Node name comes from the .yaml entry *inside* the zip, not the outer
    # .zip filename - the two can legitimately differ (e.g. a renamed backup file).
    config = next(c for c in get_node_configs() if c['name'] == 'crypto-imported')
    assert config['data']['encryption']['enabled'] is True

    key_path = VANTAGE6_CONFIG_DIR / 'private_keys' / 'crypto-imported_private_key.pem'
    assert key_path.exists()
    assert key_path.read_bytes() == b'FAKE-PEM-CONTENT'

    # Stored path is relative to VANTAGE6_CONFIG_DIR.parent, matching new_node()'s convention.
    assert config['data']['encryption']['private_key'] == str(
        key_path.relative_to(VANTAGE6_CONFIG_DIR.parent)
    )
    assert _load_node_owners()['crypto-imported'] == [OPERATOR_USERNAME]


def test_zip_import_without_key_disables_encryption_with_warning(operator_client):
    yaml_content = (
        "server_url: https://example.com\n"
        "api_key: zip-import-no-key\n"
        "encryption:\n"
        "  enabled: true\n"
        "  private_key: null\n"
    )
    # No private_key.pem entry in the zip at all.
    zbuf = _make_zip('no-key-node.yaml', yaml_content)

    resp = _upload_zip(operator_client, zbuf)
    assert resp.status_code == 302

    config = next(c for c in get_node_configs() if c['name'] == 'no-key-node')
    assert config['data']['encryption']['enabled'] is False
    assert not (VANTAGE6_CONFIG_DIR / 'private_keys' / 'no-key-node_private_key.pem').exists()


def test_zip_import_rejects_zero_yaml_entries(operator_client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('readme.txt', 'not a config')
    buffer.seek(0)

    resp = _upload_zip(operator_client, buffer, filename='bad.zip')
    assert resp.status_code == 302
    assert get_node_configs() == []


def test_zip_import_rejects_multiple_yaml_entries(operator_client):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as zf:
        zf.writestr('one.yaml', 'server_url: https://a.com\napi_key: a\n')
        zf.writestr('two.yaml', 'server_url: https://b.com\napi_key: b\n')
    buffer.seek(0)

    resp = _upload_zip(operator_client, buffer, filename='ambiguous.zip')
    assert resp.status_code == 302
    assert get_node_configs() == []


def test_zip_import_rejects_corrupt_zip(operator_client):
    resp = _upload_zip(operator_client, io.BytesIO(b'not actually a zip file'), filename='corrupt.zip')
    assert resp.status_code == 302
    assert get_node_configs() == []


def test_zip_import_respects_name_and_api_key_collision(admin_client, operator_client):
    create_node(admin_client, 'existing-node', server_url='https://admins-node.com')

    yaml_content = "server_url: https://hijack.com\napi_key: test-api-key-existing-node\n"
    zbuf = _make_zip('existing-node.yaml', yaml_content)

    _upload_zip(operator_client, zbuf, filename='hijack.zip')

    config = next(c for c in get_node_configs() if c['name'] == 'existing-node')
    assert config['data']['server_url'] == 'https://admins-node.com'
    assert _load_node_owners()['existing-node'] == [ADMIN_USERNAME]


# --- export: plain .yaml (no encryption) ---

def test_export_plain_node_returns_yaml_attachment(operator_client):
    create_node(operator_client, 'plain-export-node', server_url='https://export-me.com')

    resp = operator_client.get('/nodes/plain-export-node/export')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/x-yaml'
    assert 'plain-export-node.yaml' in resp.headers.get('Content-Disposition', '')

    data = yaml.safe_load(resp.data)
    assert data['server_url'] == 'https://export-me.com'


def test_export_blocked_for_unowned_node(operator_client, operator2_client):
    create_node(operator_client, 'not-yours-export')
    resp = operator2_client.get('/nodes/not-yours-export/export')
    assert resp.status_code == 302


# --- export: .zip (encryption enabled with a real key file) ---

def test_export_encrypted_node_returns_zip_with_config_and_key(operator_client):
    create_node(operator_client, 'crypto-export-node', server_url='https://export-crypto.com', **{
        'encryption_enabled': 'on',
        'key_source': 'generate',
        'generated_private_key': '-----BEGIN PRIVATE KEY-----\nexport-me\n-----END PRIVATE KEY-----',
    })

    resp = operator_client.get('/nodes/crypto-export-node/export')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/zip'
    assert 'crypto-export-node_backup.zip' in resp.headers.get('Content-Disposition', '')

    with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
        names = zf.namelist()
        assert 'crypto-export-node.yaml' in names
        assert 'private_key.pem' in names

        exported_config = yaml.safe_load(zf.read('crypto-export-node.yaml'))
        assert exported_config['server_url'] == 'https://export-crypto.com'
        assert exported_config['encryption']['enabled'] is True

        exported_key = zf.read('private_key.pem').decode()
        assert 'export-me' in exported_key


def test_export_encrypted_node_falls_back_to_yaml_when_key_file_missing(operator_client):
    create_node(operator_client, 'crypto-missing-key-node', **{
        'encryption_enabled': 'on',
        'key_source': 'generate',
        'generated_private_key': '-----BEGIN PRIVATE KEY-----\nwill-be-deleted\n-----END PRIVATE KEY-----',
    })
    key_path = VANTAGE6_CONFIG_DIR / 'private_keys' / 'crypto-missing-key-node_private_key.pem'
    assert key_path.exists()
    key_path.unlink()  # simulate the key file having gone missing on disk

    resp = operator_client.get('/nodes/crypto-missing-key-node/export', follow_redirects=True)
    assert resp.status_code == 200
    assert resp.mimetype == 'application/x-yaml'
    assert b'private key file not found' in resp.data.lower() or b'warning' in resp.data.lower()


# --- round trip: export an encrypted node, delete it, re-import the export ---

def test_export_then_reimport_round_trips_the_private_key(admin_client):
    create_node(admin_client, 'roundtrip-node', server_url='https://roundtrip.com', **{
        'encryption_enabled': 'on',
        'key_source': 'generate',
        'generated_private_key': '-----BEGIN PRIVATE KEY-----\nroundtrip-secret\n-----END PRIVATE KEY-----',
    })

    export_resp = admin_client.get('/nodes/roundtrip-node/export')
    assert export_resp.mimetype == 'application/zip'
    exported_zip_bytes = export_resp.data

    # Admin's delete is the real, permanent one - the name is free again.
    admin_client.post('/nodes/roundtrip-node/delete')
    assert get_node_configs() == []

    reimport_resp = _upload_zip(admin_client, io.BytesIO(exported_zip_bytes), filename='roundtrip_backup.zip')
    assert reimport_resp.status_code == 302

    config = next(c for c in get_node_configs() if c['name'] == 'roundtrip-node')
    assert config['data']['server_url'] == 'https://roundtrip.com'
    assert config['data']['encryption']['enabled'] is True

    key_path = VANTAGE6_CONFIG_DIR / 'private_keys' / 'roundtrip-node_private_key.pem'
    assert key_path.exists()
    assert b'roundtrip-secret' in key_path.read_bytes()


# --- images.node survives export/import, and import validates it same as create/edit ---

def test_export_then_reimport_round_trips_configured_image(operator_client):
    create_node(operator_client, 'image-roundtrip-node', server_url='https://example.com',
                image='ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.15.0')

    export_resp = operator_client.get('/nodes/image-roundtrip-node/export')
    assert export_resp.mimetype == 'application/x-yaml'
    exported_yaml_bytes = export_resp.data

    operator_client.post('/nodes/image-roundtrip-node/delete')

    reimport_resp = operator_client.post(
        '/nodes/import',
        data={'backup_file': (io.BytesIO(exported_yaml_bytes), 'image-roundtrip-node.yaml')},
        content_type='multipart/form-data',
    )
    assert reimport_resp.status_code == 302

    config = next(c for c in get_node_configs() if c['name'] == 'image-roundtrip-node')
    assert config['data']['images']['node'] == 'ghcr.io/mdw-nl/vantage6/infrastructure/node-lite:4.15.0'


def test_yaml_import_rejects_malformed_image(operator_client):
    # Same typo new_node()/edit_node() reject (a stray "/" where the tag's
    # ":" belongs) - import must apply the same check, or a bad config
    # re-imported from a backup silently reintroduces the "manifest unknown"
    # failure at start time instead of being caught here.
    yaml_content = yaml.dump({
        'server_url': 'https://example.com',
        'api_key': 'malformed-image-import-key',
        'databases': [{'label': 'default', 'uri': '/tmp/test.csv', 'type': 'csv'}],
        'images': {'node': 'ghcr.io/mdw-nl/vantage6/infrastructure/node-lite/4.14.0-rc8'},
    })

    resp = operator_client.post(
        '/nodes/import',
        data={'backup_file': (io.BytesIO(yaml_content.encode()), 'bad-image-import.yaml')},
        content_type='multipart/form-data',
        follow_redirects=True,
    )

    assert b'valid image reference' in resp.data.lower()
    assert 'bad-image-import' not in [c['name'] for c in get_node_configs()]
