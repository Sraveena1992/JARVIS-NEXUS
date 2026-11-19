"""JARVIS NEXUS Global: private-beta server, no OS controls or arbitrary file access."""
import ast, hmac, json, os, operator, sqlite3, threading, time, urllib.request, urllib.parse
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('JARVIS_DB',str(ROOT/'jarvis.db')))
TOKEN=os.environ.get('JARVIS_TOKEN','')
app=FastAPI(title='JARVIS NEXUS GLOBAL',docs_url=None,redoc_url=None,openapi_url=None)
_hits=defaultdict(deque); _hit_lock=threading.Lock()
def now():return datetime.now(timezone.utc).isoformat()
def connect():
 DB.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(DB,timeout=10);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY,role TEXT,content TEXT,created TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,title TEXT NOT NULL,done INTEGER DEFAULT 0,created TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY,title TEXT NOT NULL,due TEXT NOT NULL,fired INTEGER DEFAULT 0,created TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,action TEXT NOT NULL,detail TEXT,created TEXT)')
 c.commit();return c

def throttle(key,limit=60,window=60):
 t=time.monotonic()
 with _hit_lock:
  if len(_hits)>10000:
   for k in list(_hits)[:5000]:
    if not _hits[k] or _hits[k][-1]<t-window: _hits.pop(k,None)
  q=_hits[key]
  while q and q[0]<t-window:q.popleft()
  if len(q)>=limit:raise HTTPException(429,'Rate limit exceeded. Try again later.')
  q.append(t)

def auth(request:Request):
 if len(TOKEN)<32:raise HTTPException(503,'JARVIS_TOKEN must be configured (at least 32 characters)')
 supplied=request.headers.get('X-Jarvis-Token','')
 if not hmac.compare_digest(supplied,TOKEN):raise HTTPException(401,'Invalid JARVIS token')
 origin=request.headers.get('origin')
 if origin:
  p=urllib.parse.urlsplit(origin)
  host=request.headers.get('host','')
  if p.netloc!=host or p.scheme not in ('https','http'):raise HTTPException(403,'Cross-origin request blocked')
 throttle('auth:'+supplied[:12],120)
 return True

@app.middleware('http')
async def secure(request:Request,call_next):
 if request.url.path.startswith('/api/'):
  try:throttle('ip:'+request.client.host if request.client else 'ip:unknown',240)
  except HTTPException as e:return JSONResponse({'detail':e.detail},status_code=e.status_code)
 response=await call_next(request)
 response.headers['X-Content-Type-Options']='nosniff'
 response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
 response.headers['X-Frame-Options']='DENY'
 response.headers['Permissions-Policy']='camera=(), geolocation=(), payment=()'
 response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self' data:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
 if request.url.path=='/' or request.url.path.startswith('/api/'):
  response.headers['Cache-Control']='no-store'
 return response

class Chat(BaseModel):message:str=Field(min_length=1,max_length=4000)
class Task(BaseModel):title:str=Field(min_length=1,max_length=200)
class Reminder(BaseModel):title:str=Field(min_length=1,max_length=200);due:str
OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,ast.Pow:operator.pow}
def calc(s):
 if len(s)>100:raise ValueError('Expression too long')
 def walk(n,d=0):
  if d>15:raise ValueError('Expression too deep')
  if isinstance(n,ast.Expression):return walk(n.body,d+1)
  if isinstance(n,ast.Constant) and type(n.value) in (int,float) and abs(n.value)<1e12:return n.value
  if isinstance(n,ast.UnaryOp) and type(n.op) in (ast.UAdd,ast.USub):return walk(n.operand,d+1)*(1 if isinstance(n.op,ast.UAdd) else -1)
  if isinstance(n,ast.BinOp) and type(n.op) in OPS:
   a,b=walk(n.left,d+1),walk(n.right,d+1)
   if isinstance(n.op,ast.Pow) and (abs(b)>10 or abs(a)>1e6):raise ValueError('Exponent too large')
   if isinstance(n.op,(ast.Div,ast.FloorDiv,ast.Mod)) and b==0:raise ValueError('Division by zero')
   v=OPS[type(n.op)](a,b)
   if abs(v)>1e15:raise ValueError('Result too large')
   return v
  raise ValueError('Only arithmetic allowed')
 return walk(ast.parse(s,mode='eval'))

