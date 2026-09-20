import os
import re
import json
import time
import html
import argparse
import logging
import hashlib
import random
import unicodedata
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, urljoin, quote
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from io import BytesIO
from pathlib import Path
from threading import Lock

import requests
import feedparser
import trafilatura
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont, ImageFile
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from exa_py import Exa
from cerebras.cloud.sdk import Cerebras


# ============================================================
# CONFIGURATION
# ============================================================

EXA_API_KEY = os.environ["EXA_API_KEY"]
CEREBRAS_API_KEY = os.environ["CEREBRAS_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_CHANNEL = (os.environ.get("TELEGRAM_CHANNEL") or "@ComicsNewsroom").strip()
CHANNEL_TAG = TELEGRAM_CHANNEL if TELEGRAM_CHANNEL.startswith("@") else ""

# Optional. If set, feed-down alerts go here (a private chat/DM with the
# bot, not the public channel). If empty, alerts only go to the run log.
TELEGRAM_ADMIN_CHAT_ID = (os.environ.get("TELEGRAM_ADMIN_CHAT_ID") or "").strip()

NEWS_MODE = (os.environ.get("NEWS_MODE") or "update").strip().lower()

VALID_NEWS_MODES = {"update"}
if NEWS_MODE not in VALID_NEWS_MODES:
    raise ValueError(
        f"Invalid NEWS_MODE={NEWS_MODE!r}; expected one of {sorted(VALID_NEWS_MODES)}"
    )

CEREBRAS_MODEL = os.environ.get(
    "CEREBRAS_MODEL",
    "gpt-oss-120b",
)

POSTED_FILE = "posted_urls.txt"
STATE_FILE = "news_state.json"

BD_TZ = ZoneInfo("Asia/Dhaka")

# ============================================================
# TAXONOMY: COMICS + ANIME NEWSROOM
# ============================================================
SECTORS = ["Anime", "Manga", "Comics"]
REGION = "ComicAnime"

TOPICS = {"ComicAnime": [
    "Major Anime Announcement",
    "New Season / Sequel",
    "Major Trailer / PV",
    "Manga → Anime Adaptation",
    "Major Release Date",
    "Major Anime Movie",
    "Major Franchise Update",
    "Major Cast / Staff Reveal",
    "Major Production News",
    "Major Manga Announcement",
    "Major Manga Return / Hiatus",
    "Major Manga Ending",
    "Major Creator / Publisher News",
    "Major Sales / Milestone",
    "Major Marvel News",
    "Major DC News",
    "Major Comic Announcement",
    "Major Comic Storyline / Event",
    "Major Comic Adaptation",
]}

NEWS_PRIORITY = {
    "Major Anime Announcement": (1, 1),
    "New Season / Sequel": (1, 2),
    "Major Trailer / PV": (1, 3),
    "Manga → Anime Adaptation": (1, 4),
    "Major Release Date": (1, 5),
    "Major Anime Movie": (1, 6),
    "Major Franchise Update": (1, 7),
    "Major Cast / Staff Reveal": (2, 8),
    "Major Production News": (2, 9),
    "Major Manga Announcement": (2, 10),
    "Major Manga Return / Hiatus": (2, 11),
    "Major Manga Ending": (2, 12),
    "Major Creator / Publisher News": (2, 13),
    "Major Sales / Milestone": (3, 14),
    "Major Marvel News": (1, 15),
    "Major DC News": (1, 16),
    "Major Comic Announcement": (1, 17),
    "Major Comic Storyline / Event": (1, 18),
    "Major Comic Adaptation": (1, 19),
}

TOPIC_ALIASES = {
    "anime announcement": "Major Anime Announcement",
    "new anime": "Major Anime Announcement",
    "season": "New Season / Sequel",
    "sequel": "New Season / Sequel",
    "trailer": "Major Trailer / PV",
    "teaser": "Major Trailer / PV",
    "pv": "Major Trailer / PV",
    "adaptation": "Manga → Anime Adaptation",
    "manga to anime": "Manga → Anime Adaptation",
    "anime adaptation": "Manga → Anime Adaptation",
    "release date": "Major Release Date",
    "anime movie": "Major Anime Movie",
    "franchise": "Major Franchise Update",
    "cast": "Major Cast / Staff Reveal",
    "casting": "Major Cast / Staff Reveal",
    "staff": "Major Cast / Staff Reveal",
    "production": "Major Production News",
    "manga": "Major Manga Announcement",
    "manga update": "Major Manga Announcement",
    "hiatus": "Major Manga Return / Hiatus",
    "return": "Major Manga Return / Hiatus",
    "ending": "Major Manga Ending",
    "creator": "Major Creator / Publisher News",
    "publisher": "Major Creator / Publisher News",
    "sales": "Major Sales / Milestone",
    "milestone": "Major Sales / Milestone",
    "marvel": "Major Marvel News",
    "dc": "Major DC News",
    "comic": "Major Comic Announcement",
    "storyline": "Major Comic Storyline / Event",
    "event": "Major Comic Storyline / Event",
    "comic adaptation": "Major Comic Adaptation",
}

TOPIC_HASHTAGS = {
    "Major Anime Announcement": ["#Anime", "#Announcement"],
    "New Season / Sequel": ["#Anime", "#NewSeason"],
    "Major Trailer / PV": ["#Anime", "#Trailer"],
    "Manga → Anime Adaptation": ["#Manga", "#Anime"],
    "Major Release Date": ["#Anime", "#ReleaseDate"],
    "Major Anime Movie": ["#Anime", "#AnimeMovie"],
    "Major Franchise Update": ["#Anime", "#Update"],
    "Major Cast / Staff Reveal": ["#Anime", "#Cast"],
    "Major Production News": ["#Anime", "#Production"],
    "Major Manga Announcement": ["#Manga", "#Announcement"],
    "Major Manga Return / Hiatus": ["#Manga", "#MangaUpdate"],
    "Major Manga Ending": ["#Manga", "#FinalChapter"],
    "Major Creator / Publisher News": ["#Manga", "#Comics"],
    "Major Sales / Milestone": ["#Manga", "#Milestone"],
    "Major Marvel News": ["#Marvel", "#Comics"],
    "Major DC News": ["#DC", "#Comics"],
    "Major Comic Announcement": ["#Comics", "#Announcement"],
    "Major Comic Storyline / Event": ["#Comics", "#Event"],
    "Major Comic Adaptation": ["#Comics", "#Adaptation"],
}

SOURCE_NAMES = {
    "animenewsnetwork.com": "Anime News Network",
    "animecorner.me": "Anime Corner",
    "anitrendz.net": "Anime Trending",
    "myanimelist.net": "MyAnimeList",
    "animehunch.com": "Anime Hunch",
    "otakuusamagazine.com": "Otaku USA",
    "animeuknews.net": "Anime UK News",
    "otakunews.com": "Otaku News",
    "crunchyroll.com": "Crunchyroll News",
    "tokyootakumode.com": "Tokyo Otaku Mode",
    "oricon.co.jp": "ORICON NEWS",
    "animatetimes.com": "Animate Times",
    "viz.com": "VIZ Media",
    "kodansha.us": "Kodansha USA",
    "shueisha.co.jp": "Shueisha",
    "shonenjump.com": "Shonen Jump",
    "kadokawa.co.jp": "KADOKAWA",
    "comicbook.com": "ComicBook.com",
    "bleedingcool.com": "Bleeding Cool",
    "comicsbeat.com": "The Beat",
    "aiptcomics.com": "AIPT",
    "cbr.com": "CBR",
    "superherohype.com": "SuperHeroHype",
    "brokenfrontier.com": "Broken Frontier",
    "multiversitycomics.com": "Multiversity Comics",
    "thecomicsjournal.com": "The Comics Journal",
    "icv2.com": "ICv2",
    "marvel.com": "Marvel",
    "dc.com": "DC",
    "imagecomics.com": "Image Comics",
    "darkhorse.com": "Dark Horse Comics",
    "idwpublishing.com": "IDW Publishing",
    "boom-studios.com": "BOOM! Studios",
    "skybound.com": "Skybound",
    "toei-animation.com": "Toei Animation",
    "mappa.co.jp": "MAPPA",
    "aniplex.co.jp": "Aniplex",
    "ufotable.com": "ufotable",
    "witstudio.co.jp": "WIT Studio",
    "bones.co.jp": "Bones",
    "cloverworks.co.jp": "CloverWorks",
    "a1p.jp": "A-1 Pictures",
    "kyotoanimation.co.jp": "Kyoto Animation",
}

PRIMARY_DOMAINS = sorted({
    "animenewsnetwork.com", "animecorner.me", "anitrendz.net", "myanimelist.net",
    "animehunch.com", "otakuusamagazine.com", "animeuknews.net", "otakunews.com",
    "crunchyroll.com", "tokyootakumode.com", "oricon.co.jp", "animatetimes.com",
    "viz.com", "kodansha.us", "shueisha.co.jp", "shonenjump.com", "kadokawa.co.jp",
    "comicbook.com", "bleedingcool.com", "comicsbeat.com", "aiptcomics.com",
    "cbr.com", "superherohype.com", "brokenfrontier.com", "multiversitycomics.com",
    "thecomicsjournal.com", "icv2.com", "marvel.com", "dc.com", "imagecomics.com",
    "darkhorse.com", "idwpublishing.com", "boom-studios.com", "skybound.com",
    "toei-animation.com", "mappa.co.jp", "aniplex.co.jp", "ufotable.com",
    "witstudio.co.jp", "bones.co.jp", "cloverworks.co.jp", "a1p.jp", "kyotoanimation.co.jp",
    "shogakukan.com", "square-enix.com", "akitashoten.co.jp", "hakusensha.co.jp",
})
FALLBACK_DOMAINS = []
ALL_PRIMARY_DOMAINS = PRIMARY_DOMAINS
ALL_FALLBACK_DOMAINS = FALLBACK_DOMAINS
ALL_ALLOWED_DOMAINS = PRIMARY_DOMAINS

OFFICIAL_SOURCE_DOMAINS = {
    "marvel.com", "dc.com", "viz.com", "kodansha.us", "shueisha.co.jp", "shonenjump.com", "kadokawa.co.jp",
    "toei-animation.com", "mappa.co.jp", "aniplex.co.jp", "ufotable.com", "witstudio.co.jp",
    "bones.co.jp", "cloverworks.co.jp", "a1p.jp", "kyotoanimation.co.jp", "crunchyroll.com",
    "imagecomics.com", "darkhorse.com", "idwpublishing.com", "boom-studios.com", "skybound.com",
    "shogakukan.com", "square-enix.com", "akitashoten.co.jp", "hakusensha.co.jp",
    "imagecomics.com", "darkhorse.com", "idwpublishing.com", "boom-studios.com", "skybound.com",
    "shogakukan.com", "square-enix.com", "akitashoten.co.jp", "hakusensha.co.jp",
}

def source_class_for_url(url):
    return "official" if normalized_domain(url) in OFFICIAL_SOURCE_DOMAINS else "reported"

# RSS-first. Google News + Exa fill coverage gaps using the same source allow-list.
RSS_FEEDS = [
    {"name":"Anime News Network","region":REGION,"url":"https://www.animenewsnetwork.com/all/rss.xml","source_class":"reported"},
    {"name":"Anime Corner","region":REGION,"url":"https://animecorner.me/feed/","source_class":"reported"},
    {"name":"MyAnimeList News","region":REGION,"url":"https://myanimelist.net/rss/news.xml","source_class":"reported"},
    {"name":"Anime Hunch","region":REGION,"url":"https://www.animehunch.com/feed/","source_class":"reported"},
    {"name":"Anime UK News","region":REGION,"url":"https://animeuknews.net/feed/","source_class":"reported"},
    {"name":"Otaku USA","region":REGION,"url":"https://www.otakuusamagazine.com/feed/","source_class":"reported"},
    {"name":"ComicBook.com","region":REGION,"url":"https://comicbook.com/feed/","source_class":"reported"},
    {"name":"Bleeding Cool","region":REGION,"url":"https://bleedingcool.com/comics/feed/","source_class":"reported"},
    {"name":"The Beat","region":REGION,"url":"https://www.comicsbeat.com/feed/","source_class":"reported"},
    {"name":"AIPT","region":REGION,"url":"https://aiptcomics.com/feed/","source_class":"reported"},
    {"name":"CBR","region":REGION,"url":"https://www.cbr.com/feed/","source_class":"reported"},
    {"name":"SuperHeroHype","region":REGION,"url":"https://www.superherohype.com/feed","source_class":"reported"},
    {"name":"Toei Animation","region":REGION,"url":"https://www.toei-animation.com/news/feed/","source_class":"official"},
]

# ============================================================
# GLOBAL EDITORIAL SETTINGS
# ============================================================
PUBLISH_THRESHOLD = 82
RANKING_BATCH_SIZE = 20
# Proven-load model: keep the expensive AI stages small and serial.
MAX_RANK_CANDIDATES = 60
MAX_STORY_CANDIDATES = 11
STORY_CONCURRENCY = 1
NEWS_RESEARCH_TARGET = 11
NEWS_POST_TARGET_MIN = 7
NEWS_POST_MAX_PER_RUN = 10
DEEP_RESEARCH_MAX_URLS = 2
SECTOR_BALANCE_LOOKBACK_HOURS = 24
READER_EXTRA_ENABLED = True
READER_EXTRA_MAX_PER_RUN = 1
READER_EXTRA_MIN_INTERVAL_HOURS = 20
READER_EXTRA_RETENTION_DAYS = 45
READER_EXTRA_HISTORY_LIMIT = 120
READER_EXTRA_AVOID_WORK_DAYS = 14
READER_EXTRA_MAX_COMPLETION_TOKENS = 700
READER_EXTRA_TYPES = [
    "Quick Fact",
    "Hidden Detail",
    "Franchise Timeline",
    "Creator Spotlight",
    "Fan Guide",
    "Origin Story",
    "Why It Matters",
    "Did You Know",
]
RANKING_MAX_COMPLETION_TOKENS = 900
STORY_MAX_COMPLETION_TOKENS = 650
VERIFY_MAX_COMPLETION_TOKENS = 550
RESEARCH_MAX_RESULTS = 3
DISCOVERY_LOOKBACK_HOURS = 24
ROLLING_DISCOVERY_HOURS = 24
# The normal window ends at the actual run clock. Older items may enter only
# through meaningful_update_candidate().
QUEUE_RETENTION_DAYS = 3
EVENT_RETENTION_DAYS = 21
MAX_RSS_CANDIDATES = 500
MAX_EXA_CANDIDATES = 140
MAX_GOOGLE_NEWS_CANDIDATES = 120
THIN_EXCERPT_CHARS = 180
MAX_EXCERPT_ENRICH = 10
POST_DELAY_SECONDS = 0.8
# Conservative, configurable AI/search pacing. The reference working bot uses
# sequential expensive processing; ComicsNewsroom follows the same model.
CEREBRAS_REQUESTS_PER_MINUTE = max(1, int(os.environ.get("CEREBRAS_REQUESTS_PER_MINUTE", "6")))
CEREBRAS_REQUEST_INTERVAL_SECONDS = 60.0 / CEREBRAS_REQUESTS_PER_MINUTE
CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN = max(1, int(os.environ.get("CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN", "17")))
CEREBRAS_MAX_ATTEMPTS_PER_RUN = max(CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN, int(os.environ.get("CEREBRAS_MAX_ATTEMPTS_PER_RUN", "26")))
CEREBRAS_MAX_RETRY_ATTEMPTS = max(0, int(os.environ.get("CEREBRAS_MAX_RETRY_ATTEMPTS", "3")))
CEREBRAS_MAX_RETRY_WAIT_SECONDS = max(5.0, float(os.environ.get("CEREBRAS_MAX_RETRY_WAIT_SECONDS", "60")))
EXA_REQUESTS_PER_SECOND = max(0.2, float(os.environ.get("EXA_REQUESTS_PER_SECOND", "1.5")))
EXA_REQUEST_INTERVAL_SECONDS = 1.0 / EXA_REQUESTS_PER_SECOND
EXA_MAX_RETRY_ATTEMPTS = max(0, int(os.environ.get("EXA_MAX_RETRY_ATTEMPTS", "2")))
AI_FAILURE_RETRY_HOURS = max(0.25, float(os.environ.get("AI_FAILURE_RETRY_HOURS", "3")))
CONTENT_FAILURE_RETRY_HOURS = max(0.25, float(os.environ.get("CONTENT_FAILURE_RETRY_HOURS", "6")))
MAX_CONTENT_RETRY_ATTEMPTS = max(0, int(os.environ.get("MAX_CONTENT_RETRY_ATTEMPTS", "2")))
DEFAULT_EVENT_DEDUP_HOURS = 36
ANNOUNCEMENT_DEDUP_HOURS = 48
TRAILER_DEDUP_HOURS = 72
ADAPTATION_DEDUP_HOURS = 72
RELEASE_EVENT_DEDUP_HOURS = 72
MANGA_UPDATE_DEDUP_HOURS = 48
EVENT_FINGERPRINT_RETENTION_DAYS = 45
WORK_MEMORY_RETENTION_DAYS = 60
LEARNED_MIN_OBSERVATIONS = 5
LEARNED_LOW_SCORE_CEILING = 58
LEARNED_LOW_RATIO = 0.80
LEARNED_HISTORY_LIMIT = 600
LEARNED_PATTERN_RETENTION_DAYS = 45
SOURCE_LEARNING_MIN_OBSERVATIONS = 12
SOURCE_LEARNING_LOW_RATIO = 0.85
SOURCE_LEARNING_LOW_SCORE_CEILING = 55
MAX_RICH_CHARACTERS = 32768
MAX_TELEGRAM_CAPTION_CHARACTERS = 1024
PRE_FILTER_HISTORY_LIMIT = 1200

INSTITUTIONS = [
    "Toei Animation", "MAPPA", "Aniplex", "ufotable", "WIT Studio", "Bones", "CloverWorks",
    "A-1 Pictures", "Kyoto Animation", "Crunchyroll", "VIZ Media", "Kodansha", "Shueisha",
    "Shonen Jump", "Marvel", "DC", "Image Comics", "Dark Horse", "IDW", "BOOM! Studios",
    "Skybound", "Netflix", "Disney+", "Hulu", "Prime Video", "Apple TV+", "HBO Max",
]

STOPWORDS = {
    "the","a","an","and","or","of","to","in","on","for","from","with","by","at","as","is","are","was","were",
    "be","been","being","has","have","had","do","does","did","will","would","could","should","may","might","can",
    "this","that","these","those","it","its","their","they","them","he","she","his","her","we","our","you","your",
    "new","after","before","over","into","than","about","just","now","officially","official","fans","fan",
}


def canonical_topic(topic, region=REGION):
    key = safe_text(topic).lower().strip()
    if key in TOPIC_ALIASES:
        return TOPIC_ALIASES[key]
    for item in TOPICS["ComicAnime"]:
        if key == item.lower():
            return item
    patterns = [
        (("trailer","teaser","promo video","pv"), "Major Trailer / PV"),
        (("manga adaptation","anime adaptation","gets an anime","adapted into an anime"), "Manga → Anime Adaptation"),
        (("season 2","season 3","season 4","season 5","new season","sequel","returns"), "New Season / Sequel"),
        (("release date","premiere date","premieres on","set to release"), "Major Release Date"),
        (("movie","feature film","theatrical"), "Major Anime Movie"),
        (("cast","casting","voice actor","voice actress","director","staff"), "Major Cast / Staff Reveal"),
        (("production","studio change","delay","production committee"), "Major Production News"),
        (("hiatus","returns","returning","back from hiatus"), "Major Manga Return / Hiatus"),
        (("final chapter","ending","ends","concludes"), "Major Manga Ending"),
        (("marvel","x-men","spider-man","avengers"), "Major Marvel News"),
        (("dc","batman","superman","wonder woman","justice league"), "Major DC News"),
        (("comic","graphic novel","comic book"), "Major Comic Announcement"),
        (("crossover","event","storyline","universe-wide"), "Major Comic Storyline / Event"),
        (("adaptation","live-action","animated series","movie adaptation"), "Major Comic Adaptation"),
        (("sales","copies sold","million copies","milestone","record"), "Major Sales / Milestone"),
        (("announcement","announces","announced","confirmed","greenlit"), "Major Anime Announcement"),
    ]
    for needles, canon in patterns:
        if any(n in key for n in needles):
            return canon
    return "Major Anime Announcement"


def normalize_sector(value):
    raw = safe_text(value).strip().lower()
    aliases = {
        "anime": "Anime",
        "manga": "Manga",
        "marvel": "Comics",
        "dc": "Comics",
        "comics": "Comics",
        "comic": "Comics",
        "western comics": "Comics",
    }
    return aliases.get(raw, "")


def sector_hashtag(sector):
    return {"Anime": "#Anime", "Manga": "#Manga", "Comics": "#Comics"}.get(normalize_sector(sector), "#Anime")


def category_hashtags(story):
    tags = []
    for tag in TOPIC_HASHTAGS.get(safe_text(story.get("topic")), []):
        if tag not in tags:
            tags.append(tag)
    base = sector_hashtag(story.get("sector"))
    if base not in tags:
        tags.append(base)
    if "#ComicsNews" not in tags:
        tags.append("#ComicsNews")
    return tags[:3]


# ============================================================
# LOGGING + HTTP# ============================================================
# LOGGING + HTTP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("comics-anime-news-bot")

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 50_000_000

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    )
}

session = requests.Session()
session.headers.update(HEADERS)

retry_policy = Retry(
    total=4,
    connect=4,
    read=4,
    backoff_factor=1.5,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    respect_retry_after_header=True,
)

adapter = HTTPAdapter(
    max_retries=retry_policy,
    pool_connections=20,
    pool_maxsize=20,
)

session.mount("https://", adapter)
session.mount("http://", adapter)


# ============================================================
# HELPERS
# ============================================================

def safe_text(value):
    return "" if value is None else str(value).strip()


def canonical_url(url):
    raw = safe_text(url)
    if not raw:
        return ""

    parsed = urlparse(raw)

    host = (
        parsed.netloc.lower()
        .removeprefix("www.")
        .removeprefix("amp.")
    )

    path = parsed.path or "/"
    path = path.rstrip("/")
    path = re.sub(r"/amp$", "", path, flags=re.I)
    path = re.sub(r"\.amp$", "", path, flags=re.I)

    return f"{host}{path}"


def normalize_title(title):
    text = safe_text(title).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def title_tokens(text):
    text = normalize_title(text)
    return {
        token
        for token in text.split()
        if len(token) >= 3
    }


def token_jaccard(a, b):
    aa = title_tokens(a)
    bb = title_tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa & bb) / max(1, len(aa | bb))


