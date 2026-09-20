import os, sys, pathlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update({'EXA_API_KEY':'test','CEREBRAS_API_KEY':'test','TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHANNEL':'@ComicsNewsroom'})
import main

base={
    'url':'https://example.com/webtoon-awards',
    'canonical':'example.com/webtoon-awards',
    'published_dt':main.NOW_BD,
    'published_date':main.NOW_BD.isoformat(),
    'source':'Fixture Source','region':main.REGION,
    'excerpt':'World Webtoon Awards announces finalists and opens global reader vote.',
}

cases=[
    ('2026 World Webtoon Awards Announces 20 Finalists, Opens Global Reader Vote','webtoon'),
    ('Popular Manhwa Gets Anime Adaptation','manhwa'),
    ('New Manhua Series Announced by Publisher','manhua'),
    ('Digital Comic Creator Announces New Series','digital comic'),
]

for title, signal in cases:
    item={**base,'title':title}
    ok, reason=main.pre_cerebras_filter(item)
    assert ok, (title, reason)

# Preserve the intended hard rejection of unrelated gaming content.
item={**base,'title':'New Webtoon Game Review and Gameplay Guide'}
ok, reason=main.pre_cerebras_filter(item)
assert not ok and reason=='hard_low_value_title', (ok,reason)

print('EDITORIAL-WEBTOON TEST: PASS | webtoon/manhwa/manhua/digital-comic signals accepted')
