# ComicsNewsroom V2.2

A quality-first automated Anime, Manga and Comics newsroom for **@ComicsNewsroom**.

The bot is based on the previous Entertainment Newsroom execution framework, keeping the same dependency stack, Cerebras model, Exa discovery, persistent state, Telegram Rich Message transport, image handling, adaptive learning, and GitHub Actions deployment pattern. The editorial AI pipeline is optimized for low-latency parallel processing.

## Editorial goal

This is **not** a volume scraper.

The bot primarily considers stories published in the rolling **previous 24 hours** and publishes only stories that pass the editorial quality gate. There is **no fixed post quota**. A run may publish zero stories when nothing is important enough.

Core rule:

```text
FRESH + IMPORTANT + FAN-RELEVANT + VERIFIED + NEW EVENT = PUBLISH
```

## Coverage

### Anime

- Major anime announcements
- New seasons and sequels
- Major trailers / PVs
- Manga → anime adaptations
- Major release-date announcements
- Major anime movies
- Major franchise updates
- Major cast / staff reveals
- Major production news

### Manga

- Major manga announcements
- Major returns / hiatuses
- Major series endings
- Major creator / publisher news
- Major sales / milestones

### Comics

- Major Marvel news
- Major DC news
- Major comic announcements
- Major comic storylines / events
- Major comic adaptations

Routine chapter or episode reminders, merchandise, generic rankings, reviews, fan theories, rumors/leaks, routine interviews, and low-impact promotional content are intentionally filtered.

## 24-hour window

Normal candidate eligibility:

```text
NOW - 24 HOURS  →  NOW + 10 MINUTES
```

A story older than 24 hours is not normally eligible unless a materially new development has occurred.

## Execution schedule

GitHub Actions runs every **3 hours**, using UTC cron that maps to every 3 hours in Asia/Dhaka:

```text
06:00
09:00
12:00
15:00
18:00
21:00
00:00
03:00
```

The workflow never uses a fixed daily or per-run publication quota.

## Discovery architecture

```text
RSS specialist sources
        ↓
Google News gap fill
        ↓
Exa gap fill
        ↓
24-hour freshness gate
        ↓
URL + title deduplication
        ↓
Event clustering
        ↓
Deterministic low-value filter
        ↓
Cerebras editorial ranking
        ↓
82/100 publication gate
        ↓
Up to 6 selected by the three-sector balance engine
        ↓
Parallel article extraction + story generation
        ↓
One batched fact-verification pass
        ↓
Trailer / official-video discovery
        ↓
Image selection
        ↓
Dynamic Rich Message
        ↓
Telegram @ComicsNewsroom
        ↓
Persistent event memory
```

## Editorial ranking

The internal 100-point model is:

| Factor | Points |
|---|---:|
| Fan interest | 25 |
| Significance | 20 |
| Franchise reach | 15 |
| Freshness | 15 |
| Novelty | 10 |
| Source authority | 10 |
| Visual value | 5 |
| **Total** | **100** |

The publication threshold is **82**. Rumor/speculation is capped below the publication gate.

Python performs the final numeric calculation. The model does not write the score itself.

## Event-based deduplication

Different sites covering the same event are clustered together.

Example:

```text
Anime News Network ┐
Crunchyroll         ├── same event ──→ one Telegram post
Anime Corner        ┤
ORICON              ┘
```

A later meaningful development remains publishable. For example:

```text
Season announced → Trailer released → Release date confirmed
```

These are separate editorial events.

## Official video feature

For trailer/PV stories, the bot first checks the source article for direct video links. If none is available, it performs a constrained Exa lookup for:

- YouTube
- Crunchyroll

YouTube links are validated through YouTube oEmbed. The bot never trusts an LLM-generated URL and never intentionally links a generic re-upload when a matching direct video can be verified.

When a valid trailer is found, the title is followed immediately by a Rich HTML H2 action:

```text
<h2>Watch Trailer 👉 <a href="OFFICIAL_VIDEO_URL">YouTube</a></h2>
```

The URL is hidden behind the clickable `YouTube` text. Crunchyroll is used the same way when that is the verified official video platform.

For YouTube videos, the video thumbnail can also become the story image when the source article has no usable image.

## Cerebras latency design

The real-time pipeline is deliberately kept under the normal Free-tier `gpt-oss-120b` request/token envelope.

```text
40 candidates
   ↓
2 ranking requests
   ↓
top 6
   ↓
6 story-generation requests in parallel
   ↓
1 batched fact-verification request
   ↓
≈ 9 normal Cerebras requests/run
```

The SDK client disables its default automatic retries because the previous production log showed repeated 429 responses followed by 57–59 second SDK sleeps. A small concurrency semaphore prevents an uncontrolled request burst, while the pipeline avoids serial verification calls.

