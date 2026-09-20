# Changelog

## V2.0.0

### ComicsNewsroom

- Reworked the Entertainment Newsroom foundation into a dedicated Anime, Manga and Comics newsroom.
- Target channel changed to `@ComicsNewsroom`.
- Replaced entertainment-sector taxonomy with Anime, Manga, Marvel, DC and Comics editorial sectors.
- Added a strict quality-first publication model with an 82/100 gate and no fixed post quota.
- Kept a rolling 24-hour discovery window with a small future-drift tolerance.
- Added specialist anime/manga/comics RSS sources plus expanded official-source allow-list coverage.
- Added event-focused trailer / PV classification.
- Added source-page video extraction for YouTube and Crunchyroll.
- Added constrained Exa fallback search for direct video links.
- Added YouTube oEmbed validation and YouTube thumbnail fallback.
- Prevented LLM-generated URLs from being trusted directly.
- Added dynamic Rich Message layouts for announcements, trailers, seasons, adaptations, manga updates, Marvel, DC and comic events.
- Preserved deterministic HTML rendering, image fallbacks, Rich Message transport and Bot API fallback.
- Preserved persistent event memory, duplicate protection, adaptive learning and feed health tracking.
- Updated GitHub Actions schedule to run every 3 hours.
- Added ComicsNewsroom-specific README and Template documentation.
- Reset production state files for a clean first deployment.
