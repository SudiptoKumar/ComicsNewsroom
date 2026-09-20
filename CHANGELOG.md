# CHANGELOG

## V4.1 Production Reliability Release

- Replaced six-way story concurrency with serial expensive processing, matching the stable reference newsroom pattern.
- Added one global Cerebras request clock with configurable RPM, logical-call budget, attempt budget, Retry-After handling, exponential backoff and jitter.
- Added Exa pacing and bounded retry handling.
- Reduced ranking cap and research depth so the bot spends AI capacity on fewer, stronger events.
- Made 429/AI failures retryable in persistent queue state rather than permanently seen.
- Added retry caps for deterministic/content failures.
- Moved story processing to extract first, then research only when necessary, then generate.
- Official-source candidates no longer spend Exa calls merely to confirm their own source.
- Added Japanese/Korean relevance signals and major-event overrides for episode/preview headlines.
- Added hard protection against unrelated gaming and generic `News | DC` pages.
- Fixed the rolling 24-hour upper bound to the actual run clock.
- Made numeric grounding use both digit and number-word equivalents to reduce false rejection.
- Added 429 integration test to the CI workflow.
# Changelog

## V3.0 - Deep Editorial Intelligence

- Added multi-source discovery expansion for RSS, Google News, Exa and official-source research.
- Enforced exactly three sectors: Anime, Manga, Comics.
- Kept Marvel and DC under Comics.
- Increased ranking candidate capacity and deep-research pool.
- Changed selection to a quality-first 7-10 target with no forced quota.
- Reworked event handling around meaningful developments instead of URL-only duplication.
- Added stronger rolling 24-hour freshness handling.
- Added deep research and official-source evidence collection for strong candidates.
- Added compact Cerebras structured-output schemas.
- Added safe deterministic ranking fallback when AI ranking is unavailable.
- Added verification-batch salvage when the AI verification service is unavailable.
- Added direct official trailer/video discovery and verification helpers.
- Added official-source links in rich Telegram posts.
- Made sector diversity a soft tie-breaker instead of a hard quota.
- Rate-limited FAN EXTRA to avoid filler.
- Bounded Telegram retries and preserved Rich Message -> Bot API fallback.
- Added offline executable-path, schema-contract and fault-injection tests.
- Added V3 documentation and 3-hour GitHub Actions workflow validation.
- Added distinct dynamic Rich Message layouts for trailer, adaptation, manga, Marvel, DC, event, season and announcement stories.
- Added bounded meaningful-update handling for older follow-up reports.
- Added template matrix testing and final release test report.
