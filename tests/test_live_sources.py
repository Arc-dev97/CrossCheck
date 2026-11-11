import base64,copy,json,unittest
from pathlib import Path
from datetime import datetime,timezone,date
from decimal import Decimal
from contextlib import contextmanager,closing
from unittest.mock import patch
import psycopg
from pydantic import ValidationError
from fastapi.testclient import TestClient
import test_api,server
from app.auth import owner_context
from app.sources import ConnectionInput,SourceInput,FetchError,rows_data
from app.repositories import RepositoryInput,clean_path

class FixtureCursor:
    def __init__(self,fixture):self.fixture=fixture;self.result=[];self.calls=[]
    def execute(self,q,params=None):
        text=q.as_string() if hasattr(q,'as_string') else str(q);self.calls.append((text,params))
        if 'transaction_timestamp' in text:self.result=[{'snapshot_at':datetime.now(timezone.utc)}]
        elif 'information_schema.columns' in text:
            self.result=[{'table_name':t,'column_name':c,'data_type':typ} for t,cols in self.fixture['schema'].items() for c,typ in cols]
        elif 'pg_catalog.pg_index' in text:self.result=[{'table_name':t,'column_name':'row_id'} for t in self.fixture['schema']]
        elif text.startswith('SELECT '):
            table='claims' if '"claims"' in text else 'invoices'
            self.result=copy.deepcopy(self.fixture[table])
        return self
    def fetchone(self):return self.result[0]
    def fetchall(self):return self.result
    def fetchmany(self,n):return self.result[:n]

