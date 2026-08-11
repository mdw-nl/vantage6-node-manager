"""Direct unit tests for nodemanager/node_config.py's ownership backend -
previously only exercised indirectly through routes in test_ownership.py.
The one piece that most needed a dedicated test: the old single-owner
{name: username} format migration in _load_node_owners(), since real
deployments upgrading from before the multi-owner feature have exactly
that on disk right now, not the new {name: [usernames]} list format.
"""
import yaml

from nodemanager.config import NODE_OWNERS_FILE
from nodemanager.node_config import (
    _load_node_owners, _save_node_owners, get_node_owners, add_node_owner,
    set_node_owners, remove_node_owner, clear_node_owner, release_nodes_owned_by,
    filter_visible_configs, can_access_config,
)


def _write_raw_owners_file(content):
    """Write NODE_OWNERS_FILE's raw YAML directly, bypassing _save_node_owners() -
    used to simulate on-disk formats the app itself would never write anymore
    (the old single-owner format), so the migration path is genuinely exercised."""
    with open(NODE_OWNERS_FILE, 'w') as f:
        yaml.dump(content, f, default_flow_style=False)


# --- _load_node_owners: format + migration ---

def test_load_node_owners_returns_empty_dict_when_file_absent():
    assert _load_node_owners() == {}


def test_load_node_owners_passes_through_list_format_unchanged():
    _write_raw_owners_file({'alpha': ['alice', 'bob']})
    assert _load_node_owners() == {'alpha': ['alice', 'bob']}


def test_load_node_owners_migrates_old_single_string_format():
    _write_raw_owners_file({'alpha': 'alice'})
    assert _load_node_owners() == {'alpha': ['alice']}


def test_load_node_owners_drops_old_format_none_entries():
    # Old format used a bare `None` value for "released/unclaimed" - under
    # the new model that's just an absent entry, not an empty list.
    _write_raw_owners_file({'alpha': None, 'beta': 'bob'})
    assert _load_node_owners() == {'beta': ['bob']}


def test_load_node_owners_handles_mixed_old_and_new_format_in_one_file():
    # A realistic mid-migration snapshot: some nodes already touched by the
    # new multi-owner UI (list), others untouched since the old format shipped.
    _write_raw_owners_file({'alpha': 'alice', 'beta': ['bob', 'carol'], 'gamma': None})
    assert _load_node_owners() == {'alpha': ['alice'], 'beta': ['bob', 'carol']}


# --- _save_node_owners: empty-list pruning + permissions ---

def test_save_node_owners_omits_empty_lists():
    _save_node_owners({'alpha': ['alice'], 'beta': []})
    assert _load_node_owners() == {'alpha': ['alice']}


def test_save_node_owners_sets_restrictive_permissions():
    _save_node_owners({'alpha': ['alice']})
    mode = NODE_OWNERS_FILE.stat().st_mode & 0o777
    assert mode == 0o600


# --- add_node_owner ---

def test_add_node_owner_creates_new_entry():
    add_node_owner('alpha', 'alice')
    assert get_node_owners('alpha') == ['alice']


def test_add_node_owner_appends_without_disturbing_existing_owners():
    add_node_owner('alpha', 'alice')
    add_node_owner('alpha', 'bob')
    assert get_node_owners('alpha') == ['alice', 'bob']


def test_add_node_owner_is_idempotent():
    add_node_owner('alpha', 'alice')
    add_node_owner('alpha', 'alice')
    assert get_node_owners('alpha') == ['alice']


# --- set_node_owners ---

def test_set_node_owners_replaces_the_full_list():
    add_node_owner('alpha', 'alice')
    set_node_owners('alpha', ['bob', 'carol'])
    assert get_node_owners('alpha') == ['bob', 'carol']


def test_set_node_owners_dedupes_preserving_first_occurrence_order():
    set_node_owners('alpha', ['bob', 'alice', 'bob', 'carol', 'alice'])
    assert get_node_owners('alpha') == ['bob', 'alice', 'carol']


def test_set_node_owners_empty_list_makes_node_unclaimed():
    add_node_owner('alpha', 'alice')
    set_node_owners('alpha', [])
    assert get_node_owners('alpha') == []
    assert 'alpha' not in _load_node_owners()


# --- remove_node_owner ---

def test_remove_node_owner_removes_only_that_user():
    set_node_owners('alpha', ['alice', 'bob'])
    remove_node_owner('alpha', 'alice')
    assert get_node_owners('alpha') == ['bob']


def test_remove_node_owner_no_op_when_user_not_an_owner():
    set_node_owners('alpha', ['alice'])
    remove_node_owner('alpha', 'someone-else')
    assert get_node_owners('alpha') == ['alice']


def test_remove_node_owner_no_op_when_node_unknown():
    # Must not raise just because the node has no entry at all.
    remove_node_owner('never-existed', 'alice')
    assert get_node_owners('never-existed') == []


def test_remove_last_owner_makes_node_unclaimed():
    set_node_owners('alpha', ['alice'])
    remove_node_owner('alpha', 'alice')
    assert 'alpha' not in _load_node_owners()


# --- clear_node_owner ---

def test_clear_node_owner_removes_entry_regardless_of_owner_count():
    set_node_owners('alpha', ['alice', 'bob', 'carol'])
    clear_node_owner('alpha')
    assert 'alpha' not in _load_node_owners()


def test_clear_node_owner_no_op_when_node_unknown():
    clear_node_owner('never-existed')  # must not raise
    assert 'never-existed' not in _load_node_owners()


# --- release_nodes_owned_by ---

def test_release_nodes_owned_by_removes_user_from_every_node():
    set_node_owners('alpha', ['alice', 'bob'])
    set_node_owners('beta', ['alice'])
    set_node_owners('gamma', ['bob'])

    release_nodes_owned_by('alice')

    assert get_node_owners('alpha') == ['bob']
    assert 'beta' not in _load_node_owners()  # alice was its only owner
    assert get_node_owners('gamma') == ['bob']  # untouched - never had alice


def test_release_nodes_owned_by_is_a_no_op_for_unknown_user():
    set_node_owners('alpha', ['alice'])
    release_nodes_owned_by('nobody')
    assert get_node_owners('alpha') == ['alice']


# --- filter_visible_configs / can_access_config ---

def _config(name, owners):
    return {'name': name, 'owners': owners}


def test_filter_visible_configs_admin_sees_everything_including_unowned():
    configs = [_config('alpha', ['alice']), _config('beta', [])]
    assert filter_visible_configs(configs, 'admin', 'admin') == configs


def test_filter_visible_configs_non_admin_sees_only_owned():
    configs = [_config('alpha', ['alice']), _config('beta', ['bob']), _config('gamma', ['alice', 'bob'])]
    visible = filter_visible_configs(configs, 'operator', 'alice')
    assert [c['name'] for c in visible] == ['alpha', 'gamma']


def test_filter_visible_configs_non_admin_sees_nothing_unowned():
    configs = [_config('alpha', [])]
    assert filter_visible_configs(configs, 'viewer', 'alice') == []


def test_can_access_config_admin_always_true():
    assert can_access_config(_config('alpha', []), 'admin', 'admin') is True


def test_can_access_config_owner_true_non_owner_false():
    config = _config('alpha', ['alice', 'bob'])
    assert can_access_config(config, 'operator', 'alice') is True
    assert can_access_config(config, 'operator', 'carol') is False
