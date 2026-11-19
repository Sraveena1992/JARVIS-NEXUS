import importlib, os
os.environ['JARVIS_TOKEN']='test-token-123'
os.environ['JARVIS_DB']=__import__('tempfile').mktemp(suffix='.db')
os.environ['JARVIS_WORKSPACE']=__import__('tempfile').mkdtemp()
import app as jarvis
from fastapi.testclient import TestClient
c=TestClient(jarvis.app)
H={'X-Jarvis-Token':'test-token-123'}
def test_auth():
 assert c.get('/api/tasks').status_code==401
 assert c.get('/api/tasks',headers=H).status_code==200
 assert c.post('/api/tasks',headers={**H,'Origin':'https://evil.example','Host':'testserver'},json={'title':'x'}).status_code==403
def test_tasks():
 r=c.post('/api/tasks',headers=H,json={'title':'Test task'});assert r.status_code==200
 i=r.json()['id'];assert c.post(f'/api/tasks/{i}/toggle',headers=H).status_code==200
 assert c.delete(f'/api/tasks/{i}',headers=H).status_code==200
def test_calc():
 assert jarvis.calc('2+3*4')==14
 for s in ['__import__("os")','2**100','1/0']:
  try:jarvis.calc(s);assert False
  except (ValueError,ZeroDivisionError):pass
def test_chat():
 r=c.post('/api/chat',headers=H,json={'message':'calc 3*7'});assert r.json()['mode']=='calculator'
def test_files():
 assert c.post('/api/files/write',headers=H,json={'path':'notes/test.txt','content':'hello'}).status_code==200
 assert c.get('/api/files/read',headers=H,params={'path':'notes/test.txt'}).json()['content']=='hello'
 for path in ['../secret','/etc/passwd','C:\\windows\\win.ini']:
  assert c.get('/api/files/read',headers=H,params={'path':path}).status_code==400
def test_desktop_safety():
 assert c.post('/api/desktop/open',headers=H,json={'name':'cmd','confirm':True}).status_code in (400,501)
def test_reminder():
 assert c.post('/api/reminders',headers=H,json={'title':'Test','due':'2030-01-01T00:00:00+00:00'}).status_code==200
 assert len(c.get('/api/reminders',headers=H).json())>=1


def test_ollama_chat(monkeypatch):
 import io, json
 class FakeResponse:
  def __init__(self, payload):self.buffer=io.BytesIO(json.dumps(payload).encode())
  def __enter__(self):return self.buffer
  def __exit__(self,*args):pass
 def fake_open(req,timeout=None):
  assert req.full_url=='http://127.0.0.1:11434/api/chat'
  payload=json.loads(req.data)
  assert payload['model']=='qwen2.5:1.5b'
  assert 'Hindi' in payload['messages'][0]['content']
  return FakeResponse({'message':{'content':'नमस्ते! मैं जार्विस हूँ।'}})
 monkeypatch.setenv('JARVIS_AI_PROVIDER','ollama')
 monkeypatch.setattr(jarvis.urllib.request,'urlopen',fake_open)
 r=c.post('/api/chat',headers=H,json={'message':'नमस्ते'})
 assert r.status_code==200
 assert r.json()['mode']=='ai'
 assert 'नमस्ते' in r.json()['reply']

def test_ollama_health(monkeypatch):
 import io, json
 class FakeResponse:
  def __enter__(self):return io.BytesIO(json.dumps({'models':[{'name':'qwen2.5:1.5b'}]}).encode())
  def __exit__(self,*args):pass
 monkeypatch.setenv('JARVIS_AI_PROVIDER','ollama')
 monkeypatch.setattr(jarvis.urllib.request,'urlopen',lambda req,timeout=None:FakeResponse())
 r=c.get('/api/health')
 assert r.json()['ai_configured'] is True
 assert r.json()['ai_provider']=='ollama'


def test_video_lookup_auth():
 assert c.post('/api/video/lookup',json={'query':'bhajan'}).status_code==401
 assert c.post('/api/video/lookup',headers=H,json={'query':''}).status_code==422

def test_video_lookup_mock(monkeypatch):
 from types import SimpleNamespace
 def fake_run(args,**kwargs):
  assert args[0]==jarvis.sys.executable and args[2]=='yt_dlp'
  assert args[-1]=='ytsearch1:Waheguru Simran'
  return SimpleNamespace(returncode=0,stdout='{"entries":[{"id":"dQw4w9WgXcQ","title":"Test video"}]}')
 monkeypatch.setattr(jarvis.subprocess,'run',fake_run)
 r=c.post('/api/video/lookup',headers=H,json={'query':'Waheguru Simran'})
 assert r.status_code==200 and r.json()['id']=='dQw4w9WgXcQ'


def test_reference_hero_is_served():
 r=c.get('/reference-hero.webp')
 assert r.status_code==200
 assert r.headers['content-type'].startswith('image/webp')
 assert len(r.content)>10000

def test_dashboard_uses_reference_art():
 r=c.get('/')
 assert r.status_code==200
 assert '/reference-hero.webp' in r.text
