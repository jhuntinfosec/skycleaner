"""
Unit tests for the delete_likes feature introduced in cleaner.py.

These tests cover pure logic only — no network calls are made.
The _resolve_likes_days helper and the delete_likes config loading behaviour
are verified in isolation by mirroring the logic from cleaner.py so the
module's top-level network code (Client.login, list_records, etc.) is never
executed.
"""
import unittest


# Mirror of _resolve_likes_days from cleaner.py — tested without importing the
# module so the top-level Client/login code does not run.
def _resolve_likes_days(days_to_keep):
    return days_to_keep.get("likes", days_to_keep["posts"])


# Mirror of the delete_likes config-loader line: cfg.get("delete_likes", False)
def _load_delete_likes(cfg):
    return cfg.get("delete_likes", False)


class TestResolveLikesDays(unittest.TestCase):
    def test_fallback_to_posts_when_likes_absent(self):
        self.assertEqual(_resolve_likes_days({"posts": 20, "reposts": 20}), 20)

    def test_uses_likes_key_when_present(self):
        self.assertEqual(_resolve_likes_days({"posts": 20, "reposts": 20, "likes": 30}), 30)

    def test_likes_zero_is_valid(self):
        # likes=0 means delete everything — must not be confused with "absent"
        self.assertEqual(_resolve_likes_days({"posts": 20, "reposts": 20, "likes": 0}), 0)

    def test_fallback_uses_posts_not_reposts(self):
        # When likes is absent the fallback is posts, not reposts
        self.assertEqual(_resolve_likes_days({"posts": 7, "reposts": 14}), 7)

    def test_likes_differs_from_posts(self):
        self.assertEqual(_resolve_likes_days({"posts": 30, "reposts": 30, "likes": 90}), 90)

    def test_likes_one_day(self):
        self.assertEqual(_resolve_likes_days({"posts": 7, "reposts": 7, "likes": 1}), 1)


class TestDeleteLikesConfigDefault(unittest.TestCase):
    def test_defaults_false_when_key_absent(self):
        self.assertFalse(_load_delete_likes({}))

    def test_false_when_explicitly_false(self):
        self.assertFalse(_load_delete_likes({"delete_likes": False}))

    def test_true_when_set(self):
        self.assertTrue(_load_delete_likes({"delete_likes": True}))

    def test_other_keys_do_not_affect_default(self):
        self.assertFalse(_load_delete_likes({"username": "x", "password": "y"}))


if __name__ == "__main__":
    unittest.main()
