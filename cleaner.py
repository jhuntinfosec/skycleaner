"""
cleaner.py — Bluesky post/repost cleaner.

Deletes the authenticated user's posts and reposts older than the configured
`days_to_keep` thresholds.  A suite of keep-filters lets you preserve posts
that meet engagement thresholds, carry media, match content tags, or sit in
active reply chains regardless of age (see config.example.json for all options).

Usage:
    python cleaner.py

Configuration is read from config.json in the working directory.
"""
from atproto import Client, AtUri
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

# Media embed py_type values that count as "real media" for keep_with_media.
# Excludes app.bsky.embed.external (link cards) and app.bsky.embed.record
# (quote-posts without attached media) per the design decision in DEC-FILTERS-001.
_MEDIA_EMBED_TYPES = {
    "app.bsky.embed.images",
    "app.bsky.embed.video",
    "app.bsky.embed.recordWithMedia",
}


class Config():
    def __init__(self):
        self.days_to_keep = {"posts": 0, "reposts": 0}
        self.keep_pinned = True
        self.min_replies = 0
        self.min_likes = 0
        self.min_reposts = 0
        self.keep_threads = False
        self.keep_with_media = False
        self.keep_tags = []

        cfgfile = Path.cwd() / "config.json"
        if cfgfile.exists():
            with cfgfile.open() as handle:
                cfg = json.load(handle)

            self.username = cfg.get("username", None)
            self.password = cfg.get("password", None)
            self.days_to_keep = cfg.get("days_to_keep", None)
            self.keep_pinned = cfg.get("keep_pinned", True)
            self.min_replies = cfg.get("min_replies", 0)
            self.min_likes = cfg.get("min_likes", 0)
            self.min_reposts = cfg.get("min_reposts", 0)
            self.keep_threads = cfg.get("keep_threads", False)
            self.keep_with_media = cfg.get("keep_with_media", False)
            self.keep_tags = cfg.get("keep_tags", [])


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


# @decision DEC-FILTERS-001
# @title Extract should_keep as a standalone predicate returning (bool, reason)
# @status accepted
# @rationale A predicate-style function (returns (keep, reason) rather than appending
#   to a list inline) makes each filter an independent voter with a clear result.
#   This enables: (a) unit testing without any network or side-effect setup,
#   (b) the multi-pass loop to call should_keep in Pass 1 then apply thread
#   preservation in Pass 2/3 without re-entangling the logic, and (c) easy addition
#   of future filters without touching the delete loop.  keep_threads is intentionally
#   excluded from this function — it requires the global view of all kept posts and
#   is applied as a fixpoint walk in the separate Pass 2/3 (see DEC-FILTERS-002).
#   Filter ordering (pinned → replies → likes → reposts → media → tags → delete)
#   ensures the most authoritative / cheapest checks fire first.
def should_keep(post, hydrated_view, config, pinned_rkey):
    """Decide whether a single app.bsky.feed.post should be kept.

    Parameters
    ----------
    post : record object
        Raw record from list_records; exposes post.uri and post.value.
    hydrated_view : view object or None
        Result of app.bsky.feed.get_posts for this URI; exposes reply_count,
        like_count, repost_count.  Pass None when hydration failed or was skipped
        (e.g. all engagement filters disabled) — engagement filters will not match.
    config : Config
        Parsed configuration object.
    pinned_rkey : str or None
        The rkey of the currently-pinned post, or None if keep_pinned is off or
        there is no pinned post.

    Returns
    -------
    (bool, str)
        (True, reason) if the post should be kept; (False, "delete") otherwise.
    """
    uri = AtUri.from_str(post.uri)

    # Filter 1: pinned post — unconditional preservation.
    if pinned_rkey and uri.rkey == pinned_rkey:
        return (True, f"pinned rkey={pinned_rkey}")

    # Filters 2-4: engagement thresholds.  A missing hydrated_view (hydration failed
    # or was skipped) means counts default to 0, so thresholds won't match.
    reply_count = hydrated_view.reply_count if hydrated_view is not None else 0
    like_count = hydrated_view.like_count if hydrated_view is not None else 0
    repost_count = hydrated_view.repost_count if hydrated_view is not None else 0

    if config.min_replies > 0 and reply_count >= config.min_replies:
        return (True, f"replies≥{config.min_replies} (actual={reply_count})")

    if config.min_likes > 0 and like_count >= config.min_likes:
        return (True, f"likes≥{config.min_likes} (actual={like_count})")

    if config.min_reposts > 0 and repost_count >= config.min_reposts:
        return (True, f"reposts≥{config.min_reposts} (actual={repost_count})")

    # Filter 5: media embed.  Checks post.value.embed.py_type against the known
    # set of real-media types.  External link cards and plain quote-posts are excluded.
    if config.keep_with_media:
        embed = getattr(post.value, "embed", None)
        if embed is not None and getattr(embed, "py_type", None) in _MEDIA_EMBED_TYPES:
            return (True, f"media ({embed.py_type})")

    # Filter 6: tag match — case-insensitive substring on post.value.text.
    # None or empty text never matches.
    if config.keep_tags:
        text = getattr(post.value, "text", None) or ""
        text_lower = text.lower()
        for tag in config.keep_tags:
            if tag.lower() in text_lower:
                return (True, f"tag:{tag}")

    return (False, "delete")


