"""Unit tests for small pure-logic helpers in nodemanager/auth.py that aren't
already exercised end-to-end by test_permissions.py: username validation, the
placeholder-secret heuristic (a regression here means shipping a repo-known
signing key in production), and secret-key persistence across restarts.
"""
from nodemanager.auth import _valid_username, _looks_like_placeholder_secret, _get_or_create_secret_key
from nodemanager.config import VANTAGE6_CONFIG_DIR


# --- _valid_username ---

def test_valid_username_accepts_letters_numbers_underscore_hyphen():
    assert _valid_username('alice_bob-42')


def test_valid_username_rejects_spaces():
    assert not _valid_username('a b')


def test_valid_username_rejects_empty_string():
    assert not _valid_username('')


def test_valid_username_rejects_none():
    assert not _valid_username(None)


def test_valid_username_rejects_over_64_chars():
    assert not _valid_username('a' * 65)


def test_valid_username_accepts_exactly_64_chars():
    assert _valid_username('a' * 64)


def test_valid_username_rejects_path_traversal():
    assert not _valid_username('../users')


# --- _looks_like_placeholder_secret ---

def test_placeholder_secret_matches_repo_default():
    assert _looks_like_placeholder_secret('change-this-secret-key-in-production')


def test_placeholder_secret_is_case_insensitive():
    assert _looks_like_placeholder_secret('CHANGE-THIS-IN-PRODUCTION')


def test_placeholder_secret_requires_both_words():
    assert not _looks_like_placeholder_secret('change-this-please')
    assert not _looks_like_placeholder_secret('a-production-value')


def test_real_secret_is_not_flagged_as_placeholder():
    assert not _looks_like_placeholder_secret('9f8a7b6c5d4e3f2a1b0c')


# --- _get_or_create_secret_key ---

def test_generated_key_persists_across_calls(monkeypatch):
    key_file = VANTAGE6_CONFIG_DIR.parent / '.secret_key'
    key_file.unlink(missing_ok=True)
    monkeypatch.delenv('SECRET_KEY', raising=False)
    try:
        first = _get_or_create_secret_key()
        second = _get_or_create_secret_key()
        assert first == second
        assert key_file.exists()
    finally:
        key_file.unlink(missing_ok=True)


def test_placeholder_env_secret_is_ignored_in_favor_of_generated_key(monkeypatch):
    key_file = VANTAGE6_CONFIG_DIR.parent / '.secret_key'
    key_file.unlink(missing_ok=True)
    monkeypatch.setenv('SECRET_KEY', 'change-this-secret-key-in-production')
    try:
        key = _get_or_create_secret_key()
        assert key != 'change-this-secret-key-in-production'
    finally:
        key_file.unlink(missing_ok=True)


def test_real_env_secret_is_used_as_is(monkeypatch):
    monkeypatch.setenv('SECRET_KEY', 'a-genuinely-random-value-123')
    assert _get_or_create_secret_key() == 'a-genuinely-random-value-123'
