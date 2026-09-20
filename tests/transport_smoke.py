import os,sys,pathlib,tempfile
from PIL import Image
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'/'stubs'))
os.environ.update({'EXA_API_KEY':'test','CEREBRAS_API_KEY':'test','TELEGRAM_BOT_TOKEN':'test','TELEGRAM_CHANNEL':'@ComicsNewsroom'})
import main

fd,path=tempfile.mkstemp(suffix='.jpg'); os.close(fd); Image.new('RGB',(700,450),(1,2,3)).save(path,'JPEG')
orig_call=main.telegram_call
calls=[]
def fake_call(method,data=None,files=None):
    calls.append((method,data or {},files is not None))
    if method=='sendRichMessage':
        return {'ok':False,'http_status':404,'description':'sendRichMessage method not found'}
    return {'ok':True,'http_status':200,'result':{'message_id':501}}
main.telegram_call=fake_call
rich=main.send_rich_photo(path,'<p>@ComicsNewsroom</p>')
assert rich['ok'] is False and rich['http_status']==404
fallback=main.send_bot_api_fallback(path,'<p>@ComicsNewsroom</p><h1>Trailer</h1>')
assert fallback['ok'] is True
assert calls[0][0]=='sendRichMessage' and calls[1][0]=='sendPhoto'
assert calls[1][1]['chat_id']=='@ComicsNewsroom'
print('TRANSPORT-SMOKE TEST: PASS | Rich Message -> sendPhoto fallback')
main.telegram_call=orig_call
os.unlink(path)
