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

## Run
**YOU CAN NEVER GO BACK**
```bash
python cleaner.py
```

## Thanks
- [Skycleaner by halka](https://github.com/halka/skycleaner)
- [BLUESKY POST DELETER](https://deleter.shiroyama.us/)
- [sleep/deleteskee: a little script for automagically deleting blue sky (atproto) posts and reposts - Codeberg.org](https://codeberg.org/sleep/deleteskee)