now = datetime.now(timezone.utc)

post_delta = timedelta(days=config.days_to_keep["posts"])
post_hold_datetime = now - post_delta

repost_delta = timedelta(days=config.days_to_keep["reposts"])
repost_hold_datetime = now - repost_delta

records = {}
for collection in ["app.bsky.feed.post", "app.bsky.feed.repost"]:
    records[collection] = paginated_list_records(cli, config.username, collection)
    print(f"{collection}: {len(records[collection])}")


# ---------------------------------------------------------------------------
# Hydrate posts for engagement count filters
#
# @decision DEC-FILTERS-003
# @title Skip hydration entirely when all engagement filters are at their defaults
# @status accepted
# @rationale app.bsky.feed.get_posts costs one API round-trip per 25 posts.  When
#   min_replies, min_likes, and min_reposts are all 0 (the defaults), engagement
#   data is never consulted by should_keep.  Skipping hydration avoids O(N/25)
#   extra API calls for users who only use keep_pinned, keep_with_media, or
#   keep_tags.  The short-circuit is explicit and logged so future operators can
#   confirm the skip is intentional and not a bug.
# ---------------------------------------------------------------------------
hydrated_by_uri = {}
_need_hydration = (
    config.min_replies > 0 or config.min_likes > 0 or config.min_reposts > 0
)
if _need_hydration:
    post_uris = [p.uri for p in records.get("app.bsky.feed.post", [])]
    print(f"hydrating {len(post_uris)} posts for engagement filters (batches of 25)")
    for i in range(0, len(post_uris), 25):
        batch = post_uris[i:i+25]
        try:
            resp = cli.app.bsky.feed.get_posts({"uris": batch})
            for view in resp.posts:
                hydrated_by_uri[view.uri] = view
        except Exception as e:
            print(f"warning: hydration batch {i//25} failed ({e}); affected posts treated as 0 engagement")
    print(f"hydration complete: {len(hydrated_by_uri)}/{len(post_uris)} views retrieved")
else:
    print("hydration skipped — all engagement filters disabled (DEC-FILTERS-003)")


# ---------------------------------------------------------------------------
# Multi-pass delete loop
#
# @decision DEC-FILTERS-002
# @title Use a three-pass loop with fixpoint walk for keep_threads (no-orphan semantics)
# @status accepted
# @rationale "No-orphan" means: if post B survives (for any reason), post A that B
#   replies to also survives — even if A would otherwise be deleted.  This avoids
#   leaving dangling reply chains in the user's history.  Whole-chain-preservation
#   (keep B only if every ancestor also survives) was rejected because it would delete
#   posts with genuine engagement simply because a very old ancestor is being pruned.
#   The fixpoint walk guarantees transitivity (A's parent is also preserved if A is
#   preserved) while bounding iterations by total post count.
#   Reposts are unaffected: they have no engagement metrics or reply structure and
#   go directly to date-cutoff deletion unchanged.
# ---------------------------------------------------------------------------