def audit(action,detail=''):
 with connect() as c:c.execute('INSERT INTO audit(action,detail,created) VALUES(?,?,?)',(action,detail[:200],now()))

SYSTEM='You are JARVIS NEXUS, a helpful AI assistant. Reply in Hindi for Hindi/Hinglish queries, otherwise English. Do not claim you can control computers, browse websites, or access private user data. No unverified claims of action completion.'
def ai_reply(message):
 key=os.environ.get('OPENAI_API_KEY','')
 if not key:raise HTTPException(503,'AI not configured: administrator must set OPENAI_API_KEY')
 data=json.dumps({'model':os.environ.get('OPENAI_MODEL','gpt-4.1-mini'),'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':message}],'max_completion_tokens':500}).encode()
 req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=data,headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=30) as response:
   answer=json.load(response)['choices'][0]['message']['content']
   if not isinstance(answer,str) or not answer.strip():raise ValueError('Empty model reply')
   return answer.strip()
 except Exception as e:raise HTTPException(502,'AI provider request failed; check server configuration and provider logs') from e

@app.get('/api/health')
def health():return {'ok':True,'service':'jarvis-nexus-global','version':'1.0.0','ai_configured':bool(os.environ.get('OPENAI_API_KEY')),'ai_provider':'openai','token_configured':len(TOKEN)>=32}
@app.get('/api/tasks',dependencies=[Depends(auth)])
def tasks():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY id DESC LIMIT 200')]
@app.post('/api/tasks',dependencies=[Depends(auth)])
def add_task(t:Task):
 if not t.title.strip():raise HTTPException(400,'Empty title')
 with connect() as c:
  cur=c.execute('INSERT INTO tasks(title,created) VALUES (?,?)',(t.title.strip(),now()));newid=cur.lastrowid
 audit('task.create',str(newid));return {'id':newid,'title':t.title.strip(),'done':0}
@app.post('/api/tasks/{task_id}/toggle',dependencies=[Depends(auth)])
def toggle(task_id:int):
 with connect() as c:
  cur=c.execute('UPDATE tasks SET done=1-done WHERE id=?',(task_id,))
  if not cur.rowcount:raise HTTPException(404,'Task not found')
 audit('task.toggle',str(task_id));return {'ok':True}
@app.delete('/api/tasks/{task_id}',dependencies=[Depends(auth)])
def delete(task_id:int):
 with connect() as c:
  cur=c.execute('DELETE FROM tasks WHERE id=?',(task_id,))
  if not cur.rowcount:raise HTTPException(404,'Task not found')
 audit('task.delete',str(task_id));return {'ok':True}
@app.get('/api/history',dependencies=[Depends(auth)])
def history():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM (SELECT * FROM messages ORDER BY id DESC LIMIT 60) ORDER BY id')]
@app.post('/api/chat',dependencies=[Depends(auth)])
def chat(q:Chat):
 throttle('chat:'+TOKEN[:12],12,60)
 msg=q.message.strip()
 if not msg:raise HTTPException(400,'Empty message')
 low=msg.lower()
 try:
  if low.startswith(('calculate ','calc ')):
   expr=msg.split(' ',1)[1];reply=f'{expr} = {calc(expr)}';mode='calculator'
  elif low in ('time','date','today','what time is it'):
   reply='Current UTC time: '+now();mode='clock'
  elif low.startswith('add task '):
   task=add_task(Task(title=msg[9:]));reply='Task created: '+task['title'];mode='tasks'
  elif low in ('help','commands'):
   reply='Try: calculate 23*7, add task Review proposal, time. AI chat requires the configured provider. Desktop controls are unavailable in cloud edition.';mode='help'
  else:reply=ai_reply(msg);mode='ai'
 except (ValueError,ZeroDivisionError,SyntaxError,OverflowError) as e:raise HTTPException(400,str(e))
 with connect() as c:
  c.execute('INSERT INTO messages(role,content,created) VALUES(?,?,?)',('user',msg,now()))
  c.execute('INSERT INTO messages(role,content,created) VALUES(?,?,?)',('assistant',reply,now()))
 return {'reply':reply,'mode':mode}
