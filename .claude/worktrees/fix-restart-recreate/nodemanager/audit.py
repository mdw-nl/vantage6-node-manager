"""Append-only audit log of admin-relevant actions on nodes and user accounts:
who created/edited/deleted/left which node, who was granted or revoked
access, who started/stopped/restarted a container, and who created/deleted a
user account or changed its role or password. Read-only for everyone but
admin (see the /audit route in auth.py).

Stored as JSONL (one JSON object per line, oldest first) rather than YAML:
entries are only ever appended, never rewritten, so each event is a single
O(1) file write - no need to re-serialize the whole log on every event the
way _save_node_owners()/_save_users() must for their rewrite-on-every-change
files.
"""
import csv
import io
import json
import os
from datetime import datetime, timezone

from nodemanager.config import AUDIT_LOG_FILE

CSV_FIELDS = ['timestamp', 'username', 'role', 'action', 'node_name', 'target_user', 'details']


def log_event(username, role, action, node_name=None, target_user=None, details=None):
    """username/role are passed in explicitly by the caller (from
    flask_login's current_user) rather than imported here, so this module
    has no Flask/request-context dependency and stays trivially testable."""
    entry = {
        'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'username': username,
        'role': role,
        'action': action,
        'node_name': node_name,
        'target_user': target_user,
        'details': details,
    }
    with open(AUDIT_LOG_FILE, 'a') as f:
        f.write(json.dumps(entry) + '\n')
    os.chmod(str(AUDIT_LOG_FILE), 0o600)


def read_events():
    """All events, newest first. A malformed line (e.g. a partial write from
    a crash mid-append) is skipped rather than failing the whole read."""
    if not AUDIT_LOG_FILE.exists():
        return []
    events = []
    with open(AUDIT_LOG_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    events.reverse()
    return events


# Leading characters that spreadsheet apps (Excel, Sheets) may interpret as
# the start of a formula rather than plain text.
_FORMULA_TRIGGER_CHARS = ('=', '+', '-', '@', '\t', '\r')


def _csv_safe(value):
    """Neutralize formula injection: most fields are internally validated
    (node/user names are restricted to [A-Za-z0-9_-]), but a failed login's
    `username` is logged as submitted, completely unvalidated - an attacker
    could type '=cmd(...)' into the login form. Prefixing with a single
    quote is the standard mitigation; spreadsheet apps then treat the cell
    as text instead of evaluating it."""
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def events_to_csv(events):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for event in events:
        writer.writerow({field: _csv_safe(event.get(field)) for field in CSV_FIELDS})
    return buffer.getvalue()
