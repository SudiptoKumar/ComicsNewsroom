import os,sys,pathlib,tempfile
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'/'stubs'))
os.environ.update({'EXA_API_KEY':'test','CEREBRAS_API_KEY':'test','TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHANNEL':'@ComicsNewsroom'})
import main

# Isolate state and external transports, then execute the real run() orchestration.
original_state=main.STATE; original_posted=main.POSTED_URLS
originals={name:getattr(main,name) for name in [
    'prune_state','bootstrap_learning_from_queue','collect_rss','google_news_gap_fill','exa_gap_fill',
    'save_state','prepare_image','send_rich_photo','send_bot_api_fallback','generate_reader_extra','time'
]}

main.STATE={
    'queue':{},'events':{},'recent_titles':[],'publication_fingerprints':[],'work_memory':{},
    'learned_rejections':{},'source_quality':{},'reader_extra_history':[],
    'reader_extra_type_history':[],'reader_extra_work_history':[],'adaptive_metrics':{}
}
main.POSTED_URLS=set()
main.prune_state=lambda: None
main.bootstrap_learning_from_queue=lambda: None
main.collect_rss=lambda: 0
main.google_news_gap_fill=lambda *args,**kwargs: 0
main.exa_gap_fill=lambda *args,**kwargs: 0
main.save_state=lambda state: None
main.generate_reader_extra=lambda *args,**kwargs: None

# Seed 12 already-ranked strong events, then let the real process/publish loop run.
seed=[]
names=['One Piece','Jujutsu Kaisen','Demon Slayer','Chainsaw Man','Blue Lock','Berserk','X-Men','Batman','Superman','Spider-Man','Invincible','Spawn']
for i,name in enumerate(names):
    sector=['Anime','Manga','Comics'][i%3]
    seed.append({
        'title':f"{name} Major Update", 'headline':f"{name} Major Update",
        'sector':sector,'topic':'Major Anime Announcement' if sector=='Anime' else ('Major Manga Announcement' if sector=='Manga' else 'Major Comic Announcement'),
        'priority_type':'Major Anime Announcement' if sector=='Anime' else ('Major Manga Announcement' if sector=='Manga' else 'Major Comic Announcement'),
        'importance_score':95-(i%3),'important':True,'editor_rank':i+1,'canonical':f'fixture.example/story-{i}',
        'url':f'https://fixture.example/story-{i}','source':'Fixture Source','region':main.REGION,
        'source_class':'official','published_date':main.NOW_BD.isoformat(),'published_dt':main.NOW_BD,
        'excerpt':'officially announced major anime manga comics development',
        'event_key':f'fixture-event-{i}','event_cluster_id':f'fixture-event-{i}','image_url':'','image_candidates':[],
    })
for x in seed: main.STATE['queue'][x['canonical']]=dict(x,status='pending',last_seen=main.NOW_BD.isoformat())

# Bypass rank API while preserving the real candidate selection + event clustering flow.
main.prepare_ranked_region=lambda region,candidates: [dict(x) for x in seed]

def fake_process(item):
    return {**item,
      'summary':'An important confirmed development was announced.',
      'highlights':['The official announcement confirms the development.','More details are expected next.'],
      'why_it_matters':'Fans need to know about this development.',
      'news_type':item['priority_type'],'format':'Anime' if item['sector']=='Anime' else ('Manga' if item['sector']=='Manga' else 'Comic'),
      'studio':'','publisher':'','platform':'','release_date':'','status':'Confirmed',
      'year':'','episodes':'','chapters':'','languages':'','official_video_url':'','official_video_platform':'','official_video_title':'',
      'spoiler':'','note':'','bold_terms':[],'category_hashtags':['#'+item['sector'],'#ComicsNews'],
      'research_official_verified':True,'official_source_url':'','_source_article_text':'official evidence',
      'event_confidence':1.0,'event_source_count':1}
main.process_story_candidate=fake_process
main.verify_stories_batch=lambda stories: stories

# Real image preparation/Telegram are replaced only at transport boundary.
fd,tmp=tempfile.mkstemp(suffix='.jpg'); os.close(fd)
Image.new('RGB',(900,600),(20,30,40)).save(tmp,'JPEG')
main.prepare_image=lambda story,index: tmp
published=[]
def fake_send(path,html):
    published.append(html)
    return {'ok':True,'result':{'message_id':100+len(published)}}
main.send_rich_photo=fake_send

main.POST_DELAY_SECONDS=0
main.run()
assert len(published)==10, len(published)
assert sum(1 for e in main.STATE['events'].values() if e.get('status')=='published')==10
assert all('@ComicsNewsroom' in html for html in published)

os.unlink(tmp)
print(f'PRODUCTION-SMOKE TEST: PASS | run_published={len(published)} | events={len(main.STATE["events"])} | sectors={sorted({e["sector"] for e in main.STATE["events"].values() if e.get("status")=="published"})}')

# Restore globals for cleanliness.
main.STATE=original_state; main.POSTED_URLS=original_posted
