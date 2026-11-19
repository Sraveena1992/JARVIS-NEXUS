"""JARVIS-AI: local-first desktop/web assistant. Never expose the desktop server publicly."""
import ast, hmac, json, os, operator, secrets, sqlite3, subprocess, sys, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('JARVIS_DB',str(ROOT/'jarvis.db')))
WORKSPACE=Path(os.environ.get('JARVIS_WORKSPACE',str(ROOT/'workspace'))).resolve()
WORKSPACE.mkdir(parents=True,exist_ok=True)
TOKEN=os.environ.get('JARVIS_TOKEN','')
app=FastAPI(title='JARVIS-AI',version='2.0.0',docs_url=None,redoc_url=None)

def stamp():return datetime.now(timezone.utc).isoformat()
def connect():
 DB.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,created TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,title TEXT NOT NULL,done INTEGER DEFAULT 0,created TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY,title TEXT NOT NULL,due TEXT NOT NULL,fired INTEGER DEFAULT 0,created TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,detail TEXT,created TEXT)')
 c.commit();return c

def auth(request:Request):
 if not TOKEN:raise HTTPException(503,'Set JARVIS_TOKEN in your environment before starting the server')
 supplied=request.headers.get('X-Jarvis-Token','')
 if not hmac.compare_digest(supplied,TOKEN):raise HTTPException(401,'Invalid JARVIS token')
 # Cross-site browser requests cannot supply our custom header without a successful preflight.
 origin=request.headers.get('origin')
 if origin:
  from urllib.parse import urlsplit
  origin_host=urlsplit(origin).netloc
  if origin_host!=request.headers.get('host'):raise HTTPException(403,'Cross-origin request blocked')
 return True

class Chat(BaseModel):message:str=Field(min_length=1,max_length=4000)
class Task(BaseModel):title:str=Field(min_length=1,max_length=200)
class FileWrite(BaseModel):path:str=Field(min_length=1,max_length=200);content:str=Field(max_length=100000)
class Reminder(BaseModel):title:str=Field(min_length=1,max_length=200);due:str
class Action(BaseModel):name:str;confirm:bool=False
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}
def calc(expression):
 if len(expression)>100:raise ValueError('Expression too long')
 def walk(n,depth=0):
  if depth>15:raise ValueError('Expression too deep')
  if isinstance(n,ast.Expression):return walk(n.body,depth+1)
  if isinstance(n,ast.Constant) and type(n.value) in (int,float) and abs(n.value)<1e12:return n.value
  if isinstance(n,ast.UnaryOp) and isinstance(n.op,(ast.UAdd,ast.USub)):return walk(n.operand,depth+1)*(1 if isinstance(n.op,ast.UAdd) else -1)
  if isinstance(n,ast.BinOp) and type(n.op) in OPS:
   a,b=walk(n.left,depth+1),walk(n.right,depth+1)
   if isinstance(n.op,ast.Pow) and (abs(b)>10 or abs(a)>1e6):raise ValueError('Exponent too large')
   if isinstance(n.op,(ast.Div,ast.FloorDiv,ast.Mod)) and b==0:raise ValueError('Division by zero')
   v=OPS[type(n.op)](a,b)
   if abs(v)>1e15:raise ValueError('Result too large')
   return v
  raise ValueError('Only arithmetic is allowed')
 return walk(ast.parse(expression,mode='eval'))

def audit(action,detail=''):
 with connect() as c:c.execute('INSERT INTO audit(action,detail,created) VALUES(?,?,?)',(action,detail[:300],stamp()));c.commit()

def safe_path(name):
 if '\\' in name or name.startswith('/') or ':' in name:raise HTTPException(400,'Relative workspace paths only')
 path=(WORKSPACE/name).resolve()
 if not path.is_relative_to(WORKSPACE) or path==WORKSPACE:raise HTTPException(400,'Path outside workspace')
 return path

JARVIS_SYSTEM = """You are JARVIS NEXUS, a helpful, concise Windows desktop AI companion.
If the user writes in Hindi or Hinglish, answer in natural, simple Hindi (Devanagari),
using English technical terms where helpful. If the user writes in English, answer in English.
Never invent an identity or background. You cannot directly open applications, browse the web,
or create reminders through AI chat. Never claim an action happened unless the system confirms it.
Direct users to the dashboard controls for actions you cannot perform.
Avoid long repetitive lists unless requested. If unsure, say so plainly."""

