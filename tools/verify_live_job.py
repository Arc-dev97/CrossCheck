"""Register the supplied codebases and validate two fresh real Supabase job executions.
Creates/updates only named demo records in the existing owner's app workspace.
Source database access remains read-only.
"""
import sys,json,os,time
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
from app.auth import owner_context
from app.repositories import RepositoryInput
with closing(server.sqlite3.connect(server.DB)) as db:
    owners=db.execute("SELECT owner,payload FROM records WHERE kind='connection'").fetchall()
owner,connection=next((o,json.loads(p)) for o,p in owners if json.loads(p)['name']=='Supabase employee audit')
token=owner_context.set(owner)
try:
    sources={s['table']:s for s in server.listing('source') if s['connection_id']==connection['id']}
    repositories=[]
    for name,paths in [('CrossCheck application',['app/','server.py']),('CrossCheck source pipeline',['pipeline/','tools/simulate_updates.py'])]:
        repo=next((r for r in server.listing('repository') if r['name']==name),None)
        if not repo:repo=server.repositories.create(RepositoryInput(name=name,repository='Arc-dev97/CrossCheck',paths=paths))
        repositories.append(repo)
    diff=server.repositories.compare(repositories[1]['id'],'main','demo/minor-unit-bug')
    assert any(f['path']=='pipeline/invoice_import.py' and 'Decimal' in (f['patch']or'') for f in diff['files'])
    recipe=next(r for r in server.listing('recipe') if r['name']=='Live employee expense audit')
    job=next((j for j in server.listing('job') if j['name']=='Live employee audit — Supabase'),None)
    if not job:job=server.save('job',{'name':'Live employee audit — Supabase','source_mode':'database','left_id':sources['employee_expenses']['id'],'right_id':sources['uploaded_invoices']['id'],'recipe_id':recipe['id'],'interval_seconds':30,'enabled':False,'state':'paused','next_run_at':time.time()+30,'lease_until':0,'last_status':'not_run','last_error':None,'application_repo_id':repositories[0]['id'],'pipeline_repo_id':repositories[1]['id']})
    first=server.scheduler.run(job['id']);a=server.get('run',first['last_run_id'])
    second=server.scheduler.run(job['id']);b=server.get('run',second['last_run_id'])
    expected=json.loads((server.ROOT/'demo/expense_expected.json').read_text())
    assert a['result']['summary']==b['result']['summary']==expected
    assert a['left_id']!=b['left_id'] and a['right_id']!=b['right_id']
    assert server.get('run',a['id'])==a
    assert not second['enabled']
    assert set(b['code_context'])=={'application','source_pipeline'}
    print(json.dumps({'real_live_job':job['name'],'two_fresh_snapshots':True,'immutable_previous_run':True,'summary':b['result']['summary'],'registered_codebases':len(repositories),'actual_bug_branch_diff_verified':True,'job_paused':True},indent=2))
finally:owner_context.reset(token)
