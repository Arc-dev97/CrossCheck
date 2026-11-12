"""Owner-scoped Supabase sources and immutable, database-neutral snapshots."""
import base64, hashlib, json, re, time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from contextlib import contextmanager
from typing import Literal
from pathlib import Path
import psycopg
from psycopg import sql
from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, model_validator
from fastapi import HTTPException
from app.models import StrictModel, Pair
from app.engine import profile, read_csv

def root_certificate():return str(Path(__file__).parent/'certs/supabase-prod-ca-2021.crt')

MAX_ROWS=50000
MAX_BYTES=20_000_000
class FetchError(ValueError): pass

def safe_db_error(exc):
    message=str(exc).lower()
    if 'certificate' in message or 'ssl error' in message:return 'Database TLS verification failed. Check the official Supabase CA certificate.'
    if 'password authentication failed' in message or 'wrong password' in message:return 'Database authentication failed. Check the database role and its password.'
    if 'tenant or user not found' in message:return 'Database role/project routing failed. Check the pooler username and project suffix.'
    if 'timeout' in message:return 'Database read timed out. Check connectivity or narrow the source selection.'
    code=exc.sqlstate if re.fullmatch(r'[A-Z0-9]{5}',str(exc.sqlstate or '')) else 'connection'
    return 'Database read failed ('+code+'). Check connectivity, SELECT permissions and the selected schema/table.'

class ConnectionInput(StrictModel):
    name:str=Field(min_length=1,max_length=100)
    host:str=Field(pattern=r'^(?:[a-zA-Z0-9-]+\.)+(?:supabase\.co|supabase\.com)$',max_length=240)
    port:Literal[5432,6543]=5432
    database:str=Field(default='postgres',min_length=1,max_length=100)
    username:str=Field(min_length=1,max_length=150)
    password:SecretStr
    schema_name:str=Field(default='reconcile_demo',pattern=r'^[a-zA-Z_][a-zA-Z0-9_]{0,62}$')
    @model_validator(mode='after')
    def restricted(self):
        if self.schema_name.startswith('pg_') or self.schema_name=='information_schema':raise ValueError('Choose an application schema.')
        if not self.name.strip() or not self.password.get_secret_value():raise ValueError('Name and password are required.')
        return self
class SourceInput(StrictModel):
    name:str=Field(min_length=1,max_length=100)
    connection_id:str
    table:str=Field(min_length=1,max_length=63)
    columns:list[str]=Field(default_factory=list,max_length=40)
    date_column:str|None=None
    date_from:date|None=None
    date_to:date|None=None
    @model_validator(mode='after')
    def dates(self):
        if (self.date_from or self.date_to) and not self.date_column:raise ValueError('Choose the date column for the filter.')
        if self.date_from and self.date_to and self.date_from>self.date_to:raise ValueError('Start date must precede end date.')
        if self.date_to and self.date_to==date.max:raise ValueError('End date is too large.')
        return self

def snapshot_data(dataset):
    return dataset['data'] if 'data' in dataset else read_csv(dataset['text'])

def text_value(value):
    if value is None:return ''
    if isinstance(value,(datetime,date)):return value.isoformat()
    if isinstance(value,bool):return 'true' if value else 'false'
    if isinstance(value,(dict,list)):return json.dumps(value,sort_keys=True,separators=(',',':'),default=str)
    return str(value)

def rows_data(columns,rows,primary_key):
    if len(rows)>MAX_ROWS:raise FetchError('Source exceeds 50,000 rows. Narrow the source date range.')
    result=[];size=0
    for row in rows:
        values={c:text_value(row[c]) for c in columns}
        identity=json.dumps([text_value(row[k]) for k in primary_key],separators=(',',':'))
        size+=len(json.dumps(values,ensure_ascii=False).encode('utf8'))+len(identity.encode('utf8'))
        if size>MAX_BYTES:raise FetchError('Source exceeds the 20 MB snapshot limit. Select fewer columns or a narrower date range.')
        result.append({'id':identity,'values':values,'null_columns':[c for c in columns if row[c] is None]})
    return {'columns':columns,'rows':result}

