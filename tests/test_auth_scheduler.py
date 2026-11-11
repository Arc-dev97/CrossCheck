import json,time,sqlite3
from contextlib import closing
from fastapi.testclient import TestClient
from fastapi import HTTPException
import test_api
import unittest
import server
from app.auth import owner_context

class AuthSchedulerTests(unittest.TestCase):
    upload=test_api.ApiTests.upload
    preview=test_api.ApiTests.preview
    tearDown=test_api.ApiTests.tearDown
    def setUp(self):
        test_api.ApiTests.setUp(self)
        self.bclient=TestClient(server.app)
        self.bclient.cookies.set('reconcile_session',server.issue_session({'id':'test-user-b','email':'b@example.test','name':'QA B'}))
    def test_unauthenticated_and_logout(self):
        anonymous=TestClient(server.app)
        self.assertIn('Continue with Google',anonymous.get('/').text)
        for path in ['/api/datasets','/api/recipes','/api/runs','/api/jobs','/api/events','/mcp/','/docs']:
            self.assertEqual(anonymous.get(path).status_code,401,path)
        anonymous.cookies.set('reconcile_session','forged')
        self.assertEqual(anonymous.get('/api/jobs').status_code,401)
        self.assertEqual(self.client.get('/api/auth/me').json()['user']['id'],'test-user-a')
        self.client.post('/auth/logout',follow_redirects=False)
        self.assertEqual(self.client.get('/api/datasets').status_code,401)
    def test_owner_isolation(self):
        self.assertEqual(self.bclient.get('/api/datasets').json(),[])
        self.assertEqual(self.bclient.get('/api/datasets/'+self.a).status_code,404)
        p=self.preview();run=self.client.post('/api/runs',json={'preview_id':p['preview_id']}).json()
        self.assertEqual(self.bclient.get('/api/runs/'+run['id']).status_code,404)
        self.assertEqual(self.bclient.get('/api/runs/'+run['id']+'/export').status_code,404)
        self.assertEqual(self.bclient.post('/api/runs',json={'preview_id':p['preview_id']}).status_code,404)
        self.assertEqual(self.bclient.get('/api/runs').json(),[])
    def job(self,enabled=True,recipe=None):
        rid=self.client.post('/api/recipes',json={'name':'Recipe','recipe':recipe or self.recipe}).json()['id']
        payload={'name':'Daily QA check','left_id':self.a,'right_id':self.b,'recipe_id':rid,'interval_seconds':15,'enabled':enabled}
        response=self.client.post('/api/jobs',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        return response.json(),payload
    def test_scheduled_job_lifecycle(self):
        job,payload=self.job(enabled=False)
        self.assertEqual(self.bclient.get('/api/jobs').json(),[])
        self.assertEqual(self.bclient.post('/api/jobs/'+job['id']+'/run').status_code,404)
        self.assertEqual(self.bclient.post('/api/jobs',json=payload).status_code,404)
        run=self.client.post('/api/jobs/'+job['id']+'/run').json()
        self.assertEqual(run['last_status'],'completed_with_discrepancies')
        self.assertEqual(run['state'],'paused')
        events=self.client.get('/api/events').json()
        self.assertEqual(events[0]['delivery_status'],'not_connected')
        self.assertEqual(self.bclient.get('/api/events').json(),[])
        self.client.post('/api/jobs/'+job['id']+'/enabled',json={'enabled':True})
        with closing(sqlite3.connect(server.DB)) as db,db:
            data=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(job['id'],)).fetchone()[0]);data['next_run_at']=0
            db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(data),job['id']))
        server.scheduler.tick()
        self.assertEqual(len(self.client.get('/api/events').json()),2)
        server.scheduler.tick()
        self.assertEqual(len(self.client.get('/api/events').json()),2)
        self.client.post('/api/jobs/'+job['id']+'/enabled',json={'enabled':False})
        self.assertEqual(self.client.get('/api/jobs').json()[0]['state'],'paused')
    def test_failure_and_lease(self):
        # Reference exists but column mapping is incompatible: job emits a real failure.
        recipe=self.recipe|{'left_key':'missing_column'}
        job,payload=self.job(enabled=False,recipe=recipe)
        result=self.client.post('/api/jobs/'+job['id']+'/run').json()
        self.assertEqual(result['last_status'],'failed')
        self.assertIn('matching column',result['last_error'])
        self.assertIsNone(result['last_run_id'])
        with closing(sqlite3.connect(server.DB)) as db,db:
            data=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(job['id'],)).fetchone()[0]);data['lease_until']=time.time()+100
            db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(data),job['id']))
        self.assertEqual(self.client.post('/api/jobs/'+job['id']+'/run').status_code,409)
        self.assertEqual(self.client.put('/api/jobs/'+job['id'],json=payload).status_code,409)
    def test_interval_and_expired_session(self):
        job,payload=self.job()
        for interval in [0,1,14,604801]:
            self.assertEqual(self.client.post('/api/jobs',json=payload|{'interval_seconds':interval}).status_code,422)
        with closing(sqlite3.connect(server.DB)) as db,db:db.execute('UPDATE sessions SET expires=0 WHERE user_id=?',('test-user-a',))
        self.assertEqual(self.client.get('/api/jobs').status_code,401)