def title_similarity(a, b):
    na = normalize_title(a)
    nb = normalize_title(b)
    if not na or not nb:
        return 0.0
    sequence = SequenceMatcher(None, na, nb).ratio()
    jaccard = token_jaccard(na, nb)
    return max(sequence, jaccard)


def event_similarity(a, b):
    """Cheap event-level similarity without an embedding dependency."""
    sequence = SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()
    jaccard = token_jaccard(a, b)
    return (0.55 * sequence) + (0.45 * jaccard)


def likely_same_event(a, b):
    return (
        title_similarity(a, b) >= 0.90
        or event_similarity(a, b) >= 0.80
    )


def parse_datetime(value):
    raw = safe_text(value)
    if not raw:
        return None

    try:
        dt = datetime.fromisoformat(
            raw.replace("Z", "+00:00")
        )
        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )
        return dt.astimezone(BD_TZ)
    except Exception:
        pass

    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )
        return dt.astimezone(BD_TZ)
    except Exception:
        return None


def feed_entry_datetime(entry):
    for key in (
        "published_parsed",
        "updated_parsed",
        "created_parsed",
    ):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(
                    *parsed[:6],
                    tzinfo=timezone.utc,
                ).astimezone(BD_TZ)
            except Exception:
                pass

    for key in (
        "published",
        "updated",
        "created",
    ):
        dt = parse_datetime(
            entry.get(key)
        )
        if dt:
            return dt

    return None


def trim_source_text(text, limit):
    """Trim source text before rendering. Never appends ellipses."""
    text = safe_text(text)
    if len(text) <= limit:
        return text

    trimmed = text[:limit].rstrip()
    if " " in trimmed:
        trimmed = trimmed.rsplit(" ", 1)[0]

    return trimmed.rstrip(" ,:;-/—")


def clean_generated_text(text):
    text = safe_text(text)

    # Prevent visible truncation artifacts.
    text = re.sub(r"\.{2,}", ".", text)
    text = text.replace("\u2026", "")

    # Remove incomplete endings.
    text = re.sub(
        r"\s*[,;:]\s*$",
        "",
        text,
    )
    text = re.sub(
        r"\s*[-—]\s*$",
        "",
        text,
    )

    return text.strip()


def complete_text(text):
    raw = safe_text(text)
    if not raw:
        return False

    # A text that clean_generated_text() would mutilate
    # (trailing dash/comma/colon) is INCOMPLETE.
    if re.search(r"[\s,;:\-—…]+$", raw):
        return False

    text = clean_generated_text(raw)
    if not text:
        return False

    return not text.endswith(
        (",", ";", ":", "-", "—", "…")
    )


def source_name(url):
    domain = (
        urlparse(
            safe_text(url)
        )
        .netloc
        .lower()
        .removeprefix("www.")
    )

    return SOURCE_NAMES.get(
        domain,
        domain or "Source",
    )


def article_region(url):
    return REGION


def now_iso():
    return datetime.now(
        BD_TZ
    ).isoformat()


# ============================================================
# STATE: QUEUE + EVENTS + KNOWLEDGE
# ============================================================

def default_state():
    return {
        "feeds": {},
        "queue": {},
        "events": {},
        "event_clusters": {},
        "posted_event_ids": [],
        "recent_titles": [],
        "work_memory": {},
        "publication_fingerprints": [],
        "fresh_start_at": "",
        "learned_rejections": {},
        "score_history": [],
        "adaptive_metrics": {
            "raw_discovered": 0,
            "pre_cerebras_rejected": 0,
            "hard_rejected": 0,
            "duplicate_rejected": 0,
            "learned_rejected": 0,
            "passed_to_cerebras": 0,
            "cerebras_ranked": 0,
            "published": 0,
            "estimated_candidates_avoided": 0,
            "reader_extra_published": 0,
        },
        "source_quality": {},
        "category_coverage": {},
        "topic_coverage": {},
        "reader_extra_history": [],
        "reader_extra_type_history": [],
        "reader_extra_work_history": [],
    }


def load_state():
    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        if not isinstance(
            data,
            dict,
        ):
            return default_state()

        base = default_state()
        base.update(data)

        return base

    except Exception:
        return default_state()


def json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def save_state(state):
    tmp = STATE_FILE + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
            default=json_default,
        )

    os.replace(
        tmp,
        STATE_FILE,
    )


def load_posted_urls():
    try:
        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            return {
                canonical_url(line)
                for line in f
                if safe_text(line)
            }
    except FileNotFoundError:
        return set()


def save_posted_url(canonical):
    if not canonical:
        return

    with open(
        POSTED_FILE,
        "a",
        encoding="utf-8",
    ) as f:
        f.write(
            canonical
            + "\n"
        )


STATE = load_state()
POSTED_URLS = load_posted_urls()


def prune_state():
    cutoff_queue = (
        datetime.now(BD_TZ)
        - timedelta(
            days=QUEUE_RETENTION_DAYS
        )
    )

    cutoff_events = (
        datetime.now(BD_TZ)
        - timedelta(
            days=EVENT_RETENTION_DAYS
        )
    )

    queue = STATE.get(
        "queue",
        {},
    )

    keep_queue = {}

    for key, item in queue.items():
        dt = parse_datetime(
            item.get("last_seen")
            or item.get("published_date")
        )

        if (
            dt
            and dt >= cutoff_queue
        ):
            keep_queue[key] = item

    STATE["queue"] = keep_queue

    events = STATE.get(
        "events",
        {},
    )

    keep_events = {}

    for key, event in events.items():
        dt = parse_datetime(
            event.get("published_at")
            or event.get("selected_at")
        )

        if (
            dt
            and dt >= cutoff_events
        ):
            keep_events[key] = event

    STATE["events"] = keep_events

    titles = STATE.get(
        "recent_titles",
        [],
    )
    STATE["recent_titles"] = titles[-400:]

    cutoff_learning = datetime.now(BD_TZ) - timedelta(days=LEARNED_PATTERN_RETENTION_DAYS)
    learned = STATE.get("learned_rejections", {})
    for key in list(learned):
        last_seen = parse_datetime(learned[key].get("last_seen"))
        if last_seen and last_seen < cutoff_learning:
            del learned[key]
    STATE["learned_rejections"] = learned

    cutoff_work = datetime.now(BD_TZ) - timedelta(days=WORK_MEMORY_RETENTION_DAYS)
    work_memory = STATE.get("work_memory", {})
    for key in list(work_memory):
        last = parse_datetime(work_memory[key].get("last_published_at"))
        if last and last < cutoff_work:
            del work_memory[key]
    STATE["work_memory"] = work_memory

    fingerprints = STATE.get("publication_fingerprints", [])
    cutoff_fingerprints = datetime.now(BD_TZ) - timedelta(days=EVENT_FINGERPRINT_RETENTION_DAYS)
    STATE["publication_fingerprints"] = [
        fp for fp in fingerprints
        if (parse_datetime(fp.get("published_at")) is not None)
        and parse_datetime(fp.get("published_at")) >= cutoff_fingerprints
    ][-1000:]

    history = STATE.get("score_history", [])
    STATE["score_history"] = history[-LEARNED_HISTORY_LIMIT:]
    extra_history = STATE.get("reader_extra_history", [])
    cutoff_extra = datetime.now(BD_TZ) - timedelta(days=READER_EXTRA_RETENTION_DAYS)
    STATE["reader_extra_history"] = [
        x for x in extra_history
        if (parse_datetime(x.get("published_at")) is None) or parse_datetime(x.get("published_at")) >= cutoff_extra
    ][-READER_EXTRA_HISTORY_LIMIT:]
    STATE["reader_extra_type_history"] = STATE.get("reader_extra_type_history", [])[-12:]
    STATE["reader_extra_work_history"] = STATE.get("reader_extra_work_history", [])[-30:]


# ============================================================
# TIME WINDOWS
# ============================================================

NOW_BD = datetime.now(
    BD_TZ
)

TODAY_START = NOW_BD.replace(
    hour=0,
    minute=0,
    second=0,
    microsecond=0,
)

YESTERDAY_START = (
    TODAY_START
    - timedelta(days=1)
)

DISCOVERY_START = (
    NOW_BD
    - timedelta(
        hours=ROLLING_DISCOVERY_HOURS
    )
)
DISCOVERY_END = NOW_BD

DISCOVERY_TARGET_PER_REGION = 18


# ============================================================
# CLIENTS
# ============================================================

exa = Exa(
    api_key=EXA_API_KEY
)

# Disable SDK retries so the newsroom controls pacing centrally.
cerebras = Cerebras(
    api_key=CEREBRAS_API_KEY,
    max_retries=0,
    timeout=30.0,
)

# One global clock for every Cerebras call: ranking, story generation,
# verification and FAN EXTRA all share the same budget.
_cerebras_lock = Lock()
_cerebras_next_allowed_at = 0.0
_cerebras_logical_calls = 0
_cerebras_attempts = 0
_cerebras_rate_limited = False

class CerebrasRateLimitError(RuntimeError):
    pass

class CerebrasBudgetError(RuntimeError):
    pass

def _header_value(headers, *names):
    if not headers:
        return None
    for name in names:
        try:
            value = headers.get(name)
        except Exception:
            value = None
        if value is None:
            try:
                value = headers.get(name.lower())
            except Exception:
                value = None
        if value is not None:
            return value
    return None

def _exception_headers(exc):
    response = getattr(exc, "response", None)
    return getattr(response, "headers", None) or {}

def _retry_after_seconds(exc, attempt_no):
    headers = _exception_headers(exc)
    raw = _header_value(headers, "retry-after", "Retry-After")
    if raw is not None:
        try:
            return min(CEREBRAS_MAX_RETRY_WAIT_SECONDS, max(0.5, float(raw)))
        except Exception:
            pass
    for key in (
        "x-ratelimit-reset-requests-minute",
        "x-ratelimit-reset-tokens-minute",
        "x-ratelimit-reset-requests",
        "x-ratelimit-reset-tokens",
    ):
        raw = _header_value(headers, key)
        if raw is not None:
            match = re.search(r"(\d+(?:\.\d+)?)", safe_text(raw))
            if match:
                return min(CEREBRAS_MAX_RETRY_WAIT_SECONDS, max(0.5, float(match.group(1))))
    # No server hint: exponential backoff with small jitter.
    base = min(CEREBRAS_MAX_RETRY_WAIT_SECONDS, 2 ** max(0, attempt_no - 1))
    return base + random.uniform(0.15, 0.75)

def _reserve_cerebras_attempt():
    global _cerebras_next_allowed_at, _cerebras_attempts
    with _cerebras_lock:
        if _cerebras_attempts >= CEREBRAS_MAX_ATTEMPTS_PER_RUN:
            raise CerebrasBudgetError(
                f"Cerebras attempt budget exhausted ({CEREBRAS_MAX_ATTEMPTS_PER_RUN})"
            )
        now = time.monotonic()
        wait = max(0.0, _cerebras_next_allowed_at - now)
        _cerebras_next_allowed_at = max(now, _cerebras_next_allowed_at) + CEREBRAS_REQUEST_INTERVAL_SECONDS
        _cerebras_attempts += 1
    if wait > 0:
        time.sleep(wait)

def cerebras_create(**kwargs):
    """Centralized, paced, retry-aware Cerebras request. All stages use it."""
    global _cerebras_logical_calls, _cerebras_rate_limited
    with _cerebras_lock:
        if _cerebras_logical_calls >= CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN:
            raise CerebrasBudgetError(
                f"Cerebras logical-call budget exhausted ({CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN})"
            )
        _cerebras_logical_calls += 1

    last_exc = None
    for attempt in range(1, CEREBRAS_MAX_RETRY_ATTEMPTS + 2):
        try:
            _reserve_cerebras_attempt()
            response = cerebras.chat.completions.create(**kwargs)
            logger.info("Cerebras call succeeded | logical=%d attempt=%d", _cerebras_logical_calls, attempt)
            return response
        except Exception as exc:
            last_exc = exc
            message = safe_text(exc)
            status = getattr(exc, "status_code", None)
            is_429 = status == 429 or "429" in message or "rate limit" in message.lower()
            if is_429 and attempt <= CEREBRAS_MAX_RETRY_ATTEMPTS:
                delay = _retry_after_seconds(exc, attempt)
                logger.warning(
                    "Cerebras 429 | attempt=%d/%d | retry_in=%.1fs",
                    attempt, CEREBRAS_MAX_RETRY_ATTEMPTS + 1, delay,
                )
                time.sleep(delay)
                continue
            if is_429:
                _cerebras_rate_limited = True
                logger.error("Cerebras 429 exhausted retries | attempts=%d", attempt)
                raise CerebrasRateLimitError(message or "Cerebras rate limit") from exc
            if status in {500, 502, 503, 504} and attempt <= 2:
                delay = min(8.0, 1.5 * attempt + random.uniform(0.1, 0.4))
                logger.warning("Cerebras transient %s | retry_in=%.1fs", status, delay)
                time.sleep(delay)
                continue
            raise
    raise RuntimeError(str(last_exc) if last_exc else "Cerebras request failed")


# ============================================================
# CANDIDATE FILTERING
# ============================================================

BAD_PATH_RE = re.compile(r"/(opinion|editorial|sponsored|tag|topic|live-blog|liveblog|photos?|quiz|poll)(/|$)", re.I)
BAD_TITLE_RE = re.compile(r"\b(sponsored|advertisement|promo|opinion|editorial|quiz|poll)\b", re.I)
HARD_BAD_TITLE_RE = re.compile(
    r"\b(?:review|reviews|recap|ending explained|fan theory|watchlist|what to watch|"
    r"best .* to watch|ranking|ranked|rumou?r|leak(?:ed)?|reaction|quiz|listicle|"
    r"merchandise|merch|giveaway)\b", re.I,
)
HARD_OFF_TOPIC_RE = re.compile(
    r"\b(?:sports?|football|soccer|cricket|tennis|basketball|baseball|golf|"
    r"formula\s*1|motogp|nascar|boxing|mma|ufc|wwe|aew|wrestling|politics?|"
    r"election|stock market|weather|finance|celebrity dating|"
    r"video game|gaming|gameplay|game review|playstation|xbox|steam|nintendo|persona 4|metroid)\b", re.I,
)
POSITIVE_TERMS = {
    "anime","manga","manhwa","manhua","comic","comics","graphic novel","one piece","naruto",
    "dragon ball","bleach","jujutsu kaisen","demon slayer","chainsaw man","my hero academia",
    "solo leveling","pokemon","marvel","dc comics","batman","superman","spider-man","x-men",
    "avengers","trailer","teaser","pv","anime adaptation","manga adaptation","season 2","season 3",
    "new season","sequel","release date","key visual","visual","cast","voice actor","studio",
    "production","hiatus","returns","final chapter","ending","chapter","volume","publisher",
    "marvel","dc","comic book","crossover","event","storyline","greenlit","announced","confirmed",
}

JAPANESE_POSITIVE_TERMS = {"アニメ","漫画","マンガ","コミック","第2期","第3期","第4期","第2弾","制作決定","放送","公開","特報","予告","PV","メインPV","劇場版","映画化","アニメ化","声優","キャスト","新作","連載","休載","再開","最終回","新刊"}
KOREAN_POSITIVE_TERMS = {"애니","애니메이션","만화","웹툰","시즌 2","시즌2","제작 결정","방영","개봉","예고편","PV","성우","연재","휴재","복귀"}
GENERIC_SOURCE_PAGE_RE = re.compile(r"^\s*(?:news|latest news|updates?)\s*[|:]\s*(?:dc|marvel|comics?)\s*$", re.I)
LOW_VALUE_PATTERNS = {
    "routine_review": re.compile(r"\b(?:review|reviews|recap|ending explained|fan theory|watchlist|what to watch|best .* to watch)\b", re.I),
    "rumor": re.compile(r"\b(?:rumou?r|leak(?:ed)?)\b", re.I),
    "routine_interview": re.compile(r"\b(?:interview|q&a|talks about|opens up|speaks about)\b", re.I),
    "merchandise": re.compile(r"\b(?:merchandise|merch|figurine|figure collection|giveaway)\b", re.I),
    "routine_rank": re.compile(r"\b(?:ranking|ranked|top 10|most popular|poll results)\b", re.I),
}


def content_blob(item):
    return safe_text(" ".join([
        safe_text(item.get("title")),
        safe_text(item.get("excerpt")),
        urlparse(safe_text(item.get("url"))).path,
    ])).lower()

def deterministic_pattern(item):
    blob = content_blob(item)
    title = safe_text(item.get("title"))
    if HARD_OFF_TOPIC_RE.search(blob) and not re.search(r"\b(?:anime|manga|comic|marvel|dc|superhero)\b", blob, re.I):
        return "off_topic"
    for name, pattern in LOW_VALUE_PATTERNS.items():
        if pattern.search(title) or pattern.search(blob):
            return name
    if re.search(r"\b(?:episode|chapter)\s+(?:\d+|[0-9]+)", title, re.I) and not re.search(r"\b(?:final|record|return|break|hiatus|ending|major|special)\b", title, re.I):
        return "routine_episode_chapter"
    if re.search(r"\b(?:figure|statue|collectible|toy|shirt|merch)\b", title, re.I):
        return "merchandise"
    return ""

def infer_priority_type(item):
    blob = content_blob(item)
    patterns = [
        ("Major Trailer / PV", r"\b(?:trailer|teaser|promo video|promotional video|pv)\b"),
        ("Manga → Anime Adaptation", r"\b(?:manga|manhwa|manhua)\b.*\b(?:anime adaptation|adapted into an anime|gets an anime|anime series)\b|\b(?:anime adaptation)\b"),
        ("New Season / Sequel", r"\b(?:season\s+[2-9]\b|new season|sequel|returns for|renewed for|part 2)\b"),
        ("Major Release Date", r"\b(?:release date|premiere date|premieres on|debut(?:s|ing)? on|set for .* release)\b"),
        ("Major Anime Movie", r"\b(?:anime movie|feature film|theatrical film|movie)\b"),
        ("Major Cast / Staff Reveal", r"\b(?:cast|casting|voice actor|voice actress|director|staff)\b"),
        ("Major Production News", r"\b(?:production|studio change|delay|production committee|production halted)\b"),
        ("Major Manga Return / Hiatus", r"\b(?:hiatus|returns|returning|back from hiatus)\b"),
        ("Major Manga Ending", r"\b(?:final chapter|series ends|manga ends|concludes|ending)\b"),
        ("Major Sales / Milestone", r"\b(?:million copies|copies sold|sales milestone|record|milestone)\b"),
        ("Major Marvel News", r"\b(?:marvel|x-men|spider-man|avengers|fantastic four)\b"),
        ("Major DC News", r"\b(?:dc comics|batman|superman|wonder woman|justice league)\b"),
        ("Major Comic Storyline / Event", r"\b(?:crossover|comic event|storyline|universe-wide|event series)\b"),
        ("Major Comic Adaptation", r"\b(?:comic adaptation|graphic novel adaptation|comic book movie|comic book series)\b"),
        ("Major Comic Announcement", r"\b(?:comic book|graphic novel|new comic|new series|new ongoing|limited series)\b"),
        ("Major Creator / Publisher News", r"\b(?:creator|writer|artist|publisher|publishing)\b"),
        ("Major Franchise Update", r"\b(?:franchise|official announcement|greenlit|confirmed|major update)\b"),
    ]
    for priority, pattern in patterns:
        if re.search(pattern, blob, re.I):
            return priority
    return "Major Anime Announcement"

