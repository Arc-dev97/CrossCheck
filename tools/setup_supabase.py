r"""One-time interactive setup for a NEW demo schema. No secrets printed.
Run: .\.venv\Scripts\python.exe tools/setup_supabase.py
Uses a Supabase admin connection only for seed/role creation, then saves a
separate SELECT-only reader connection encrypted in the chosen local workspace.
"""
import sys,re,getpass,secrets,hashlib,json
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from psycopg import sql
import server
from app.auth import owner_context
from app.sources import ConnectionInput,root_certificate,safe_db_error

def status(stage,error=None):
    (server.DATA/'supabase-setup-status.json').write_text(json.dumps({'stage':stage,'error_type':type(error).__name__ if error else None,'sqlstate':getattr(error,'sqlstate',None)}),encoding='utf-8')

def main():
    status('waiting_for_inputs')
    host=input('Pooler host [aws-1-ap-southeast-2.pooler.supabase.com]: ').strip() or 'aws-1-ap-southeast-2.pooler.supabase.com'
    username=input('Admin username [postgres.qiejcpkceecwhhdnxvll]: ').strip() or 'postgres.qiejcpkceecwhhdnxvll'
    password=getpass.getpass('Existing database password (hidden): ')
    with closing(server.sqlite3.connect(server.DB)) as db:users=db.execute('SELECT id,email FROM users').fetchall()
    for index,(_,email) in enumerate(users,1):print(str(index)+'. '+email)
    chosen=int(input('Save connection in workspace number: '))-1
    if not 0<=chosen<len(users):raise ValueError('Invalid workspace number.')
    # Reuse input validation to reject arbitrary hosts; password stays local.
    ConnectionInput(name='validation',host=host,username=username,password=password)
    project_ref=username.split('.',1)[1] if '.' in username else ''
    if not project_ref:raise ValueError('Use the session pooler username with the project suffix.')
    role='reconcile_reader_'+secrets.token_hex(5);reader_password=secrets.token_urlsafe(36)
    status('connecting_admin')
    with psycopg.connect(host=host,port=5432,dbname='postgres',user=username,password=password,sslmode='verify-full',sslrootcert=root_certificate(),connect_timeout=10) as conn:
        conn.execute("SET LOCAL statement_timeout='30000ms'")
        status('seeding_tables')
        conn.execute((server.ROOT/'demo/supabase_seed.sql').read_text(encoding='utf-8'),prepare=False)
        status('creating_reader')
        conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS').format(sql.Identifier(role),sql.Literal(reader_password)))
        conn.execute(sql.SQL('GRANT USAGE ON SCHEMA reconcile_demo TO {}').format(sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT SELECT ON ALL TABLES IN SCHEMA reconcile_demo TO {}').format(sql.Identifier(role)))
    token=owner_context.set(users[chosen][0])
    try:
        status('testing_reader')
        connection=server.sources.create_connection(ConnectionInput(name='Supabase employee audit',host=host,username=role+'.'+project_ref,password=reader_password))
        from app.sources import SourceInput
        sources=[server.sources.create_source(SourceInput(name=label,connection_id=connection['id'],table=table)) for table,label in [('employee_expenses','Live employee expense claims'),('uploaded_invoices','Live uploaded invoices')]]
        recipe=server.save('recipe',{'name':'Live employee expense audit','recipe':json.loads((server.ROOT/'demo/expense_recipe.json').read_text())})
        status('complete')
        print('Seeded 92 claims and 91 invoices. SELECT-only connection, two live sources and an expense recipe saved.')
        print('Refresh the app, select Live database tables in Scheduled jobs, then choose these sources and the saved recipe.')
    finally:owner_context.reset(token)
if __name__=='__main__':
    try:
        main()
        input('Setup complete. Press Enter to close this window.')
    except Exception as exc:
        status('failed',exc)
        print('Setup could not complete. Error type: '+type(exc).__name__)
        print(safe_db_error(exc) if isinstance(exc,psycopg.Error) else str(exc) if isinstance(exc,ValueError) else 'Inspect the current setup stage; no credentials were logged.')
        input('Press Enter to close. Share only the error type above if help is needed.')
        raise SystemExit(1)
