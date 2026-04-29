"""
cleaner.py — Bluesky post/repost cleaner.

Deletes the authenticated user's posts and reposts older than the configured
`days_to_keep` thresholds.  Optionally preserves the user's currently-pinned
post regardless of age (see `keep_pinned` in config.json).

Usage:
    python cleaner.py

Configuration is read from config.json in the working directory.
"""
from atproto import Client, AtUri
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

class Config():
    def __init__(self):
        self.days_to_keep = {"posts": 0, "reposts": 0}
        self.keep_pinned = True

        cfgfile = Path.cwd() / "config.json"
        if cfgfile.exists():
            with cfgfile.open() as handle:
                cfg = json.load(handle)

            self.username = cfg.get("username", None)
            self.password = cfg.get("password", None)
            self.days_to_keep = cfg.get("days_to_keep", None)
            self.keep_pinned = cfg.get("keep_pinned", True)

config = Config()

cli = Client()
profile = cli.login(config.username, config.password)

# @decision DEC-KEEPPIN-001
# @title Use com.atproto.repo.get_record to fetch the pinned post, not app.bsky.actor.get_profile
# @status accepted
# @rationale app.bsky.actor.get_profile returns a hydrated AppView object whose shape
#   varies by server version and may omit raw lexicon fields like pinned_post.
#   com.atproto.repo.get_record reads the raw repo record directly — the same namespace
#   used by list_records and apply_writes throughout this script — and is the
#   authoritative source of truth for the profile lexicon record.
pinned_rkey = None
if config.keep_pinned:
    try:
        resp = cli.com.atproto.repo.get_record({
            "repo": config.username,
            "collection": "app.bsky.actor.profile",
            "rkey": "self",
        })
        pinned_post = getattr(resp.value, "pinned_post", None)
        if pinned_post is not None:
            pinned_rkey = AtUri.from_str(pinned_post.uri).rkey
            print(f"keep_pinned enabled — preserving pinned post rkey={pinned_rkey}")
        else:
            print("keep_pinned enabled — no pinned post on profile")
    except Exception as e:
        print(f"keep_pinned: could not fetch profile record ({e}); proceeding without exception")

def paginated_list_records(cli, repo, collection):
    params = {
        "repo": repo,
        "collection": collection,
        "limit": 100,
    }

    records = []
    while True:
        resp = cli.com.atproto.repo.list_records(params)

        records.extend(resp.records)

        if resp.cursor:
            params["cursor"] = resp.cursor
        else:
            break

    return records

now = datetime.now(timezone.utc)

post_delta = timedelta(days=config.days_to_keep["posts"])
post_hold_datetime = now - post_delta

repost_delta = timedelta(days=config.days_to_keep["reposts"])
repost_hold_datetime = now - repost_delta

records = {}
for collection in ["app.bsky.feed.post", "app.bsky.feed.repost"]:
    records[collection] = paginated_list_records(cli, config.username, collection)
    print(f"{collection}: {len(records[collection])}")


deletes = []
for collection, posts in records.items():
    if collection == "app.bsky.feed.post":
        hold_datetime = post_hold_datetime
    elif collection == "app.bsky.feed.repost":
        hold_datetime = repost_hold_datetime
    else:
        break

    for post in reversed(posts):
        # remove charactors on `created_at` behined of `Z`
        z_index_in_created_at = post.value.created_at.index('Z')
        post_created_at = datetime.fromisoformat(post.value.created_at[:z_index_in_created_at+1])
        if post_created_at <= hold_datetime:
            uri = AtUri.from_str(post.uri)
            # Skip the pinned post — only posts can be pinned, not reposts.
            if collection == "app.bsky.feed.post" and pinned_rkey and uri.rkey == pinned_rkey:
                print(f"keep_pinned: skipping pinned post rkey={pinned_rkey}")
                continue
            deletes.append({
                "$type": "com.atproto.repo.applyWrites#delete",
                "rkey": uri.rkey,
                "collection": collection,
            })
        else:
           pass


print(f'{datetime.now()} COMMENCE DELETE: {len(deletes)} posts/reposts')
if len(deletes) > 0:
    for i in range(0, len(deletes), 200):
        cli.com.atproto.repo.apply_writes({"repo": config.username, "writes": deletes[i:i+200]})
print(f'{datetime.now()} DELETE COMPLETED')