def work_key_from_text(title):
    text = normalize_title(title)
    if not text:
        return ""
    text = re.sub(r"\b(?:season|series|part|chapter|episode)\s+\d+\b", " ", text)
    text = re.sub(r"\b(?:19|20)\d{2}\b", " ", text)
    text = re.sub(
        r"\b(?:official|confirmed|confirmation|announced|announcement|now|streaming|streams|streamed|"
        r"upcoming|release|released|release date|date|premiere|premieres|renewed|renewal|episode|trailer|"
        r"teaser|first look|first glimpse|poster|posters|casting|cast|joins|join|production|filming|filmed|"
        r"wrapped|wraps|theatrical|re release|re-release|box office|opens|grosses|grossed|rights|acquired|"
        r"acquisition|dub|dubbed|hindi|language|available|availability|coming|returns|returning|back|"
        r"reaches|reach|crosses|crossed|hits|hit|tops|top|earns|earned|adds|added|logs|logged|grosses|"
        r"nears|near|sets|set|becomes|became|fastest|record|records|milestone|domestic|worldwide|total|"
        r"weekend|weekends|day|days|million|billion|for|to|on|at|in|with|from|by|of)\b",
        " ", text, flags=re.I,
    )
    text = re.sub(r"\b\d+\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _work_keys_similar(a, b):
    a, b = safe_text(a), safe_text(b)
    if not a or not b:
        return False
    if a == b:
        return True
    aa, bb = set(a.split()), set(b.split())
    overlap = len(aa & bb) / max(1, min(len(aa), len(bb)))
    return overlap >= 0.80 or SequenceMatcher(None, a, b).ratio() >= 0.88


def _event_text(item):
    if safe_text(item.get("event_text")):
        return safe_text(item.get("event_text"))
    return safe_text(" ".join([
        safe_text(item.get("title") or item.get("headline")),
        safe_text(item.get("excerpt")),
        safe_text(item.get("summary")),
        " ".join(safe_text(x) for x in item.get("highlights", [])[:3]),
        safe_text(item.get("platform")),
        safe_text(item.get("release_date")),
    ]))


def _event_core(item):
    text = normalize_title(_event_text(item))
    work = work_key_from_text(safe_text(item.get("title") or item.get("headline")))
    for token in set(work.split()):
        if len(token) >= 3:
            text = re.sub(rf"\b{re.escape(token)}\b", " ", text)
    generic = {
        "official","confirmed","confirmation","announce","announced","announcement","new","now",
        "available","availability","release","released","premiere","premieres","upcoming","streaming",
        "season","series","episode","episodes","trailer","teaser","first","look","glimpse","poster",
        "casting","cast","joins","join","production","filming","filmed","wrapped","wraps","theatrical",
        "cinema","box","office","gross","grossed","grosses","rights","acquired","acquisition","dub",
        "dubbed","hindi","language","languages","update","updates","news","report","reports","says",
        "reveals","talks","actor","actress","director","film","movie","show","tv",
    }
    return " ".join(t for t in text.split() if len(t) >= 3 and t not in generic)[:500]


def _event_core_similarity(a, b):
    aa, bb = _event_core(a), _event_core(b)
    if not aa or not bb:
        return 0.0
    return max(SequenceMatcher(None, aa, bb).ratio(), token_jaccard(aa, bb))


def event_signature_from_item(item):
    work = work_key_from_text(safe_text(item.get("title") or item.get("headline")))
    priority = safe_text(item.get("priority_type")) or infer_priority_type(item)
    return f"{work}|{priority}|{_event_core(item)}"


def _dedup_hours_for_priority(priority):
    return {
        "Major Trailer / PV": TRAILER_DEDUP_HOURS,
        "Manga → Anime Adaptation": ADAPTATION_DEDUP_HOURS,
        "New Season / Sequel": ANNOUNCEMENT_DEDUP_HOURS,
        "Major Release Date": RELEASE_EVENT_DEDUP_HOURS,
        "Major Anime Announcement": ANNOUNCEMENT_DEDUP_HOURS,
        "Major Manga Return / Hiatus": MANGA_UPDATE_DEDUP_HOURS,
        "Major Manga Ending": ANNOUNCEMENT_DEDUP_HOURS,
        "Major Marvel News": ANNOUNCEMENT_DEDUP_HOURS,
        "Major DC News": ANNOUNCEMENT_DEDUP_HOURS,
        "Major Comic Announcement": ANNOUNCEMENT_DEDUP_HOURS,
        "Major Comic Storyline / Event": ANNOUNCEMENT_DEDUP_HOURS,
        "Major Comic Adaptation": ADAPTATION_DEDUP_HOURS,
    }.get(priority, DEFAULT_EVENT_DEDUP_HOURS)


def _publication_event_match(candidate, previous):
    candidate_work = work_key_from_text(safe_text(candidate.get("title") or candidate.get("headline")))
    previous_work = safe_text(previous.get("work_key")) or work_key_from_text(safe_text(previous.get("title") or previous.get("headline")))
    if not _work_keys_similar(candidate_work, previous_work):
        return False
    candidate_priority = safe_text(candidate.get("priority_type")) or infer_priority_type(candidate)
    previous_priority = safe_text(previous.get("priority_type"))
    if not candidate_priority or candidate_priority != previous_priority:
        return False
    published_at = parse_datetime(previous.get("published_at")) or NOW_BD
    age_hours = abs((NOW_BD - published_at).total_seconds()) / 3600.0
    if age_hours > _dedup_hours_for_priority(candidate_priority):
        return False
    if event_signature_from_item(candidate) == safe_text(previous.get("fingerprint")):
        return True
    title_score = title_similarity(
        safe_text(candidate.get("title") or candidate.get("headline")),
        safe_text(previous.get("headline") or previous.get("title")),
    )
    core_score = _event_core_similarity(candidate, previous)
    if title_score >= 0.55 or core_score >= 0.55:
        return True
    return False


MEANINGFUL_UPDATE_LOOKBACK_HOURS = 72
MEANINGFUL_UPDATE_MARKERS = re.compile(
    r"\b(?:officially\s+announced|officially\s+confirmed|confirmed|announced|new\s+(?:trailer|teaser|pv|footage|visual|poster)|"
    r"release\s+date|premiere\s+date|first\s+look|returns?|returning|back\s+from\s+hiatus|hiatus|final\s+chapter|series\s+ends?|"
    r"studio\s+change|production\s+(?:change|halted|delayed)|new\s+cast|casting|voice\s+actor|major\s+event|crossover)\b",
    re.I,
)

def meaningful_update_candidate(item):
    """Allow a slightly older article only when it contains a concrete new development."""
    dt = parse_datetime(item.get("published_dt") or item.get("published_date"))
    if not dt:
        return False
    age_hours = (NOW_BD - dt).total_seconds() / 3600
    if age_hours <= ROLLING_DISCOVERY_HOURS or age_hours > MEANINGFUL_UPDATE_LOOKBACK_HOURS:
        return False
    title = safe_text(item.get("title"))
    excerpt = safe_text(item.get("excerpt"))
    if not MEANINGFUL_UPDATE_MARKERS.search(title + " " + excerpt):
        return False
    work_key = work_key_from_text(title)
    if work_key in STATE.get("work_memory", {}):
        return True
    for previous in STATE.get("publication_fingerprints", [])[-1000:]:
        if work_key and _work_keys_similar(work_key, previous.get("work_key", "")):
            return True
    return source_class_for_url(item.get("url")) == "official"


def event_memory_hit(item):
    title = safe_text(item.get("title") or item.get("headline"))
    canonical = safe_text(item.get("canonical"))
    if canonical and canonical in POSTED_URLS:
        return True, "posted_url"
    for previous in reversed(STATE.get("publication_fingerprints", [])[-1000:]):
        if _publication_event_match(item, previous):
            if meaningful_update_candidate(item) and safe_text(item.get("priority_type") or item.get("topic")) != safe_text(previous.get("priority_type") or previous.get("topic")):
                continue
            return True, f"same_work_same_event:{previous.get('priority_type','')}"
    work_key = work_key_from_text(title)
    priority = infer_priority_type(item)
    if work_key:
        memory = STATE.get("work_memory", {}).get(work_key)
        if memory and priority in (memory.get("published_events", {}) or {}):
            dt = parse_datetime(memory["published_events"][priority])
            if dt and (NOW_BD - dt).total_seconds() <= _dedup_hours_for_priority(priority) * 3600:
                return True, f"legacy_work_cooldown:{priority}"
    if not meaningful_update_candidate(item):
        for previous in STATE.get("recent_titles", [])[-250:]:
            if title_similarity(title, previous) >= 0.92:
                return True, "near_identical_recent_title"
    return False, ""

def update_filter_metric(reason):
    metrics = STATE.setdefault("adaptive_metrics", {})
    metrics["pre_cerebras_rejected"] = int(metrics.get("pre_cerebras_rejected", 0)) + 1
    if reason.startswith("hard_") or reason in {"no_comic_anime_signal", "low_value_editorial", "sports", "promotion", "celebrity_lifestyle"}:
        metrics["hard_rejected"] = int(metrics.get("hard_rejected", 0)) + 1
    elif reason.startswith("learned_"):
        metrics["learned_rejected"] = int(metrics.get("learned_rejected", 0)) + 1
    elif reason.startswith("same_work") or reason.startswith("near_identical") or reason in {"posted_url", "duplicate_title"}:
        metrics["duplicate_rejected"] = int(metrics.get("duplicate_rejected", 0)) + 1

def update_pass_metric():
    metrics = STATE.setdefault("adaptive_metrics", {})
    metrics["passed_to_cerebras"] = int(metrics.get("passed_to_cerebras", 0)) + 1

def learned_pattern_block(item):
    pattern = deterministic_pattern(item)
    if not pattern or pattern in {"sports", "low_value_editorial", "celebrity_lifestyle", "promotion"}:
        return False, ""
    stats = STATE.get("learned_rejections", {}).get(pattern)
    if not stats:
        return False, ""
    observations = int(stats.get("observations", 0))
    low_count = int(stats.get("low_score_count", 0))
    avg_score = float(stats.get("avg_score", 100))
    if observations >= LEARNED_MIN_OBSERVATIONS and low_count / max(1, observations) >= LEARNED_LOW_RATIO and avg_score <= LEARNED_LOW_SCORE_CEILING:
        return True, f"learned_pattern:{pattern}"
    return False, ""

def learned_source_block(item):
    domain = urlparse(safe_text(item.get("url"))).netloc.lower().removeprefix("www.")
    if not domain:
        return False, ""
    stats = STATE.get("source_quality", {}).get(domain)
    if not stats:
        return False, ""
    observations = int(stats.get("observations", 0))
    low = int(stats.get("low_score_count", 0))
    avg = float(stats.get("avg_score", 100))
    if observations >= SOURCE_LEARNING_MIN_OBSERVATIONS and low / max(1, observations) >= SOURCE_LEARNING_LOW_RATIO and avg <= SOURCE_LEARNING_LOW_SCORE_CEILING:
        # Source-level blocking is only allowed for clearly junk-dominated sources.
        return True, f"learned_source:{domain}"
    return False, ""

def pre_cerebras_filter(item):
    title = safe_text(item.get("title"))
    blob = content_blob(item)
    lower = blob.lower()
    if GENERIC_SOURCE_PAGE_RE.search(title) and not re.search(r"\b(?:announc|confirm|trailer|event|series|comic|manga|anime)\b", lower, re.I):
        return False, "generic_source_page"
    has_core_context = bool(re.search(r"\b(?:anime|manga|manhwa|manhua|comic|comics|graphic novel|marvel|dc|batman|superman|x-men|spider-man|avengers)\b", lower, re.I))
    has_multilingual_context = any(term in blob for term in (*JAPANESE_POSITIVE_TERMS, *KOREAN_POSITIVE_TERMS))
    if HARD_OFF_TOPIC_RE.search(blob) and not has_core_context and not has_multilingual_context:
        return False, "off_topic"
    if HARD_BAD_TITLE_RE.search(title):
        # Editorial titles like “final episode preview” are allowed when a major
        # development override is present elsewhere in the headline.
        major_override = bool(re.search(r"\b(?:season\s*[2-9]|new season|announc|confirm|trailer|teaser|pv|adaptation|final chapter|series ends|major event|crossover)\b", title, re.I)) or bool(re.search(r"(?:制作決定|第2期|第3期|特報|予告|アニメ化|最終回)", title))
        if not major_override:
            return False, "hard_low_value_title"
    positives = sum(1 for term in POSITIVE_TERMS if term in lower)
    positives += 2 if has_multilingual_context else 0
    if positives == 0:
        return False, "no_comic_anime_signal"
    hit, reason = event_memory_hit(item)
    if hit:
        return False, reason
    hit, reason = learned_pattern_block(item)
    if hit:
        return False, reason
    hit, reason = learned_source_block(item)
    if hit:
        return False, reason
    return True, ""

def candidate_basic_allowed(item):
    url = safe_text(
        item.get("url")
    )
    title = safe_text(
        item.get("title")
    )
    published = item.get(
        "published_dt"
    )

    if (
        not url
        or not title
        or not published
    ):
        return False

    if BAD_PATH_RE.search(
        urlparse(url).path
    ):
        return False

    if BAD_TITLE_RE.search(
        title
    ):
        return False

    within_normal_window = DISCOVERY_START <= published <= DISCOVERY_END
    if not within_normal_window and not meaningful_update_candidate(item):
        return False

    fresh_start = parse_datetime(STATE.get("fresh_start_at"))
    if fresh_start and published < fresh_start:
        return False

    region = safe_text(item.get("region")) or REGION
    if region and not allowed_source_for_region(url, region):
        return False

    canonical = canonical_url(
        url
    )
    item_for_filter = {**item, "canonical": canonical, "url": url, "title": title}
    allowed, reason = pre_cerebras_filter(item_for_filter)
    if not allowed:
        update_filter_metric(reason)
        logger.info("PRE-CEREBRAS DROP: %s | %s", reason, title)
        return False

    update_pass_metric()
    return bool(canonical)


def title_duplicate_against_state(title):
    for previous in STATE.get(
        "recent_titles",
        [],
    )[-250:]:
        if title_similarity(
            title,
            previous,
        ) >= 0.88:
            return True

    return False


def title_duplicate_against_list(
    title,
    candidates,
    threshold=0.88,
):
    for candidate in candidates:
        if title_similarity(
            title,
            candidate["title"],
        ) >= threshold:
            return True

    return False


# ============================================================
# RSS INGESTION + PERSISTENT QUEUE
# ============================================================

def extract_entry_image(
    entry,
    page_url,
):
    for key in (
        "media_content",
        "media_thumbnail",
    ):
        for item in entry.get(
            key,
            [],
        ):
            image_url = safe_text(
                item.get("url")
            )

            if image_url:
                return urljoin(
                    page_url,
                    image_url,
                )

    for enclosure in entry.get(
        "enclosures",
        [],
    ):
        href = safe_text(
            enclosure.get("href")
        )

        mime = safe_text(
            enclosure.get("type")
        ).lower()

        if (
            href
            and (
                not mime
                or mime.startswith(
                    "image/"
                )
            )
        ):
            return urljoin(
                page_url,
                href,
            )

    return ""


def queue_candidate(item):
    canonical = item["canonical"]

    existing = STATE["queue"].get(
        canonical
    )

    if existing:
        existing.update(
            {
                "last_seen": now_iso(),
                "image": (
                    item.get("image")
                    or existing.get("image", "")
                ),
            }
        )
        return

    STATE["queue"][canonical] = {
        **item,
        "status": "pending",
        "first_seen": now_iso(),
        "last_seen": now_iso(),
    }


def fetch_rss_feed(
    feed_def,
):
    url = feed_def["url"]

    old = STATE["feeds"].get(
        url,
        {},
    )

    headers = dict(
        HEADERS
    )

    if old.get("etag"):
        headers["If-None-Match"] = old[
            "etag"
        ]

    if old.get(
        "last_modified"
    ):
        headers["If-Modified-Since"] = old[
            "last_modified"
        ]

    try:
        response = session.get(
            url,
            headers=headers,
            timeout=20,
        )

        # 304 means the queue remains intact. The feed is reachable,
        # so this counts as healthy and clears any fail streak.
        if response.status_code == 304:
            logger.info(
                "RSS 304: %s",
                feed_def["name"],
            )
            mark_feed_healthy(feed_def, old)
            return 0

        if response.status_code >= 400:
            logger.warning(
                "RSS %s returned %s",
                feed_def["name"],
                response.status_code,
            )
            mark_feed_failed(feed_def, old)
            return 0

        STATE["feeds"][url] = {
            "etag": response.headers.get(
                "ETag",
                old.get("etag"),
            ),
            "last_modified": response.headers.get(
                "Last-Modified",
                old.get("last_modified"),
            ),
            "last_checked": now_iso(),
            "fail_count": 0,
            "alerted": False,
        }

        parsed = feedparser.parse(
            response.content
        )

        added = 0

        for entry in parsed.entries:
            published_dt = feed_entry_datetime(
                entry
            )

            date_estimated = False

            if not published_dt:
                # Some feeds send a date format we cannot parse.
                # Do not throw the story away: use fetch time instead,
                # and mark it so downstream code knows it is a guess.
                published_dt = datetime.now(
                    BD_TZ
                )
                date_estimated = True

            article_url = urljoin(
                url,
                safe_text(
                    entry.get("link")
                ),
            )

            title = safe_text(
                entry.get("title")
            )

            if not article_url or not title:
                continue

            item = {
                "title": title,
                "url": article_url,
                "canonical": canonical_url(
                    article_url
                ),
                "published_dt": published_dt.isoformat(),
                "published_date": published_dt.isoformat(),
                "source": feed_def["name"],
                "region": feed_def["region"],
                "excerpt": BeautifulSoup(
                    safe_text(
                        entry.get(
                            "summary"
                        )
                        or entry.get(
                            "description"
                        )
                    ),
                    "html.parser",
                ).get_text(
                    " ",
                    strip=True,
                )[:2000],
                "image": extract_entry_image(
                    entry,
                    article_url,
                ),
                "discovery": "rss",
                "date_estimated": date_estimated,
                "source_class": source_class_for_url(article_url),
            }

            if not candidate_basic_allowed(
                {
                    **item,
                    "published_dt": published_dt,
                }
            ):
                continue

            if (
                item["canonical"]
                in POSTED_URLS
            ):
                continue

            before = item["canonical"] in STATE[
                "queue"
            ]

            queue_candidate(
                item
            )

            if not before:
                added += 1

        return added

    except Exception as exc:
        logger.warning(
            "RSS failed %s: %s",
            feed_def["name"],
            exc,
        )
        mark_feed_failed(feed_def, old)
        return 0


# Consecutive failed runs before we alert about a broken feed.
FEED_FAIL_ALERT_THRESHOLD = 3


def mark_feed_healthy(feed_def, old):
    STATE["feeds"][feed_def["url"]] = {
        **old,
        "last_checked": now_iso(),
        "fail_count": 0,
        "alerted": False,
    }


def mark_feed_failed(feed_def, old):
    fail_count = int(old.get("fail_count", 0)) + 1

    STATE["feeds"][feed_def["url"]] = {
        **old,
        "last_checked": now_iso(),
        "fail_count": fail_count,
    }

    if fail_count >= FEED_FAIL_ALERT_THRESHOLD and not old.get("alerted"):
        alert_feed_down(feed_def, fail_count)
        STATE["feeds"][feed_def["url"]]["alerted"] = True


def alert_feed_down(feed_def, fail_count):
    """Tell the admin a source has gone quiet, instead of failing silently forever."""
    message = (
        f"Feed down: {feed_def['name']} ({feed_def['region']})\n"
        f"Failed {fail_count} runs in a row.\n"
        f"URL: {feed_def['url']}\n"
        f"It will keep retrying, but this source is not feeding the bot right now."
    )

    if TELEGRAM_ADMIN_CHAT_ID:
        try:
            telegram_call("sendMessage", data={"chat_id": TELEGRAM_ADMIN_CHAT_ID, "text": message})
        except Exception as exc:
            logger.warning(
                "Feed-down alert failed to send: %s",
                exc,
            )

    logger.error(message)


def collect_rss():
    added = 0

    for feed_def in RSS_FEEDS:
        added += fetch_rss_feed(
            feed_def
        )

    # Critical: queue is saved together with feed validators.
    # A later 304 cannot erase unposted queued stories.
    save_state(
        STATE
    )

    logger.info(
        "RSS queue additions: %d",
        added,
    )

    return added


# ============================================================
# EXA GAP-FILL DISCOVERY
# ============================================================

# ============================================================
# SOURCE UNIVERSE
# ============================================================

def normalized_domain(url_or_source):
    raw = safe_text(url_or_source).lower()
    if "://" in raw:
        raw = urlparse(raw).netloc
    return raw.split(":")[0].removeprefix("www.").strip().rstrip("/")


def is_domain_allowed(url, domains):
    d = normalized_domain(url)
    return any(d == x or d.endswith("." + x) for x in domains)


def primary_domain_allowed(url, region=None):
    return is_domain_allowed(url, ALL_PRIMARY_DOMAINS)


def fallback_domain_allowed(url, region=None):
    return is_domain_allowed(url, ALL_FALLBACK_DOMAINS)


def allowed_source_for_region(url, region=None):
    return primary_domain_allowed(url, region) or fallback_domain_allowed(url, region)


# ============================================================
# GOOGLE NEWS RSS: FREE GAP FILL
# ============================================================
GOOGLE_NEWS_QUERIES = {REGION: [
    'latest major anime announcement trailer sequel season adaptation news',
    'latest major manga news hiatus ending return adaptation sales milestone',
    'latest Marvel comics major announcement event storyline trailer',
    'latest DC comics major announcement event storyline adaptation',
    'latest major comics announcement creator publisher adaptation news',
    'latest anime manga comics official trailer release date news',
]}
GOOGLE_NEWS_LOCALE = {REGION: ("en-US", "US", "US:en")}

def resolve_google_news_url(link):
    """Google News RSS gives a redirect link, not the publisher URL.
    Follow it once (without downloading the full page) to get the
    real article URL. Return "" if it cannot be resolved safely."""
    try:
        response = session.get(
            link,
            timeout=10,
            allow_redirects=True,
            headers=HEADERS,
            stream=True,
        )
        real_url = safe_text(response.url)
        response.close()

        if not real_url or "news.google.com" in real_url:
            return ""

        return real_url

    except Exception:
        return ""


def google_news_gap_fill(
    region,
    existing_count,
    needed,
):
    # Same thin-coverage trigger as Exa, tried first because it is free.
    if existing_count >= 80:
        return 0

    queries = GOOGLE_NEWS_QUERIES.get(REGION, [])
    hl, gl, ceid = GOOGLE_NEWS_LOCALE.get(REGION, ("en-US", "US", "US:en"))

    added = 0

    for query in queries:
        try:
            feed_url = (
                "https://news.google.com/rss/search?q="
                + quote(f"{query} when:2d")
                + f"&hl={hl}&gl={gl}&ceid={ceid}"
            )

            response = session.get(
                feed_url,
                timeout=15,
                headers=HEADERS,
            )

            if response.status_code >= 400:
                continue

            parsed = feedparser.parse(
                response.content
            )

            for entry in parsed.entries[:6]:
                title = safe_text(
                    entry.get("title")
                )
                link = safe_text(
                    entry.get("link")
                )

                if not title or not link:
                    continue

                real_url = resolve_google_news_url(
                    link
                )

                if not real_url:
                    continue

                published_dt = feed_entry_datetime(
                    entry
                )
                date_estimated = False

                if not published_dt:
                    published_dt = datetime.now(
                        BD_TZ
                    )
                    date_estimated = True

                item = {
                    "title": title,
                    "url": real_url,
                    "canonical": canonical_url(
                        real_url
                    ),
                    "published_dt": published_dt.isoformat(),
                    "published_date": published_dt.isoformat(),
                    "source": source_name(
                        real_url
                    ),
                    "region": region,
                    "excerpt": BeautifulSoup(
                        safe_text(
                            entry.get("summary")
                        ),
                        "html.parser",
                    ).get_text(
                        " ",
                        strip=True,
                    )[:2000],
                    "image": "",
                    "discovery": "google_news",
                    "date_estimated": date_estimated,
                "source_class": source_class_for_url(real_url),
                }

                if not primary_domain_allowed(real_url, region):
                    continue

                if not candidate_basic_allowed(
                    {
                        **item,
                        "published_dt": published_dt,
                    }
                ):
                    continue

                if item["canonical"] in POSTED_URLS:
                    continue

                if item["canonical"] in STATE["queue"]:
                    continue

                queue_candidate(
                    item
                )
                added += 1

                if added >= MAX_GOOGLE_NEWS_CANDIDATES:
                    return added

        except Exception as exc:
            logger.warning(
                "Google News gap fill failed %s: %s",
                region,
                exc,
            )

    return added


_exa_lock = Lock()
_exa_next_allowed_at = 0.0

def _reserve_exa_slot():
    global _exa_next_allowed_at
    with _exa_lock:
        now = time.monotonic()
        wait = max(0.0, _exa_next_allowed_at - now)
        _exa_next_allowed_at = max(now, _exa_next_allowed_at) + EXA_REQUEST_INTERVAL_SECONDS
    if wait > 0:
        time.sleep(wait)

def _exa_call(method, *args, **kwargs):
    last_exc = None
    for attempt in range(1, EXA_MAX_RETRY_ATTEMPTS + 2):
        try:
            _reserve_exa_slot()
            return getattr(exa, method)(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            text_exc = safe_text(exc).lower()
            if ("429" in text_exc or "rate limit" in text_exc or "too many requests" in text_exc) and attempt <= EXA_MAX_RETRY_ATTEMPTS:
                delay = min(8.0, 1.5 * attempt + random.uniform(0.1, 0.5))
                logger.warning("Exa rate limit | attempt=%d/%d | retry_in=%.1fs", attempt, EXA_MAX_RETRY_ATTEMPTS + 1, delay)
                time.sleep(delay)
                continue
            raise
    raise last_exc or RuntimeError("Exa request failed")

def _exa_search(query, domains=None, num_results=10, deep=False, date_filtered=True):
    """Rate-limited Exa search wrapper. All search traffic goes through one clock."""
    kwargs = {"num_results": num_results, "contents": {"highlights": True}}
    if domains:
        kwargs["include_domains"] = domains
    if date_filtered:
        kwargs["start_published_date"] = DISCOVERY_START.isoformat()
        kwargs["end_published_date"] = DISCOVERY_END.isoformat()
    kwargs["type"] = "deep-lite" if deep else "auto"
    try:
        return _exa_call("search", query, **kwargs)
    except TypeError:
        kwargs.pop("type", None)
        return _exa_call("search", query, **kwargs)

def _exa_get_contents(urls, **kwargs):
    """Rate-limited Exa content retrieval."""
    return _exa_call("get_contents", urls, **kwargs)


def _exa_highlights(result):
    value = getattr(result, "highlights", None)
    if isinstance(value, list):
        return " ".join(safe_text(x) for x in value)
    return safe_text(value)


def exa_gap_fill(region, existing_count, needed, fallback=False):
    domains = FALLBACK_DOMAINS if fallback else PRIMARY_DOMAINS
    if not domains:
        return 0
    queries = [
        "latest major anime announcements new seasons sequels trailers adaptations release dates",
        "latest major manga announcements returns hiatus endings adaptations milestones",
        "latest major Marvel Comics announcements events storylines adaptations",
        "latest major DC Comics announcements events storylines adaptations",
        "latest major comics announcements creators publishers storylines adaptations",
        "latest official anime manga comics trailer PV teaser key visual news",
    ]
    added = 0
    for query in queries:
        try:
            results = _exa_search(query, domains=domains, num_results=12)
            for result in getattr(results, "results", []) or []:
                url = safe_text(getattr(result, "url", ""))
                title = safe_text(getattr(result, "title", ""))
                published_dt = parse_datetime(getattr(result, "published_date", "")) or NOW_BD
                if not url or not title:
                    continue
                if fallback and not fallback_domain_allowed(url, region):
                    continue
                if not fallback and not primary_domain_allowed(url, region):
                    continue
                item = {
                    "title": title,
                    "url": url,
                    "canonical": canonical_url(url),
                    "published_dt": published_dt.isoformat(),
                    "published_date": published_dt.isoformat(),
                    "source": source_name(url),
                    "region": REGION,
                    "excerpt": _exa_highlights(result)[:2400],
                    "image": safe_text(getattr(result, "image", "")),
                    "discovery": "exa_fallback" if fallback else "exa",
                    "source_pool": "fallback" if fallback else "primary",
                    "source_class": source_class_for_url(url),
                }
                if not candidate_basic_allowed({**item, "published_dt": published_dt}):
                    continue
                if item["canonical"] in POSTED_URLS or item["canonical"] in STATE["queue"]:
                    continue
                queue_candidate(item)
                added += 1
                if added >= MAX_EXA_CANDIDATES:
                    return added
        except Exception as exc:
            logger.warning("Exa %s discovery failed: %s", "fallback" if fallback else "primary", exc)
    return added


def queue_candidates_for_region(
    region,
):
    count = 0

    for item in STATE[
        "queue"
    ].values():
        if (
            item.get("region")
            == region
            and item.get("status")
            == "pending"
        ):
            published = parse_datetime(
                item.get(
                    "published_date"
                )
            )

            if published and (DISCOVERY_START <= published <= DISCOVERY_END or meaningful_update_candidate(item)):
                count += 1

    return count


# ============================================================
# CANDIDATE NORMALIZATION
# ============================================================

# ============================================================
# ARTICLE ENRICHMENT FOR THIN FEED EXCERPTS
# ============================================================

def enrich_thin_excerpt(item):
    """Best-effort article enrichment. Failure never removes a candidate."""
    try:
        downloaded = trafilatura.fetch_url(item["url"])
        if not downloaded:
            return None
        text = trafilatura.extract(downloaded)
        return safe_text(text)[:1200] if text else None
    except Exception:
        return None


def enrich_thin_excerpts(regional):
    enriched = 0
    for item in regional:
        if enriched >= MAX_EXCERPT_ENRICH:
            break
        excerpt = safe_text(item.get("excerpt", ""))
        if len(excerpt) >= THIN_EXCERPT_CHARS:
            continue
        fuller = enrich_thin_excerpt(item)
        if fuller and len(fuller) > len(excerpt):
            item["excerpt"] = fuller
            enriched += 1
    return regional


# ============================================================
# EDITORIAL RANKING: QUALITY > QUANTITY
# ============================================================
RANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "score": {"type": "integer"},
                    "sector": {"type": "string", "enum": SECTORS},
                    "topic": {"type": "string", "enum": list(NEWS_PRIORITY.keys())},
                    "event_key": {"type": "string"},
                    "status": {"type": "string", "enum": ["rumor", "reported", "announced", "confirmed", "released"]},
                    "reason": {"type": "string"},
                },
                "required": ["id", "score", "sector", "topic", "event_key", "status", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ranked"],
    "additionalProperties": False,
}


def rank_score(row):
    if "score" in row:
        return max(0, min(100, int(row.get("score", 0))))
    return max(0, min(100, sum(int(row.get(k, 0)) for k in [
        "fan_interest", "significance", "franchise_reach", "freshness", "novelty", "source_authority", "visual_value"
    ])))


def record_low_score_learning(rows):
    learned = STATE.setdefault("learned_rejections", {})
    history = STATE.setdefault("score_history", [])
    for row in rows:
        score = int(row.get("importance_score", 0))
        title = safe_text(row.get("title"))
        pattern = deterministic_pattern(row)
        priority = safe_text(row.get("priority_type"))
        if pattern:
            stats = learned.setdefault(pattern, {"observations":0,"low_score_count":0,"total_score":0,"avg_score":0,"last_seen":now_iso(),"examples":[]})
            stats["observations"] = int(stats.get("observations",0)) + 1
            stats["low_score_count"] = int(stats.get("low_score_count",0)) + int(score < PUBLISH_THRESHOLD)
            stats["total_score"] = int(stats.get("total_score",0)) + score
            stats["avg_score"] = round(stats["total_score"] / max(1, stats["observations"]), 1)
            stats["last_seen"] = now_iso()
            ex = [x for x in stats.get("examples",[]) if x.get("title") != title]
            ex.append({"title":title[:140],"score":score,"priority_type":priority})
            stats["examples"] = ex[-5:]
        history.append({"title":title[:140],"score":score,"pattern":pattern,"priority_type":priority,"source":safe_text(row.get("source")),"seen_at":now_iso()})
    STATE["score_history"] = history[-LEARNED_HISTORY_LIMIT:]


def update_source_quality(rows):
    quality = STATE.setdefault("source_quality", {})
    for row in rows:
        domain = normalized_domain(row.get("url"))
        if not domain:
            continue
        score = int(row.get("importance_score",0))
        stats = quality.setdefault(domain,{"observations":0,"low_score_count":0,"total_score":0,"avg_score":0,"last_seen":now_iso()})
        stats["observations"] = int(stats.get("observations",0)) + 1
        stats["low_score_count"] = int(stats.get("low_score_count",0)) + int(score < PUBLISH_THRESHOLD)
        stats["total_score"] = int(stats.get("total_score",0)) + score
        stats["avg_score"] = round(stats["total_score"] / max(1, stats["observations"]),1)
        stats["last_seen"] = now_iso()


def bootstrap_learning_from_queue():
    rows=[]
    for item in STATE.get("queue",{}).values():
        if item.get("importance_score") is None:
            continue
        score=int(item.get("importance_score",0))
        if score>=PUBLISH_THRESHOLD:
            continue
        rows.append({"title":item.get("title",""),"source":item.get("source",""),"priority_type":item.get("priority_type",""),"importance_score":score,"excerpt":item.get("excerpt","")})
    if rows:
        existing={(x.get("title"),int(x.get("score",-1))) for x in STATE.get("score_history",[])}
        fresh=[x for x in rows if (safe_text(x.get("title")),int(x.get("importance_score",0))) not in existing]
        if fresh:
            record_low_score_learning(fresh); update_source_quality(fresh)


def deterministic_editorial_score(item):
    blob = content_blob(item)
    dt = parse_datetime(item.get("published_date"))
    age_hours = max(0.0, (NOW_BD - dt).total_seconds() / 3600) if dt else 24
    score = 50
    if age_hours <= 6:
        score += 15
    elif age_hours <= 12:
        score += 10
    elif age_hours <= 24:
        score += 5
    score += {
        "Major Trailer / PV": 18,
        "Manga → Anime Adaptation": 17,
        "New Season / Sequel": 16,
        "Major Anime Announcement": 14,
        "Major Release Date": 12,
        "Major Anime Movie": 11,
        "Major Franchise Update": 11,
        "Major Marvel News": 13,
        "Major DC News": 13,
        "Major Comic Storyline / Event": 13,
        "Major Comic Adaptation": 13,
        "Major Comic Announcement": 11,
        "Major Manga Return / Hiatus": 10,
        "Major Manga Ending": 10,
        "Major Production News": 9,
        "Major Cast / Staff Reveal": 8,
        "Major Creator / Publisher News": 8,
        "Major Sales / Milestone": 6,
    }.get(infer_priority_type(item), 0)
    src = source_class_for_url(item.get("url"))
    score += 10 if src == "official" else 6 if source_name(item.get("url")) in {
        "Anime News Network", "Crunchyroll News", "ORICON NEWS", "ComicBook.com", "Bleeding Cool", "The Beat"
    } else 0
    if re.search(r"\b(?:officially|official|announced|confirmed|revealed|first trailer|new trailer|adaptation|release date)\b", blob, re.I):
        score += 5
    if deterministic_pattern(item):
        score -= 18
    if safe_text(item.get("source_class")).lower() == "rumor":
        score = min(score, 69)
    return max(0, min(88, int(score)))


def normalize_sector_from_item(item):
    blob = content_blob(item)
    if re.search(r"\b(?:marvel|dc comics|dc universe|batman|superman|wonder woman|x-men|avengers|spider-man|comic book|graphic novel)\b", blob, re.I):
        return "Comics"
    if re.search(r"\b(?:manga|manhwa|manhua|chapter|volume|shueisha|kodansha|viz media)\b", blob, re.I) and not re.search(r"\banime\b", blob, re.I):
        return "Manga"
    if re.search(r"\b(?:anime|season|episode|voice actor|studio|trailer|pv)\b", blob, re.I) or any(x in blob for x in ("アニメ","声優","第2期","第3期","制作決定","予告","PV")):
        return "Anime"
    return ""


def _apply_deterministic_rank(item, editor_rank, reason):
    score = deterministic_editorial_score(item)
    item.update({
        "editor_rank": editor_rank,
        "importance_score": score,
        "important": score >= PUBLISH_THRESHOLD,
        "sector": normalize_sector_from_item(item),
        "topic": infer_priority_type(item),
        "priority_type": infer_priority_type(item),
        "event_key": event_signature_from_item(item),
        "event_status": "reported",
        "source_class": safe_text(item.get("source_class")) or source_class_for_url(item.get("url")),
        "rank_reason": reason,
        "ai_ranked": False,
    })


def _rank_batch(batch):
    lines = []
    for idx, item in enumerate(batch, 1):
        dt = parse_datetime(item.get("published_date"))
        age = f"{max(0.0, (NOW_BD-dt).total_seconds()/3600):.1f}h" if dt else "unknown"
        lines.append("\n".join([
            f"ID: {idx}", f"TITLE: {item.get('title','')}", f"SOURCE: {item.get('source','')}",
            f"PUBLISHED: {item.get('published_date','')}", f"AGE: {age}",
            f"EXCERPT: {trim_source_text(item.get('excerpt',''),600)}",
        ]))
    prompt = f"""You are the senior editorial gatekeeper for @ComicsNewsroom.
Only select stories a real Anime, Manga or Comics fan would genuinely care about today.
Reject routine episode/chapter reminders, ordinary interviews, merchandise, generic rankings, reviews, theories, weak rumors, and recycled coverage.
Prefer major announcements, trailers/PVs, adaptations, new seasons, significant release dates, major franchise developments, meaningful production changes, major creator news, and major Marvel/DC/comics events.
Exactly three sectors exist: Anime, Manga, Comics. Marvel and DC are Comics.
Status must be one of rumor, reported, announced, confirmed, released. Never upgrade the evidence.
Score 0-100. 82+ means the story is potentially publishable. The score is editorial value, not article popularity.
Choose one topic from: {', '.join(NEWS_PRIORITY.keys())}.
Create a stable event_key for the underlying event. Return every ID exactly once. Keep reason under 160 characters."""
    response = cerebras_create(
        model=CEREBRAS_MODEL,
        messages=[{"role":"system","content":prompt},{"role":"user","content":"\n\n".join(lines)}],
        response_format={"type":"json_schema","json_schema":{"name":"comics_news_rank_v3","strict":True,"schema":RANK_SCHEMA}},
        reasoning_effort="low", temperature=0.0, max_completion_tokens=RANKING_MAX_COMPLETION_TOKENS,
    )
    data = json.loads(safe_text(response.choices[0].message.content))
    return data.get("ranked", [])


def rank_candidates(candidates, region):
    if not candidates:
        return []
    regional = list(candidates)
    regional = enrich_thin_excerpts(regional)
    rows = []
    # Cheap deterministic pre-ordering keeps the AI ranking cap focused on
    # the strongest event signals instead of simply taking the newest items.
    regional.sort(key=lambda x: (deterministic_editorial_score(x), parse_datetime(x.get("published_date")).timestamp() if parse_datetime(x.get("published_date")) else 0), reverse=True)
    regional = regional[:MAX_RANK_CANDIDATES]
    for offset in range(0, len(regional), RANKING_BATCH_SIZE):
        batch = regional[offset:offset+RANKING_BATCH_SIZE]
        try:
            raw = _rank_batch(batch)
            by_id = {i:x for i,x in enumerate(batch,1)}
            returned = set()
            for r in raw:
                idx = int(r.get("id",0)); item = by_id.get(idx)
                if not item:
                    continue
                returned.add(idx)
                item = dict(item)
                topic = canonical_topic(r.get("topic"), region)
                item.update({
                    "importance_score": max(0,min(100,int(r.get("score",0)))),
                    "important": int(r.get("score",0)) >= PUBLISH_THRESHOLD,
                    "sector": normalize_sector(r.get("sector")) or normalize_sector_from_item(item),
                    "topic": topic,
                    "priority_type": topic,
                    "event_key": safe_text(r.get("event_key")) or event_signature_from_item(item),
                    "event_status": safe_text(r.get("status")) or "reported",
                    "source_class": safe_text(item.get("source_class")) or source_class_for_url(item.get("url")),
                    "rank_reason": trim_source_text(r.get("reason"), 180),
                    "ai_ranked": True,
                })
                rows.append(item)
            for idx,item in enumerate(batch,1):
                if idx not in returned:
                    item = dict(item)
                    _apply_deterministic_rank(item, offset+idx, "AI ranking omitted candidate")
                    rows.append(item)
        except Exception as exc:
            logger.warning("Ranking batch failed; using deterministic fallback: %s", exc)
            for idx,item in enumerate(batch,1):
                item = dict(item)
                _apply_deterministic_rank(item, offset+idx, "AI ranking unavailable")
                rows.append(item)
    rows.sort(key=lambda x:(-int(x.get("importance_score",0)), -(parse_datetime(x.get("published_date")) or datetime.min.replace(tzinfo=timezone.utc)).timestamp()))
    for global_rank,row in enumerate(rows,1):
        row["editor_rank"] = global_rank
        row["important"] = int(row.get("importance_score",0)) >= PUBLISH_THRESHOLD
        tier,prank = NEWS_PRIORITY.get(safe_text(row.get("priority_type")),(9,99))
        row["priority_tier"] = tier; row["priority_rank"] = prank
        q=STATE.get("queue",{}).get(row.get("canonical"))
        if q is not None:
            q.update({"importance_score":int(row.get("importance_score",0)),"priority_type":safe_text(row.get("priority_type")),"priority_tier":tier,"priority_rank":prank,"sector":safe_text(row.get("sector")),"rank_reason":safe_text(row.get("rank_reason")),"last_ranked_at":now_iso(),"learning_pattern":deterministic_pattern(row),"event_key":safe_text(row.get("event_key")),"event_status":safe_text(row.get("event_status"))})
    record_low_score_learning(rows); update_source_quality(rows)
    STATE.setdefault("adaptive_metrics",{})["cerebras_ranked"] = int(STATE.setdefault("adaptive_metrics",{}).get("cerebras_ranked",0)) + sum(1 for x in rows if x.get("ai_ranked"))
    return rows


def extract_entities(text):
    words = re.findall(r"[A-Za-z][A-Za-z&'-]{2,}", safe_text(text).lower())
    return {w for w in words if w not in STOPWORDS}


def entity_overlap(a, b):
    ea = extract_entities(f"{a.get('title','')} {a.get('excerpt','')}")
    eb = extract_entities(f"{b.get('title','')} {b.get('excerpt','')}")
    if not ea or not eb:
        return 0.0
    return len(ea & eb) / max(1, min(len(ea), len(eb)))


def event_similarity_v04(a, b):
    title_score = title_similarity(a.get("title", ""), b.get("title", ""))
    entity_score = entity_overlap(a, b)
    return (0.75 * title_score) + (0.25 * entity_score)


def same_event_window(a, b, hours=30):
    da = parse_datetime(a.get("published_date"))
    db = parse_datetime(b.get("published_date"))
    if not da or not db:
        return False
    return abs((da - db).total_seconds()) <= hours * 3600


def cluster_ranked_events(ranked):
    """Conservative event clustering. Uncertain items are always kept."""
    clusters = []
    ordered = sorted(
        ranked,
        key=lambda x: x.get("editor_rank", 9999),
    )
    for item in ordered:
        placed = False
        for cluster in clusters:
            representative = cluster[0]
            same_key = bool(
                safe_text(item.get("event_key"))
                and safe_text(item.get("event_key")) == safe_text(representative.get("event_key"))
            )
            if same_key or (
                same_event_window(item, representative)
                and event_similarity_v04(item, representative) >= 0.88
            ) or (
                safe_text(item.get("priority_type"))
                and safe_text(item.get("priority_type")) == safe_text(representative.get("priority_type"))
                and _work_keys_similar(work_key_from_text(item.get("title", "")), work_key_from_text(representative.get("title", "")))
                and same_event_window(item, representative, hours=48)
                and (title_similarity(item.get("title", ""), representative.get("title", "")) >= 0.55
                     or _event_core_similarity(item, representative) >= 0.55)
            ):
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])

    output = []
    for index, cluster in enumerate(clusters, start=1):
        representative = cluster[0]
        stable_key = normalize_title(representative.get("title", "")) or representative.get("canonical", "")
        digest = hashlib.sha1(stable_key.encode("utf-8")).hexdigest()[:10]
        cluster_id = f"evt_{digest}"
        sources = sorted({safe_text(x.get("source")) for x in cluster if safe_text(x.get("source"))})
        for member in cluster:
            row = dict(member)
            row.update({
                "event_cluster_id": cluster_id,
                "event_cluster_size": len(cluster),
                "event_sources": sources,
                "event_source_count": len(sources),
                "event_confidence": 1.0 if len(cluster) > 1 else 0.6,
            })
            output.append(row)
    return output


