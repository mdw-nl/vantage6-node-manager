"""Reading node configuration YAML files from disk, and tracking which app
user (operator) created each one.

Ownership is deliberately NOT stored inside the per-node YAML files
themselves: those files are mounted directly into the node's own Docker
container and passed as-is to the real vantage6 node software
(`vnode-local start --config /mnt/config/{name}.yaml`, see node_actions.py) -
adding an unrecognized key to that file risks breaking a config schema this
app doesn't own. Ownership lives in a separate file instead.
"""
import os
import yaml

from nodemanager.config import VANTAGE6_CONFIG_DIR, VANTAGE6_SYSTEM_CONFIG_DIR, NODE_OWNERS_FILE


def _load_node_owners():
    """Returns {name: [usernames]}. Transparently upgrades the old
    {name: username_or_None} format written by earlier versions of this
    file, so existing deployments don't need a manual migration step."""
    if not NODE_OWNERS_FILE.exists():
        return {}
    with open(NODE_OWNERS_FILE, 'r') as f:
        raw = yaml.safe_load(f) or {}

    owners = {}
    for name, value in raw.items():
        if isinstance(value, list):
            owners[name] = value
        elif value:
            owners[name] = [value]
        # else: old-format None ("unclaimed") - drop the entry, same as [].
    return owners


def _save_node_owners(owners):
    # Don't persist empty lists - an unclaimed node is simply absent from
    # the file, same meaning as before this became list-valued.
    owners = {name: usernames for name, usernames in owners.items() if usernames}
    with open(NODE_OWNERS_FILE, 'w') as f:
        yaml.dump(owners, f, default_flow_style=False)
    os.chmod(str(NODE_OWNERS_FILE), 0o600)


def get_node_owners(name):
    return list(_load_node_owners().get(name, []))


def add_node_owner(name, username):
    """Grant a user access to a node without disturbing its other owners -
    used when a user creates/imports a node (they become its first owner)
    and is the building block for admin's multi-owner management UI."""
    owners = _load_node_owners()
    current = owners.setdefault(name, [])
    if username not in current:
        current.append(username)
    _save_node_owners(owners)


def set_node_owners(name, usernames):
    """Replace a node's entire owner list in one go - used by admin's
    owner-management form, which submits the full desired set of owners
    rather than one add/remove at a time."""
    owners = _load_node_owners()
    owners[name] = list(dict.fromkeys(usernames))  # de-dupe, preserve order
    _save_node_owners(owners)


def remove_node_owner(name, username):
    """Remove a single user from a node's owner list, leaving the config
    file and every other owner's access untouched - this is what a
    non-admin's "delete" actually does (see nodes.py's delete_node): it
    only ever removes *them*, never the underlying node, even if they were
    the one who originally created it. Only admin can trigger a real
    delete (the config file itself, via os.remove + clear_node_owner)."""
    owners = _load_node_owners()
    if name in owners and username in owners[name]:
        owners[name] = [u for u in owners[name] if u != username]
        _save_node_owners(owners)


def clear_node_owner(name):
    """Remove a node's entry entirely - called on node deletion, not on
    ownership changes (use set_node_owners()/remove a single username for
    that)."""
    owners = _load_node_owners()
    if owners.pop(name, None) is not None:
        _save_node_owners(owners)


def release_nodes_owned_by(username):
    """Remove this user from every node's owner list - called when the user
    is deleted, so node_owners.yaml doesn't accumulate stale entries
    pointing at a username that no longer exists. Admin can already see and
    manage any node regardless of its owner list, so this isn't required
    for admin's own access; it's purely to keep the file's state tidy and
    keep an orphaned node's owner list from listing a ghost username."""
    owners = _load_node_owners()
    changed = False
    for name, usernames in list(owners.items()):
        if username in usernames:
            owners[name] = [u for u in usernames if u != username]
            changed = True
    if changed:
        _save_node_owners(owners)


def filter_visible_configs(configs, role, username):
    """Which of these configs a given app user is allowed to see.

    admin sees everything, always. Everyone else - operator and viewer alike
    - sees only nodes they're listed as an owner of (a node can have more
    than one owner - e.g. two people at the same hospital both watching the
    same physical node). Nothing is visible by default just because nobody
    owns it: nodes with an empty owner list (covers both nodes created
    before this feature existed and 'system'-type configs) are admin-only
    until explicitly handed to someone via the owner-management route.
    Operator and viewer differ only in whether they can also start/stop/
    restart a container they own - see actions_bp's blueprint-wide gate in
    node_actions.py, which this function has no bearing on.
    """
    if role == 'admin':
        return configs
    return [c for c in configs if username in c.get('owners', [])]


def can_access_config(config, role, username):
    """Whether a given app user may view/manage this specific node's config.

    Same admin-sees-all, everyone-else-owns-only rule as
    filter_visible_configs(), just applied to a single config instead of a
    list - used by every single-node and bulk route. Does NOT govern
    container control (start/stop/restart) - actions_bp gates that
    separately and more strictly (operator+admin only, regardless of
    ownership).
    """
    return role == 'admin' or username in config.get('owners', [])


def get_node_configs():
    """Get all available node configurations"""
    configs = []
    owners = _load_node_owners()

    # User configurations
    if VANTAGE6_CONFIG_DIR.exists():
        for config_file in VANTAGE6_CONFIG_DIR.glob('*.yaml'):
            try:
                with open(config_file, 'r') as f:
                    config_data = yaml.safe_load(f)
                configs.append({
                    'name': config_file.stem,
                    'path': str(config_file),
                    'type': 'user',
                    'data': config_data,
                    'owners': owners.get(config_file.stem, []),
                })
            except Exception as e:
                print(f"Error loading {config_file}: {e}")

    # System configurations - a vantage6 CLI concept (system-wide vs
    # per-user config directories), unrelated to app-level ownership. Never
    # created through this app's UI, so there's no operator to attribute
    # them to; always treated as unclaimed/shared.
    if VANTAGE6_SYSTEM_CONFIG_DIR.exists():
        for config_file in VANTAGE6_SYSTEM_CONFIG_DIR.glob('*.yaml'):
            try:
                with open(config_file, 'r') as f:
                    config_data = yaml.safe_load(f)
                configs.append({
                    'name': config_file.stem,
                    'path': str(config_file),
                    'type': 'system',
                    'data': config_data,
                    'owners': [],
                })
            except Exception as e:
                print(f"Error loading {config_file}: {e}")

    return configs
