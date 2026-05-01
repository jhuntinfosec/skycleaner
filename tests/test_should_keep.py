"""
Unit tests for should_keep() and _parse_keep_tags() in cleaner.py.

cleaner.py runs network code at module level (login, list_records).  This
file stubs out the atproto package and patches away I/O before importing
cleaner so the tests work with no network and no config.json.
"""
import sys
import os
import types
import unittest
from unittest import mock

# ---------------------------------------------------------------------------
# Stub atproto BEFORE cleaner is imported so the import succeeds without
# the real library needing a network connection.
# ---------------------------------------------------------------------------

class _AtUri:
    """Minimal AtUri stub: extracts the rkey from an AT URI string."""
    def __init__(self, rkey):
        self.rkey = rkey

    @classmethod
    def from_str(cls, uri):
        return cls(uri.rsplit('/', 1)[-1])


_mock_list_resp = mock.MagicMock()
_mock_list_resp.records = []
_mock_list_resp.cursor = None

_mock_client_instance = mock.MagicMock()
_mock_client_instance.com.atproto.repo.list_records.return_value = _mock_list_resp

_atproto_stub = types.ModuleType('atproto')
_atproto_stub.Client = mock.MagicMock(return_value=_mock_client_instance)
_atproto_stub.AtUri = _AtUri
sys.modules.setdefault('atproto', _atproto_stub)

# ---------------------------------------------------------------------------
# Import cleaner while patching away config.json I/O and login.
# keep_pinned=False avoids the profile-record fetch, and the mock client
# handles the remaining API surfaces (list_records, apply_writes).
# ---------------------------------------------------------------------------
_DUMMY_CFG = {
    'username': 'test.bsky.social',
    'password': 'test-pass',
    'days_to_keep': {'posts': 0, 'reposts': 0},
    'keep_pinned': False,
    'min_replies': 0,
    'min_likes': 0,
    'min_reposts': 0,
    'keep_threads': False,
    'keep_with_media': False,
    'keep_tags': [],
}

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

with mock.patch('pathlib.Path.exists', return_value=True), \
     mock.patch('pathlib.Path.open', mock.mock_open()), \
     mock.patch('json.load', return_value=_DUMMY_CFG):
    import cleaner  # noqa: E402

from cleaner import should_keep, _parse_keep_tags  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_post(text, rkey='abc123', embed=None):
    """Build a minimal fake post record matching the shape cleaner.py expects."""
    value = types.SimpleNamespace(text=text, embed=embed)
    return types.SimpleNamespace(
        uri=f'at://did:plc:test/app.bsky.feed.post/{rkey}',
        value=value,
    )


def make_cfg(keep_tags):
    """Build a minimal Config-like namespace with pre-parsed keep_tags."""
    return types.SimpleNamespace(
        keep_pinned=False,
        min_replies=0,
        min_likes=0,
        min_reposts=0,
        keep_with_media=False,
        keep_tags=keep_tags,
        keep_tags_parsed=_parse_keep_tags(keep_tags),
    )


# ---------------------------------------------------------------------------
# Tests for _parse_keep_tags
# ---------------------------------------------------------------------------

class TestParseKeepTags(unittest.TestCase):

    def test_plain_string_produces_substring_entry(self):
        parsed = _parse_keep_tags(['hello'])
        self.assertEqual(parsed, [('substring', 'hello')])

    def test_multiple_plain_strings(self):
        parsed = _parse_keep_tags(['#important', 'pinned'])
        self.assertEqual(parsed, [('substring', '#important'), ('substring', 'pinned')])

    def test_regex_entry_produces_compiled_pattern(self):
        parsed = _parse_keep_tags(['/^#proj-/i'])
        self.assertEqual(len(parsed), 1)
        kind, pat = parsed[0]
        self.assertEqual(kind, 'regex')
        self.assertIsNotNone(pat.match('#proj-alpha'))
        self.assertIsNone(pat.match('other'))

    def test_regex_flag_i_is_case_insensitive(self):
        _, pat = _parse_keep_tags(['/^#proj-/i'])[0]
        self.assertIsNotNone(pat.match('#PROJ-ALPHA'))
        self.assertIsNotNone(pat.match('#Proj-release'))

    def test_regex_no_flags_is_case_sensitive(self):
        _, pat = _parse_keep_tags(['/^#proj-/'])[0]
        self.assertIsNone(pat.match('#PROJ-ALPHA'))
        self.assertIsNotNone(pat.match('#proj-alpha'))

    def test_invalid_regex_is_skipped_not_fatal(self):
        parsed = _parse_keep_tags(['valid', '/[invalid/'])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0], ('substring', 'valid'))

    def test_invalid_regex_warning_is_printed(self):
        with mock.patch('builtins.print') as mock_print:
            _parse_keep_tags(['/[bad/'])
        calls = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn('warning', calls)
        self.assertIn('/[bad/', calls)

    def test_empty_list_returns_empty(self):
        self.assertEqual(_parse_keep_tags([]), [])

    def test_mixed_plain_and_regex(self):
        parsed = _parse_keep_tags(['#important', '/^#proj-/i'])
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0][0], 'substring')
        self.assertEqual(parsed[1][0], 'regex')