def collapse_event_clusters(ranked):
    clustered = cluster_ranked_events(ranked)
    winners = {}
    for item in clustered:
        key = item.get("event_cluster_id") or item.get("canonical")
        old = winners.get(key)
        if old is None:
            winners[key] = item
            continue
        # Preserve the highest editorial rank, then newest story.
        item_key = (
            item.get("editor_rank", 9999),
            -(parse_datetime(item.get("published_date")).timestamp() if parse_datetime(item.get("published_date")) else 0),
        )
        old_key = (
            old.get("editor_rank", 9999),
            -(parse_datetime(old.get("published_date")).timestamp() if parse_datetime(old.get("published_date")) else 0),
        )
        if item_key < old_key:
            winners[key] = item
    return sorted(winners.values(), key=lambda x: x.get("editor_rank", 9999))


def persist_event_cluster_state(ranked):
    clusters = STATE.setdefault("event_clusters", {})
    for item in ranked:
        event_id = item.get("event_cluster_id")
        if not event_id:
            continue
        clusters[event_id] = {
            "event_id": event_id,
            "topic": item.get("topic", ""),
            "region": item.get("region", ""),
            "sources": item.get("event_sources", []),
            "source_count": item.get("event_source_count", 0),
            "confidence": item.get("event_confidence", 0),
            "last_seen": now_iso(),
            "headline": item.get("title", ""),
        }


def remember_posted_event(story):
    event_id = story.get("event_cluster_id") or make_event_id(story)
    ids = STATE.setdefault("posted_event_ids", [])
    if event_id and event_id not in ids:
        ids.append(event_id)
    STATE["posted_event_ids"] = ids[-500:]

    work_key = work_key_from_text(story.get("headline", ""))
    if work_key:
        memory = STATE.setdefault("work_memory", {}).setdefault(work_key, {
            "title": story.get("headline", ""),
            "sector": story.get("sector", ""),
            "first_published_at": now_iso(),
            "published_events": {},
        })
        memory["title"] = story.get("headline", memory.get("title", ""))
        memory["sector"] = story.get("sector", memory.get("sector", ""))
        memory["last_published_at"] = now_iso()
        priority = safe_text(story.get("priority_type")) or infer_priority_type({"title": story.get("headline", ""), "excerpt": story.get("summary", "")})
        if priority:
            memory.setdefault("published_events", {})[priority] = now_iso()
        records = STATE.setdefault("publication_fingerprints", [])
        records.append({
            "fingerprint": event_signature_from_item({**story, "priority_type": priority}),
            "work_key": work_key,
            "priority_type": priority,
            "headline": story.get("headline", ""),
            "event_text": _event_text(story)[:1400],
            "core": _event_core(story),
            "event_key": safe_text(story.get("event_key")),
            "canonical": safe_text(story.get("canonical")),
            "published_at": now_iso(),
        })
        STATE["publication_fingerprints"] = records[-1000:]
    return event_id


# ============================================================
# ARTICLE EXTRACTION
# ============================================================

def find_og_image(
    url,
    page_html=None,
    final_url=None,
):
    try:
        base_url = (
            final_url
            or url
        )

        if page_html is None:
            response = session.get(
                url,
                headers={
                    **HEADERS,
                    "Referer": url,
                },
                timeout=20,
            )

            if response.status_code >= 400:
                return ""

            page_html = response.text
            base_url = response.url

        soup = BeautifulSoup(
            page_html,
            "html.parser",
        )

        for attrs in (
            {"property": "og:image"},
            {"property": "og:image:url"},
            {"name": "twitter:image"},
        ):
            tag = soup.find(
                "meta",
                attrs=attrs,
            )

            if tag and tag.get(
                "content"
            ):
                return urljoin(
                    base_url,
                    safe_text(
                        tag["content"]
                    ),
                )

    except Exception:
        pass

    return ""


