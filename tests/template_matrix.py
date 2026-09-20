import os, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests' / 'stubs'))
os.environ.update({'EXA_API_KEY':'test','CEREBRAS_API_KEY':'test','TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHANNEL':'@ComicsNewsroom'})
import main

base = {
    'title':'Example Story', 'summary':'A major official development fans need to know today.',
    'sector':'Anime', 'highlights':['The official announcement confirms the development.','More details are expected.'],
    'why_it_matters':'This is important to fans of the franchise.', 'studio':'Example Studio', 'publisher':'Example Publisher',
    'platform':'YouTube', 'format':'TV Anime', 'episodes':'12', 'chapters':'', 'status':'Confirmed', 'release_date':'2026',
    'year':'2026','source':'Anime News Network','url':'https://example.com/story',
    'official_source_url':'https://official.example/story','importance_score':95,
    'official_video_url':'https://www.youtube.com/watch?v=dQw4w9WgXcQ','official_video_platform':'YouTube',
    'official_video_title':'Example Official Trailer', 'spoiler':'','note':'','bold_terms':['Example Story'],
}
variants = [
    ('announcement', {'sector':'Anime','priority_type':'Major Anime Announcement','topic':'Major Anime Announcement'}),
    ('trailer', {'sector':'Anime','priority_type':'Major Trailer / PV','topic':'Major Trailer / PV'}),
    ('manga_anime', {'sector':'Manga','priority_type':'Manga → Anime Adaptation','topic':'Manga → Anime Adaptation'}),
    ('manga_update', {'sector':'Manga','priority_type':'Major Manga Return / Hiatus','topic':'Major Manga Return / Hiatus','official_video_url':'','official_video_platform':''}),
    ('marvel', {'sector':'Comics','priority_type':'Major Marvel News','topic':'Major Marvel News'}),
    ('dc', {'sector':'Comics','priority_type':'Major DC News','topic':'Major DC News'}),
    ('comic_event', {'sector':'Comics','priority_type':'Major Comic Storyline / Event','topic':'Major Comic Storyline / Event'}),
    ('adaptation', {'sector':'Comics','priority_type':'Major Comic Adaptation','topic':'Major Comic Adaptation'}),
    ('season', {'sector':'Anime','priority_type':'New Season / Sequel','topic':'New Season / Sequel'}),
]
for name, patch in variants:
    story = {**base, **patch}
    rendered = main.dynamic_rich_html(story)
    assert '@ComicsNewsroom' in rendered, name
    assert 'Source:' in rendered, name
    assert '<h1>' in rendered, name
    if name == 'trailer':
        assert 'NEW TRAILER' in rendered and 'Watch Trailer 👉' in rendered, name
    if name == 'manga_anime':
        assert 'MANGA → ANIME' in rendered, name
    if name == 'marvel':
        assert 'MARVEL COMICS' in rendered, name
    if name == 'dc':
        assert 'DC COMICS' in rendered, name
print(f'TEMPLATE-MATRIX TEST: PASS | variants={len(variants)}')
