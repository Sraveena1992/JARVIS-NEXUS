import os, tempfile
os.environ['JARVIS_TOKEN']='T'*48
os.environ['JARVIS_DB']=tempfile.mktemp(suffix='.db')
from fastapi.testclient import TestClient
from app import app
client=TestClient(app)
H={'X-Jarvis-Token':'T'*48}
def test_health_and_locked():
 assert client.get('/api/health').status_code==200
 assert client.get('/api/tasks').status_code==401
 assert client.get('/api/tasks',headers=H).status_code==200
def test_tasks_and_commands():
 assert client.post('/api/chat',headers=H,json={'message':'calculate 7*8'}).json()['reply']=='7*8 = 56'
 assert client.post('/api/chat',headers=H,json={'message':'add task Check deployment'}).status_code==200
 assert client.get('/api/tasks',headers=H).json()[0]['title']=='Check deployment'
def test_restricted():
 assert client.post('/api/desktop/open',headers=H,json={'name':'notepad','confirm':True}).status_code==501
 assert client.get('/api/files',headers=H).status_code==501
 assert client.get('/api/tasks',headers={**H,'Origin':'https://evil.example'}).status_code==403
def test_ui():
 r=client.get('/');assert r.status_code==200 and 'JARVIS' in r.text
 assert client.get('/icon-192.png').status_code==200
 assert client.get('/app.py').status_code==404
