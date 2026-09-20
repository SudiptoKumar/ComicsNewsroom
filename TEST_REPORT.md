# ComicsNewsroom V4.1 Test Report

Date: 2026-09-20
Target: @ComicsNewsroom
Schedule: every 3 hours
Freshness: rolling 24 hours, plus bounded meaningful-update exception
Sectors: Anime, Manga, Comics
Typical selection: 7-10, never a forced quota

## Test suite

| Test | Result |
|---|---|
| Python compile | PASS |
| Self-test | PASS |
| Executable fixture test | PASS |
| Cerebras schema contract | PASS |
| AI failure / candidate isolation | PASS |
| Partial Cerebras 429 preservation | PASS |
| Cerebras retry/backoff simulation | PASS |
| AI/research/video pipeline smoke | PASS |
| Dynamic template matrix | PASS |
| Telegram Rich Message -> sendPhoto fallback | PASS |
| Full production orchestration smoke | PASS |
| GitHub Actions workflow contract | PASS |

Result: **ALL AVAILABLE OFFLINE TESTS PASS**

## Tested behavior

- 3-hour workflow cadence with overlap protection
- @ComicsNewsroom channel configuration
- exact three-sector taxonomy
- Marvel/DC normalized under Comics
- rolling 24-hour freshness with no future upper-bound window
- meaningful older update handling
- multilingual Anime/Manga signal detection including Japanese and Korean headlines
- unrelated gaming and generic source-page rejection
- event-based duplicate collapse before expensive generation
- quality-first 7-10 selection with no filler quota
- soft sector diversity
- deterministic ranking fallback
- globally paced, serial Cerebras calls
- centralized Cerebras 429 retry/backoff
- candidate-level failure isolation
- rate-limited events remain retryable rather than permanently seen
- partial success survives a mid-run Cerebras 429
- bounded Exa request pacing and retry handling
- bounded Telegram retry behavior
- Rich Message fallback to Bot API sendPhoto
- official-source-first research path
- direct official YouTube/Crunchyroll trailer linking
- nine dynamic editorial rendering variants
- strict Cerebras JSON-schema compatibility audit
- persistent event publication path

## Live-service limitation

The build sandbox did not have access to production API credentials and live external service calls were not executed here. The tests therefore validate the real executable path with deterministic stubs plus production-like failure injection, including Cerebras 429 behavior and Telegram 429 behavior.

A live GitHub Actions run using the real secrets is still required to validate current account-specific Cerebras/Exa limits, source availability, image retrieval, and Telegram transport in production.