def ollama_available():
 try:
  req=urllib.request.Request('http://127.0.0.1:11434/api/tags')
  with urllib.request.urlopen(req,timeout=1.5) as response:
   models=json.load(response).get('models',[])
  wanted=os.environ.get('OLLAMA_MODEL','qwen2.5:1.5b')
  return any(m.get('name')==wanted or m.get('model')==wanted for m in models)
 except (OSError,ValueError,KeyError):return False

def ai_reply(message):
 provider=os.environ.get('JARVIS_AI_PROVIDER','ollama').lower()
 messages=[{'role':'system','content':JARVIS_SYSTEM},{'role':'user','content':message}]
 if provider=='ollama':
  payload=json.dumps({'model':os.environ.get('OLLAMA_MODEL','qwen2.5:1.5b'),'messages':messages,'stream':False,'options':{'temperature':0.35,'num_predict':350}}).encode('utf-8')
  req=urllib.request.Request('http://127.0.0.1:11434/api/chat',data=payload,headers={'Content-Type':'application/json'},method='POST')
  with urllib.request.urlopen(req,timeout=120) as response:
   result=json.load(response)
  answer=result.get('message',{}).get('content','').strip()
  if not answer:raise ValueError('Ollama returned an empty response')
  return answer
 if provider=='openai':
  key=os.environ.get('OPENAI_API_KEY')
  if not key:return None
  payload=json.dumps({'model':os.environ.get('OPENAI_MODEL','gpt-4.1-mini'),'messages':messages}).encode('utf-8')
  req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=payload,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=25) as response:return json.load(response)['choices'][0]['message']['content']
 raise ValueError('JARVIS_AI_PROVIDER must be ollama or openai')

@app.get('/api/health')
def health():
 provider=os.environ.get('JARVIS_AI_PROVIDER','ollama').lower()
 ready=ollama_available() if provider=='ollama' else bool(os.environ.get('OPENAI_API_KEY')) if provider=='openai' else False
 return {'ok':True,'service':'jarvis-ai','version':'3.5.0','token_configured':bool(TOKEN),'ai_configured':ready,'ai_provider':provider,'ai_model':os.environ.get('OLLAMA_MODEL','qwen2.5:1.5b') if provider=='ollama' else os.environ.get('OPENAI_MODEL','gpt-4.1-mini')}
@app.get('/api/tasks',dependencies=[Depends(auth)])
def tasks():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY id DESC')]
@app.post('/api/tasks',dependencies=[Depends(auth)])
def add_task(t:Task):
 title=t.title.strip()
 if not title:raise HTTPException(400,'Empty title')
 with connect() as c:
  cur=c.execute('INSERT INTO tasks(title,created) VALUES (?,?)',(title,stamp()));c.commit()
 audit('task.create',str(cur.lastrowid));return {'id':cur.lastrowid,'title':title,'done':0}
@app.post('/api/tasks/{task_id}/toggle',dependencies=[Depends(auth)])
def toggle(task_id:int):
 with connect() as c:
  cur=c.execute('UPDATE tasks SET done=1-done WHERE id=?',(task_id,));c.commit()
  if not cur.rowcount:raise HTTPException(404,'Task not found')
 audit('task.toggle',str(task_id));return {'ok':True}
@app.delete('/api/tasks/{task_id}',dependencies=[Depends(auth)])
def delete(task_id:int):
 with connect() as c:
  cur=c.execute('DELETE FROM tasks WHERE id=?',(task_id,));c.commit()
  if not cur.rowcount:raise HTTPException(404,'Task not found')
 audit('task.delete',str(task_id));return {'ok':True}
