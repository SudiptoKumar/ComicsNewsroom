import os, sys, pathlib
from types import SimpleNamespace
from datetime import timedelta

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'/'stubs'))
os.environ.update({"EXA_API_KEY":"test","CEREBRAS_API_KEY":"test","TELEGRAM_BOT_TOKEN":"test","CEREBRAS_MODEL":"gpt-oss-120b"})
import main

# AI ranking failure must degrade to deterministic scoring, not zero every story.
original_rank=main._rank_batch
main._rank_batch=lambda batch: (_ for _ in ()).throw(RuntimeError('simulated AI outage'))
items=[]
for i,title in enumerate([
    'Major Anime Trailer Officially Released',
    'Popular Manga Gets Anime Adaptation',
    'Marvel Announces Major X-Men Event',
]):
    items.append({
        'title':title,'excerpt':'officially announced trailer adaptation event',
        'source':'Anime News Network','url':f'https://example.com/{i}',
        'canonical':f'example.com/{i}','published_date':main.NOW_BD.isoformat(),
        'published_dt':main.NOW_BD,'region':main.REGION,'source_class':'reported'
    })
ranked=main.rank_candidates(items,main.REGION)
assert len(ranked)==3
assert all(int(x.get('importance_score',0))>0 for x in ranked)
assert any(x.get('sector')=='Comics' for x in ranked)
main._rank_batch=original_rank

# Orchestration: one candidate may fail, but the others continue through final selection.
original_process=main.process_story_candidate
original_verify=main.verify_stories_batch

def fake_process(item):
    if item.get('title')=='FAIL ME':
        raise RuntimeError('simulated candidate failure')
    return {**item,
        'title':item['title'],'headline':item['title'],'summary':'A verified development happened.',
        'sector':item.get('sector'),'news_type':'Major Announcement','priority_type':'Major Anime Announcement',
        'highlights':['Important fact one.','Important fact two.'],'why_it_matters':'Fans need to know this.',
        'source':item.get('source','Source'),'url':item['url'],'canonical':item['canonical'],
        'importance_score':int(item.get('importance_score',90)),'important':True,'editor_rank':int(item.get('editor_rank',1)),
        'image_url':'','image_candidates':[],'official_source_url':'','research_official_verified':True,
        'category_hashtags':['#Anime','#ComicsNews'],'_source_article_text':'verified source evidence',
        'event_key':item.get('event_key',''),'event_cluster_id':item.get('event_cluster_id','') or item['canonical']}

main.process_story_candidate=fake_process
main.verify_stories_batch=lambda stories: stories
cands=[]
for i in range(18):
    sector=['Anime','Manga','Comics'][i%3]
    cands.append({'title':('FAIL ME' if i==3 else f'Strong Story {i}'),'sector':sector,'importance_score':90-i%4,'important':True,'editor_rank':i+1,'canonical':f'story-{i}','url':f'https://example.com/story-{i}','region':main.REGION})
final=main.process_ranked_region(main.REGION,cands)
assert len(final)==10, len(final)
assert all(x.get('title')!='FAIL ME' for x in final)
assert all(main.normalize_sector(x.get('sector')) in main.SECTORS for x in final)
main.process_story_candidate=original_process
main.verify_stories_batch=original_verify

# Telegram 429 is bounded to two attempts and a capped wait.
class FakeResponse:
    status_code=429
    def json(self): return {'ok':False,'description':'Too Many Requests','parameters':{'retry_after':60}}
class FakeSession:
    def __init__(self): self.calls=0
    def post(self,*args,**kwargs): self.calls+=1; return FakeResponse()
fake_session=FakeSession()
original_session,original_sleep=main.session,main.time.sleep
main.session=fake_session
main.time.sleep=lambda _: None
result=main.telegram_call('sendPhoto',data={})
assert result.get('ok') is False
assert fake_session.calls==2, fake_session.calls
main.session,main.time.sleep=original_session,original_sleep

print('FAULT-INJECTION TEST: PASS | AI fallback, candidate isolation, 10-story selection, Telegram 429 bound')
