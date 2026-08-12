"""Path constants and other environment-derived configuration, shared by every module."""
import os
from pathlib import Path

# Configuration - use environment variables for container flexibility
VANTAGE6_CONFIG_DIR = Path(os.environ.get('VANTAGE6_CONFIG_DIR', '/root/.config/vantage6/node'))
VANTAGE6_SYSTEM_CONFIG_DIR = Path(os.environ.get('VANTAGE6_SYSTEM_CONFIG_DIR', '/etc/vantage6/node'))
VANTAGE6_DATA_DIR = Path(os.environ.get('VANTAGE6_DATA_DIR', '/data'))
# Kept outside VANTAGE6_CONFIG_DIR: get_node_configs() globs *.yaml directly inside
# that directory and would otherwise misread this file as a node config.
USERS_FILE = Path(os.environ.get('USERS_FILE', str(VANTAGE6_CONFIG_DIR.parent / 'users.yaml')))
# Same reasoning as USERS_FILE - a sibling, not a child, of VANTAGE6_CONFIG_DIR.
NODE_OWNERS_FILE = Path(os.environ.get('NODE_OWNERS_FILE', str(VANTAGE6_CONFIG_DIR.parent / 'node_owners.yaml')))
# Same reasoning again - a sibling, not a child, of VANTAGE6_CONFIG_DIR.
AUDIT_LOG_FILE = Path(os.environ.get('AUDIT_LOG_FILE', str(VANTAGE6_CONFIG_DIR.parent / 'audit.log')))
APPNAME = 'vantage6'

# Default node image to pull when no locally cached image matches the running
# server's version. node-lite only publishes release-candidate-suffixed tags
# (e.g. "4.14.0-rc8"), which don't line up with the plain version string the
# server reports over its /version endpoint, so this can't be derived
# automatically - it's a pinned value, kept in sync with the server tag in
# server/docker-compose.server.yml.
NODE_IMAGE_REGISTRY = os.environ.get('NODE_IMAGE_REGISTRY', 'ghcr.io/mdw-nl/vantage6/infrastructure/node-lite')
NODE_IMAGE_TAG = os.environ.get('NODE_IMAGE_TAG', '4.14.0-rc8')

# Ensure config directory exists
VANTAGE6_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