@app.get('/api/history',dependencies=[Depends(auth)])
def history():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM (SELECT * FROM messages ORDER BY id DESC LIMIT 60) ORDER BY id ASC')]
@app.post('/api/chat',dependencies=[Depends(auth)])
def chat(q:Chat):
 message=q.message.strip()
 if not message:raise HTTPException(400,'Empty message')
 lower=message.lower()
 try:
  if lower.startswith(('calculate ','calc ')):
   expr=message.split(' ',1)[1];answer=f'{expr} = {calc(expr)}';mode='calculator'
  elif lower in ('time','what time is it','date','today'):
   answer=f'Current server UTC time: {stamp()}';mode='clock'
  elif lower.startswith('add task '):
   task=add_task(Task(title=message[9:]));answer=f'Task created: {task["title"]} (#{task["id"]})';mode='tasks'
  elif lower in ('help','commands'):
   answer='Try calculate 23*7, add task Review proposal, time. Use the dashboard panels for file operations, web lookup, reminders and approved desktop apps.';mode='help'
  else:
   try:answer=ai_reply(message)
   except Exception as e:raise HTTPException(502,'Local AI unavailable. Check Ollama is running and qwen2.5:1.5b is installed; see server logs.') from e
   if answer is None:answer='AI provider is not configured. Local commands work: help, calculate 2+2, add task Buy groceries, time.';mode='setup'
   else:mode='ai'
 except (ValueError,ZeroDivisionError,SyntaxError,OverflowError) as e:raise HTTPException(400,str(e))
 with connect() as c:
  c.execute('INSERT INTO messages(role,content,created) VALUES (?,?,?)',('user',message,stamp()))
  c.execute('INSERT INTO messages(role,content,created) VALUES (?,?,?)',('assistant',answer,stamp()));c.commit()
 return {'reply':answer,'mode':mode}

@app.get('/api/files',dependencies=[Depends(auth)])
def files():return [{'path':str(p.relative_to(WORKSPACE)),'bytes':p.stat().st_size} for p in sorted(WORKSPACE.rglob('*')) if p.is_file() and not p.is_symlink()][:200]
@app.get('/api/files/read',dependencies=[Depends(auth)])
def read_file(path:str):
 p=safe_path(path)
 if not p.is_file() or p.is_symlink():raise HTTPException(404,'File not found')
 if p.stat().st_size>100000:raise HTTPException(413,'File too large')
 try:return {'path':path,'content':p.read_text(encoding='utf-8')}
 except UnicodeError:raise HTTPException(415,'Only UTF-8 text files supported')
@app.post('/api/files/write',dependencies=[Depends(auth)])
def write_file(f:FileWrite):
 p=safe_path(f.path)
 if p.is_symlink():raise HTTPException(400,'Symlink not allowed')
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(f.content,encoding='utf-8');audit('file.write',f.path)
 return {'ok':True,'path':f.path,'bytes':len(f.content.encode())}

@app.get('/api/research',dependencies=[Depends(auth)])
def research(q:str):
 if not q.strip() or len(q)>120:raise HTTPException(400,'Query must be 1–120 characters')
 # Fixed host and fixed path, not arbitrary URL fetching. Source is Wikipedia, not general web search.
 url='https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode({'action':'query','generator':'search','gsrsearch':q,'gsrlimit':5,'prop':'extracts','exintro':1,'explaintext':1,'exsentences':2,'format':'json'})
 req=urllib.request.Request(url,headers={'User-Agent':'JARVIS-AI/2.0 (local research prototype)'})
 try:
  with urllib.request.urlopen(req,timeout=12) as r:data=json.load(r)
 except Exception as e:raise HTTPException(502,'Wikipedia lookup unavailable') from e
 pages=data.get('query',{}).get('pages',{}).values()
 return {'provider':'Wikipedia','results':[{'title':p.get('title',''),'summary':p.get('extract','')[:600],'url':'https://en.wikipedia.org/wiki/'+urllib.parse.quote(p.get('title','').replace(' ','_'))} for p in pages]}

@app.post('/api/reminders',dependencies=[Depends(auth)])
def add_reminder(r:Reminder):
 try:due=datetime.fromisoformat(r.due.replace('Z','+00:00'))
 except ValueError:raise HTTPException(400,'Invalid ISO timestamp')
 if due.tzinfo is None:raise HTTPException(400,'Timezone required')
 if due<=datetime.now(timezone.utc):raise HTTPException(400,'Due time must be in the future')
 with connect() as c:
  cur=c.execute('INSERT INTO reminders(title,due,created) VALUES (?,?,?)',(r.title.strip(),due.astimezone(timezone.utc).isoformat(),stamp()));c.commit()
 audit('reminder.create',str(cur.lastrowid));return {'id':cur.lastrowid,'due':due.isoformat()}
