# skycleaner
Delete your posts and reposts on Bluesky.

## Prepare
0. (Recommend) Setup venv
1. Install Required packages
```bash
    pip install -r requirements.txt
```
2. Copy `config.example.json` to `config.json` and edit it

```bash
cp config.example.json config.json
```

`config.json` is gitignored so your real credentials never get committed.

**Use App Password for safety.**
```json
   {
    "username": "your_handle.bsky.social",
    "password": "ISSUED APP PASSWORD",
    "days_to_keep": {
      "posts": 20,
      "reposts": 20
    },
    "keep_pinned": true
   }
```

### days_to_keep
Avoid deleting posts/reposts configured duration. 

Set as **days**.

### keep_pinned
Preserve your currently-pinned post regardless of age.

Default: `true` — the pinned post is never deleted.

Set to `false` to disable this protection and allow the pinned post to be deleted normally when it falls outside `days_to_keep`.

The script reads your profile record once at startup to determine the pinned post's rkey.  If you have no pinned post, or if the lookup fails, cleanup proceeds normally with no error.

### min_replies / min_likes / min_reposts
Preserve posts that have received at least this many replies, likes, or reposts respectively.

Default: `0` — engagement filters are disabled; all posts are eligible for deletion.

Set any value above `0` to activate the corresponding filter.  For example, `"min_likes": 10` preserves any post that has 10 or more likes regardless of age.

When any of these three filters is non-zero, the script makes one additional API call per 25 posts to fetch live engagement counts.  If the API call fails for a batch, those posts are treated as having zero engagement and will not be preserved by these filters (media and tag filters still apply to them).

### keep_threads
Preserve posts that are parents of a surviving post (no-orphan semantics).

Default: `false` — thread structure is not considered; posts are evaluated individually.

Set to `true` to activate.  When enabled, if any post survives the cleanup (because it is within `days_to_keep`, pinned, or matched by another filter), all posts it replies to — and their ancestors in turn — are also preserved.  This prevents dangling reply chains where the reply survives but the post it replied to is gone.

Only applies to `app.bsky.feed.post` records.  Reposts are unaffected.

### keep_with_media
Preserve posts that contain image, video, or mixed-media embeds.

Default: `false` — embed type is not considered.

Set to `true` to preserve any post with an `app.bsky.embed.images`, `app.bsky.embed.video`, or `app.bsky.embed.recordWithMedia` attachment.  Plain external link cards (`app.bsky.embed.external`) and plain quote-posts (`app.bsky.embed.record`) are not counted as media and will still be deleted.

### keep_tags
Preserve posts whose text contains any of the listed strings (case-insensitive substring match).

Default: `[]` — tag filter is disabled.

Set to a list of strings to activate.  For example:

```json
"keep_tags": ["#important", "pinned"]
```

This preserves any post whose text contains `#important` or `pinned` (in any capitalisation).  Include the `#` character in the string if you want to match a hashtag specifically rather than any word containing the text.

Posts with no text (e.g. image-only posts) never match the tag filter.

## Run
**YOU CAN NEVER GO BACK**
```bash
python cleaner.py
```

## Thanks
- [Skycleaner by halka](https://github.com/halka/skycleaner)
- [BLUESKY POST DELETER](https://deleter.shiroyama.us/)
- [sleep/deleteskee: a little script for automagically deleting blue sky (atproto) posts and reposts - Codeberg.org](https://codeberg.org/sleep/deleteskee)
