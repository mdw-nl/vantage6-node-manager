"""Unit tests for nodemanager/audit.py's module-level functions, called
directly rather than through the /audit routes (see test_audit.py for the
route-level, actor/action-recording integration coverage).
"""
from nodemanager.audit import log_event, read_events, events_to_csv, _csv_safe
from nodemanager.config import AUDIT_LOG_FILE


def test_read_events_returns_empty_list_when_file_absent():
    assert read_events() == []


def test_log_event_round_trips_all_fields():
    log_event('alice', 'admin', 'node.create', node_name='n1', target_user=None, details='extra info')
    events = read_events()
    assert len(events) == 1
    assert events[0]['username'] == 'alice'
    assert events[0]['role'] == 'admin'
    assert events[0]['action'] == 'node.create'
    assert events[0]['node_name'] == 'n1'
    assert events[0]['details'] == 'extra info'


def test_read_events_returns_newest_first():
    log_event('alice', 'admin', 'first.event')
    log_event('alice', 'admin', 'second.event')
    events = read_events()
    assert [e['action'] for e in events] == ['second.event', 'first.event']


def test_read_events_skips_malformed_line():
    log_event('alice', 'admin', 'good.event')
    with open(AUDIT_LOG_FILE, 'a') as f:
        f.write('not valid json\n')
    log_event('alice', 'admin', 'also.good.event')

    events = read_events()
    assert [e['action'] for e in events] == ['also.good.event', 'good.event']


def test_read_events_skips_blank_lines():
    log_event('alice', 'admin', 'only.event')
    with open(AUDIT_LOG_FILE, 'a') as f:
        f.write('\n\n')
    assert len(read_events()) == 1


# --- _csv_safe / events_to_csv formula-injection guard ---

def test_csv_safe_prefixes_formula_trigger_chars():
    for trigger in ('=cmd()', '+1+1', '-2+3', '@SUM(A1)', '\ttabbed', '\rcr'):
        assert _csv_safe(trigger).startswith("'")


def test_csv_safe_leaves_normal_strings_untouched():
    assert _csv_safe('normal-username') == 'normal-username'


def test_csv_safe_passes_through_non_strings():
    assert _csv_safe(None) is None
    assert _csv_safe(42) == 42


def test_events_to_csv_includes_header_and_neutralizes_injection():
    log_event('=cmd|calc!A1', None, 'user.login_failed', details='unknown username')
    csv_data = events_to_csv(read_events())
    assert 'timestamp,username,role,action' in csv_data
    assert "'=cmd|calc!A1" in csv_data
