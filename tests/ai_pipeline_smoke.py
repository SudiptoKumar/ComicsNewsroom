import os,sys,pathlib,json
from types import SimpleNamespace
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'/'stubs'))
os.environ.update({'EXA_API_KEY':'test','CEREBRAS_API_KEY':'test','TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHANNEL':'@ComicsNewsroom'})
import main

article_html='''<html><head><meta property="og:image" content="https://img.example.com/one-piece.jpg"></head><body>Article</body></html>'''
article_text=("Toei Animation officially released a new One Piece trailer. "
              "The official announcement confirms new footage and a major production update. "
              "The trailer is available on the official YouTube channel.")

class FakeResp:
    def __init__(self, status=200, data=None, text=''):
        self.status_code=status; self._data=data or {}; self.text=text; self.url='https://example.com/final'
    def json(self): return self._data

original_get=main.session.get
original_extract=main.trafilatura.extract
original_exa=main.exa
original_create=main.cerebras.chat.completions.create

class FakeExa:
    def search(self, query, **kwargs):
        if 'official trailer' in query or 'official announcement' in query:
            return SimpleNamespace(results=[
                SimpleNamespace(url='https://www.toei-animation.com/news/one-piece-trailer', title='One Piece Official Trailer Announcement', highlights=['Toei Animation confirms a new One Piece trailer.'], image=''),
                SimpleNamespace(url='https://www.crunchyroll.com/news/one-piece-trailer', title='One Piece Trailer Released', highlights=['The official trailer is now available.'], image=''),
            ])
        return SimpleNamespace(results=[])
    def get_contents(self, urls, **kwargs):
        results=[SimpleNamespace(text='Toei Animation officially confirms the new trailer and release information.') for _ in urls]
        return SimpleNamespace(results=results)
main.exa=FakeExa()

def fake_get(url,*args,**kwargs):
    if 'youtube.com/oembed' in url:
        return FakeResp(200, {'title':'One Piece Official Trailer'})
    return FakeResp(200, text=article_html)
main.session.get=fake_get
main.trafilatura.extract=lambda *args,**kwargs: article_text

story_json={
    'title':'One Piece New Official Trailer','summary':'A new official trailer for One Piece has been released.',
    'sector':'Anime','news_type':'Trailer','highlights':['Toei Animation confirmed the new trailer.','The official video is now available.'],
    'why_it_matters':'It gives fans new official footage from a major franchise.','studio':'Toei Animation','publisher':'','platform':'YouTube','release_date':'','status':'Released'
}
def fake_create(**kwargs):
    name=kwargs.get('response_format',{}).get('json_schema',{}).get('name','')
    if name=='comics_anime_story_v3': content=json.dumps(story_json)
    elif name=='story_claim_verification': content=json.dumps({'supported':True,'unsupported_claims':[]})
    else: content=json.dumps({'results':[{'id':i,'supported':True,'unsupported_claims':[]} for i in range(1,20)]})
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
main.cerebras.chat.completions.create=fake_create

item={'title':'One Piece New Official Trailer','url':'https://animecorner.me/one-piece-trailer','canonical':'animecorner.me/one-piece-trailer','published_date':main.NOW_BD.isoformat(),'published_dt':main.NOW_BD,'region':main.REGION,'source':'Anime Corner','source_class':'reported','excerpt':'A new official trailer has been released.','image':'','image_candidates':[],'video_candidates':['https://www.youtube.com/watch?v=dQw4w9WgXcQ']}
story=main.process_story_candidate(item)
assert story is not None
assert story['official_source_url'].startswith('https://www.toei-animation.com/')
assert story['official_video_platform']=='YouTube'
assert story['official_video_url']=='https://www.youtube.com/watch?v=dQw4w9WgXcQ'
html=main.dynamic_rich_html(story)
assert 'Official Source' in html and 'Watch Trailer 👉' in html and 'YouTube' in html
print('AI-PIPELINE-SMOKE: PASS')
print('--- ACTUAL RENDERED RICH MESSAGE ---')
print(html)

main.session.get=original_get; main.trafilatura.extract=original_extract; main.exa=original_exa; main.cerebras.chat.completions.create=original_create