class LiveTests(unittest.TestCase):
    upload=test_api.ApiTests.upload
    preview=test_api.ApiTests.preview
    tearDown=test_api.ApiTests.tearDown
    def setUp(self):
        test_api.ApiTests.setUp(self)
        self.other=TestClient(server.app);self.other.cookies.set('reconcile_session',server.issue_session({'id':'test-user-b','email':'b@example.test','name':'B'}))
        self.fixture={'schema':{'claims':[('row_id','bigint'),('ref','text'),('amount','numeric'),('day','date')],'invoices':[('row_id','bigint'),('ref','text'),('amount','numeric'),('day','date')]},'claims':[{'row_id':1,'ref':'0001','amount':Decimal('123456789012345.123456'),'day':date(2026,11,12)}],'invoices':[{'row_id':7,'ref':'0001','amount':Decimal('123456789012345.123456'),'day':date(2026,11,12)}]}
        self.cursors=[]
        @contextmanager
        def session(connection):
            c=FixtureCursor(self.fixture);self.cursors.append(c);yield c
        self.mock=patch.object(server.sources,'session',session);self.mock.start();self.addCleanup(self.mock.stop)
        p={'name':'QA database','host':'aws-0-test.pooler.supabase.com','username':'reader.ref','password':'not-a-real-password'}
        r=self.client.post('/api/connections',json=p);self.assertEqual(r.status_code,200,r.text);self.connection=r.json()['id']
        self.sources=[]
        for table in ['claims','invoices']:
            r=self.client.post('/api/sources',json={'name':table,'connection_id':self.connection,'table':table});self.assertEqual(r.status_code,200,r.text);self.sources.append(r.json()['id'])
        self.live_recipe={'left_key':'ref','right_key':'ref','comparisons':[{'left':'amount','right':'amount','type':'number','tolerance':0}]}
    def snapshot(self):
        r=self.client.post('/api/sources/snapshot',json={'left_id':self.sources[0],'right_id':self.sources[1]});self.assertEqual(r.status_code,200,r.text);return r.json()
    def job(self):
        recipe=self.client.post('/api/recipes',json={'name':'Live amount check','recipe':self.live_recipe}).json()['id']
        r=self.client.post('/api/jobs',json={'name':'Live QA','source_mode':'database','left_id':self.sources[0],'right_id':self.sources[1],'recipe_id':recipe,'interval_seconds':30,'enabled':False});self.assertEqual(r.status_code,200,r.text);return r.json()['id']
    def test_encryption_redaction_isolation_and_snapshot_pair(self):
        response=self.client.get('/api/connections');self.assertNotIn('password',response.text);self.assertNotIn('credentials',response.text)
        with closing(server.sqlite3.connect(server.DB)) as db:
            payload=db.execute("select payload from records where kind='connection'").fetchone()[0];self.assertNotIn('not-a-real-password',payload)
        self.assertEqual(self.other.get('/api/connections').json(),[])
        self.assertEqual(self.other.get('/api/connections/'+self.connection+'/tables').status_code,404)
        self.assertEqual(self.other.post('/api/sources/snapshot',json={'left_id':self.sources[0],'right_id':self.sources[1]}).status_code,404)
        before=len(self.cursors);s=self.snapshot();self.assertEqual(len(self.cursors),before+1)
        a=self.client.get('/api/datasets/'+s['left_id']).json();b=self.client.get('/api/datasets/'+s['right_id']).json()
        self.assertEqual(a['data']['rows'][0]['values']['amount'],'123456789012345.123456')
        self.assertEqual(a['data']['rows'][0]['values']['ref'],'0001');self.assertEqual(a['data']['rows'][0]['id'],'["1"]')
        self.assertEqual(a['provenance']['batch_id'],b['provenance']['batch_id'])
        p=self.client.post('/api/previews',json={'left_id':s['left_id'],'right_id':s['right_id'],'recipe':self.live_recipe});self.assertEqual(p.json()['summary'],{'matched':1})
    def test_fresh_jobs_preserve_history_and_report_changes(self):
        id=self.job();first=self.client.post('/api/jobs/'+id+'/run').json();saved=self.client.get('/api/runs/'+first['last_run_id']).json()
        self.fixture['invoices'][0]['amount']=Decimal('1.25')
        second=self.client.post('/api/jobs/'+id+'/run').json();changed=self.client.get('/api/runs/'+second['last_run_id']).json()
        self.assertEqual(saved['result']['summary'],{'matched':1});self.assertEqual(changed['result']['summary'],{'mismatch':1})
        self.assertNotEqual(saved['left_id'],changed['left_id']);self.assertEqual(changed['changes']['new'],1)
        self.assertEqual(self.client.get('/api/runs/'+first['last_run_id']).json(),saved)
        self.fixture['invoices'][0]['amount']=self.fixture['claims'][0]['amount']
        third=self.client.post('/api/jobs/'+id+'/run').json();resolved=self.client.get('/api/runs/'+third['last_run_id']).json()
        self.assertEqual(resolved['changes']['resolved'],1);self.assertEqual(resolved['sources']['left']['table'],'claims')
        self.assertEqual(len(resolved['build']['application_fingerprint']),64)
    def test_schema_failure_does_not_save_partial_datasets(self):
        id=self.job();before=len(self.client.get('/api/datasets').json());self.fixture['schema']['invoices']=[('row_id','bigint'),('ref','text')]
        r=self.client.post('/api/jobs/'+id+'/run').json();self.assertEqual(r['last_status'],'failed');self.assertIn('missing',r['last_error'])
        self.assertEqual(len(self.client.get('/api/datasets').json()),before)
        event=self.client.get('/api/events').json()[0];self.assertEqual(event['stage'],'source_fetch');self.assertIsNone(event['run_id'])
    def test_date_filters_and_quoted_identifiers(self):
        p={'name':'Filtered','connection_id':self.connection,'table':'claims','columns':['ref','amount'],'date_column':'day','date_from':'2026-11-01','date_to':'2026-11-12'}
        r=self.client.post('/api/sources',json=p);self.assertEqual(r.status_code,200)
        self.client.post('/api/sources/snapshot',json={'left_id':r.json()['id'],'right_id':self.sources[1]})
        query,params=next(c for c in self.cursors[-1].calls if c[0].startswith('SELECT "'))
        self.assertIn('"reconcile_demo"."claims"',query);self.assertIn('"day" >= %s',query);self.assertEqual(params[-1],50001);self.assertEqual(params[1],date(2026,11,13))
        for host in ['localhost','127.0.0.1','aws.supabase.com.evil.test','evil.test']:
            self.assertEqual(self.client.post('/api/connections',json={'name':'x','host':host,'username':'x','password':'x'}).status_code,422)
    def test_row_byte_limits_nulls_and_empty_tables(self):
        data=rows_data(['id','value'],[{'id':'001','value':None}],['id']);self.assertEqual(data['rows'][0]['null_columns'],['value'])
        self.assertEqual(data['rows'][0]['values']['value'],'');self.assertEqual(rows_data(['id'],[],['id'])['rows'],[])
        with patch('app.sources.MAX_ROWS',1):
            with self.assertRaises(FetchError):rows_data(['id'],[{'id':1},{'id':2}],['id'])
        with patch('app.sources.MAX_BYTES',2):
            with self.assertRaises(FetchError):rows_data(['id'],[{'id':1}],['id'])
    def test_notification_pagination_and_isolation(self):
        token=owner_context.set('test-user-a')
        try:
            for i in range(13):server.save('event',{'job_id':'fixture','job_name':'Event '+str(i),'status':'failed','error':'fixture','summary':{}})
        finally:owner_context.reset(token)
        pages=[self.client.get('/api/notifications',params={'page':i,'page_size':5}).json() for i in [1,2,3]]
        self.assertEqual([len(p['items']) for p in pages],[5,5,3]);self.assertEqual(len({e['id'] for p in pages for e in p['items']}),13)
        self.assertEqual(pages[0]['items'][0]['job_name'],'Event 12');self.assertEqual(self.other.get('/api/notifications').json()['total'],0)
        self.assertEqual(self.client.get('/api/notifications?page=0').status_code,422)
        self.assertEqual(self.client.get('/api/notifications?page=99').json()['page'],3)
    def test_repository_secret_paths_refs_and_isolation(self):
        sha='a'*40;head='b'*40
        def github(repo,path,params=None):
            if path.startswith('commits/'):return {'sha':head if 'feature' in path else sha}
            if path.startswith('contents/'):return {'type':'file','encoding':'base64','size':12,'content':base64.b64encode(b'amount / 100').decode(),'html_url':'https://github.com/example/repo/blob/'+sha+'/pipeline/import.py'}
            if path.startswith('compare/'):return {'status':'ahead','total_commits':1,'files':[{'filename':'pipeline/import.py','status':'modified','patch':'- amount / 100\n+ amount','additions':1,'deletions':1},{'filename':'.env','patch':'secret'}]}
            return []
        with patch.object(server.repositories,'get',github):
            r=self.client.post('/api/repositories',json={'name':'Pipeline','repository':'example/repo','branch':'main','paths':['pipeline/'],'token':'fixture-secret'});self.assertEqual(r.status_code,200,r.text);repo=r.json();self.assertNotIn('fixture-secret',r.text);self.assertNotIn('credentials',r.text)
            token=owner_context.set('test-user-a')
            try:
                file=server.repositories.file(repo['id'],'pipeline/import.py');self.assertEqual(file['commit_sha'],sha)
                result=server.repositories.compare(repo['id'],'main','feature');self.assertEqual(result['head_sha'],head);self.assertEqual(len(result['files']),1)
                for path in ['../.env','.env','app/auth.py','pipeline/../.env','pipeline/.env']:
                    with self.assertRaises(ValueError):server.repositories.file(repo['id'],path)
                with self.assertRaises(ValueError):server.repositories.file(repo['id'],'pipeline/import.py','main?bad=1')
            finally:owner_context.reset(token)
            self.assertEqual(self.other.get('/api/repositories').json(),[])
            self.assertEqual(self.other.get('/api/repositories/'+repo['id']+'/branches').status_code,404)

