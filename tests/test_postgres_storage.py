"""Real PostgreSQL regression tests. Only the isolated crosscheck_qa schema.
Run via tools/verify_postgres.py after private setup; default discovery skips these.
"""
import concurrent.futures,os,tempfile,threading,time,unittest
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import HTTPException
import test_api,server
from app import storage
from app.auth import owner_context

@unittest.skipUnless(os.getenv('CROSSCHECK_TEST_DATABASE_URL'),'Private PostgreSQL QA connection is not configured')
class PostgresTests(test_api.ApiTests):
    def setUp(self):
        if os.getenv('CROSSCHECK_DB_SCHEMA')!='crosscheck_qa':raise RuntimeError('Refusing to test outside crosscheck_qa.')
        self.old=server.DB;self.temp=tempfile.TemporaryDirectory();server.DB=os.environ['CROSSCHECK_TEST_DATABASE_URL']
        storage.initialize(server.DB)
        with closing(storage.connect(server.DB)) as db,db:
            for name in ['records','users','sessions','oauth_store','workspace_archives']:db.execute('DELETE FROM '+name)
        server.mcp_oauth.init_db()
        self.client=TestClient(server.app)
        self.client.cookies.set('reconcile_session',server.issue_session({'id':'test-user-a','email':'a@example.test','name':'QA A'}))
        self.recipe={'left_key':'id','right_key':'code','comparisons':[{'left':'name','right':'label','type':'text'}]}
        self.a=self.upload('a.csv','id,name\n001,Camera\n002,\n003,Tripod\n')
        self.b=self.upload('b.csv','code,label\n001,Camera\n002,\n003,Stand\n')
    def test_atomic_oauth_consumption(self):
        provider=server.mcp_oauth;provider.put('code','qa-single-use',{'payload':'one'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:values=list(pool.map(lambda _:provider.consume('code','qa-single-use'),range(8)))
        self.assertEqual(sum(x is not None for x in values),1)
    def test_owner_isolation_and_persistence(self):
        run=self.client.post('/api/runs',json={'preview_id':self.preview()['preview_id']}).json()
        other=TestClient(server.app);other.cookies.set('reconcile_session',server.issue_session({'id':'test-user-b','email':'b@example.test','name':'QA B'}))
        self.assertEqual(other.get('/api/runs/'+run['id']).status_code,404)
        # Recreate all database connections, simulating process storage reconnect.
        pool=storage._pool(server.DB);pool.close();storage._pools.clear()
        self.assertEqual(self.client.get('/api/runs/'+run['id']).json()['result'],run['result'])
        self.assertTrue(self.client.get('/api/auth/me').json()['authenticated'])
    def test_reset_undo_and_rollback(self):
        run=self.client.post('/api/runs',json={'preview_id':self.preview()['preview_id']}).json()
        summary=self.client.get('/api/workspace/reset-summary').json()
        with patch.object(server.workspace,'cancel_deliveries',side_effect=RuntimeError('QA rollback')):
            token=owner_context.set('test-user-a')
            try:
                from app.workspace import ResetInput
                with self.assertRaises(RuntimeError):server.workspace.reset(ResetInput(revision=summary['revision'],confirmation='RESET_DEMO'))
            finally:owner_context.reset(token)
        self.assertEqual(self.client.get('/api/runs/'+run['id']).status_code,200)
        r=self.client.post('/api/workspace/reset',json={'revision':summary['revision'],'confirmation':'RESET_DEMO'});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/runs').json(),[])
        r=self.client.post('/api/workspace/undo-reset',json={'archive_id':r.json()['archive_id']});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/runs/'+run['id']).json()['result'],run['result'])
    def test_scheduler_overlap_lease(self):
        recipe=self.client.post('/api/recipes',json={'name':'PG QA recipe','recipe':self.recipe}).json()
        job=self.client.post('/api/jobs',json={'name':'PG QA check','left_id':self.a,'right_id':self.b,'recipe_id':recipe['id'],'interval_seconds':15,'enabled':False}).json()
        entered=threading.Event();release=threading.Event();preview=server.preview
        def delayed(p):
            entered.set()
            if not release.wait(12):raise RuntimeError('QA timeout')
            return preview(p)
        def perform():
            token=owner_context.set('test-user-a')
            try:return server.scheduler.run(job['id'])
            finally:owner_context.reset(token)
        with patch.object(server,'preview',side_effect=delayed),concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            first=pool.submit(perform)
            try:
                self.assertTrue(entered.wait(10))
                with self.assertRaises(HTTPException) as error:perform()
                self.assertEqual(error.exception.status_code,409)
            finally:release.set()
            self.assertIn(first.result(timeout=45)['last_status'],['completed','completed_with_discrepancies'])
    def test_state_role_cannot_write_demo_sources(self):
        import psycopg
        for table in ['employee_expenses','uploaded_invoices']:
            with closing(storage.connect(server.DB)) as db:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):db.raw.execute('UPDATE reconcile_demo.'+table+' SET row_id=row_id WHERE false')
    def test_compact_lists_keep_summary_without_snapshots(self):
        run=self.client.post('/api/runs',json={'preview_id':self.preview()['preview_id']}).json()
        token=owner_context.set('test-user-a')
        try:
            reports=server.listing('run',compact=True)
            self.assertEqual(reports[0]['result'],{'summary':run['result']['summary']})
            datasets=server.listing('dataset',compact=True)
            self.assertEqual(len(datasets),2)
            self.assertTrue(all('text' not in d and 'data' not in d and d['profile']['rows']==3 for d in datasets))
        finally:owner_context.reset(token)
        listed=self.client.get('/api/runs').json()[0]
        self.assertEqual(listed['id'],run['id']);self.assertEqual(listed['summary'],run['result']['summary'])
        self.assertEqual(len(self.client.get('/api/datasets').json()),2)