def extract_article(
    item,
):
    url = item["url"]

    try:
        response = session.get(
            url,
            headers={
                **HEADERS,
                "Referer": url,
            },
            timeout=25,
        )

        if response.status_code < 400:
            page_html = response.text
            item["image_candidates"] = _extract_image_candidates_from_html(page_html, response.url, item.get("title", ""))[:20]
            item["video_candidates"] = discover_direct_video_links(item.get("url", ""), page_html)[:8]

            text = trafilatura.extract(
                page_html,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )

            image_url = (
                item.get("image")
                or find_og_image(
                    url,
                    page_html,
                    response.url,
                )
            )

            if text and len(safe_text(text)) >= 500:
                return (
                    safe_text(text),
                    image_url,
                )

    except Exception as exc:
        logger.warning(
            "Local extraction failed %s: %s",
            url,
            exc,
        )

    try:
        result_set = _exa_get_contents(
            [url],
            text={"max_characters": 12000},
        )

        if result_set.results:
            result = result_set.results[0]

            text = safe_text(
                getattr(
                    result,
                    "text",
                    "",
                )
            )

            image_url = (
                item.get("image")
                or safe_text(
                    getattr(
                        result,
                        "image",
                        "",
                    )
                )
            )

            if text:
                return (
                    text,
                    image_url,
                )

    except Exception as exc:
        logger.warning(
            "Exa article fallback failed %s: %s",
            url,
            exc,
        )

    return (
        "",
        item.get("image", ""),
    )


# ============================================================
# STORY + KNOWLEDGE GENERATION
# ============================================================
STORY_SCHEMA={
    "type":"object",
    "properties":{
        "title":{"type":"string"},
        "summary":{"type":"string"},
        "sector":{"type":"string","enum":SECTORS},
        "news_type":{"type":"string","enum":[
            "Major Announcement","Season / Sequel","Trailer","Adaptation","Release Date",
            "Movie","Franchise Update","Cast / Staff","Production","Manga Update","Ending",
            "Marvel","DC","Comic Announcement","Storyline / Event","Comic Adaptation",
            "Creator / Publisher","Milestone"
        ]},
        "highlights":{"type":"array","items":{"type":"string"}},
        "why_it_matters":{"type":"string"},
        "studio":{"type":"string"},
        "publisher":{"type":"string"},
        "platform":{"type":"string"},
        "release_date":{"type":"string"},
        "status":{"type":"string"},
    },
    "required":["title","summary","sector","news_type","highlights","why_it_matters","studio","publisher","platform","release_date","status"],
    "additionalProperties":False,
}


def first_sentence(text):
    text = clean_generated_text(text)
    protected = {
        "U.S.": "US_SENTINEL", "U.K.": "UK_SENTINEL", "E.U.": "EU_SENTINEL",
        "No.": "NO_SENTINEL", "Inc.": "INC_SENTINEL", "Ltd.": "LTD_SENTINEL",
        "Dr.": "DR_SENTINEL", "Mr.": "MR_SENTINEL", "Mrs.": "MRS_SENTINEL", "Ms.": "MS_SENTINEL",
    }
    working=text
    for old,marker in protected.items(): working=working.replace(old,marker)
    match=re.search(r"(.+?[.!?])(?:\s|$)",working)
    sentence=match.group(1) if match else working
    for old,marker in protected.items(): sentence=sentence.replace(marker,old)
    return clean_generated_text(sentence)


def generate_story(item,article_text,research_context=""):
    sector_hint=normalize_sector(item.get("sector")) or normalize_sector_from_item(item)
    prompt=f"""You are the senior editor for @ComicsNewsroom, a premium Anime, Manga and Comics fan newsroom.
Create a compact, source-grounded story only when the development is genuinely worth a fan's attention today.
Exactly three sectors exist: Anime, Manga, Comics. Marvel and DC are always Comics.
Allowed event types: Major Announcement, Season / Sequel, Trailer, Adaptation, Release Date, Movie, Franchise Update,
Cast / Staff, Production, Manga Update, Ending, Marvel, DC, Comic Announcement, Storyline / Event, Comic Adaptation,
Creator / Publisher, Milestone.

Editorial rules:
- Title is the real work/franchise/subject, not clickbait.
- Summary is one factual sentence.
- Highlights: 2-4 concrete facts.
- why_it_matters: one concise sentence, only when useful.
- Never invent dates, cast, studios, platforms, figures or status.
- Do not upgrade rumor/reported into announced/confirmed/released.
- Use the research evidence when present, but do not add facts absent from it.
- No Markdown or HTML.
Return only the JSON schema."""
    user=(
        f"SOURCE: {item.get('source','')}\nSOURCE CLASS: {item.get('source_class','reported')}\n"
        f"TITLE: {item.get('title','')}\nDATE: {item.get('published_date','')}\nCATEGORY HINT: {sector_hint}\n"
        f"ARTICLE:\n{article_text[:10000]}\n\nRESEARCH / OFFICIAL EVIDENCE:\n{research_context[:9000]}"
    )
    try:
        response=cerebras_create(
            model=CEREBRAS_MODEL,
            messages=[{"role":"system","content":prompt},{"role":"user","content":user}],
            response_format={"type":"json_schema","json_schema":{"name":"comics_anime_story_v3","strict":True,"schema":STORY_SCHEMA}},
            reasoning_effort="low",temperature=0.1,max_completion_tokens=STORY_MAX_COMPLETION_TOKENS,
        )
        data=json.loads(safe_text(response.choices[0].message.content))
        title=clean_generated_text(data.get("title")); summary=first_sentence(data.get("summary"))
        highlights=[clean_generated_text(x) for x in data.get("highlights",[]) if clean_generated_text(x)]
        why=clean_generated_text(data.get("why_it_matters")); news_type=safe_text(data.get("news_type"))
        out_sector=normalize_sector(data.get("sector"))
        allowed_types=set(STORY_SCHEMA["properties"]["news_type"]["enum"])
        if not title or not summary or news_type not in allowed_types or out_sector not in SECTORS or not (2<=len(highlights)<=4):
            raise ValueError("Invalid story structure")
        story={**item,
            "title":trim_source_text(title,120),"headline":trim_source_text(title,120),
            "summary":trim_source_text(summary,280),"sector":out_sector,"news_type":news_type,
            "priority_type":infer_priority_type({**item,"title":title,"excerpt":article_text[:12000],"topic":news_type}),
            "highlights":[trim_source_text(x,160) for x in highlights],"why_it_matters":trim_source_text(why,240),
            "studio":trim_source_text(clean_generated_text(data.get("studio")),180),
            "publisher":trim_source_text(clean_generated_text(data.get("publisher")),180),
            "platform":trim_source_text(clean_generated_text(data.get("platform")),180),
            "release_date":trim_source_text(clean_generated_text(data.get("release_date")),120),
            "status":trim_source_text(clean_generated_text(data.get("status")),100),
            "year":"","format":"","episodes":"","chapters":"","languages":"",
            "official_video_url":"","official_video_platform":"","official_video_title":"",
            "spoiler":"","note":"","bold_terms":[],
        }
        return story
    except CerebrasRateLimitError:
        raise
    except CerebrasBudgetError:
        raise
    except Exception as exc:
        logger.warning("Story generation failed: %s",exc)
        return None


def discover_direct_video_links(article_url, page_html=None):
    """Return likely direct YouTube/Crunchyroll video links found on the source page."""
    urls=[]
    try:
        if page_html is None:
            response=session.get(article_url,headers={**HEADERS,"Referer":article_url},timeout=20)
            if response.status_code>=400:
                return []
            page_html=response.text
            base=response.url
        else:
            base=article_url
        soup=BeautifulSoup(page_html,"html.parser")
        for tag in soup.find_all(["a","iframe"], href=True):
            raw=safe_text(tag.get("href"))
            if raw: urls.append(urljoin(base,raw))
        for tag in soup.find_all("iframe", src=True):
            urls.append(urljoin(base,safe_text(tag.get("src"))))
    except Exception:
        return []
    out=[]; seen=set()
    for url in urls:
        if not re.match(r"^https?://",url,re.I): continue
        u=url.lower()
        if "youtube.com/watch" in u or "youtu.be/" in u or "youtube.com/embed/" in u or "crunchyroll.com/watch" in u:
            if url not in seen:
                seen.add(url); out.append(url)
    return out[:8]


def verify_video_url(url, expected_title=""):
    if not url or not re.match(r"^https?://",url,re.I):
        return False, "", ""
    try:
        if "youtube.com" in url or "youtu.be" in url:
            if "youtube.com/embed/" in url:
                video_url=url.replace("/embed/","/watch?v=")
            else:
                video_url=url
            r=session.get("https://www.youtube.com/oembed?url="+quote(video_url,safe="")+"&format=json",timeout=15,headers=HEADERS)
            if r.status_code<400:
                d=r.json()
                return True, "YouTube", safe_text(d.get("title"))
        if "crunchyroll.com/watch" in url:
            # Direct URL from the publisher page is enough for our editorial link.
            return True, "Crunchyroll", expected_title
    except Exception:
        pass
    return False, "", ""


def _youtube_video_id(url):
    raw=safe_text(url)
    patterns=[r"[?&]v=([A-Za-z0-9_-]{6,})",r"youtu\.be/([A-Za-z0-9_-]{6,})",r"youtube\.com/embed/([A-Za-z0-9_-]{6,})"]
    for pattern in patterns:
        m=re.search(pattern,raw,re.I)
        if m:return m.group(1)
    return ""

def youtube_thumbnail(url):
    vid=_youtube_video_id(url)
    return f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg" if vid else ""

def video_title_relevant(video_title, work_title):
    vt=normalize_title(video_title)
    wt=normalize_title(work_title)
    if not vt or not wt:return False
    vt=re.sub(r"\b(?:official|trailer|teaser|pv|promo|video|clip|new)\b"," ",vt)
    wt=re.sub(r"\b(?:anime|manga|comic|season|part|movie|film)\b"," ",wt)
    return title_similarity(vt,wt)>=0.22 or wt in vt or vt in wt

def exa_video_search(work_title):
    """Find a likely official YouTube/Crunchyroll video for a major trailer story."""
    for domain in ("youtube.com", "crunchyroll.com"):
        for query in (
            f'"{work_title}" official trailer',
            f'"{work_title}" official teaser',
            f'"{work_title}" official PV',
        ):
            try:
                results = _exa_search(query, domains=[domain], num_results=5, date_filtered=False)
                for result in getattr(results, "results", []) or []:
                    url = safe_text(getattr(result, "url", ""))
                    title = safe_text(getattr(result, "title", ""))
                    ok, platform, video_title = verify_video_url(url, title or work_title)
                    chosen_title = video_title or title
                    if ok and video_title_relevant(chosen_title, work_title):
                        return {"url": url, "platform": platform, "title": chosen_title, "verified": True}
            except Exception as exc:
                logger.info("Exa video lookup skipped: %s", exc)
    return None


# ============================================================
# NUMERIC GROUNDING
# ============================================================

NUMBER_RE = re.compile(
    r"""
    (?:
        (?:US|U\.S\.|HK|HK\$|Tk|BDT|USD|EUR|GBP|JPY|CNY|INR|৳|\$|€|£|¥)
        \s*
    )?
    \d[\d,]*(?:\.\d+)?
    \s*
    (?:
        million|billion|trillion|
        crore|lakh|bn|mn|b|m|k|%
    )?
    """,
    re.I | re.X,
)

YEAR_RE = re.compile(
    r"^(?:19|20)\d{2}$"
)


def normalize_number(
    raw,
):
    text = (
        safe_text(raw)
        .lower()
        .replace(",", "")
        .replace("৳", "tk")
        .replace("$", "usd")
    )

    return re.sub(
        r"\s+",
        "",
        text,
    )


NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
    "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16",
    "seventeen": "17", "eighteen": "18", "nineteen": "19", "twenty": "20",
}
ORDINAL_WORDS = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
    "eleventh": "11", "twelfth": "12", "thirteenth": "13", "fourteenth": "14",
    "fifteenth": "15", "sixteenth": "16", "seventeenth": "17", "eighteenth": "18", "nineteenth": "19", "twentieth": "20",
}

def numeric_tokens(text):
    tokens = []
    for match in NUMBER_RE.finditer(safe_text(text)):
        token = safe_text(match.group(0))
        stripped = re.sub(r"[^\d.]", "", token)
        if YEAR_RE.match(stripped) and not any(x in token.lower() for x in ("tk","usd","bdt","$","€","£","¥","%","million","billion","crore","lakh")):
            continue
        if token:
            tokens.append(token)
    return tokens

def numeric_equivalents(text):
    values = {normalize_number(x) for x in numeric_tokens(text) if normalize_number(x)}
    words = re.findall(r"\b(?:" + "|".join(re.escape(x) for x in sorted({*NUMBER_WORDS, *ORDINAL_WORDS}, key=len, reverse=True)) + r")\b", safe_text(text).lower())
    for word in words:
        values.add(NUMBER_WORDS.get(word) or ORDINAL_WORDS.get(word))
    return {x for x in values if x}

def numeric_grounded(story, article_text):
    source_numbers = numeric_equivalents(article_text)
    generated_text = " ".join([story.get("headline", ""), story.get("summary", ""), *story.get("highlights", [])])
    for token in numeric_tokens(generated_text):
        normalized = normalize_number(token)
        if normalized and normalized not in source_numbers:
            # If the numeric statement is an ordinal/season/chapter marker and
            # the source expresses it in words, numeric_equivalents() already matched it.
            return False, token
    return True, ""


def derive_bold_terms(
    story,
):
    terms = [
        safe_text(x)
        for x in story.get(
            "bold_terms",
            [],
        )
        if safe_text(x)
    ]

    combined = " ".join(
        [
            story.get(
                "summary",
                "",
            ),
            *story.get(
                "highlights",
                [],
            ),
        ]
    )

    # Financial figures, but do not bold bare years.
    for match in NUMBER_RE.finditer(
        combined
    ):
        token = safe_text(
            match.group(0)
        )

        numeric_only = re.sub(
            r"[^\d.]",
            "",
            token,
        )

        if (
            YEAR_RE.match(
                numeric_only
            )
            and not re.search(
                r"(Tk|BDT|USD|EUR|GBP|JPY|CNY|INR|৳|\$|€|£|¥|%|million|billion|crore|lakh)",
                token,
                re.I,
            )
        ):
            continue

        if token:
            terms.append(
                token
            )

    unique = []
    seen = set()

    for term in sorted(
        terms,
        key=len,
        reverse=True,
    ):
        key = term.lower()

        if (
            len(term) >= 2
            and key not in seen
        ):
            seen.add(key)
            unique.append(term)

    return unique[:16]


def escape_rich_html(
    text,
):
    return html.escape(
        clean_generated_text(text),
        quote=False,
    )


def bold_terms_html(
    text,
    terms,
):
    text = clean_generated_text(
        text
    )

    if not text:
        return ""

    result = text

    # Use letter-only markers to avoid collisions with numeric terms.
    replacements = []

    for index, term in enumerate(
        sorted(
            {
                safe_text(x)
                for x in terms
                if safe_text(x)
            },
            key=len,
            reverse=True,
        )
    ):
        marker = (
            f"__RICHBOLD_{chr(65 + (index % 26))}"
            f"{index // 26}__"
        )

        pattern = re.compile(
            re.escape(term),
            re.I,
        )

        match = pattern.search(
            result
        )

        if match:
            original = match.group(
                0
            )
            result = (
                result[:match.start()]
                + marker
                + result[match.end():]
            )
            replacements.append(
                (
                    marker,
                    original,
                )
            )

    escaped = html.escape(
        result,
        quote=False,
    )

    for marker, original in replacements:
        escaped = escaped.replace(
            marker,
            "<b>"
            + html.escape(
                original,
                quote=False,
            )
            + "</b>",
        )

    return escaped


# ============================================================
# TELEGRAM RICH MESSAGE HTML
# ============================================================
def rich_visible_length(text):
    no_tags=re.sub(r"<[^>]+>","",safe_text(text))
    return len(html.unescape(no_tags))


def add_media_reference():
    return '<img src="tg://photo?id=newsphoto">'


def _story_hook(story):
    priority=safe_text(story.get("priority_type"))
    score=int(story.get("importance_score",0) or 0)
    if priority == "Major Trailer / PV": return "🚨 MAJOR TRAILER" if score>=92 else "🎞️ NEW TRAILER"
    if priority == "Manga → Anime Adaptation": return "⚡ MANGA → ANIME"
    if priority == "New Season / Sequel": return "🔄 NEW SEASON"
    if priority == "Major Release Date": return "📅 RELEASE DATE"
    if priority == "Major Anime Movie": return "🎬 ANIME MOVIE"
    if priority == "Major Cast / Staff Reveal": return "🎭 CAST / STAFF"
    if priority == "Major Manga Return / Hiatus": return "📖 MANGA UPDATE"
    if priority == "Major Manga Ending": return "📖 MANGA FINALE"
    if priority == "Major Marvel News" or safe_text(story.get("sector")) == "Marvel": return "◆ MARVEL COMICS"
    if priority == "Major DC News" or safe_text(story.get("sector")) == "DC": return "◆ DC COMICS"
    if priority == "Major Comic Storyline / Event": return "◆ MAJOR COMIC EVENT"
    if priority == "Major Comic Adaptation": return "🎬 COMIC ADAPTATION"
    if priority == "Major Sales / Milestone": return "📈 MAJOR MILESTONE"
    if priority == "Major Production News": return "🎬 PRODUCTION UPDATE"
    if priority == "Major Creator / Publisher News": return "✦ CREATOR / PUBLISHER"
    if score>=92: return "🚨 BREAKING"
    return "✦ MAJOR NEWS"


def _story_icon(story):
    sector=safe_text(story.get("sector"))
    return {"Anime":"🎬","Manga":"📖","Marvel":"◆","DC":"◆","Comics":"◆"}.get(sector,"✦")


def _rich_story_meta(story, *, include_release=True):
    labels = [
        ("Studio", "studio"),
        ("Publisher", "publisher"),
        ("Platform", "platform"),
        ("Format", "format"),
        ("Episodes", "episodes"),
        ("Chapters", "chapters"),
        ("Status", "status"),
        ("Release", "release_date"),
    ]
    if not include_release:
        labels = [x for x in labels if x[1] != "release_date"]
    lines = []
    for label, key in labels:
        value = safe_text(story.get(key))
        if value:
            lines.append(f"<p>✦ <b>{label}:</b> {escape_rich_html(value)}</p>")
    return lines


def _rich_source_footer(story):
    lines = []
    hashtags = " ".join(category_hashtags(story))
    footer = " ".join(x for x in [CHANNEL_TAG, hashtags] if x)
    if footer:
        lines.append(f"<p>{escape_rich_html(footer)}</p>")

    official = safe_text(story.get("official_source_url"))
    main_url = safe_text(story.get("url", ""))
    if official and official != main_url:
        safe_official = html.escape(official, quote=True)
        lines.append(f'<p>✦ <a href="{safe_official}"><b>Official Source</b></a></p>')

    source = escape_rich_html(story.get("source", "Source"))
    url = html.escape(safe_text(story.get("url", "")), quote=True)
    if url:
        lines.append(f'<footer><b>Source:</b> <a href="{url}">{source}</a></footer>')
    else:
        lines.append(f"<footer><b>Source:</b> {source}</footer>")
    return lines


def _rich_content(story, *, max_highlights=4, include_why=True):
    terms = derive_bold_terms(story)
    lines = []
    summary = bold_terms_html(story.get("summary", "") or "", terms)
    if summary:
        lines.append(f"<blockquote>📖 {summary}</blockquote>")
    for detail in story.get("highlights", [])[:max_highlights]:
        value = bold_terms_html(detail, terms)
        if value:
            lines.append(f"<p>✦ {value}</p>")
    why = safe_text(story.get("why_it_matters"))
    if include_why and why and int(story.get("importance_score", 0) or 0) >= 88:
        lines.append(f"<p>💡 <b>Why fans care:</b> {bold_terms_html(why, terms)}</p>")
    return lines


def _rich_watch_block(story):
    video = safe_text(story.get("official_video_url"))
    platform = safe_text(story.get("official_video_platform"))
    if not video or not platform:
        return []
    safe_video = html.escape(video, quote=True)
    if safe_text(story.get("priority_type")) == "Major Trailer / PV":
        return [f'<h2>Watch Trailer 👉 <a href="{safe_video}">{escape_rich_html(platform)}</a></h2>']
    return [f'<p>▶ <a href="{safe_video}"><b>Watch Official Video</b></a> · {escape_rich_html(platform)}</p>']


def _rich_optional_blocks(story, terms=None):
    terms = terms or derive_bold_terms(story)
    lines = []
    spoiler = safe_text(story.get("spoiler"))
    if spoiler:
        lines.append(f"<p>🙈 <b>Spoiler:</b> <tg-spoiler>{bold_terms_html(spoiler, terms)}</tg-spoiler></p>")
    note = safe_text(story.get("note"))
    if note:
        lines.append(f"<details><summary>ℹ️ More</summary><p>{bold_terms_html(note, terms)}</p></details>")
    return lines


def _rich_template(story, badge, icon, *, meta=True, include_why=True, max_highlights=4, watch=False):
    terms = derive_bold_terms(story)
    title = escape_rich_html(story.get("title") or story.get("headline") or "")
    year = safe_text(story.get("year"))
    lines = [add_media_reference(), f"<p><b>{escape_rich_html(badge)}</b></p>"]
    lines.append(f"<h1><b>{escape_rich_html(icon)} {title}" + (f" ({escape_rich_html(year)})" if year else "") + "</b></h1>")
    if meta:
        lines.extend(_rich_story_meta(story))
    lines.extend(_rich_content(story, max_highlights=max_highlights, include_why=include_why))
    if watch:
        lines.extend(_rich_watch_block(story))
    lines.extend(_rich_optional_blocks(story, terms))
    lines.extend(_rich_source_footer(story))
    return "\n".join(lines)


