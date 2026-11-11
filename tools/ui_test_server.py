"""Isolated browser QA with a mock OIDC provider. Never used by server.py.
Run with --isolated-qa. Uses a temporary database and a synthetic identity, not Google.
"""
import sys,os,tempfile,sqlite3,secrets
from pathlib import Path
from contextlib import closing
if '--isolated-qa' not in sys.argv:raise SystemExit('This test harness requires --isolated-qa.')
os.environ.update(GOOGLE_CLIENT_ID='qa-only',GOOGLE_CLIENT_SECRET='qa-only',APP_BASE_URL='http://localhost:8001',PUBLIC_BASE_URL='http://localhost:8001')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from fastapi.responses import RedirectResponse
workspace=tempfile.TemporaryDirectory(prefix='reconcile-ui-qa-')
server.DB=Path(workspace.name)/'qa.sqlite'
with closing(sqlite3.connect(server.DB)) as db,db:
    db.execute('CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT,payload TEXT,owner TEXT)')
    db.execute('CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT,name TEXT)')
    db.execute('CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id TEXT,expires REAL)')
# All below is gated by --isolated-qa and uses a temporary DB plus fixture tables.
server.mcp_oauth.init_db()
import hashlib,json
from datetime import date
from decimal import Decimal
from contextlib import contextmanager
from app.auth import owner_context
from app.sources import ConnectionInput,SourceInput
sys.path.insert(0,str(server.ROOT/'tests'))
from test_live_sources import FixtureCursor
fixture={'schema':{'claims':[('row_id','bigint'),('ref','text'),('amount','numeric'),('day','date')],'invoices':[('row_id','bigint'),('ref','text'),('amount','numeric'),('day','date')]},'claims':[{'row_id':1,'ref':'0001','amount':Decimal('10.50'),'day':date(2026,11,12)}],'invoices':[{'row_id':9,'ref':'0001','amount':Decimal('11.50'),'day':date(2026,11,12)}]}
@contextmanager
def fixture_session(connection):yield FixtureCursor(fixture)
server.sources.session=fixture_session
fixture_owner=hashlib.sha256(b'google:isolated-ui-fixture').hexdigest()
token=owner_context.set(fixture_owner)
try:
    connection=server.sources.create_connection(ConnectionInput(name='QA fixture database',host='aws-0-test.pooler.supabase.com',username='qa',password='fixture-only'))
    for table in ['claims','invoices']:server.sources.create_source(SourceInput(name='Live '+table,connection_id=connection['id'],table=table))
    server.save('recipe',{'name':'Live amount check','recipe':{'left_key':'ref','right_key':'ref','comparisons':[{'left':'amount','right':'amount','type':'number','tolerance':0}]}})
    for index in range(13):server.save('event',{'job_id':'qa-fixture','job_name':'QA notification '+str(index+1),'status':'failed','summary':{},'error':'Synthetic browser test notification','delivery_status':'not_connected'})
finally:owner_context.reset(token)

async def mock_redirect(request,redirect_uri):
    state=secrets.token_urlsafe(24);request.session['qa_state']=state
    return RedirectResponse('/auth/google/callback?state='+state)
async def mock_token(request):
    expected=request.session.pop('qa_state',None)
    if not expected or not secrets.compare_digest(expected,request.query_params.get('state','')):raise ValueError('Invalid QA state')
    return {'userinfo':{'sub':'isolated-ui-fixture','email':'qa@example.test','email_verified':True,'name':'QA fixture — mock Google'}}
server.oauth.google.authorize_redirect=mock_redirect
server.oauth.google.authorize_access_token=mock_token
if __name__=='__main__':
    import uvicorn
    try:uvicorn.run(server.app,host='127.0.0.1',port=8001,access_log=False)
    finally:workspace.cleanup()
