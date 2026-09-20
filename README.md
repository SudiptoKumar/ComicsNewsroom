# ComicsNewsroom V3

A production-oriented Telegram newsroom for **@ComicsNewsroom**, covering three equal top-level sectors:

```text
ANIME
MANGA
COMICS
  ├─ Marvel
  └─ DC
```

V3 restores the broad-discovery behavior that worked well in the previous entertainment pipeline while fixing the main failure found in V2.2: oversized AI ranking responses that could fail after a successful HTTP 200 response.

## Core editorial objective

**Coverage first, quality second, verification before publication.**

The bot normally targets **7–10 genuinely useful posts per 3-hour run**, but never pads the feed with weak stories.

```text
150–300+ raw discoveries
        ↓
24h freshness + broad relevance filter
        ↓
70–120 usable candidates
        ↓
event/title deduplication
        ↓
30–60 deterministic pre-ranked candidates
        ↓
compact AI editorial ranking
        ↓
12–20 reviewable candidates
        ↓
selective article extraction + story generation
        ↓
batched fact verification
        ↓
final sector-balanced selection
        ↓
0–10 news posts
        ↓
optional 1 FAN EXTRA
```

## Discovery

The bot does not wait for a weak RSS count before using gap-fill discovery. Every run can use:

- Specialist RSS feeds
- Google News RSS queries
- Exa news discovery
- Official-domain discovery through the allowed source registry
- Official trailer/video lookup for qualifying trailer stories

The discovery window is a rolling **24 hours**, with a small future tolerance for feed clock skew. A story older than 24 hours is normally excluded unless a fresh qualifying development creates a new event.

## Candidate strategy

V3 deliberately keeps the early filter broad enough to reduce false negatives. The Python layer removes obvious off-topic, duplicate, review/listicle, rumor and low-value material, then performs deterministic pre-ranking.

The deterministic pre-ranker uses source authority, event type, freshness, franchise reach, novelty, evidence-rich excerpts and image availability. It is a routing layer, not the final editorial decision.

## AI ranking fix

V2.2 asked the model to return many fields for every candidate. That created oversized responses and caused ranking JSON parse failures.

V3 uses a compact structured-output contract:

```json
{
  "items": [
    {"id": 1, "score": 91, "sector": "Anime", "publish": true}
  ]
}
```

The model is no longer responsible for generating `event_key`, `rank_reason`, `institution`, topic taxonomy, source class or other metadata that Python can derive.

Cerebras Structured Outputs remain enabled with `strict: true`. The production schemas intentionally avoid unsupported strict-mode array-size keywords. Cerebras documents strict structured output as the recommended production path and notes that `max_completion_tokens` includes reasoning tokens. 

## Cerebras runtime protection

V3 uses:

```text
Ranking model:      qwen-3.8-27b
Story model:        gpt-oss-120b
Ranking reasoning:  none
Story reasoning:    low
SDK retries:        0
Concurrency:        2
Per-model pacing:   configurable, default 12 seconds
Per-run request cap: 36
```

The request wrapper logs model, duration, finish reason and token usage. Failed infrastructure requests are never converted into editorial score `0`, and failed requests are not fed into adaptive learning.

The documented Free Trial limits currently list 5 RPM and 30K uncached TPM for both `gpt-oss-120b` and `qwen-3.8-27b`; Developer tier limits are substantially higher. The workflow therefore paces requests by default instead of relying on burst concurrency. urlCerebras rate limitshttps://inference-docs.cerebras.ai/support/rate-limits

## Story generation

Only the strongest reviewable candidates reach article extraction and generation.

V3 can process up to **15 review candidates** with a small worker pool. This creates enough headroom for extraction/generation failures while still allowing the final feed to reach the desired 7–10 posts.

Final news publication:

```text
TARGET: 7–10
HARD MAX: 10
MAX PER SECTOR: 4
```

The sector rule is an opportunity rule, not a quota. The system never invents a weak post just to maintain equal counts.

## Event deduplication

Multiple articles about one event are clustered before final selection.

```text
Source A ┐
Source B ├─ same event → one post
Source C ┘
```

Meaningful later developments remain separate events when appropriate:

```text
Season announced
      ↓
Trailer released
      ↓
Release date confirmed
```

## Verification

Each generated story must pass local numeric grounding. The surviving stories are then fact-checked in one compact batch call.

If the verification service fails, the bot does not pretend that the stories were verified. It may publish only high-trust candidates with strong official or multi-source evidence under the degraded fallback rules in `main.py`.

## Trailer intelligence

Trailer/PV stories receive a deterministic video lookup. The bot prefers a verified direct official video, especially YouTube or an official platform. LLM-generated URLs are never trusted.

When verified, the Rich Message contains:

```html
<h2>Watch Trailer 👉 <a href="OFFICIAL_URL">YouTube</a></h2>
```

## FAN EXTRA

V3 keeps one separate optional non-news reader-value post per run. Formats rotate across:

```text
Quick Fact
Hidden Detail
Franchise Timeline
Creator Spotlight
Fan Guide
Origin Story
Why It Matters
Did You Know
```

The extra is source-grounded and is skipped when reliable evidence is insufficient.

## Runtime budget

The application has a hard internal budget of **590 seconds** and the GitHub Actions job has a slightly larger external timeout so state cleanup can complete.

The bot should finish earlier when work is exhausted. Ten minutes is a safety ceiling, not a requirement to wait.

## State

`news_state.json` is the only durable runtime state file.

It stores feed health, queued candidates, event clusters, publication fingerprints, posted event memory, adaptive metrics, sector coverage, reader-extra history and source/score learning.

There is no `posted_urls.txt` file in V3.

## GitHub Actions

The workflow runs every three hours:

```text
00:00 UTC
03:00 UTC
06:00 UTC
09:00 UTC
12:00 UTC
15:00 UTC
18:00 UTC
21:00 UTC
```

It also supports manual runs.

Required repository secrets:

```text
EXA_API_KEY
CEREBRAS_API_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_ADMIN_CHAT_ID   (optional)
```

The workflow supplies:

```text
TELEGRAM_CHANNEL=@ComicsNewsroom
CEREBRAS_MODEL=gpt-oss-120b
CEREBRAS_RANK_MODEL=qwen-3.8-27b
CEREBRAS_MIN_INTERVAL_SECONDS=12
```

## Production structure

```text
ComicsNewsroom/
├── .github/
│   └── workflows/
│       └── newbot.yml
├── README.md
├── Template.md
├── main.py
├── requirements.txt
└── news_state.json
```

No `.gitignore`, `CHANGELOG.md`, test directory, import workflow, ZIP archive or `posted_urls.txt` is required in the production repository.

## Local checks

```bash
python -m py_compile main.py
```

```bash
EXA_API_KEY=dummy \
CEREBRAS_API_KEY=dummy \
TELEGRAM_BOT_TOKEN=dummy \
python main.py --self-test
```

## Definition of Done

A production run should:

1. Discover broadly across all enabled source classes.
2. Keep the candidate funnel large enough to avoid missing good stories.
3. Use compact, structured AI ranking that cannot be accidentally inflated by a fixed post quota.
4. Separate service failures from editorial rejections.
5. Preserve event-based deduplication and three-sector coverage.
6. Generate and verify only the strongest candidates.
7. Publish roughly 7–10 posts when that many strong events exist.
8. Continue safely when individual feeds, pages, video lookups or AI requests fail.
9. Persist only `news_state.json` as runtime state.
10. Stay within the 10-minute internal run budget.
