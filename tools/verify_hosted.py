"""Authenticated public MCP and timed-job QA in a synthetic owner workspace.
Reads private deployment settings locally; never prints credentials. Source tables
are not modified. Usage: python tools/verify_hosted.py https://service.onrender.com
After a Render restart, append --restart to verify the saved session and report.
"""
import asyncio,json,logging,os,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]
BASE=sys.argv[1].rstrip('/')
u=urlsplit(BASE)
if BASE!='https://crosscheck-demo.onrender.com':raise SystemExit('Only the approved CrossCheck hosted origin may be tested.')
for k,v in dotenv_values(ROOT/'data/render-secrets.env').items():os.environ[k]=v
os.environ.update(APP_BASE_URL=BASE,PUBLIC_BASE_URL=BASE,CROSSCHECK_DB_SCHEMA='crosscheck_state')
sys.path.insert(0,str(ROOT))
import httpx,server
from contextlib import closing
from app.auth import owner_context
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('mcp.client.streamable_http').setLevel(logging.WARNING)
assert server.storage.is_postgres(server.DB) and server.storage.schema_name()=='crosscheck_state', 'Hosted QA cleanup must target the same remote PostgreSQL state as the service.'
OWNER='hosted-protocol-fixture'
PROOF=ROOT/'data/hosted-qa-private.json'

def cleanup_fixture():
    # Same durable remote PostgreSQL DB as the hosted app, not the local SQLite DB.
    assert server.storage.is_postgres(server.DB)
    with closing(server.storage.connect(server.DB)) as db,db:
        server.storage.begin_write(db)
        rows=db.execute("SELECT payload FROM records WHERE kind='job' AND owner=?",(OWNER,)).fetchall()
        if any(json.loads(r[0]).get('lease_until',0)>time.time() for r in rows):raise RuntimeError('QA job is still finishing; leave it paused and retry cleanup after completion.')
        families=[r[0] for r in db.execute("SELECT DISTINCT payload::jsonb->>'family' FROM oauth_store WHERE kind IN ('access','refresh') AND payload::jsonb->>'subject'=?",(OWNER,)).fetchall()]
        db.execute('DELETE FROM records WHERE owner=?',(OWNER,))
        db.execute('DELETE FROM sessions WHERE user_id=?',(OWNER,))
        db.execute('DELETE FROM users WHERE id=?',(OWNER,))
        db.execute("DELETE FROM oauth_store WHERE payload::jsonb->>'subject'=? OR payload::jsonb->>'client_id'=? OR (kind='client' AND key=?)",(OWNER,'hosted-protocol-qa','hosted-protocol-qa'))
        for family in families:db.execute("DELETE FROM oauth_store WHERE kind='revoked' AND key=?",(family,))

