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

# Ensure config directory exists
VANTAGE6_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