@app.post('/api/reminders',dependencies=[Depends(auth)])
def add_reminder(r:Reminder):
 try:due=datetime.fromisoformat(r.due.replace('Z','+00:00'))
 except ValueError:raise HTTPException(400,'Invalid due date')
 if due.tzinfo is None or due<=datetime.now(timezone.utc):raise HTTPException(400,'Future timezone-aware date required')
 if not r.title.strip():raise HTTPException(400,'Empty title')
 with connect() as c:
  cur=c.execute('INSERT INTO reminders(title,due,created) VALUES(?,?,?)',(r.title.strip(),due.astimezone(timezone.utc).isoformat(),now()));newid=cur.lastrowid
 audit('reminder.create',str(newid));return {'id':newid,'due':due.isoformat()}
@app.get('/api/reminders',dependencies=[Depends(auth)])
def reminders():
 with connect() as c:
  c.execute('UPDATE reminders SET fired=1 WHERE fired=0 AND due<=?',(now(),))
  return [dict(r) for r in c.execute('SELECT * FROM reminders ORDER BY due DESC LIMIT 100')]
@app.get('/api/audit',dependencies=[Depends(auth)])
def audit_log():
 with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 40')]
@app.get('/api/research',dependencies=[Depends(auth)])
def research(q:str):
 if not q.strip() or len(q)>120:raise HTTPException(400,'Query must be 1–120 characters')
 url='https://en.wikipedia.org/w/api.php?'+urllib.parse.urlencode({'action':'query','generator':'search','gsrsearch':q,'gsrlimit':5,'prop':'extracts','exintro':1,'explaintext':1,'exsentences':2,'format':'json'})
 req=urllib.request.Request(url,headers={'User-Agent':'JARVIS-NEXUS-Global/1.0 (research prototype)'})
 try:
  with urllib.request.urlopen(req,timeout=12) as r:data=json.load(r)
 except Exception as e:raise HTTPException(502,'Wikipedia lookup unavailable') from e
 return {'provider':'Wikipedia','results':[{'title':p.get('title',''),'summary':p.get('extract','')[:600],'url':'https://en.wikipedia.org/wiki/'+urllib.parse.quote(p.get('title','').replace(' ','_'))} for p in data.get('query',{}).get('pages',{}).values()]}
# Explicitly unavailable: no remote desktop controls, arbitrary file APIs, or shell.
@app.post('/api/desktop/open',dependencies=[Depends(auth)])
def desktop_disabled():raise HTTPException(501,'Desktop controls are unavailable in cloud edition')
@app.get('/api/files',dependencies=[Depends(auth)])
def files_disabled():raise HTTPException(501,'Cloud file workspace is not enabled')
@app.get('/api/files/read',dependencies=[Depends(auth)])
def file_read_disabled():raise HTTPException(501,'Cloud file workspace is not enabled')
@app.post('/api/files/write',dependencies=[Depends(auth)])
def file_write_disabled():raise HTTPException(501,'Cloud file workspace is not enabled')
@app.post('/api/video/lookup',dependencies=[Depends(auth)])
def video_disabled():raise HTTPException(501,'YouTube lookup is not available in cloud edition')
@app.get('/',response_class=HTMLResponse)
def home():return (ROOT/'index.html').read_text(encoding='utf-8')
@app.get('/{filename}',include_in_schema=False)
def static(filename:str):
 if filename not in ('hologram.webp','reference-hero.webp','jarvis-nexus-logo.png','icon-192.png','icon-512.png','manifest.webmanifest'):raise HTTPException(404,'Not found')
 return FileResponse(ROOT/filename,media_type='application/manifest+json' if filename.endswith('webmanifest') else None)