def dynamic_rich_html(story):
    """Render one of several editorially distinct mobile-first Rich Message layouts."""
    priority = safe_text(story.get("priority_type"))
    sector = normalize_sector(story.get("sector"))
    topic = safe_text(story.get("topic"))

    if priority == "Major Trailer / PV" or topic == "Major Trailer / PV":
        return _rich_template(story, "🎞️ NEW TRAILER", "🎬", max_highlights=3, watch=True)

    if priority == "Manga → Anime Adaptation" or topic == "Manga → Anime Adaptation":
        return _rich_template(story, "⚡ MANGA → ANIME", "📖", max_highlights=4, include_why=True)

    if sector == "Manga" and priority in {"Major Manga Return / Hiatus", "Major Manga Ending", "Major Sales / Milestone"}:
        return _rich_template(story, "📖 MANGA UPDATE", "📖", max_highlights=3, include_why=True)

    if sector == "Comics" and priority == "Major Marvel News":
        return _rich_template(story, "◆ MARVEL COMICS", "◆", max_highlights=4, include_why=True)

    if sector == "Comics" and priority == "Major DC News":
        return _rich_template(story, "◆ DC COMICS", "◆", max_highlights=4, include_why=True)

    if priority == "Major Comic Storyline / Event":
        return _rich_template(story, "◆ MAJOR COMIC EVENT", "◆", max_highlights=4, include_why=True)

    if priority == "Major Comic Adaptation":
        return _rich_template(story, "🎬 COMIC ADAPTATION", "🎬", max_highlights=4, include_why=True, watch=True)

    if priority == "New Season / Sequel":
        return _rich_template(story, "🔄 NEW SEASON", "🎬", max_highlights=3, include_why=True)

    if priority == "Major Release Date":
        return _rich_template(story, "📅 RELEASE DATE", "📅", max_highlights=3, include_why=True)

    if priority == "Major Anime Movie":
        return _rich_template(story, "🎬 ANIME MOVIE", "🎬", max_highlights=3, include_why=True, watch=True)

    if priority == "Major Cast / Staff Reveal":
        return _rich_template(story, "🎭 CAST / STAFF", "🎭", max_highlights=3, include_why=True)

    if priority == "Major Production News":
        return _rich_template(story, "🎬 PRODUCTION UPDATE", "🎬", max_highlights=3, include_why=True)

    if priority == "Major Creator / Publisher News":
        return _rich_template(story, "✦ CREATOR / PUBLISHER", "✦", max_highlights=3, include_why=True)

    if priority == "Major Sales / Milestone":
        return _rich_template(story, "📈 MAJOR MILESTONE", "📈", max_highlights=3, include_why=True)

    return _rich_template(story, "✦ MAJOR ANNOUNCEMENT", "✦", max_highlights=4, include_why=True)


def fit_rich_html(story):
    variants=[
        dict(story),
        dict(story,why_it_matters="",summary=trim_source_text(story.get("summary",""),210),highlights=[trim_source_text(x,120) for x in story.get("highlights",[])[:3]],note=trim_source_text(story.get("note",""),180)),
        dict(story,why_it_matters="",summary=trim_source_text(story.get("summary",""),160),highlights=[trim_source_text(x,95) for x in story.get("highlights",[])[:2]],note=""),
    ]
    for candidate in variants:
        rendered=dynamic_rich_html(candidate)
        if rich_visible_length(rendered)<=MAX_RICH_CHARACTERS:
            return rendered
    raise ValueError("Unable to fit Rich Message within Telegram limits")


# ============================================================
# IMAGE BRANDING: ONLY @ComicsNewsroom
# ============================================================

def find_font(
    bold=False,
):
    candidates = (
        [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        ]
        if bold
        else [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
    )

    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def download_image(
    url,
    referer,
):
    if not url or safe_text(url).lower().startswith("data:image/"):
        return None

    try:
        response = session.get(
            url,
            headers={
                **HEADERS,
                "Referer": referer,
            },
            timeout=20,
            stream=True,
        )

        if response.status_code >= 400:
            return None

        content_type = (
            response.headers.get(
                "content-type",
                "",
            )
            .lower()
        )

        if (
            content_type
            and not content_type.startswith(
                "image/"
            )
        ):
            return None

        buf = BytesIO()

        for chunk in response.iter_content(
            65536
        ):
            if not chunk:
                continue

            buf.write(
                chunk
            )

            if buf.tell() > 8_000_000:
                return None

        buf.seek(0)

        image = Image.open(
            buf
        )
        image.load()

        if (
            image.width < 400
            or image.height < 250
        ):
            return None

        return image.convert(
            "RGB"
        )

    except Exception as exc:
        logger.warning(
            "Image download failed: %s",
            exc,
        )
        return None


def crop_cover(image, size=(1200, 675)):
    target_w, target_h = size
    ratio = max(target_w / image.width, target_h / image.height)
    resized = image.resize((int(image.width * ratio), int(image.height * ratio)), Image.Resampling.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def fit_full_poster(image, max_size=(1200, 1800)):
    """Resize full poster only if necessary. Preserve poster aspect ratio; never crop or add wide 16:9 padding."""
    max_w,max_h=max_size
    ratio=min(1.0, max_w/image.width, max_h/image.height)
    if ratio < 1.0:
        return image.resize((max(1,int(image.width*ratio)),max(1,int(image.height*ratio))),Image.Resampling.LANCZOS).convert("RGB")
    return image.convert("RGB")


def image_average_brightness(image):
    return image.resize((1, 1)).convert("L").getpixel((0, 0))


def branded_card(photo):
    """Brand normal editorial photos only. Posters intentionally bypass this."""
    base = crop_cover(photo).convert("RGBA")
    brightness = image_average_brightness(base)
    bg = (245, 245, 245, 225) if brightness < 125 else (18, 22, 28, 205)
    fg = (20, 24, 28, 255) if brightness < 125 else (245, 245, 245, 255)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font_path = find_font(bold=True)
    font = ImageFont.truetype(font_path, 24) if font_path else ImageFont.load_default()
    text = "@ComicsNewsroom"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    padding_x, padding_y = 22, 10
    chip_w, chip_h = text_w + padding_x * 2, text_h + padding_y * 2
    x2, y2 = 1200 - 28, 675 - 24
    x1, y1 = x2 - chip_w, y2 - chip_h
    draw.rounded_rectangle((x1, y1, x2, y2), radius=18, fill=bg)
    draw.text((x1 + padding_x, y1 + padding_y - 1), text, font=font, fill=fg)
    return Image.alpha_composite(base, overlay).convert("RGB")


def _story_priority_label(story):
    priority=safe_text(story.get("priority_type"))
    return priority if priority in NEWS_PRIORITY else infer_priority_type(story)


def _is_poster_priority(story):
    return safe_text(story.get("format")) in {"Anime","Manga","Comic","Movie"}


def _extract_image_candidates_from_html(page_html, base_url, title):
    """Collect page image candidates, preferring explicit poster/key-art/title matches."""
    scored = []
    try:
        soup = BeautifulSoup(page_html, "html.parser")
        for tag in soup.find_all("meta"):
            prop = safe_text(tag.get("property") or tag.get("name")).lower()
            content = safe_text(tag.get("content"))
            if content and prop in {"og:image", "og:image:url", "twitter:image"}:
                scored.append((2, urljoin(base_url, content)))
        needle = normalize_title(title)
        for img in soup.find_all("img")[:80]:
            src = safe_text(img.get("src") or img.get("data-src") or img.get("data-lazy-src"))
            if not src:
                srcset = safe_text(img.get("srcset") or img.get("data-srcset"))
                if srcset:
                    src = safe_text(srcset.split(",")[0].strip().split(" ")[0])
            if not src:
                continue
            alt = normalize_title(img.get("alt", ""))
            raw_src = safe_text(src).lower()
            score = 0
            if "poster" in alt or "key art" in alt or (needle and needle in alt): score += 8
            if any(token in raw_src for token in ("poster", "key-art", "keyart")): score += 6
            scored.append((score, urljoin(base_url, src)))
    except Exception:
        pass
    dedup=[]; seen=set()
    for score,url in sorted(scored, key=lambda x:x[0], reverse=True):
        if url and url not in seen:
            seen.add(url); dedup.append(url)
    return dedup


def _download_source_logo(source, article_url):
    """Best-effort official publication logo/icon for image fallback."""
    try:
        parsed=urlparse(article_url)
        host=parsed.netloc.lower().removeprefix("www.")
        if not host: return None
        homepage=f"https://{host}/"
        response=session.get(homepage,headers={**HEADERS,"Referer":article_url},timeout=15)
        if response.status_code>=400:return None
        soup=BeautifulSoup(response.text,"html.parser")
        urls=[]
        for script in soup.find_all("script",type="application/ld+json"):
            try:
                data=json.loads(script.string or script.get_text())
                records=data if isinstance(data,list) else [data]
                for record in records:
                    if isinstance(record,dict):
                        logo=record.get("logo")
                        if isinstance(logo,dict): logo=logo.get("url")
                        if logo: urls.insert(0,urljoin(response.url,safe_text(logo)))
            except Exception: pass
        for link in soup.find_all("link"):
            rel=" ".join(link.get("rel",[])).lower(); href=safe_text(link.get("href"))
            if href and ("icon" in rel or "logo" in rel): urls.append(urljoin(response.url,href))
        # Favicon fallback from the official host, still retrieved from the publisher domain.
        urls.append(urljoin(response.url,"/favicon.ico"))
        for url in urls:
            try:
                r=session.get(url,headers={**HEADERS,"Referer":homepage},timeout=10)
                if r.status_code>=400: continue
                buf=BytesIO(r.content); img=Image.open(buf); img.load()
                if img.width>=40 and img.height>=40:
                    return img.convert("RGBA")
            except Exception: continue
    except Exception:
        pass
    return None


def _source_logo_card(logo, source="Source"):
    canvas=Image.new("RGB",(1200,675),(24,34,46))
    canvas_rgba=canvas.convert("RGBA")
    if logo is not None:
        if logo.mode!="RGBA": logo=logo.convert("RGBA")
        max_w,max_h=520,300
        ratio=min(max_w/logo.width,max_h/logo.height)
        resized=logo.resize((max(1,int(logo.width*ratio)),max(1,int(logo.height*ratio))),Image.Resampling.LANCZOS)
        x=(1200-resized.width)//2; y=(675-resized.height)//2
        canvas_rgba.alpha_composite(resized,(x,y))
        return canvas_rgba.convert("RGB")
    # Last fallback: source name only, centered. Never add channel branding here.
    draw=ImageDraw.Draw(canvas_rgba)
    font_path=find_font(bold=True)
    font=ImageFont.truetype(font_path,64) if font_path else ImageFont.load_default()
    text=safe_text(source) or "Source"
    max_width=980
    while font.size > 28 and draw.textbbox((0,0),text,font=font)[2]-draw.textbbox((0,0),text,font=font)[0] > max_width:
        font=ImageFont.truetype(font_path,font.size-4) if font_path else ImageFont.load_default()
    bbox=draw.textbbox((0,0),text,font=font); tw=bbox[2]-bbox[0]; th=bbox[3]-bbox[1]
    draw.text(((1200-tw)//2,(675-th)//2),text,font=font,fill=(245,245,245,255))
    return canvas_rgba.convert("RGB")


def prepare_image(story,index):
    image_urls=[]
    primary=safe_text(story.get("image_url"))
    if primary:image_urls.append(primary)
    for candidate in story.get("image_candidates",[])[:20]:
        if candidate and candidate not in image_urls:image_urls.append(candidate)

    if _is_poster_priority(story):
        for url in image_urls:
            image=download_image(url,story.get("url",""))
            if image and image.height >= image.width * 1.05:
                path=f"/tmp/news_{index}.jpg"
                fit_full_poster(image).save(path,"JPEG",quality=94,optimize=True)
                return path

    for url in image_urls:
        image=download_image(url,story.get("url",""))
        if image:
            path=f"/tmp/news_{index}.jpg"
            branded_card(image).save(path,"JPEG",quality=88,optimize=True)
            return path

    logo=_download_source_logo(story.get("source",""),story.get("url",""))
    path=f"/tmp/news_{index}.jpg"
    _source_logo_card(logo, story.get("source", "Source")).save(path,"JPEG",quality=92,optimize=True)
    return path


# ============================================================
# TELEGRAM RICH MESSAGES
# ============================================================

def telegram_call(method, data=None, files=None):
    if not TELEGRAM_BOT_TOKEN:
        return {"ok": False, "description": "TELEGRAM_BOT_TOKEN missing", "configuration_error": True}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    last = {"ok": False, "description": "Unknown error"}
    for attempt in range(1, 3):
        try:
            response = session.post(url, data=data or {}, files=files, timeout=90)
            result = response.json()
            result["http_status"] = response.status_code
            if result.get("ok"):
                result["ambiguous"] = False
                return result
            last = result
            if response.status_code == 429:
                retry_after = int(result.get("parameters", {}).get("retry_after", 3))
                retry_after = min(max(1, retry_after), 10)
                logger.warning("Telegram 429; bounded wait %ss", retry_after)
                time.sleep(retry_after)
                continue
            if response.status_code >= 500:
                time.sleep(2 * attempt)
                continue
            break
        except requests.Timeout as exc:
            return {"ok": False, "description": f"timeout: {exc}", "transport_error": True, "ambiguous": True}
        except requests.RequestException as exc:
            return {"ok": False, "description": str(exc), "transport_error": True, "ambiguous": True}
        except Exception as exc:
            return {"ok": False, "description": str(exc), "transport_error": True, "ambiguous": True}
    return last

def send_bot_api_fallback(image_path, rich_html):
    """Last-resort photo send when Rich Messages are unavailable."""
    text = re.sub(r"<details[^>]*>|</details>|<summary[^>]*>|</summary>", "", rich_html, flags=re.I)
    text = re.sub(r"<tg-spoiler>|</tg-spoiler>", "", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|h1|h2|h3|footer|blockquote)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_TELEGRAM_CAPTION_CHARACTERS:
        text = text[:MAX_TELEGRAM_CAPTION_CHARACTERS].rsplit(" ", 1)[0].rstrip() + "..."
    try:
        with open(image_path, "rb") as photo:
            return telegram_call(
                "sendPhoto",
                data={"chat_id": TELEGRAM_CHANNEL, "caption": text},
                files={"photo": photo},
            )
    except Exception as exc:
        return {"ok": False, "description": str(exc)}


def send_rich_photo(image_path, rich_html):
    """Send image + rich HTML through Telegram Bot API Rich Messages."""
    rich_message = {
        "html": rich_html,
        "media": [{
            "id": "newsphoto",
            "media": {"type": "photo", "media": "attach://photo"},
        }],
        "skip_entity_detection": False,
    }
    with open(image_path, "rb") as photo:
        return telegram_call(
            "sendRichMessage",
            data={"chat_id": TELEGRAM_CHANNEL, "rich_message": json.dumps(rich_message, ensure_ascii=False)},
            files={"photo": photo},
        )

# ============================================================
# KNOWLEDGE / EVENT RECORD
# ============================================================

def make_event_id(
    story,
):
    event_key = safe_text(
        story.get(
            "event_key"
        )
    )

    if event_key:
        return (
            re.sub(
                r"[^a-z0-9]+",
                "_",
                event_key.lower(),
            ).strip("_")
        )

    return canonical_url(
        story["url"]
    )


def store_event(story, published=False, message_id=None):
    event_id=make_event_id(story)
    event={
        "event_id":event_id,
        "canonical_url":story.get("canonical",""),
        "original_url":story.get("url",""),
        "source":story.get("source",""),
        "region":REGION,
        "sector":story.get("sector",""),
        "topic":story.get("topic",""),
        "institution":story.get("institution",""),
        "event_cluster_id":story.get("event_cluster_id",event_id),
        "event_confidence":story.get("event_confidence",0),
        "event_source_count":story.get("event_source_count",0),
        "headline":story.get("headline",story.get("title","")),
        "summary":story.get("summary",""),
        "highlights":story.get("highlights",[]),
        "why_it_matters":story.get("why_it_matters", ""),
        "concepts":story.get("concepts",[]),
        "key_numbers":story.get("key_numbers",[]),
        "priority_type":story.get("priority_type",infer_priority_type(story)),
        "source_class":story.get("source_class","reported"),
        "official_video_url":story.get("official_video_url",""),
        "published_at":story.get("published_date",now_iso()),
        "selected_at":now_iso(),
        "status":"published" if published else "selected",
        "event_kind":story.get("event_kind", "news"),
        "message_id":message_id,
    }
    STATE["events"][event_id]=event
    return event_id


# ============================================================
# ============================================================



# ============================================================
# VERSION 1 FALLBACK POOLS
# ============================================================

def build_candidate_pool(ranked,threshold=PUBLISH_THRESHOLD):
    return [dict(item) for item in ranked if int(item.get("importance_score",0))>=threshold and bool(item.get("important"))]


VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "unsupported_claims": {
            "type": "array",
            "items": {"type": "string"},
            
        },
    },
    "required": ["supported", "unsupported_claims"],
    "additionalProperties": False,
}


def claims_grounded(story, article_text):
    """Second-pass editorial verification for non-numeric factual claims."""
    claims = [
        story.get("headline", ""),
        story.get("summary", ""),
        *story.get("highlights", []),
    ]
    claims = [safe_text(x) for x in claims if safe_text(x)]

    prompt = """
You are a strict fact-checking editor. Compare the generated claims with the source article.
Mark supported=true only if every material factual claim in the headline, summary and highlights
is directly supported by the source article, either explicitly or by a faithful paraphrase.
Do not reject normal wording changes. Reject invented facts, unsupported causal claims, wrong dates,
wrong institutions, wrong people, wrong figures, exaggerated rankings, or claims stronger than the source.
Return only the JSON schema.
"""

    user = (
        "SOURCE ARTICLE:\n" + article_text[:12000]
        + "\n\nGENERATED CLAIMS:\n- " + "\n- ".join(claims)
    )

    try:
        response = cerebras_create(
            model=CEREBRAS_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "story_claim_verification",
                    "strict": True,
                    "schema": VERIFY_SCHEMA,
                },
            },
            reasoning_effort="low",
            temperature=0.0,
            max_completion_tokens=500,
        )
        data = json.loads(safe_text(response.choices[0].message.content))
        return bool(data.get("supported")), data.get("unsupported_claims", [])
    except Exception as exc:
        logger.warning("Claim verification failed: %s", exc)
        # Verification is a publication gate. Infrastructure failure is not evidence.
        return False, ["verification infrastructure failure"]


def event_status_verified(story,article_text):
    claims="\n".join([story.get("headline",""),story.get("summary",""),*story.get("highlights",[])])
    status_terms=re.findall(r"\b(?:confirmed|announced|renewed|cancelled|canceled|coming to|premieres|released|in theaters|production started|production wrapped|acquired|acquires|rights)\b[^.?!]{0,120}",claims,re.I)
    if not status_terms:return True,[]
    schema={"type":"object","properties":{"supported":{"type":"boolean"},"unsupported_claims":{"type":"array","items":{"type":"string"}}},"required":["supported","unsupported_claims"],"additionalProperties":False}
    prompt="You are a strict Anime/Manga/Comics status verifier. Check whether status claims in the generated story are directly supported by the source article. Reject upgrades from speculation to confirmation and misstatements of release, renewal, cancellation, production, rights, platform availability or theatrical status. Return only JSON."
    try:
        r=cerebras_create(model=CEREBRAS_MODEL,messages=[{"role":"system","content":prompt},{"role":"user","content":"SOURCE ARTICLE:\n"+article_text[:12000]+"\n\nSTATUS CLAIMS:\n- "+"\n- ".join(status_terms)}],response_format={"type":"json_schema","json_schema":{"name":"comics_anime_status_check","strict":True,"schema":schema}},reasoning_effort="low",temperature=0.0,max_completion_tokens=350)
        d=json.loads(safe_text(r.choices[0].message.content));return bool(d.get("supported")),d.get("unsupported_claims",[])
    except Exception as exc:
        logger.warning("Event-status verification failed: %s",exc);return False,["verification infrastructure failure"]


def official_domains_for_item(item):
    sector=normalize_sector(item.get("sector")) or normalize_sector_from_item(item)
    blob=content_blob(item)
    domains=set()
    if sector=="Comics":
        domains.update(["marvel.com","dc.com","imagecomics.com","darkhorse.com","idwpublishing.com","boom-studios.com","skybound.com","viz.com","kodansha.us","shueisha.co.jp","shonenjump.com","kadokawa.co.jp","shogakukan.com","square-enix.com","akitashoten.co.jp","hakusensha.co.jp"])
    elif sector=="Manga":
        domains.update(["viz.com","kodansha.us","shueisha.co.jp","shonenjump.com","kadokawa.co.jp","shogakukan.com","square-enix.com","akitashoten.co.jp","hakusensha.co.jp","oricon.co.jp","animatetimes.com"])
    else:
        domains.update(["toei-animation.com","mappa.co.jp","aniplex.co.jp","ufotable.com","witstudio.co.jp","bones.co.jp","cloverworks.co.jp","a1p.jp","kyotoanimation.co.jp","crunchyroll.com","oricon.co.jp","animatetimes.com"])
    if re.search(r"\b(?:marvel|x-men|spider-man|avengers)\b",blob,re.I): domains.add("marvel.com")
    if re.search(r"\b(?:dc|batman|superman|wonder woman|justice league)\b",blob,re.I): domains.add("dc.com")
    return sorted(domains)


def deep_research_story(item, article_text=""):
    """Research only strong candidates. Official source first; Exa only for reported stories needing confirmation."""
    title = safe_text(item.get("title"))
    if not title:
        return {"context": "", "official_verified": False, "official_source_url": "", "sources": []}
    domains = official_domains_for_item(item)
    evidence = []
    official_url = ""
    official_verified = False

    # The source article itself is already evidence. Do not spend Exa calls when
    # the candidate is an official publisher/studio/platform post.
    if source_class_for_url(item.get("url")) == "official":
        official_url = safe_text(item.get("url"))
        official_verified = True
        return {
            "context": safe_text(article_text)[:16000],
            "official_verified": True,
            "official_source_url": official_url,
            "sources": [{"url": official_url, "title": title, "highlights": "", "official": True}],
        }

    query = f'"{title}" official announcement trailer release adaptation'
    try:
        results = _exa_search(query, domains=domains, num_results=RESEARCH_MAX_RESULTS, deep=True, date_filtered=False)
        for result in getattr(results, "results", []) or []:
            url = safe_text(getattr(result, "url", ""))
            rtitle = safe_text(getattr(result, "title", ""))
            highlights = _exa_highlights(result)
            if not url or not rtitle:
                continue
            dom = normalized_domain(url)
            is_official = dom in OFFICIAL_SOURCE_DOMAINS
            if is_official and not official_url:
                official_url = url
                official_verified = True
            evidence.append({"url": url, "title": rtitle, "highlights": highlights, "official": is_official})
    except Exception as exc:
        logger.info("Deep research search skipped: %s", exc)

    # One compact specialist cross-check only when official search did not give
    # enough evidence. Avoid the previous 2-search + 4-content-call pattern.
    if len(evidence) < 2:
        try:
            results = _exa_search(
                f'"{title}" anime manga comics latest news',
                domains=PRIMARY_DOMAINS, num_results=RESEARCH_MAX_RESULTS, deep=False, date_filtered=True,
            )
            for result in getattr(results, "results", []) or []:
                url = safe_text(getattr(result, "url", "")); rtitle = safe_text(getattr(result, "title", "")); highlights = _exa_highlights(result)
                if url and rtitle and not any(x["url"] == url for x in evidence):
                    evidence.append({"url": url, "title": rtitle, "highlights": highlights, "official": normalized_domain(url) in OFFICIAL_SOURCE_DOMAINS})
        except Exception as exc:
            logger.info("Deep research broad search skipped: %s", exc)

    texts = []
    for ev in evidence[:DEEP_RESEARCH_MAX_URLS]:
        try:
            contents = _exa_get_contents([ev["url"]], text={"max_characters": 5000})
            results = getattr(contents, "results", []) or []
            text_value = safe_text(getattr(results[0], "text", "")) if results else ""
            if text_value:
                texts.append(f"SOURCE: {ev['title']}\nURL: {ev['url']}\nOFFICIAL: {ev['official']}\n{text_value[:5000]}")
            else:
                texts.append(f"SOURCE: {ev['title']}\nURL: {ev['url']}\nOFFICIAL: {ev['official']}\n{ev['highlights'][:2200]}")
        except Exception:
            texts.append(f"SOURCE: {ev['title']}\nURL: {ev['url']}\nOFFICIAL: {ev['official']}\n{ev['highlights'][:2200]}")

    context_parts = [safe_text(article_text)[:9000]] if article_text else []
    context_parts.extend(texts)
    if official_url:
        item["official_source_url"] = official_url
    return {
        "context": "\n\n".join(x for x in context_parts if x)[:16000],
        "official_verified": official_verified,
        "official_source_url": official_url,
        "sources": evidence[:DEEP_RESEARCH_MAX_URLS],
    }