class SourceManager:
    def __init__(self,b):
        self.b=b
        self.cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(b.secret_material).digest()))
        self.connect=psycopg.connect
    def encrypt(self,value):return self.cipher.encrypt(json.dumps(value).encode()).decode()
    def decrypt(self,value):return json.loads(self.cipher.decrypt(value.encode()))
    def public_connection(self,obj):return {k:v for k,v in obj.items() if k!='credentials'}
    @contextmanager
    def session(self,connection):
        credentials=self.decrypt(connection['credentials'])
        try:
            with self.connect(**credentials,connect_timeout=8,sslmode='verify-full',sslrootcert=root_certificate(),application_name='Reconcile reader') as conn:
                conn.isolation_level=psycopg.IsolationLevel.REPEATABLE_READ
                conn.read_only=True
                with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    cur.execute("SET LOCAL statement_timeout = '10000ms'")
                    cur.execute("SET LOCAL lock_timeout = '2000ms'")
                    cur.execute("SET LOCAL TIME ZONE 'UTC'")
                    yield cur
        except psycopg.Error as exc:
            raise FetchError(safe_db_error(exc)) from None
    def discover(self,connection,cur):
        cur.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema=%s AND table_name IN (SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE') ORDER BY table_name,ordinal_position",(connection['schema_name'],connection['schema_name']))
        tables={}
        for row in cur.fetchall():tables.setdefault(row['table_name'],{'name':row['table_name'],'columns':[],'primary_key':[]})['columns'].append({'name':row['column_name'],'type':row['data_type']})
        cur.execute("SELECT c.relname AS table_name,a.attname AS column_name FROM pg_catalog.pg_index i JOIN pg_catalog.pg_class c ON c.oid=i.indrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS keys(attnum,ord) JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid AND a.attnum=keys.attnum WHERE i.indisprimary AND n.nspname=%s AND has_table_privilege(c.oid,'SELECT') ORDER BY c.relname,keys.ord",(connection['schema_name'],))
        for row in cur.fetchall():
            if row['table_name'] in tables:tables[row['table_name']]['primary_key'].append(row['column_name'])
        return list(tables.values())
    def create_connection(self,p):
        credentials={'host':p.host,'port':p.port,'dbname':p.database,'user':p.username,'password':p.password.get_secret_value()}
        candidate={'name':p.name.strip(),'schema_name':p.schema_name,'credentials':self.encrypt(credentials),'host':p.host,'port':p.port}
        with self.session(candidate) as cur:tables=self.discover(candidate,cur)
        if not tables:raise ValueError('No readable base tables found in this schema. Apply the setup SQL and grant SELECT first.')
        obj=self.b.save('connection',candidate|{'last_tested_at':datetime.now(timezone.utc).isoformat()})
        return self.public_connection(obj)|{'tables':tables}
    def schema(self,id):
        connection=self.b.get('connection',id)
        with self.session(connection) as cur:return self.discover(connection,cur)
    def validate_source(self,source,connection,cur):
        tables={t['name']:t for t in self.discover(connection,cur)}
        table=tables.get(source['table'])
        if not table:raise FetchError('Selected table is missing or no longer readable: '+source['table'])
        if not table['primary_key']:raise FetchError('The table needs a primary key to preserve row provenance.')
        available={c['name']:c['type'] for c in table['columns']}
        columns=list(dict.fromkeys(source.get('columns') or available))
        columns=list(dict.fromkeys(columns+table['primary_key']))
        missing=[c for c in columns if c not in available]
        if missing:raise FetchError('Selected columns are missing: '+', '.join(missing))
        dc=source.get('date_column')
        if dc and available.get(dc) not in ('date','timestamp with time zone','timestamp without time zone'):raise FetchError('Date filter column must be a date or timestamp.')
        return columns,table['primary_key'],[c for c in table['columns'] if c['name'] in columns]
    def create_source(self,p):
        connection=self.b.get('connection',p.connection_id);source=p.model_dump(mode='json')
        if not p.name.strip():raise ValueError('Enter a source name.')
        with self.session(connection) as cur:columns,pk,schema=self.validate_source(source,connection,cur)
        return self.b.save('source',source|{'name':p.name.strip(),'columns':columns,'primary_key':pk,'schema':schema})
    def read(self,source,connection,cur):
        columns,pk,schema=self.validate_source(source,connection,cur)
        if source.get('schema')!=schema or source.get('primary_key')!=pk:raise FetchError('Source schema changed. Register a new source and review its recipe before running again.')
        query=sql.SQL('SELECT {} FROM {}.{}').format(sql.SQL(', ').join(map(sql.Identifier,columns)),sql.Identifier(connection['schema_name']),sql.Identifier(source['table']))
        clauses=[];params=[]
        if source.get('date_from'):
            clauses.append(sql.SQL('{} >= %s').format(sql.Identifier(source['date_column'])));params.append(date.fromisoformat(source['date_from']))
        if source.get('date_to'):
            clauses.append(sql.SQL('{} < %s').format(sql.Identifier(source['date_column'])));params.append(date.fromisoformat(source['date_to'])+timedelta(days=1))
        if clauses:query+=sql.SQL(' WHERE ')+sql.SQL(' AND ').join(clauses)
        query+=sql.SQL(' ORDER BY {} LIMIT %s').format(sql.SQL(', ').join(map(sql.Identifier,pk)));params.append(MAX_ROWS+1)
        cur.execute(query,params)
        data=rows_data(columns,cur.fetchmany(MAX_ROWS+1),pk)
        return data,schema,pk
    def snapshot_pair(self,left_id,right_id):
        sources=[self.b.get('source',id) for id in (left_id,right_id)]
        if sources[0]['connection_id']!=sources[1]['connection_id']:raise ValueError('Choose two sources from the same connection for a consistent snapshot.')
        connection=self.b.get('connection',sources[0]['connection_id'])
        started=datetime.now(timezone.utc).isoformat()
        with self.session(connection) as cur:
            # One transaction freezes both table reads at the same Postgres snapshot.
            cur.execute('SELECT transaction_timestamp() AS snapshot_at');snapshot_at=text_value(cur.fetchone()['snapshot_at'])
            pairs=[self.read(s,connection,cur) for s in sources]
        batch=hashlib.sha256((started+left_id+right_id).encode()).hexdigest()[:20]
        datasets=[]
        for source,(data,schema,pk) in zip(sources,pairs):
            provenance={'source_id':source['id'],'connection_id':connection['id'],'schema_name':connection['schema_name'],'table':source['table'],'primary_key':pk,'schema':schema,'date_column':source.get('date_column'),'date_from':source.get('date_from'),'date_to':source.get('date_to'),'snapshot_at':snapshot_at,'fetched_at':datetime.now(timezone.utc).isoformat(),'batch_id':batch}
            commits=sorted({r['values'].get('producer_commit_sha','') for r in data['rows'] if re.fullmatch(r'[0-9a-fA-F]{40}',r['values'].get('producer_commit_sha',''))})
            provenance.update(producer_commits=commits[:20],producer_commits_truncated=len(commits)>20)
            datasets.append(self.b.save('dataset',{'name':source['name']+' · database snapshot','data':data,'profile':profile(data),'provenance':provenance}))
        return {'left_id':datasets[0]['id'],'right_id':datasets[1]['id'],'batch_id':batch,'snapshot_at':snapshot_at,'profiles':{side:d['profile'] for side,d in zip(('left','right'),datasets)}}

def install_sources(app,b):
    manager=SourceManager(b)
    @app.get('/api/connections')
    def connections():return [manager.public_connection(c) for c in b.listing('connection')]
    @app.post('/api/connections')
    def create_connection(p:ConnectionInput):return manager.create_connection(p)
    @app.get('/api/connections/{id}/tables')
    def tables(id:str):return manager.schema(id)
    @app.get('/api/sources')
    def sources():return b.listing('source')
    @app.post('/api/sources')
    def create_source(p:SourceInput):return manager.create_source(p)
    @app.post('/api/sources/snapshot')
    def snapshot(p:Pair):return manager.snapshot_pair(p.left_id,p.right_id)
    return manager