Cerebras documents that real-time limits are measured by requests/minute and tokens/minute, using continuously replenished token buckets. It does not publish one universal real-time concurrency number, so the bot controls concurrency conservatively instead of assuming unlimited parallel requests.

## Dynamic Rich Message templates

The renderer selects a presentation based on the event type.

Supported visual modes include:

- Major / breaking announcement
- New season / sequel
- Trailer / PV
- Manga → anime adaptation
- Anime movie
- Manga update / ending
- Marvel
- DC
- Comic event / storyline
- Comic adaptation

The model produces structured JSON only. Python deterministically renders Rich HTML.

### Example trailer structure

```text
[media]

🎞️ NEW TRAILER

🎬 Title

One-sentence explanation.

✦ Studio: ...
✦ Release: ...
✦ Key reveal: ...

<h2>Watch Trailer 👉 <a href="OFFICIAL_VIDEO_URL">YouTube</a></h2>

@ComicsNewsroom #Anime #Trailer

Source: Anime News Network
```

### Example adaptation structure

```text
[media]

⚡ MANGA → ANIME

🎬 Title

The manga has officially received an anime adaptation.

✦ Studio: ...
✦ Format: ...
✦ Release: ...

@ComicsNewsroom #Manga #Anime

Source: ...
```

Only supported fields are rendered. Empty fields disappear.

## Image pipeline

Priority:

```text
Official key visual / artwork
        ↓
Official promotional image
        ↓
Article image
        ↓
Verified YouTube thumbnail for trailer stories
        ↓
Source logo
        ↓
Source-name fallback
```

Portrait artwork preserves its aspect ratio. Posters/covers are not forced into 16:9.

Normal editorial images may receive a small `@ComicsNewsroom` branding chip. Full posters/covers do not.

## Sources

### RSS-first sources

- Anime News Network
- Anime Corner
- MyAnimeList News
- Anime Hunch
- Anime UK News
- Otaku USA
- ComicBook.com
- Bleeding Cool
- The Beat
- AIPT
- CBR
- SuperHeroHype
- Toei Animation

### Gap-fill / verification domains

The source allow-list also covers specialist and official domains such as Crunchyroll, Tokyo Otaku Mode, ORICON, Animate Times, VIZ Media, Kodansha USA, Shueisha, Shonen Jump, Marvel, DC, Image Comics, Dark Horse, IDW, BOOM! Studios, Skybound, MAPPA, Aniplex, ufotable, WIT Studio, Bones, CloverWorks, A-1 Pictures and Kyoto Animation. Marvel and DC are consumed through gap-fill discovery rather than the broken RSS endpoints shown in the previous production log.

## Required GitHub Secrets

```text
EXA_API_KEY
CEREBRAS_API_KEY
TELEGRAM_BOT_TOKEN
```

Optional:

```text
TELEGRAM_ADMIN_CHAT_ID
```

The public channel is hard-configured by the workflow as:

```text
@ComicsNewsroom
```

The AI model remains:

```text
gpt-oss-120b
```

## Dependencies

The project intentionally keeps the previous stack:

```text
cerebras_cloud_sdk
exa-py
requests
urllib3
beautifulsoup4
Pillow
feedparser
trafilatura
```

## Local validation

With project dependencies installed:

```bash
python -m py_compile main.py
python main.py --self-test
```

The self-test covers taxonomy, ranking arithmetic, low-value filtering, 24-hour window behavior, video-link rendering, and poster aspect-ratio preservation.

## Repository tree

```text
.
├── .github/
│   └── workflows/
│       ├── newbot.yml
│       └── import-zip.yml
├── main.py
├── Template.md
├── README.md
├── requirements.txt
├── news_state.json
└── posted_urls.txt
```

## Three-sector balance

The newsroom has exactly three top-level sectors:

```text
Anime | Manga | Comics
```

Marvel and DC are treated as high-value subtopics within Comics. News selection is sector-balanced:

1. Give every populated sector a first-pass opportunity.
2. Never force a weak story merely to fill a sector.
3. Limit a sector to two news posts per run.
4. Fill remaining slots by editorial score with a small 24-hour under-coverage adjustment.
5. Use the previous 24 hours of published sector counts to prevent one sector from dominating repeatedly.

This is equal opportunity, not forced equal output.

## Fan Extra: one value post per run

Every scheduled run can publish **one separate FAN EXTRA** in addition to the news selection. The extra is designed to make the channel useful even when the reader is not looking for breaking news.

The value formats rotate to avoid repetition:

- Quick Fact
- Hidden Detail
- Franchise Timeline
- Creator Spotlight
- Fan Guide
- Origin Story
- Why It Matters
- Did You Know

The extra is generated only from source-backed context from a strong current or recent story. It remembers recently used formats and works so the same franchise/format does not repeat too often. It uses the same Cerebras model, the same Rich Message transport, and the existing image pipeline.

The extra is stored separately from news-event history and does not consume a news-sector slot. It is limited to one per scheduled run.
