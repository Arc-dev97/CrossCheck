from contextlib import closing
import csv, io, json, tempfile, unittest
from pathlib import Path
from fastapi.testclient import TestClient
import server

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=server.DB;server.DB=Path(self.temp.name)/'test.sqlite'
        with closing(server.sqlite3.connect(server.DB)) as db, db: db.execute('CREATE TABLE records(id TEXT PRIMARY KEY,kind TEXT,payload TEXT,owner TEXT)')
        with closing(server.sqlite3.connect(server.DB)) as db,db:
            db.execute('CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT,name TEXT)')
            db.execute('CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id TEXT,expires REAL)')
        server.mcp_oauth.init_db()
        self.client=TestClient(server.app)
        self.client.cookies.set('reconcile_session',server.issue_session({'id':'test-user-a','email':'a@example.test','name':'QA A'}))
        self.recipe={'left_key':'id','right_key':'code','comparisons':[{'left':'name','right':'label','type':'text'}]}
        self.a=self.upload('a.csv','id,name\n001,Camera\n002,\n003,Tripod\n')
        self.b=self.upload('b.csv','code,label\n001,Camera\n002,\n003,Stand\n')
    def tearDown(self): server.DB=self.old;self.temp.cleanup()
    def upload(self,name,text):
        r=self.client.post('/api/datasets',json={'name':name,'text':text});self.assertEqual(r.status_code,200,r.text);return r.json()['id']
    def preview(self,recipe=None):
        r=self.client.post('/api/previews',json={'left_id':self.a,'right_id':self.b,'recipe':recipe or self.recipe});self.assertEqual(r.status_code,200,r.text);return r.json()
    def test_snapshot_and_persistence(self):
        p=self.preview();self.assertEqual(p['summary'],{'matched':1,'missing_data':1,'mismatch':1})
        run=self.client.post('/api/runs',json={'preview_id':p['preview_id']}).json()
        self.assertEqual(run['result']['summary'],p['summary'])
        self.assertEqual(self.client.post('/api/runs',json={'preview_id':p['preview_id']}).json()['id'],run['id'])
        other=TestClient(server.app);other.cookies.update(self.client.cookies)
        self.assertEqual(other.get('/api/runs/'+run['id']).json(),run)
        self.assertEqual(other.get('/api/datasets/'+self.a).json()['text'],'id,name\n001,Camera\n002,\n003,Tripod\n')
        recipe=other.post('/api/recipes',json={'name':'My recipe','recipe':self.recipe}).json()
        self.assertEqual(other.get('/api/recipes').json()[0],recipe)
        changed=dict(self.recipe,include_missing=False);p2=self.preview(changed)
        self.assertEqual(p2['excluded_groups'],1)
        self.assertEqual(other.get('/api/runs/'+run['id']).json(),run)
    def test_readable_run_name(self):
        p=self.preview()
        run=self.client.post('/api/runs',json={'preview_id':p['preview_id'],'name':'October expense review'}).json()
        self.assertEqual(run['name'],'October expense review')
        self.assertEqual(self.client.get('/api/runs').json()[0]['name'],'October expense review')
        p=self.preview()
        automatic=self.client.post('/api/runs',json={'preview_id':p['preview_id']}).json()
        self.assertEqual(automatic['name'],'a vs b')

    def test_validation(self):
        for change in [{'comparisons':[]},{'left_key':'missing'},{'extra':'bad'},{'comparisons':[{'left':'name','right':'label','type':'sql'}]},{'comparisons':[{'left':'name','right':'label','tolerance':-1}]}]:
            r=self.client.post('/api/previews',json={'left_id':self.a,'right_id':self.b,'recipe':self.recipe|change})
            self.assertIn(r.status_code,[400,422]);self.assertIn('error',r.json())
        self.assertEqual(self.client.post('/api/runs',json={'preview_id':'missing'}).status_code,404)
        for text in ['id,name\n','id,id\n1,2\n','id,name\n1,a,extra\n']:
            self.assertEqual(self.client.post('/api/datasets',json={'name':'bad.csv','text':text}).status_code,400)
        self.assertEqual(self.client.post('/api/datasets',content='bad',headers={'Content-Type':'application/json'}).status_code,422)
        self.assertEqual(self.client.post('/api/recipes',json={'name':'x','recipe':self.recipe},headers={'origin':'https://evil.example'}).status_code,403)
    def test_export(self):
        p=self.preview(dict(self.recipe,include_missing=False));run=self.client.post('/api/runs',json={'preview_id':p['preview_id']}).json()
        response=self.client.get('/api/runs/'+run['id']+'/export')
        rows=list(csv.DictReader(io.StringIO(response.content.decode('utf-8-sig'))))
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['key'],'001')
        self.assertEqual(json.loads(rows[0]['source_a_records'])[0]['values']['name'],'Camera')
        self.assertNotIn('002',[r['key'] for r in rows])
    def test_formula_export(self):
        a=self.upload('a.csv','id,name\n=1+1,Camera\n');b=self.upload('b.csv','code,label\n=1+1,Camera\n')
        p=self.client.post('/api/previews',json={'left_id':a,'right_id':b,'recipe':self.recipe}).json()
        run=self.client.post('/api/runs',json={'preview_id':p['preview_id']}).json()
        rows=list(csv.DictReader(io.StringIO(self.client.get('/api/runs/'+run['id']+'/export').content.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['key'],"'=1+1")
if __name__=='__main__': unittest.main()