class TransactionTests(unittest.TestCase):
    def test_readonly_repeatable_transaction_and_tls(self):
        from unittest.mock import MagicMock
        from app.sources import SourceManager
        connection={'credentials':server.sources.encrypt({'host':'db.example.supabase.co','user':'reader','password':'fixture','dbname':'postgres'})}
        conn=MagicMock();conn.__enter__.return_value=conn;cursor=MagicMock();conn.cursor.return_value.__enter__.return_value=cursor
        with patch.object(server.sources,'connect',return_value=conn) as connect:
            with server.sources.session(connection):pass
            self.assertEqual(conn.isolation_level,psycopg.IsolationLevel.REPEATABLE_READ);self.assertTrue(conn.read_only)
            self.assertEqual(connect.call_args.kwargs['sslmode'],'verify-full')
            self.assertTrue(any('statement_timeout' in c.args[0] for c in cursor.execute.call_args_list))
    def test_connection_error_redaction(self):
        from app.sources import FetchError
        connection={'credentials':server.sources.encrypt({'host':'db.example.supabase.co','user':'reader','password':'very-private','dbname':'postgres'})}
        with patch.object(server.sources,'connect',side_effect=psycopg.OperationalError('very-private')):
            with self.assertRaises(FetchError) as caught:
                with server.sources.session(connection):pass
            self.assertNotIn('very-private',str(caught.exception))

class BoundaryTests(unittest.TestCase):
    def test_database_tls_error_is_actionable_and_redacted(self):
        from app.sources import safe_db_error,root_certificate
        message=safe_db_error(psycopg.OperationalError('SSL error: certificate verify failed; password=do-not-print'))
        self.assertIn('TLS verification',message);self.assertNotIn('do-not-print',message)
        self.assertTrue(Path(root_certificate()).read_text().startswith('-----BEGIN CERTIFICATE-----'))
    def test_pipeline_minor_unit_conversion(self):
        from pipeline.invoice_import import invoice_total
        from pipeline.invoice_import_bug_example import invoice_total as broken
        self.assertEqual(invoice_total(12550),Decimal('125.5'))
        self.assertEqual(invoice_total('1'),Decimal('0.01'))
        self.assertEqual(broken(12550),Decimal('12550'))
    def test_github_redirects_never_forward_credentials(self):
        from unittest.mock import MagicMock
        repo={'repository':'example/repo'}
        response=MagicMock();response.status_code=302
        with patch('app.repositories.httpx.stream') as stream:
            stream.return_value.__enter__.return_value=response
            with self.assertRaises(ValueError):server.repositories.get(repo,'commits/main')
            self.assertFalse(stream.call_args.kwargs['follow_redirects'])
            self.assertEqual(stream.call_args.args[0],'GET')
            self.assertTrue(stream.call_args.args[1].startswith('https://api.github.com/repos/'))
