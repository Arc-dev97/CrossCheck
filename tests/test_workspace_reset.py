import json,time,threading,unittest
from contextlib import closing
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_api,server
from app.auth import owner_context
from app.workspace import ResetInput

class WorkspaceResetTests(unittest.TestCase):
    upload=test_api.ApiTests.upload
    preview=test_api.ApiTests.preview
    tearDown=test_api.ApiTests.tearDown
    def setUp(self):
        test_api.ApiTests.setUp(self)
        self.other=TestClient(server.app);self.other.cookies.set('reconcile_session',server.issue_session({'id':'test-user-b','email':'b@example.test','name':'B'}))
        token=owner_context.set('test-user-a')
        try:
            self.connection=server.save('connection',{'name':'Keep connection','credentials':'fixture-private-credential'})
            self.source=server.save('source',{'name':'Keep source','connection_id':self.connection['id'],'table':'claims'})
            self.recipe_id=server.save('recipe',{'name':'Keep rules','recipe':self.recipe})['id']
            self.job=server.save('job',{'name':'Demo job','left_id':self.a,'right_id':self.b,'recipe_id':self.recipe_id,'interval_seconds':30,'enabled':True,'lease_until':0,'state':'scheduled','next_run_at':time.time()+30})
            self.event=server.save('event',{'job_id':self.job['id'],'job_name':'Demo job','status':'failed','summary':{},'error':'Fixture','delivery_status':'not_connected'})
            self.draft=server.save('draft',{'name':'draft','left_id':self.a,'right_id':self.b})
        finally:owner_context.reset(token)
        p=self.preview();self.run=self.client.post('/api/runs',json={'preview_id':p['preview_id']}).json()
    def reset(self):
        summary=self.client.get('/api/workspace/reset-summary').json()
        r=self.client.post('/api/workspace/reset',json={'revision':summary['revision'],'confirmation':'RESET_DEMO'})
        self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_owner_scoped_reset_keeps_setup_and_signin(self):
        other=self.other.post('/api/datasets',json={'name':'Other account','text':'id,name\n1,Other\n'}).json()['id']
        result=self.reset()
        for path in ['datasets','jobs','events','runs','drafts']:self.assertEqual(self.client.get('/api/'+path).json(),[])
        self.assertEqual(self.client.get('/api/auth/me').json()['authenticated'],True)
        self.assertEqual(len(self.client.get('/api/recipes').json()),1)
        self.assertEqual(len(self.client.get('/api/connections').json()),1)
        self.assertEqual(len(self.client.get('/api/sources').json()),1)
        self.assertEqual(self.other.get('/api/datasets').json()[0]['id'],other)
        with closing(server.sqlite3.connect(server.DB)) as db:
            archive=db.execute('SELECT payload FROM workspace_archives WHERE id=?',(result['archive_id'],)).fetchone()[0]
            self.assertNotIn('fixture-private-credential',archive)
            self.assertEqual(db.execute('SELECT count(*) FROM users').fetchone()[0],2)
    def test_undo_restores_exact_reports_and_pauses_jobs(self):
        result=self.reset();r=self.client.post('/api/workspace/undo-reset',json={'archive_id':result['archive_id']});self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.get('/api/runs/'+self.run['id']).json(),self.run)
        job=self.client.get('/api/jobs').json()[0];self.assertFalse(job['enabled']);self.assertEqual(job['state'],'paused');self.assertEqual(job['lease_until'],0)
        self.assertEqual(len(self.client.get('/api/datasets').json()),2)
        self.assertEqual(self.client.post('/api/workspace/undo-reset',json={'archive_id':result['archive_id']}).status_code,404)
    def test_stale_review_and_running_job_rejected(self):
        review=self.client.get('/api/workspace/reset-summary').json();self.upload('new.csv','id,name\n4,Added\n')
        self.assertEqual(self.client.post('/api/workspace/reset',json={'revision':review['revision'],'confirmation':'RESET_DEMO'}).status_code,409)
        with closing(server.sqlite3.connect(server.DB)) as db,db:
            job=self.job|{'lease_until':time.time()+60};db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(job),self.job['id']))
        review=self.client.get('/api/workspace/reset-summary').json();self.assertTrue(review['running'])
        self.assertEqual(self.client.post('/api/workspace/reset',json={'revision':review['revision'],'confirmation':'RESET_DEMO'}).status_code,409)
        self.assertEqual(len(self.client.get('/api/jobs').json()),1)
    def test_reset_rolls_back_on_failure(self):
        review=self.client.get('/api/workspace/reset-summary').json();token=owner_context.set('test-user-a')
        try:
            with patch.object(server.workspace,'cancel_deliveries',side_effect=RuntimeError('fixture transaction failure')):
                with self.assertRaises(RuntimeError):server.workspace.reset(ResetInput(revision=review['revision'],confirmation='RESET_DEMO'))
        finally:owner_context.reset(token)
        self.assertEqual(self.client.get('/api/runs/'+self.run['id']).json(),self.run)
        with closing(server.sqlite3.connect(server.DB)) as db:self.assertEqual(db.execute('SELECT count(*) FROM workspace_archives').fetchone()[0],0)
    def test_cross_account_undo_and_reset_permissions(self):
        anonymous=TestClient(server.app);self.assertEqual(anonymous.get('/api/workspace/reset-summary').status_code,401)
        review=self.client.get('/api/workspace/reset-summary').json()
        self.assertEqual(self.other.post('/api/workspace/reset',json={'revision':review['revision'],'confirmation':'RESET_DEMO'}).status_code,409)
        self.assertEqual(self.client.post('/api/workspace/reset',json={'revision':review['revision'],'confirmation':'anything'}).status_code,422)
        self.assertEqual(self.client.post('/api/workspace/reset',headers={'Origin':'https://evil.example'},json={'revision':review['revision'],'confirmation':'RESET_DEMO'}).status_code,403)
        result=self.reset();self.assertEqual(self.other.post('/api/workspace/undo-reset',json={'archive_id':result['archive_id']}).status_code,404)
    def test_restored_events_never_replay_pending_callbacks(self):
        sub={'id':'fixture-sub','owner':'test-user-a','client_id':'fixture','family':'fixture','active':True,'expires':time.time()+1000,'since':'1970-01-01T00:00:00+00:00','arguments':{}}
        server.mcp_oauth.put('subscription',sub['id'],sub)
        result=self.reset();self.client.post('/api/workspace/undo-reset',json={'archive_id':result['archive_id']})
        state=server.mcp_oauth.read('delivery',sub['id']+':'+self.event['id']);self.assertTrue(state['done']);self.assertEqual(state['cancelled_by_reset'],result['archive_id'])
        with patch.object(server.event_hub,'send') as send:
            server.event_hub.deliver_pending();send.assert_not_called()
    def test_reset_serializes_with_inflight_delivery(self):
        review=self.client.get('/api/workspace/reset-summary').json();entered=threading.Event();release=threading.Event();finished=threading.Event();errors=[]
        def delivery():
            token=owner_context.set('test-user-a')
            try:
                with server.workspace.delivery_guard(self.event['id']) as alive:
                    self.assertTrue(alive);entered.set();release.wait(3)
            finally:owner_context.reset(token)
        def resetter():
            token=owner_context.set('test-user-a')
            try:server.workspace.reset(ResetInput(revision=review['revision'],confirmation='RESET_DEMO'));finished.set()
            except Exception as e:errors.append(e)
            finally:owner_context.reset(token)
        first=threading.Thread(target=delivery);first.start();self.assertTrue(entered.wait(1))
        second=threading.Thread(target=resetter);second.start();self.assertFalse(finished.wait(.1));release.set();first.join(3);second.join(3)
        self.assertFalse(errors);self.assertTrue(finished.is_set())
        token=owner_context.set('test-user-a')
        try:
            with server.workspace.delivery_guard(self.event['id']) as alive:self.assertFalse(alive)
        finally:owner_context.reset(token)
