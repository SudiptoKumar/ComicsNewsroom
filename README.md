# ComicsNewsroom V4.0 Production

Automated editorial newsroom for **@ComicsNewsroom** covering only high-value Anime, Manga and Comics developments.

## Editorial policy

- Exactly three sectors: **Anime**, **Manga**, **Comics**.
- Marvel and DC are subtopics of Comics.
- Normal discovery window: rolling **24 hours**.
- Meaningful fresh developments can update an older event; a bounded 72-hour exception is allowed when concrete new development signals are present.
- The bot runs every **3 hours**.
- Typical output target: **7-10 strong stories per run** when enough quality news exists. The bot never manufactures filler to hit the target.
- There is no forced quota. The bot may publish fewer or zero stories.
- Duplicate reporting is clustered into one event.
- Deep research is reserved for strong candidates.
- Official studios, publishers, platforms and primary sources are preferred for verification.
- Rumor, reported, announced, confirmed and released are kept distinct.
- Major trailers/PVs/teasers trigger direct official video discovery.
- FAN EXTRA is optional and strongly rate-limited so it never becomes filler.

## Pipeline

```text
RSS + Google News + Exa + Official Sources + Video Discovery
        -> 24h filter
        -> prefilter
        -> URL/title dedup
        -> event clustering
        -> AI editorial ranking
        -> deep research of strong candidates
        -> official-source verification
        -> fact/status verification
        -> soft sector diversity tie-breaker
        -> dynamic template selection
        -> image/video enrichment
        -> Telegram Rich Message
        -> persistent state + learning
```

## Production-load model

The expensive stages deliberately follow the proven working newsroom architecture: Cerebras calls are globally paced and sequential, story candidates are processed one at a time, Exa calls share a rate-limited clock, and one candidate failure does not cancel successful candidates. The run stops gracefully when the AI budget or rate limit is exhausted, leaving failed events retryable for a later run.

## AI / search stack

- Cerebras `gpt-oss-120b`
- `cerebras_cloud_sdk`
- `exa-py`
- `requests`, `urllib3`
- `beautifulsoup4`, `feedparser`, `trafilatura`
- `Pillow`

The bot uses the current Exa `search()` / `get_contents()` SDK flow and compact Cerebras strict JSON schemas.

## Telegram publishing

Primary transport:

```text
Rich Message -> photo + rich HTML + inline links
```

Fallback transport:

```text
Telegram Bot API -> sendPhoto
```

Trailer posts can include direct official video buttons such as YouTube or Crunchyroll when verified.

## GitHub Actions

The workflow runs every three hours and persists `news_state.json` / `posted_urls.txt` back to the repository.

Required GitHub secrets:

```text
EXA_API_KEY
CEREBRAS_API_KEY
TELEGRAM_BOT_TOKEN
```

Optional:

```text
TELEGRAM_ADMIN_CHAT_ID
```

## Local testing

The production dependencies are listed in `requirements.txt`.

Fast tests that do not need external APIs:

```bash
python main.py --self-test
python main.py --fixture-test
```

The repository also includes an offline executable-path harness under `tests/` that provides dependency stubs so the real `main.py` entrypoint can be executed without network access.

## Important limitation during offline validation

The build environment used for this release could not reach PyPI or the external APIs, so live Cerebras, Exa, RSS, YouTube/Crunchyroll and Telegram publishing could not be executed here. The offline executable path, schema contract, orchestration and fault-injection tests were run instead.


## Reliability tests

```bash
python main.py --self-test
python main.py --fixture-test
python main.py --rate-limit-test
```

The rate-limit test simulates 429 responses and proves that retries happen through one centralized Cerebras gate rather than through concurrent worker bursts.