# Build a fast lookup: uri → post record for posts only
post_by_uri = {p.uri: p for p in records.get("app.bsky.feed.post", [])}

deletes = []

# --- Reposts: simple date-cutoff, no filter logic ---
for post in reversed(records.get("app.bsky.feed.repost", [])):
    # remove characters on `created_at` behind of `Z`
    z_index_in_created_at = post.value.created_at.index('Z')
    post_created_at = datetime.fromisoformat(post.value.created_at[:z_index_in_created_at+1])
    if post_created_at <= repost_hold_datetime:
        uri = AtUri.from_str(post.uri)
        deletes.append({
            "$type": "com.atproto.repo.applyWrites#delete",
            "rkey": uri.rkey,
            "collection": "app.bsky.feed.repost",
        })

# --- Posts: three-pass logic ---

# Pass 1: classify each post past the cutoff as keep or candidate_delete.
# Posts within the date window go straight into kept_uris.
kept_uris = set()
candidate_deletes = {}  # uri -> delete descriptor dict

for post in reversed(records.get("app.bsky.feed.post", [])):
    # remove characters on `created_at` behind of `Z`
    z_index_in_created_at = post.value.created_at.index('Z')
    post_created_at = datetime.fromisoformat(post.value.created_at[:z_index_in_created_at+1])

    if post_created_at > post_hold_datetime:
        # Within the retention window — always keep.
        kept_uris.add(post.uri)
        continue

    # Past the cutoff — evaluate filters.
    hydrated_view = hydrated_by_uri.get(post.uri)  # None if skipped or failed
    keep, reason = should_keep(post, hydrated_view, config, pinned_rkey)

    if keep:
        print(f"keeping post rkey={AtUri.from_str(post.uri).rkey}: {reason}")
        kept_uris.add(post.uri)
    else:
        uri = AtUri.from_str(post.uri)
        candidate_deletes[post.uri] = {
            "$type": "com.atproto.repo.applyWrites#delete",
            "rkey": uri.rkey,
            "collection": "app.bsky.feed.post",
        }

# Pass 2: fixpoint walk for keep_threads (no-orphan semantics).
# For every kept post that is a reply, its parent URI is added to parents_to_preserve.
# Repeat until no new parents are discovered.
parents_to_preserve = set()
if config.keep_threads:
    frontier = set(kept_uris)
    visited = set()
    while frontier:
        next_frontier = set()
        for uri_str in frontier:
            if uri_str in visited:
                continue
            visited.add(uri_str)
            post = post_by_uri.get(uri_str)
            if post is None:
                continue  # URI points to another user's post or is unknown
            reply = getattr(post.value, "reply", None)
            if reply is None:
                continue
            parent = getattr(reply, "parent", None)
            if parent is None:
                continue
            parent_uri = getattr(parent, "uri", None)
            if parent_uri and parent_uri not in visited:
                parents_to_preserve.add(parent_uri)
                next_frontier.add(parent_uri)
        frontier = next_frontier

    if parents_to_preserve:
        preserved_count = len(parents_to_preserve & set(candidate_deletes.keys()))
        print(f"keep_threads: preserving {preserved_count} parent post(s) from candidate deletes")

# Pass 3: final deletes = candidate_deletes minus parents_to_preserve.
for uri_str, descriptor in candidate_deletes.items():
    if uri_str in parents_to_preserve:
        rkey = AtUri.from_str(uri_str).rkey
        print(f"keep_threads: preserving parent post rkey={rkey}")
        continue
    deletes.append(descriptor)


print(f'{datetime.now()} COMMENCE DELETE: {len(deletes)} posts/reposts')
if len(deletes) > 0:
    for i in range(0, len(deletes), 200):
        cli.com.atproto.repo.apply_writes({"repo": config.username, "writes": deletes[i:i+200]})
print(f'{datetime.now()} DELETE COMPLETED')
