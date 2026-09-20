# ComicsNewsroom V3.0 Test Report

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
| Fault injection | PASS |
| AI/research/video pipeline smoke | PASS |
| Dynamic template matrix | PASS |
| Telegram Rich Message -> sendPhoto fallback | PASS |
| Full production orchestration smoke | PASS |
| GitHub Actions workflow contract | PASS |

Result: **ALL AVAILABLE OFFLINE TESTS PASS**

## Tested behavior

- 3-hour workflow cadence
- @ComicsNewsroom channel configuration
- exact three-sector taxonomy
- Marvel/DC normalized under Comics
- rolling 24-hour freshness
- meaningful older update handling
- event-based duplicate collapse
- quality-first 7-10 selection
- soft sector diversity
- AI ranking fallback
- candidate-level failure isolation
- bounded Telegram retry behavior
- Rich Message fallback to Bot API sendPhoto
- official-source research path
- direct official YouTube trailer linking
- nine dynamic editorial rendering variants
- strict Cerebras JSON-schema compatibility audit
- persistent event publication path

## Live-service limitation

The build sandbox could not reach PyPI or the external production APIs, and production API credentials were not available. Therefore live RSS/Google News/Exa/Cerebras/YouTube/Crunchyroll/Telegram requests were not executed here. The repository includes offline stubs and fixture tests for the executable path and failure behavior.