# ---------------------------------------------------------------------------
# Tests for should_keep — tag filter (Filter 6)
# ---------------------------------------------------------------------------

class TestShouldKeepTagFilter(unittest.TestCase):

    def _call(self, post, keep_tags, pinned_rkey=None):
        cfg = make_cfg(keep_tags)
        return should_keep(post, None, cfg, pinned_rkey)

    # --- plain substring ---

    def test_substring_match_keeps_post(self):
        post = make_post('This is #important content')
        keep, reason = self._call(post, ['#important'])
        self.assertTrue(keep)
        self.assertEqual(reason, 'tag:#important')

    def test_substring_match_is_case_insensitive(self):
        post = make_post('This is #IMPORTANT content')
        keep, reason = self._call(post, ['#important'])
        self.assertTrue(keep)

    def test_substring_no_match_deletes_post(self):
        post = make_post('Nothing relevant here')
        keep, reason = self._call(post, ['#important'])
        self.assertFalse(keep)
        self.assertEqual(reason, 'delete')

    def test_empty_text_never_matches_substring(self):
        post = make_post('')
        keep, _ = self._call(post, ['#important'])
        self.assertFalse(keep)

    def test_none_text_never_matches_substring(self):
        post = make_post(None)
        keep, _ = self._call(post, ['#important'])
        self.assertFalse(keep)

    # --- regex ---

    def test_regex_match_keeps_post(self):
        post = make_post('#PROJ-alpha launch day')
        keep, reason = self._call(post, ['/^#proj-/i'])
        self.assertTrue(keep)
        self.assertIn('tag:regex', reason)
        self.assertIn('^#proj-', reason)

    def test_regex_no_match_deletes_post(self):
        post = make_post('Just a random post, no project tag')
        keep, reason = self._call(post, ['/^#proj-/i'])
        self.assertFalse(keep)
        self.assertEqual(reason, 'delete')

    def test_regex_word_boundary(self):
        post = make_post('announcing a new release today')
        keep, _ = self._call(post, [r'/\brelease\b/i'])
        self.assertTrue(keep)

    def test_regex_word_boundary_no_partial(self):
        post = make_post('prereleased yesterday')
        keep, _ = self._call(post, [r'/\brelease\b/i'])
        self.assertFalse(keep)

    # --- invalid regex does not crash; valid entries still work ---

    def test_invalid_regex_skipped_valid_substring_still_matches(self):
        post = make_post('this has #keepme in it')
        keep, reason = self._call(post, ['/[invalid/', '#keepme'])
        self.assertTrue(keep)
        self.assertEqual(reason, 'tag:#keepme')

    def test_invalid_regex_skipped_no_other_match_deletes(self):
        post = make_post('nothing here')
        keep, reason = self._call(post, ['/[invalid/', '#keepme'])
        self.assertFalse(keep)
        self.assertEqual(reason, 'delete')

    # --- empty keep_tags ---

    def test_empty_keep_tags_deletes_post(self):
        post = make_post('#important content')
        keep, reason = self._call(post, [])
        self.assertFalse(keep)
        self.assertEqual(reason, 'delete')


if __name__ == '__main__':
    unittest.main()