def mark_candidate_retryable(item, stage, reason, content_failure=False):
    canonical = safe_text(item.get("canonical"))
    if not canonical:
        return
    q = STATE.get("queue", {}).get(canonical)
    if q is None:
        return
    field = "content_retry_count" if content_failure else "ai_retry_count"
    attempts = int(q.get(field, 0)) + 1
    q[field] = attempts
    max_attempts = MAX_CONTENT_RETRY_ATTEMPTS if content_failure else 999999
    if attempts >= max_attempts:
        q["status"] = "rejected"
        q["rejected_at"] = now_iso()
        q["failure_stage"] = stage
        q["failure_reason"] = safe_text(reason)[:500]
        q["retry_exhausted"] = True
        logger.warning("Candidate permanently rejected after retries | stage=%s | title=%s", stage, item.get("title", ""))
        return
    q["status"] = "retryable"
    q["failure_stage"] = stage
    q["failure_reason"] = safe_text(reason)[:500]
    delay_hours = CONTENT_FAILURE_RETRY_HOURS if content_failure else AI_FAILURE_RETRY_HOURS
    q["retry_at"] = (datetime.now(BD_TZ) + timedelta(hours=delay_hours)).isoformat()
    q["retry_exhausted"] = False
    logger.info("Candidate queued for retry | stage=%s attempt=%d | retry_at=%s | title=%s", stage, attempts, q["retry_at"], item.get("title", ""))

def mark_candidate_selected(item):
    canonical = safe_text(item.get("canonical"))
    q = STATE.get("queue", {}).get(canonical)
    if q:
        q["status"] = "selected"
        q["selected_at"] = now_iso()
        q.pop("retry_at", None)
        q.pop("failure_reason", None)
        q.pop("failure_stage", None)

def process_story_candidate(item):
    """Serial deep research + generation + local grounding for one strong event."""
    item["_failure_kind"] = ""
    supplied_video_candidates = list(item.get("video_candidates", []) or [])
    supplied_image_candidates = list(item.get("image_candidates", []) or [])
    supplied_image = safe_text(item.get("image"))
    article_text, image_url = extract_article(item)
    if not article_text:
        item["_failure_kind"] = "extraction"
        logger.warning("DROP extraction: %s", item.get("title"))
        return None

    item["video_candidates"] = list(dict.fromkeys(supplied_video_candidates + list(item.get("video_candidates", []) or [])))[:12]
    item["image_candidates"] = list(dict.fromkeys(supplied_image_candidates + list(item.get("image_candidates", []) or [])))[:20]

    source_is_official = source_class_for_url(item.get("url")) == "official"
    research = deep_research_story(item, article_text) if not source_is_official else {
        "context": article_text[:12000],
        "official_verified": True,
        "official_source_url": item.get("url", ""),
        "sources": [{"url": item.get("url", ""), "title": item.get("title", ""), "highlights": "", "official": True}],
    }

    supplied_video_candidates = list(item.get("video_candidates", []) or [])
    supplied_image_candidates = list(item.get("image_candidates", []) or [])
    item["video_candidates"] = list(dict.fromkeys(supplied_video_candidates + list(item.get("video_candidates", []) or [])))[:12]
    item["image_candidates"] = list(dict.fromkeys(supplied_image_candidates + list(item.get("image_candidates", []) or [])))[:20]

    try:
        story = generate_story(item, article_text, research.get("context", ""))
    except CerebrasRateLimitError:
        item["_failure_kind"] = "ai_rate_limit"
        raise
    except CerebrasBudgetError:
        item["_failure_kind"] = "ai_budget"
        raise
    if not story:
        item["_failure_kind"] = "generation"
        logger.warning("DROP generation: %s", item.get("title"))
        return None

    region = item.get("region", REGION)
    story["topic"] = canonical_topic(story.get("news_type") or item.get("topic"), region)
    story["image_url"] = image_url or supplied_image or item.get("image")
    story["official_source_url"] = research.get("official_source_url", "")
    story["research_official_verified"] = bool(research.get("official_verified"))
    story["research_sources"] = research.get("sources", [])
    story["reader_context"] = trim_source_text(article_text, 6000)

    grounding_text = article_text + "\n\nRESEARCH EVIDENCE:\n" + safe_text(research.get("context", ""))
    grounded, bad_number = numeric_grounded(story, grounding_text)
    if not grounded:
        item["_failure_kind"] = "numeric_grounding"
        logger.warning("DROP numeric grounding: %s (%s)", story.get("headline"), bad_number)
        return None

    story["institution"] = item.get("institution", "")
    story["event_key"] = item.get("event_key", "")
    story["event_cluster_id"] = item.get("event_cluster_id", "")
    story["event_confidence"] = item.get("event_confidence", 0)
    story["event_source_count"] = item.get("event_source_count", 0)
    story["official_video_url"] = safe_text(story.get("official_video_url")) if story.get("official_video_url") else ""
    story["official_video_platform"] = safe_text(story.get("official_video_platform")) if story.get("official_video_url") else ""
    story["official_video_title"] = safe_text(story.get("official_video_title")) if story.get("official_video_url") else ""

    if story.get("priority_type") == "Major Trailer / PV" or re.search(r"\b(?:trailer|teaser|pv|promo video|first look|new footage)\b", f"{item.get('title','')} {item.get('excerpt','')}", re.I) or re.search(r"(?:PV|予告|特報|メインPV|trailer|teaser)", f"{item.get('title','')} {item.get('excerpt','')}", re.I):
        for candidate_url in item.get("video_candidates", [])[:8]:
            ok, platform, video_title = verify_video_url(candidate_url, story.get("title", ""))
            if ok and video_title_relevant(video_title or story.get("title", ""), story.get("title", "")):
                story["official_video_url"] = candidate_url
                story["official_video_platform"] = platform
                story["official_video_title"] = video_title or story.get("title", "")
                break
        if not story.get("official_video_url"):
            found = exa_video_search(story.get("title", ""))
            if found:
                story["official_video_url"] = found["url"]
                story["official_video_platform"] = found["platform"]
                story["official_video_title"] = found["title"]
        if story.get("official_video_url") and not story.get("image_url"):
            thumb = youtube_thumbnail(story.get("official_video_url"))
            if thumb:
                story["image_url"] = thumb
    story["category_hashtags"] = category_hashtags(story)
    story["_source_article_text"] = article_text
    return story


