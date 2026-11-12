"""Interactive one-time free-host migration. Passwords and tokens are never logged.
Uses an existing Supabase admin password only to create isolated app-state roles
and schemas. The running app receives no admin access and cannot write source tables.
"""
import getpass,json,os,secrets,sqlite3,sys,time,logging
from pathlib import Path
from contextlib import closing
from urllib.parse import quote
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
from dotenv import dotenv_values
from app import storage
from app.sources import root_certificate,ConnectionInput
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data';DATA.mkdir(exist_ok=True)
STATUS=DATA/'hosted-setup-status.json'
CONFIG=DATA/'hosted-storage-private.json'
logging.getLogger('psycopg.pool').setLevel(logging.CRITICAL)

def status(stage,**extra):STATUS.write_text(json.dumps({'stage':stage,**extra}),encoding='utf-8')
def env_line(key,value):return key+'='+json.dumps(str(value),ensure_ascii=True)

def main():
    if CONFIG.exists():
        config=json.loads(CONFIG.read_text(encoding='utf-8'))
        print('Using the isolated app-storage role already prepared locally.')
    else:
        print('This creates separate app-state and QA schemas, without changing source tables.')
        host=input('Pooler host [aws-1-ap-southeast-2.pooler.supabase.com]: ').strip() or 'aws-1-ap-southeast-2.pooler.supabase.com'
        user=input('Admin username [postgres.qiejcpkceecwhhdnxvll]: ').strip() or 'postgres.qiejcpkceecwhhdnxvll'
        password=getpass.getpass('Existing Supabase database password (hidden): ')
        ConnectionInput(name='validation',host=host,username=user,password=password)
        project=user.split('.',1)[1] if '.' in user else ''
        if not project:raise ValueError('Use the pooler username with a project suffix.')
        role='crosscheck_state_'+secrets.token_hex(5);secret=secrets.token_urlsafe(40)
        status('creating_isolated_storage')
        with psycopg.connect(host=host,port=5432,dbname='postgres',user=user,password=password,sslmode='verify-full',sslrootcert=root_certificate(),connect_timeout=12) as db:
            for schema in ['crosscheck_state','crosscheck_qa']:
                if db.execute('SELECT 1 FROM information_schema.schemata WHERE schema_name=%s',(schema,)).fetchone():raise ValueError('An app-state schema already exists. Nothing was overwritten; inspect before retrying.')
            db.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(secret)))
            db.execute(sql.SQL('GRANT {} TO CURRENT_USER').format(sql.Identifier(role)))
            for schema in ['crosscheck_state','crosscheck_qa']:
                db.execute(sql.SQL('CREATE SCHEMA {} AUTHORIZATION {}').format(sql.Identifier(schema),sql.Identifier(role)))
                db.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC,anon,authenticated').format(sql.Identifier(schema)))
        dsn='postgresql://'+quote(role+'.'+project,safe='')+':'+quote(secret,safe='')+'@'+host+':5432/postgres'
        config={'dsn':dsn,'role':role}
        CONFIG.write_text(json.dumps(config),encoding='utf-8')
    dsn=config['dsn'];status('initializing_app_tables')
    for schema in ['crosscheck_state','crosscheck_qa']:
        os.environ['CROSSCHECK_DB_SCHEMA']=schema;storage.initialize(dsn)
        with closing(storage.connect(dsn)) as db,db:
            for table in ['records','users','sessions','oauth_store','workspace_archives']:
                # Not part of the exposed public API schemas; revoke public access explicitly too.
                db.raw.execute(sql.SQL('REVOKE ALL ON TABLE {}.{} FROM PUBLIC,anon,authenticated').format(sql.Identifier(schema),sql.Identifier(table)))
                db.raw.execute(sql.SQL('ALTER TABLE {}.{} ENABLE ROW LEVEL SECURITY').format(sql.Identifier(schema),sql.Identifier(table)))
    os.environ['CROSSCHECK_DB_SCHEMA']='crosscheck_state'
    backup=DATA/'backups';backup.mkdir(exist_ok=True)
    snapshot=backup/('pre-hosted-'+str(int(time.time()))+'.sqlite3')
    with closing(sqlite3.connect(DATA/'workspace.sqlite3')) as source,closing(sqlite3.connect(snapshot)) as dest:source.backup(dest)
    counts={};status('migrating_workspace')
    with closing(sqlite3.connect(snapshot)) as local,closing(storage.connect(dsn)) as db,db:
        storage.begin_write(db)
        if db.execute('SELECT count(*) FROM records').fetchone()[0]:
            if not config.get('migration_complete'):raise ValueError('Target state is not empty. Inspect it before importing; nothing was overwritten.')
            print('App records are already migrated; existing cloud records were preserved.')
        else:
            db.raw.execute("SET LOCAL statement_timeout='180000ms'")
            with db.raw.cursor().copy('COPY records(id,kind,payload,owner,rowid) FROM STDIN') as batch:
                for rowid,id,kind,payload,owner in local.execute('SELECT rowid,id,kind,payload,owner FROM records ORDER BY rowid'):
                    if kind=='job':
                        job=json.loads(payload);job.update(enabled=False,state='paused',lease_until=0);payload=json.dumps(job)
                    batch.write_row((id,kind,payload,owner,rowid))
            with db.raw.cursor().copy('COPY users(id,email,name) FROM STDIN') as batch:
                for row in local.execute('SELECT id,email,name FROM users'):batch.write_row(row)
            if local.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace_archives'").fetchone():
                with db.raw.cursor().copy('COPY workspace_archives(id,owner,payload,created_at,undone_at) FROM STDIN') as batch:
                    for row in local.execute('SELECT id,owner,payload,created_at,undone_at FROM workspace_archives'):batch.write_row(row)
            # Keep record ordering correct after explicit identity values from SQLite.
            db.execute("SELECT setval(pg_get_serial_sequence('crosscheck_state.records','rowid'),COALESCE(max(rowid),1),count(*)>0) FROM records")
            # Old sessions, OAuth grants and webhook destinations are intentionally not migrated.
        for table in ['records','users','sessions','oauth_store','workspace_archives']:counts[table]=db.execute('SELECT count(*) FROM '+table).fetchone()[0]
    config['migration_complete']=True;CONFIG.write_text(json.dumps(config),encoding='utf-8')
    status('checking_permissions')
    for table in ['employee_expenses','uploaded_invoices']:
        with closing(storage.connect(dsn)) as db:
            try:db.raw.execute('UPDATE reconcile_demo.'+table+' SET row_id=row_id WHERE false')
            except psycopg.errors.InsufficientPrivilege:pass
            else:raise ValueError('The state role unexpectedly has source write privileges.')
    env=dotenv_values(ROOT/'.env')
    key=(DATA/'session-signing.key').read_text(encoding='utf-8').strip()
    if len(key)<32:raise ValueError('Existing signing material is unavailable.')
    exported={'CROSSCHECK_DATABASE_URL':dsn,'APP_SECRET_KEY':key,'GOOGLE_CLIENT_ID':env.get('GOOGLE_CLIENT_ID',''),'GOOGLE_CLIENT_SECRET':env.get('GOOGLE_CLIENT_SECRET','')}
    if not exported['GOOGLE_CLIENT_ID'] or not exported['GOOGLE_CLIENT_SECRET']:raise ValueError('Google sign-in values are missing from the local .env.')
    (DATA/'render-secrets.env').write_text('\n'.join(env_line(k,v) for k,v in exported.items())+'\n',encoding='utf-8')
    qa={'CROSSCHECK_TEST_DATABASE_URL':dsn,'CROSSCHECK_DB_SCHEMA':'crosscheck_qa'}
    (DATA/'postgres-qa.env').write_text('\n'.join(env_line(k,v) for k,v in qa.items())+'\n',encoding='utf-8')
    status('complete',counts=counts,source_writes_denied=True)
    print('Storage migration complete. Local backup preserved and cloud jobs paused.')
    print('Private Render environment values are saved in data/render-secrets.env. Never send this file to chat or GitHub.')
    print('Old connector sessions were not copied. The hosted app will use fresh sign-in and MCP consent.')

def pause(message):
    try:input(message)
    except EOFError:pass

if __name__=='__main__':
    try:
        status('waiting_for_password');main();pause('Press Enter to close.')
    except Exception as exc:
        status('failed',error_type=type(exc).__name__,sqlstate=getattr(exc,'sqlstate',None),message=getattr(getattr(exc,'diag',None),'message_primary',None))
        print('Setup did not complete. Error type: '+type(exc).__name__)
        if isinstance(exc,ValueError):print(str(exc))
        pause('Press Enter to close. Share only the error type, never passwords.')
        raise SystemExit(1)