@app.get('/api/reminders',dependencies=[Depends(auth)])
def reminders():
 now=stamp()
 with connect() as c:
  c.execute('UPDATE reminders SET fired=1 WHERE fired=0 AND due<=?',(now,));c.commit()
  return [dict(r) for r in c.execute('SELECT * FROM reminders ORDER BY due DESC LIMIT 100')]

# Explicit, limited Windows app launch: no shell, user confirmation required.
ALLOWED_APPS={'notepad':['notepad.exe'],'calculator':['calc.exe'],'paint':['mspaint.exe'],'explorer':['explorer.exe']}
@app.post('/api/desktop/open',dependencies=[Depends(auth)])
def desktop_open(a:Action):
 if sys.platform!='win32':raise HTTPException(501,'Desktop app launch requires Windows')
 if a.name not in ALLOWED_APPS:raise HTTPException(400,'App not allowlisted')
 if not a.confirm:raise HTTPException(409,'Explicit confirmation required')
 try:subprocess.Popen(ALLOWED_APPS[a.name],shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 except OSError as e:raise HTTPException(502,'Could not launch application') from e
 audit('desktop.open',a.name);return {'ok':True,'launched':a.name}
@app.get('/api/audit',dependencies=[Depends(auth)])
def audit_log():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 40')]
@app.get('/',response_class=HTMLResponse)
def home():return (ROOT/'index.html').read_text(encoding='utf-8')


@app.get("/hologram.webp", include_in_schema=False)
def jarvis_hologram():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).with_name("hologram.webp"), media_type="image/webp")


# Optional video lookup: retrieves metadata only; never downloads media.
# YouTube can change its search interface or block automated lookups.
import re as _video_re
class VideoLookup(BaseModel):
 query:str=Field(min_length=1,max_length=120)

@app.post('/api/video/lookup',dependencies=[Depends(auth)])
def video_lookup(item:VideoLookup):
 query=item.query.strip()
 if not query:raise HTTPException(400,'Search query required')
 try:
  # yt-dlp is optional and executes as a fixed module with arguments, never shell.
  proc=subprocess.run([sys.executable,'-m','yt_dlp','--no-playlist','--skip-download',
      '--no-warnings','--dump-single-json','--socket-timeout','5',
      'ytsearch1:'+query],capture_output=True,text=True,timeout=18,check=False)
 except subprocess.TimeoutExpired as exc:
  raise HTTPException(504,'YouTube lookup timed out; use search results') from exc
 if proc.returncode!=0:
  raise HTTPException(502,'YouTube lookup unavailable; use search results')
 try:
  payload=json.loads(proc.stdout)
  entries=payload.get('entries') or []
  first=entries[0] if entries else payload
  video_id=first.get('id','')
  if not _video_re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id):raise ValueError('Invalid video ID')
  return {'id':video_id,'title':str(first.get('title','Video'))[:180],
          'watch_url':'https://www.youtube.com/watch?v='+video_id}
 except (ValueError,TypeError,KeyError,IndexError,AttributeError) as exc:
  raise HTTPException(502,'No usable YouTube video found; use search results') from exc


# v4.2 mobile-web static assets. No private workspace or secrets are served.
@app.get('/reference-hero.webp', include_in_schema=False)
async def reference_hero():
    from fastapi.responses import FileResponse
    return FileResponse(ROOT / 'reference-hero.webp', media_type='image/webp')

@app.get('/jarvis-nexus-logo.png', include_in_schema=False)
@app.get('/icon-192.png', include_in_schema=False)
@app.get('/icon-512.png', include_in_schema=False)
async def nexus_icon(request: Request):
    from fastapi.responses import FileResponse
    filename=request.url.path.lstrip('/')
    return FileResponse(Path(__file__).with_name(filename), media_type='image/png')

@app.get('/manifest.webmanifest', include_in_schema=False)
async def nexus_manifest():
    from fastapi.responses import FileResponse
    return FileResponse(Path(__file__).with_name('manifest.webmanifest'), media_type='application/manifest+json')