VERIFY_BATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "supported": {"type": "boolean"},
                    "unsupported_claims": {
                        "type": "array",
                        "items": {"type": "string"},
                        
                    },
                },
                "required": ["id", "supported", "unsupported_claims"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


def verify_stories_batch(stories):
    """Verify stories in one compact batch. On infrastructure failure, salvage independently official stories."""
    if not stories: return []
    records=[]
    for idx,story in enumerate(stories,1):
        claims=[story.get("headline",""),story.get("summary",""),*story.get("highlights",[])]
        records.append(f"ID: {idx}\nTITLE: {story.get('headline','')}\nCLAIMS:\n- " + "\n- ".join(safe_text(x) for x in claims if safe_text(x)) + f"\nSOURCE ARTICLE:\n{trim_source_text(story.get('_source_article_text',''),5500)}")
    prompt="""You are the final fact-checking editor for @ComicsNewsroom. For each ID, mark supported=true only when the headline, summary and highlights are directly supported by the supplied evidence. Reject invented facts, wrong dates/names/studios/platforms, stronger status wording than the evidence, and rumor-to-confirmed upgrades. Return every ID exactly once."""
    try:
        response=cerebras_create(model=CEREBRAS_MODEL,messages=[{"role":"system","content":prompt},{"role":"user","content":"\n\n".join(records)}],response_format={"type":"json_schema","json_schema":{"name":"comics_story_batch_verification_v3","strict":True,"schema":VERIFY_BATCH_SCHEMA}},reasoning_effort="low",temperature=0.0,max_completion_tokens=VERIFY_MAX_COMPLETION_TOKENS)
        data=json.loads(safe_text(response.choices[0].message.content)); by_id={int(r.get("id",0)):r for r in data.get("results",[])}
        verified=[]
        for idx,story in enumerate(stories,1):
            result=by_id.get(idx)
            if result and bool(result.get("supported")):
                story["verification_status"]="ai_verified"; verified.append(story)
            else:
                logger.warning("DROP claim verification: %s | %s",story.get("headline",story.get("title","")),(result or {}).get("unsupported_claims",["unsupported or missing verification"]))
        return verified
    except Exception as exc:
        logger.warning("Batch verification unavailable; salvaging independently supported stories: %s",exc)
        salvaged=[]
        for story in stories:
            if story.get("research_official_verified") or source_class_for_url(story.get("url"))=="official":
                story["verification_status"]="official_fallback"; salvaged.append(story)
            else:
                logger.warning("DROP verification unavailable: %s",story.get("headline",story.get("title","")))
        return salvaged


def update_category_coverage(story):
    metrics = STATE.setdefault("category_coverage", {})
    sector = safe_text(story.get("sector")) or "Other"
    topic = safe_text(story.get("priority_type")) or safe_text(story.get("topic")) or "Other"
    metrics[sector] = int(metrics.get(sector, 0)) + 1
    topics = STATE.setdefault("topic_coverage", {})
    topics[topic] = int(topics.get(topic, 0)) + 1


# ============================================================
# MAIN
# ============================================================

def is_already_published_candidate(item):
    canonical = safe_text(item.get("canonical"))
    if canonical and canonical in POSTED_URLS:
        return True

    title = safe_text(item.get("title"))
    if not title:
        return False

    for event in STATE.get("events", {}).values():
        if event.get("status") != "published":
            continue
        if event.get("region") != item.get("region"):
            continue
        published_at = parse_datetime(event.get("published_at"))
        if not published_at or (NOW_BD - published_at).total_seconds() > EVENT_RETENTION_DAYS * 86400:
            continue
        previous_title = safe_text(event.get("headline"))
        if previous_title and title_similarity(title, previous_title) >= 0.90:
            return True
    return False


def available_candidates(region, source_pool=None):
    candidates = []
    seen = set()

    for item in STATE.get("queue", {}).values():
        if item.get("region") != region:
            continue
        status = item.get("status")
        if status not in {"pending", "selected", "retryable"}:
            continue
        if status == "retryable":
            retry_at = parse_datetime(item.get("retry_at"))
            if retry_at and retry_at > NOW_BD:
                continue

        published = parse_datetime(item.get("published_date"))
        if not published or not (DISCOVERY_START <= published <= DISCOVERY_END or meaningful_update_candidate(item)):
            continue

        url = safe_text(item.get("url"))
        canonical = safe_text(item.get("canonical"))
        if not canonical or canonical in seen:
            continue

        if source_pool == "primary" and not primary_domain_allowed(url, region):
            continue
        if source_pool == "fallback" and not fallback_domain_allowed(url, region):
            continue
        if source_pool is None and not allowed_source_for_region(url, region):
            continue

        allowed, reason = pre_cerebras_filter(item)
        if not allowed:
            logger.info("PRE-CEREBRAS DROP (queue): %s | %s", reason, item.get("title", ""))
            continue
        if is_already_published_candidate(item):
            continue
        if title_duplicate_against_list(item.get("title", ""), candidates, threshold=0.94):
            continue
        if title_duplicate_against_state(item.get("title", "")):
            continue

        candidates.append(dict(item))
        seen.add(canonical)

    candidates.sort(
        key=lambda x: parse_datetime(x.get("published_date"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return candidates[:MAX_RSS_CANDIDATES]


def prepare_ranked_region(region, candidates):
    ranked = rank_candidates(candidates, region)
    ranked = collapse_event_clusters(ranked)
    ranked = [item for item in ranked if item.get("importance_score", 0) >= PUBLISH_THRESHOLD and item.get("important") is True]
    persist_event_cluster_state(ranked)
    return ranked



def published_sector_counts_24h():
    counts = {sector: 0 for sector in SECTORS}
    cutoff = NOW_BD - timedelta(hours=SECTOR_BALANCE_LOOKBACK_HOURS)
    for event in STATE.get("events", {}).values():
        if event.get("status") != "published":
            continue
        if event.get("event_kind") == "reader_extra":
            continue
        dt = parse_datetime(event.get("published_at"))
        if not dt or dt < cutoff:
            continue
        sector = normalize_sector(event.get("sector"))
        counts[sector] = counts.get(sector, 0) + 1
    return counts


def balanced_news_selection(ranked,limit=NEWS_POST_MAX_PER_RUN):
    """Quality-first selection. Sector diversity is only a tie-breaker, never a hard quota."""
    eligible=[dict(item) for item in ranked if int(item.get("importance_score",0))>=PUBLISH_THRESHOLD and bool(item.get("important")) and normalize_sector(item.get("sector")) in SECTORS]
    if not eligible: return []
    counts=published_sector_counts_24h()
    selected=[]; remaining=list(eligible); used=set()
    while remaining and len(selected)<limit:
        max_score=max(int(x.get("importance_score",0)) for x in remaining)
        band=[x for x in remaining if int(x.get("importance_score",0))>=max_score-2]
        def key(x):
            sec=normalize_sector(x.get("sector")); deficit=max(counts.values(),default=0)-counts.get(sec,0)
            diversity_boost=min(2.0,max(0.0,float(deficit)/2.0))
            return (int(x.get("importance_score",0))+diversity_boost,-int(x.get("editor_rank",9999)))
        winner=max(band,key=key)
        selected.append(winner); used.add(winner.get("canonical")); remaining=[x for x in remaining if x.get("canonical") not in used]
    selected.sort(key=lambda x:(-int(x.get("importance_score",0)),int(x.get("editor_rank",9999))))
    return selected


def reader_extra_type():
    history = STATE.get("reader_extra_type_history", [])[-8:]
    counts = {kind: history.count(kind) for kind in READER_EXTRA_TYPES}
    lowest = min(counts.values(), default=0)
    candidates = [kind for kind in READER_EXTRA_TYPES if counts[kind] == lowest]
    # Stable rotation among equally unused types.
    cursor = len(STATE.get("reader_extra_type_history", [])) % max(1, len(candidates))
    return candidates[cursor]


def reader_extra_recent_global():
    cutoff=NOW_BD-timedelta(hours=READER_EXTRA_MIN_INTERVAL_HOURS)
    for item in reversed(STATE.get("reader_extra_history",[])):
        dt=parse_datetime(item.get("published_at"))
        if dt and dt>=cutoff:
            return True
    return False


def reader_extra_work_recent(work_key):
    work_key = normalize_title(work_key)
    if not work_key:
        return False
    cutoff = NOW_BD - timedelta(days=READER_EXTRA_AVOID_WORK_DAYS)
    for item in STATE.get("reader_extra_history", []):
        dt = parse_datetime(item.get("published_at"))
        if dt and dt >= cutoff and normalize_title(item.get("work")) == work_key:
            return True
    return False


READER_EXTRA_SCHEMA = {
    "type": "object",
    "properties": {
        "extra_type": {"type": "string", "enum": READER_EXTRA_TYPES},
        "title": {"type": "string"},
        "work": {"type": "string"},
        "sector": {"type": "string", "enum": SECTORS},
        "intro": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
        "takeaway": {"type": "string"},
        "source_url": {"type": "string"},
        "source_name": {"type": "string"},
        "bold_terms": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["extra_type", "title", "work", "sector", "intro", "points", "takeaway", "source_url", "source_name", "bold_terms"],
    "additionalProperties": False,
}


def generate_reader_extra(seed_story):
    """Create one source-grounded reader-value post from a verified/current newsroom story."""
    if not seed_story:
        return None
    work = safe_text(seed_story.get("title") or seed_story.get("headline"))
    if not work or reader_extra_work_recent(work):
        return None
    extra_kind = reader_extra_type()
    article_text = safe_text(seed_story.get("_source_article_text")) or safe_text(seed_story.get("reader_context"))
    if not article_text:
        article_text = "\n".join([
            safe_text(seed_story.get("summary")),
            *[safe_text(x) for x in seed_story.get("highlights", [])],
            safe_text(seed_story.get("why_it_matters")),
        ])
    if len(article_text.strip()) < 150:
        return None

    prompt = f"""You are the reader-value editor for @ComicsNewsroom. Create ONE compact non-news FAN EXTRA based only on the supplied evidence.
This is not another news report. It should give the reader something interesting they can enjoy or learn in under 15 seconds.
Chosen format: {extra_kind}
Allowed formats: {', '.join(READER_EXTRA_TYPES)}.
Rules:
- Use only facts directly supported by the evidence. Do not rely on unstated memory.
- Do not invent trivia, dates, sales, creator biography, chronology or behind-the-scenes details.
- The title should be curiosity-driven but factual and not clickbait.
- intro: one concise setup sentence.
- points: 2-4 genuinely interesting facts or context points.
- takeaway: one concise reader-friendly closing thought.
- source_url must be copied EXACTLY from the supplied source URL. Do not invent URLs.
- source_name must be copied from the supplied source name.
- sector must be Anime, Manga or Comics. Marvel/DC stories use Comics.
- No Markdown or HTML.
Return only the JSON schema."""
    user = (
        f"WORK: {work}\n"
        f"SECTOR: {normalize_sector(seed_story.get('sector'))}\n"
        f"SOURCE NAME: {safe_text(seed_story.get('source'))}\n"
        f"SOURCE URL: {safe_text(seed_story.get('url'))}\n"
        f"RECENT STORY: {safe_text(seed_story.get('headline') or seed_story.get('title'))}\n"
        f"EVIDENCE:\n{article_text[:11000]}"
    )
    try:
        response = cerebras_create(
            model=CEREBRAS_MODEL,
            messages=[{"role": "system", "content": prompt}, {"role": "user", "content": user}],
            response_format={"type": "json_schema", "json_schema": {"name": "comics_reader_extra_v1", "strict": True, "schema": READER_EXTRA_SCHEMA}},
            reasoning_effort="low",
            temperature=0.25,
            max_completion_tokens=READER_EXTRA_MAX_COMPLETION_TOKENS,
        )
        data = json.loads(safe_text(response.choices[0].message.content))
        source_url = safe_text(data.get("source_url"))
        if source_url != safe_text(seed_story.get("url")):
            source_url = safe_text(seed_story.get("url"))
        points = [trim_source_text(clean_generated_text(x), 170) for x in data.get("points", []) if clean_generated_text(x)]
        extra = {
            "event_kind": "reader_extra",
            "extra_type": safe_text(data.get("extra_type")) if safe_text(data.get("extra_type")) in READER_EXTRA_TYPES else extra_kind,
            "title": trim_source_text(clean_generated_text(data.get("title")), 110),
            "work": trim_source_text(clean_generated_text(data.get("work")) or work, 110),
            "sector": normalize_sector(data.get("sector")),
            "intro": trim_source_text(clean_generated_text(data.get("intro")), 250),
            "points": points[:4],
            "takeaway": trim_source_text(clean_generated_text(data.get("takeaway")), 220),
            "source_url": source_url,
            "source_name": trim_source_text(clean_generated_text(data.get("source_name")) or seed_story.get("source"), 90),
            "bold_terms": [safe_text(x) for x in data.get("bold_terms", []) if safe_text(x)][:8],
            "image_url": safe_text(seed_story.get("image_url")),
            "url": source_url,
            "canonical": canonical_url(source_url) or safe_text(seed_story.get("canonical")),
            "importance_score": int(seed_story.get("importance_score", 0) or 0),
        }
        if not extra["title"] or not extra["intro"] or len(extra["points"]) < 2 or not extra["source_url"]:
            return None
        return extra
    except Exception as exc:
        logger.warning("Reader extra generation failed: %s", exc)
        return None


def dynamic_reader_extra_html(extra):
    kind = escape_rich_html(extra.get("extra_type") or "FAN EXTRA")
    work = escape_rich_html(extra.get("work") or "")
    title = escape_rich_html(extra.get("title") or "")
    terms = extra.get("bold_terms", [])
    lines = [add_media_reference(), f"<p><b>💎 FAN EXTRA · {kind}</b></p>", f"<h1><b>✦ {title}</b></h1>"]
    if work:
        lines.append(f"<p><b>{work}</b></p>")
    intro = bold_terms_html(extra.get("intro", ""), terms)
    if intro:
        lines.append(f"<blockquote>✨ {intro}</blockquote>")
    for point in extra.get("points", [])[:4]:
        lines.append(f"<p>✦ {bold_terms_html(point, terms)}</p>")
    takeaway = bold_terms_html(extra.get("takeaway", ""), terms)
    if takeaway:
        lines.append(f"<p>💡 <b>Takeaway:</b> {takeaway}</p>")
    footer = " ".join([CHANNEL_TAG, "#Fans", "#AnimeNews" if normalize_sector(extra.get("sector")) == "Anime" else ("#Manga" if normalize_sector(extra.get("sector")) == "Manga" else "#Comics")])
    lines.append(f"<p>{escape_rich_html(footer)}</p>")
    source = escape_rich_html(extra.get("source_name") or "Source")
    url = html.escape(safe_text(extra.get("source_url")), quote=True)
    if url:
        lines.append(f"<footer><b>Source:</b> <a href=\"{url}\">{source}</a></footer>")
    else:
        lines.append(f"<footer><b>Source:</b> {source}</footer>")
    return "\n".join(lines)


def fit_reader_extra_html(extra):
    variants = [
        dict(extra),
        dict(extra, takeaway="", intro=trim_source_text(extra.get("intro", ""), 190), points=[trim_source_text(x, 130) for x in extra.get("points", [])[:3]]),
        dict(extra, takeaway="", intro=trim_source_text(extra.get("intro", ""), 160), points=[trim_source_text(x, 100) for x in extra.get("points", [])[:2]]),
    ]
    for candidate in variants:
        rendered = dynamic_reader_extra_html(candidate)
        if rich_visible_length(rendered) <= MAX_RICH_CHARACTERS:
            return rendered
    raise ValueError("Unable to fit reader extra Rich Message")


def store_reader_extra(extra, message_id=None):
    now = now_iso()
    record = {
        "id": hashlib.sha1(f"{extra.get('work')}|{extra.get('title')}|{now}".encode("utf-8")).hexdigest()[:16],
        "event_kind": "reader_extra",
        "extra_type": extra.get("extra_type", ""),
        "title": extra.get("title", ""),
        "work": extra.get("work", ""),
        "sector": normalize_sector(extra.get("sector")),
        "source": extra.get("source_name", ""),
        "source_url": extra.get("source_url", ""),
        "published_at": now,
        "message_id": message_id,
        "status": "published",
    }
    STATE.setdefault("reader_extra_history", []).append(record)
    STATE["reader_extra_history"] = STATE["reader_extra_history"][-READER_EXTRA_HISTORY_LIMIT:]
    STATE.setdefault("reader_extra_type_history", []).append(extra.get("extra_type", ""))
    STATE["reader_extra_type_history"] = STATE["reader_extra_type_history"][-12:]
    STATE.setdefault("reader_extra_work_history", []).append(extra.get("work", ""))
    STATE["reader_extra_work_history"] = STATE["reader_extra_work_history"][-30:]


def choose_reader_extra_seed(stories, ranked):
    candidates = []
    for story in stories:
        if int(story.get("importance_score", 0) or 0) >= PUBLISH_THRESHOLD:
            candidates.append(story)
    if not candidates:
        for item in ranked:
            if int(item.get("importance_score", 0) or 0) >= PUBLISH_THRESHOLD:
                candidates.append(item)
    candidates = [x for x in candidates if not reader_extra_work_recent(x.get("title") or x.get("headline"))]
    if not candidates:
        # Fall back to a previously published event with enough stored context.
        old = []
        for event in reversed(list(STATE.get("events", {}).values())):
            if event.get("status") != "published" or event.get("event_kind") == "reader_extra":
                continue
            work = safe_text(event.get("headline"))
            if work and not reader_extra_work_recent(work):
                old.append(event)
        if old:
            event = old[0]
            return {
                "title": event.get("headline", ""),
                "headline": event.get("headline", ""),
                "sector": normalize_sector(event.get("sector")),
                "summary": event.get("summary", ""),
                "highlights": event.get("highlights", []),
                "why_it_matters": event.get("why_it_matters", ""),
                "source": event.get("source", ""),
                "url": event.get("original_url", ""),
                "image_url": "",
                "importance_score": 82,
                "canonical": event.get("canonical_url", ""),
            }
    return candidates[0] if candidates else None

def process_ranked_region(region, ranked):
    """Process a bounded candidate set serially, isolating every candidate failure."""
    candidates = [dict(x) for x in ranked if int(x.get("importance_score", 0)) >= PUBLISH_THRESHOLD and bool(x.get("important"))]
    candidates = candidates[:NEWS_RESEARCH_TARGET]
    if not candidates:
        logger.info("DEEP RESEARCH: no candidates above editorial gate")
        return []

    logger.info("DEEP RESEARCH: processing %d strong candidates | SERIAL", len(candidates))
    stories = []
    for position, item in enumerate(candidates, 1):
        canonical = safe_text(item.get("canonical"))
        q = STATE.get("queue", {}).get(canonical)
        if q:
            q["status"] = "processing"
            q["processing_at"] = now_iso()
            q["processing_rank"] = position
        save_state(STATE)
        try:
            story = process_story_candidate(item)
            if story:
                mark_candidate_selected(item)
                stories.append(story)
            else:
                failure = item.get("_failure_kind") or "story_pipeline"
                content_failure = failure in {"numeric_grounding", "generation", "extraction"}
                mark_candidate_retryable(item, failure, f"{failure} failed", content_failure=content_failure)
        except CerebrasRateLimitError as exc:
            mark_candidate_retryable(item, "ai_rate_limit", str(exc), content_failure=False)
            logger.warning("Stopping story generation for this run after Cerebras rate limit; successful stories remain publishable.")
            save_state(STATE)
            break
        except CerebrasBudgetError as exc:
            mark_candidate_retryable(item, "ai_budget", str(exc), content_failure=False)
            logger.warning("Stopping story generation for this run after Cerebras budget exhaustion.")
            save_state(STATE)
            break
        except Exception as exc:
            mark_candidate_retryable(item, "candidate_pipeline", str(exc), content_failure=False)
            logger.warning("Candidate isolated failure: %s | %s", item.get("title", ""), exc)
        save_state(STATE)

    stories.sort(key=lambda x: (-int(x.get("importance_score", 0)), int(x.get("editor_rank", 9999))))
    if _cerebras_rate_limited:
        verified = []
        for story in stories:
            if story.get("research_official_verified") or source_class_for_url(story.get("url")) == "official":
                story["verification_status"] = "official_fallback"
                verified.append(story)
        logger.warning("AI verification skipped after hard Cerebras rate limit; kept %d independently official stories", len(verified))
    else:
        verified = verify_stories_batch(stories)
    verified_ids = {safe_text(x.get("canonical")) for x in verified}
    for story in stories:
        if safe_text(story.get("canonical")) not in verified_ids:
            mark_candidate_retryable(story, "claim_verification", "AI/source verification rejected story", content_failure=True)
    for story in verified:
        story["sector"] = normalize_sector(story.get("sector")) or normalize_sector_from_item(story)
        story["topic"] = canonical_topic(story.get("topic") or story.get("news_type") or "", region)
        story["category_hashtags"] = category_hashtags(story)
    final = balanced_news_selection(verified, limit=NEWS_POST_MAX_PER_RUN)
    logger.info("FINAL VALID: %d | researched=%d generated=%d verified=%d target=%d-%d", len(final), len(candidates), len(stories), len(verified), NEWS_POST_TARGET_MIN, NEWS_POST_MAX_PER_RUN)
    return final



def publication_duplicate_reason(story, reserved):
    candidate = dict(story)
    candidate["title"] = story.get("headline") or story.get("title", "")
    hit, reason = event_memory_hit(candidate)
    if hit:
        return reason
    for previous in reserved:
        if _publication_event_match(candidate, previous):
            return f"same_run_duplicate:{previous.get('headline','')}"
    return ""


def run():
    logger.info("COMICSNEWSROOM V4.0 PRODUCTION RUN")
    logger.info("Channel=%s Mode=%s Threshold=%d/100",TELEGRAM_CHANNEL,NEWS_MODE,PUBLISH_THRESHOLD)
    logger.info("24H WINDOW | %s -> %s",DISCOVERY_START.isoformat(),DISCOVERY_END.isoformat())

    prune_state()
    bootstrap_learning_from_queue()
    collect_rss()

    count=queue_candidates_for_region(REGION)
    google_added=google_news_gap_fill(REGION,count,MAX_GOOGLE_NEWS_CANDIDATES)
    exa_added=exa_gap_fill(REGION,count+google_added,MAX_EXA_CANDIDATES)
    logger.info("DISCOVERY GAP FILL: google_added=%d exa_added=%d",google_added,exa_added)
    save_state(STATE)

    candidates=available_candidates(REGION,source_pool="primary")
    metrics=STATE.setdefault("adaptive_metrics",{})
    metrics["raw_discovered"]=len(STATE.get("queue",{}))
    logger.info("PRE-CEREBRAS: rejected=%d hard=%d duplicate=%d learned=%d passed=%d",int(metrics.get("pre_cerebras_rejected",0)),int(metrics.get("hard_rejected",0)),int(metrics.get("duplicate_rejected",0)),int(metrics.get("learned_rejected",0)),int(metrics.get("passed_to_cerebras",0)))
    logger.info("CANDIDATES AFTER FILTER: %d | RANK CAP=%d | AI LOGICAL BUDGET=%d | AI RPM=%d | STORY MODE=SERIAL",len(candidates),MAX_RANK_CANDIDATES,CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN,CEREBRAS_REQUESTS_PER_MINUTE)

    ranked=prepare_ranked_region(REGION,candidates)
    logger.info("RANKED ABOVE GATE: %d",len(ranked))
    stories=process_ranked_region(REGION,ranked)

    # Dynamic quality-first publication. No daily or per-run quota.
    reserved_this_run=[]
    published_count=0
    for index,story in enumerate(stories,1):
        try:
            duplicate_reason=publication_duplicate_reason(story,reserved_this_run)
            if duplicate_reason:
                logger.info("FINAL PUBLISH DROP: %s | %s",duplicate_reason,story.get("headline",""))
                continue
            rich_html=fit_rich_html(story)
            image_path=prepare_image(story,index)
            result=send_rich_photo(image_path,rich_html)
            if not result.get("ok"):
                if result.get("ambiguous") or result.get("transport_error"):
                    raise RuntimeError("Ambiguous Telegram transport failure; publish not retried")
                description=safe_text(result.get("description")).lower(); status=int(result.get("http_status",0) or 0)
                can_fallback=status in {400,404,405} and ("rich" in description or "method" in description or "not found" in description)
                if can_fallback:
                    logger.warning("Rich Message unavailable; trying Bot API photo fallback")
                    result=send_bot_api_fallback(image_path,rich_html)
                else:
                    raise RuntimeError(result.get("description") or "Telegram Rich Message publish failed")
            if not result.get("ok"):
                raise RuntimeError(result.get("description") or "Telegram publish failed")
            message=result.get("result",{})
            message_id=message.get("message_id") if isinstance(message,dict) else None
            canonical=story.get("canonical","")
            if canonical:
                POSTED_URLS.add(canonical); save_posted_url(canonical)
                qi=STATE.get("queue",{}).get(canonical)
                if qi: qi["status"]="posted"; qi["posted_at"]=now_iso()
            store_event(story,published=True,message_id=message_id)
            remember_posted_event(story)
            update_category_coverage(story)
            STATE.setdefault("recent_titles",[]).append(normalize_title(story.get("headline",story.get("title",""))))
            reserved_this_run.append(dict(story)); published_count+=1
            logger.info("Published #%d score=%s sector=%s type=%s: %s",published_count,story.get("importance_score",0),story.get("sector"),story.get("news_type"),story.get("headline"))
        except Exception as exc:
            logger.error("Telegram publication failed for %s: %s",story.get("headline"),exc)
        save_state(STATE)
        time.sleep(POST_DELAY_SECONDS)

    # One compact reader-value post per run, separate from the three-sector news quota.
    extra_published = 0
    if READER_EXTRA_ENABLED and READER_EXTRA_MAX_PER_RUN and not _cerebras_rate_limited and not reader_extra_recent_global():
        seed = choose_reader_extra_seed(stories, ranked)
        if seed and not reader_extra_work_recent(seed.get("title") or seed.get("headline")):
            # Current-run stories retain their source article text until this point.
            extra = generate_reader_extra(seed)
            if extra:
                try:
                    extra_html = fit_reader_extra_html(extra)
                    image_path = prepare_image(seed, "fan_extra")
                    result = send_rich_photo(image_path, extra_html)
                    if not result.get("ok"):
                        description = safe_text(result.get("description")).lower()
                        status = int(result.get("http_status", 0) or 0)
                        can_fallback = status in {400, 404, 405} and ("rich" in description or "method" in description or "not found" in description)
                        if can_fallback:
                            result = send_bot_api_fallback(image_path, extra_html)
                        else:
                            raise RuntimeError(result.get("description") or "Reader extra publish failed")
                    if result.get("ok"):
                        message = result.get("result", {})
                        message_id = message.get("message_id") if isinstance(message, dict) else None
                        store_reader_extra(extra, message_id=message_id)
                        store_event(extra, published=True, message_id=message_id)
                        metrics["reader_extra_published"] = int(metrics.get("reader_extra_published", 0)) + 1
                        extra_published = 1
                        logger.info("Published FAN EXTRA: type=%s sector=%s work=%s", extra.get("extra_type"), extra.get("sector"), extra.get("work"))
                except Exception as exc:
                    logger.warning("FAN EXTRA skipped: %s", exc)
    metrics["published"]=int(metrics.get("published",0))+published_count
    metrics["estimated_candidates_avoided"]=int(metrics.get("pre_cerebras_rejected",0))
    save_state(STATE)
    logger.info("FINISHED | news_published=%d | fan_extra=%d | candidates=%d",published_count,extra_published,len(candidates))


# ============================================================
# SELF TEST
# ============================================================

def self_test():
    """Fast invariant tests; never depends on the repository's persisted state."""
    sample = {
        "title":"Example Anime", "year":"2026", "summary":"The anime's new season has been officially confirmed.",
        "sector":"Anime", "format":"Anime", "news_type":"Trailer", "priority_type":"Major Trailer / PV",
        "highlights":["The next season has been officially confirmed.","More production details are expected later."],
        "why_it_matters":"It confirms the franchise will continue.", "platform":"Crunchyroll", "episodes":"12", "chapters":"", "languages":"Japanese, English", "status":"Coming Soon", "release_date":"2026",
        "official_video_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ", "official_video_platform":"YouTube", "official_video_title":"Example Anime Official Trailer", "spoiler":"", "note":"", "bold_terms":["Example Anime","Crunchyroll"],
        "source":"Anime News Network", "url":"https://www.animenewsnetwork.com/example/story", "region":REGION, "topic":"Major Trailer / PV", "institution":"", "importance_score":90, "important":True, "event_key":"example_anime_season_2", "source_class":"reported", "image_url":"", "image_candidates":[], "canonical":"animenewsnetwork.com/example/story"
    }
    rendered = dynamic_rich_html(sample)
    assert "@ComicsNewsroom" in rendered and "Watch Trailer 👉" in rendered and "<h2>" in rendered
    assert set(SECTORS) == {"Anime", "Manga", "Comics"}
    assert normalize_sector("DC") == "Comics" and normalize_sector("Marvel") == "Comics"
    assert normalize_sector("unknown") == ""
    assert rank_score({"score":100}) == 100 and rank_score({"score":140}) == 100 and rank_score({"score":-4}) == 0
    assert canonical_topic("trailer") == "Major Trailer / PV"
    assert canonical_topic("manga to anime") == "Manga → Anime Adaptation"
    # Isolated state for filtering tests.
    saved_state = globals().get("STATE")
    saved_posted = globals().get("POSTED_URLS")
    globals()["STATE"] = default_state(); globals()["POSTED_URLS"] = set()
    fresh = NOW_BD - timedelta(hours=2); stale = NOW_BD - timedelta(hours=25)
    assert candidate_basic_allowed({"url":"https://animecorner.me/fresh","title":"Major anime announcement","published_dt":fresh,"region":REGION}) is True
    assert candidate_basic_allowed({"url":"https://animecorner.me/stale","title":"Major anime announcement","published_dt":stale,"region":REGION}) is False
    jp = {"url":"https://oricon.co.jp/news/example","title":"『魔法騎士レイアース』メインPV第2弾公開","excerpt":"アニメ新作の制作決定と第2弾PV公開", "published_dt":fresh, "region":REGION}
    assert candidate_basic_allowed(jp) is True
    gaming = {"url":"https://animenewsnetwork.com/news/persona","title":"Persona 4 gets a new game update","excerpt":"video game gameplay update", "published_dt":fresh, "region":REGION}
    assert candidate_basic_allowed(gaming) is False
    generic_dc = {"url":"https://dc.com/news/example","title":"News | DC","excerpt":"", "published_dt":fresh, "region":REGION}
    assert candidate_basic_allowed(generic_dc) is False
    # Numeric grounding accepts “Season 2” vs “second season”.
    ok, _ = numeric_grounded({"headline":"Example Season 2", "summary":"The second season is confirmed.", "highlights":[]}, "The second season is officially confirmed.")
    assert ok is True
    # Retryable state does not become seen forever.
    c = {"canonical":"example.com/a","title":"Example","region":REGION}
    globals()["STATE"]["queue"][c["canonical"]] = {**c,"status":"pending"}
    mark_candidate_retryable(c,"ai_rate_limit","429")
    assert globals()["STATE"]["queue"][c["canonical"]]["status"] == "retryable"
    globals()["STATE"]["queue"][c["canonical"]]["retry_at"] = (NOW_BD-timedelta(minutes=1)).isoformat()
    globals()["STATE"]["queue"][c["canonical"]]["status"] = "retryable"
    assert len(available_candidates(REGION) if False else [x for x in globals()["STATE"]["queue"].values() if x.get("status") == "retryable"]) == 1
    globals()["STATE"] = saved_state; globals()["POSTED_URLS"] = saved_posted
    assert DISCOVERY_END == NOW_BD
    assert STORY_CONCURRENCY == 1
    assert CEREBRAS_REQUESTS_PER_MINUTE >= 1 and CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN >= 10
    assert NEWS_POST_TARGET_MIN == 7 and NEWS_POST_MAX_PER_RUN == 10
    logger.info("SELF-TEST: PASS | serialized AI, multilingual filter, retryable state, numeric grounding")


def rate_limit_test():
    """Simulate a production-like burst and prove the centralized wrapper retries without concurrency storms."""
    global _cerebras_next_allowed_at, _cerebras_logical_calls, _cerebras_attempts, _cerebras_rate_limited
    original_client = globals()["cerebras"]
    original_interval = globals()["CEREBRAS_REQUEST_INTERVAL_SECONDS"]
    original_logical = globals()["CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN"]
    original_attempts = globals()["CEREBRAS_MAX_ATTEMPTS_PER_RUN"]
    original_retries = globals()["CEREBRAS_MAX_RETRY_ATTEMPTS"]

    class FakeHeaders(dict):
        pass
    class FakeExc(Exception):
        status_code = 429
        def __init__(self):
            super().__init__("429 Requests per minute limit exceeded")
            self.response = type("R", (), {"headers": FakeHeaders({"retry-after":"0.01"})})()
    class FakeCreate:
        def __init__(self): self.calls = 0
        def __call__(self, **kwargs):
            self.calls += 1
            if self.calls in {2, 3}:
                raise FakeExc()
            return type("Response", (), {"choices":[type("Choice", (), {"message":type("Msg", (), {"content":"{\"ok\":true}"})()})()]})()
    fake = FakeCreate()
    globals()["cerebras"] = type("C", (), {"chat":type("Chat", (), {"completions":type("Comp", (), {"create": fake})()})()})()
    globals()["CEREBRAS_REQUEST_INTERVAL_SECONDS"] = 0.0
    globals()["CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN"] = 3
    globals()["CEREBRAS_MAX_ATTEMPTS_PER_RUN"] = 8
    globals()["CEREBRAS_MAX_RETRY_ATTEMPTS"] = 2
    _cerebras_next_allowed_at = 0.0; _cerebras_logical_calls = 0; _cerebras_attempts = 0; _cerebras_rate_limited = False
    for _ in range(2):
        r = cerebras_create(model="test", messages=[], max_completion_tokens=1)
        assert r.choices
    assert fake.calls == 4
    assert _cerebras_attempts == 4
    globals()["cerebras"] = original_client
    globals()["CEREBRAS_REQUEST_INTERVAL_SECONDS"] = original_interval
    globals()["CEREBRAS_MAX_LOGICAL_CALLS_PER_RUN"] = original_logical
    globals()["CEREBRAS_MAX_ATTEMPTS_PER_RUN"] = original_attempts
    globals()["CEREBRAS_MAX_RETRY_ATTEMPTS"] = original_retries
    logger.info("RATE-LIMIT-TEST: PASS | 429 backoff/retry centralized | attempts=%d", _cerebras_attempts)


def fixture_test():
    """Offline end-to-end fixture test for the executable path; no network/API calls required."""
    self_test()
    # Feed fixtures through prefilter → rank fallback → event collapse → selection.
    base=NOW_BD-timedelta(hours=3)
    fixtures=[
        {"title":"Example Anime Season 3 Officially Announced","excerpt":"officially announced new season trailer","source":"Anime News Network","url":"https://www.animenewsnetwork.com/news/example-anime-season-3","canonical":"animenewsnetwork.com/news/example-anime-season-3","published_date":base.isoformat(),"published_dt":base,"region":REGION,"source_class":"reported"},
        {"title":"Example Anime Season 3 Officially Announced","excerpt":"officially announced new season","source":"Crunchyroll News","url":"https://www.crunchyroll.com/news/example-anime-season-3","canonical":"crunchyroll.com/news/example-anime-season-3","published_date":(base+timedelta(minutes=5)).isoformat(),"published_dt":base+timedelta(minutes=5),"region":REGION,"source_class":"official"},
        {"title":"Marvel Announces Major X-Men Event","excerpt":"Marvel officially announces major crossover event","source":"Marvel","url":"https://www.marvel.com/articles/comics/x-men-event","canonical":"marvel.com/articles/comics/x-men-event","published_date":base.isoformat(),"published_dt":base,"region":REGION,"source_class":"official"},
        {"title":"Routine Anime Episode Reminder","excerpt":"episode airs tomorrow","source":"Anime Corner","url":"https://animecorner.me/routine","canonical":"animecorner.me/routine","published_date":base.isoformat(),"published_dt":base,"region":REGION,"source_class":"reported"},
    ]
    allowed=[x for x in fixtures if candidate_basic_allowed(x) and pre_cerebras_filter(x)[0]]
    assert len(allowed)>=3
    for i,item in enumerate(allowed,1): _apply_deterministic_rank(item,i,"fixture fallback")
    collapsed=collapse_event_clusters(sorted(allowed,key=lambda x:-int(x.get("importance_score",0))))
    selected=balanced_news_selection(collapsed,limit=3)
    assert selected and len(selected)<=3
    assert all(normalize_sector(x.get("sector")) in SECTORS for x in selected)
    # No actual Telegram publish in fixture mode.
    logger.info("FIXTURE-TEST: PASS | fixtures=%d allowed=%d collapsed=%d selected=%d",len(fixtures),len(allowed),len(collapsed),len(selected))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    parser.add_argument("--fixture-test",action="store_true")
    parser.add_argument("--rate-limit-test",action="store_true")
    args=parser.parse_args()
    if args.fixture_test:
        fixture_test()
    elif args.self_test:
        self_test()
    elif args.rate_limit_test:
        rate_limit_test()
    else:
        run()