async def main():
    async with httpx.AsyncClient(timeout=30) as http:
        health=await http.get(BASE+'/api/auth/me');assert health.status_code==200 and health.json()['google_configured']
        if '--restart' in sys.argv:
            proof=json.loads(PROOF.read_text());cookie={'Cookie':'reconcile_session='+proof['session']}
            identity=await http.get(BASE+'/api/auth/me',headers=cookie);assert identity.json()['authenticated']
            saved=await http.get(BASE+'/api/runs/'+proof['run_id'],headers=cookie);assert saved.status_code==200 and saved.json()['result']['summary']==proof['summary']
            cleanup_fixture()
            print(json.dumps({'hosted_restart_persistence':True,'saved_session_valid':True,'saved_report_unchanged':True,'synthetic_workspace_removed':True}));return
        rejected=await http.get(BASE+'/api/runs');assert rejected.status_code==401
        session_cookie=server.issue_session({'id':OWNER,'email':'hosted-qa@example.test','name':'Hosted protocol QA'})
        cookie={'Cookie':'reconcile_session='+session_cookie}
        provider=server.mcp_oauth
        await provider.register_client(OAuthClientInformationFull(client_id='hosted-protocol-qa',client_name='Hosted QA',redirect_uris=['https://client.example/callback'],token_endpoint_auth_method='none'))
        tokens=provider.mint(OWNER,'hosted-protocol-qa',['reconcile'],BASE+'/mcp/')
        headers={'Authorization':'Bearer '+tokens.access_token};job=None
        recipe={'left_key':'id','right_key':'ref','comparisons':[{'left':'amount','right':'total','type':'number','tolerance':0}]}
        try:
            async with streamablehttp_client(BASE+'/mcp/',headers=headers) as (reader,writer,_):
                async with ClientSession(reader,writer) as mcp:
                    init=await mcp.initialize();assert getattr(init.capabilities,'events',None) is not None
                    catalog=await mcp.list_tools();assert len(catalog.tools)==16
                    async def call(name,args):
                        result=await mcp.call_tool(name,args)
                        if result.isError:raise RuntimeError('Public MCP tool failed: '+name)
                        return result.structuredContent or json.loads(result.content[0].text)
                    left=await call('upload_csv',{'name':'Hosted QA claims.csv','csv_text':'id,amount\n001,10.50\n002,20.00\n'})
                    right=await call('upload_csv',{'name':'Hosted QA invoices.csv','csv_text':'ref,total\n001,10.50\n002,21.00\n'})
                    draft=await call('create_reconciliation_draft',{'name':'Hosted QA draft','left_dataset_id':left['id'],'right_dataset_id':right['id'],'recipe':recipe})
                    assert draft['summary']=={'matched':1,'mismatch':1} and draft['review_url'].startswith(BASE+'/?draft=')
                    invalid=await mcp.call_tool('create_reconciliation_draft',{'name':'Rejected QA rules','left_dataset_id':left['id'],'right_dataset_id':right['id'],'recipe':{**recipe,'left_key':'missing'}});assert invalid.isError
            discovery=await http.post(BASE+'/mcp/',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'events/list','params':{}});assert discovery.status_code==200
            saved=await http.post(BASE+'/api/recipes',headers=cookie,json={'name':'Hosted timer QA','recipe':recipe});assert saved.status_code==200
            response=await http.post(BASE+'/api/jobs',headers=cookie,json={'name':'Hosted timer QA','source_mode':'files','left_id':left['id'],'right_id':right['id'],'recipe_id':saved.json()['id'],'interval_seconds':15,'enabled':True});assert response.status_code==200
            job=response.json();deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                jobs=await http.get(BASE+'/api/jobs',headers=cookie);current=next(x for x in jobs.json() if x['id']==job['id'])
                if current.get('last_run_id'):
                    job=current;break
                if current.get('last_status')=='failed':raise RuntimeError('Hosted timer QA failed.')
                await asyncio.sleep(3)
            else:raise RuntimeError('Hosted timer did not finish within the QA window.')
            report=await http.get(BASE+'/api/runs/'+job['last_run_id'],headers=cookie);assert report.status_code==200
            assert report.json()['result']['summary']=={'matched':1,'mismatch':1}
            PROOF.write_text(json.dumps({'session':session_cookie,'run_id':job['last_run_id'],'job_id':job['id'],'summary':report.json()['result']['summary']}),encoding='utf-8')
            print(json.dumps({'public_https':True,'anonymous_api_denied':True,'tools':16,'mcp_draft_creation':True,'invalid_rule_rejected':True,'events_discovery':True,'automatic_timer_run':True,'summary':report.json()['result']['summary'],'deployed_commit':report.json().get('build',{}).get('application_commit')},indent=2))
        finally:
            if job:
                token=owner_context.set(OWNER)
                try:
                    with closing(server.storage.connect(server.DB)) as db,db:
                        server.storage.begin_write(db)
                        row=db.execute("SELECT payload FROM records WHERE kind='job' AND id=? AND owner=?",(job['id'],OWNER)).fetchone()
                        if row:
                            obj=json.loads(row[0]);obj.update(enabled=False,state='paused');db.execute('UPDATE records SET payload=? WHERE id=? AND owner=?',(json.dumps(obj),job['id'],OWNER))
                finally:owner_context.reset(token)
            access=await provider.load_access_token(tokens.access_token)
            if access:await provider.revoke_token(access)

async def bounded():
    await asyncio.wait_for(main(),timeout=150)
    if '--quick' in sys.argv:
        cleanup_fixture()
        print(json.dumps({'synthetic_workspace_removed':True,'separate_host_restart_test':'skipped_for_time_limit'}))

if __name__=='__main__':asyncio.run(bounded())
