from contextlib import closing
from pathlib import Path
import csv, io, json, os, sqlite3, uuid, re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from app.engine import read_csv, profile, reconcile
from app.auth import require_owner, owner_context, install_auth

ROOT=Path(__file__).parent
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
from app import storage
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
if os.getenv('RENDER_EXTERNAL_URL') and not os.getenv('CROSSCHECK_DATABASE_URL'):raise RuntimeError('Hosted service requires durable CROSSCHECK_DATABASE_URL.')
DB=os.getenv('CROSSCHECK_DATABASE_URL') or DATA/'workspace.sqlite3'
if storage.is_postgres(DB) and len(os.getenv('APP_SECRET_KEY',''))<32:raise RuntimeError('Hosted state requires APP_SECRET_KEY with at least 32 characters.')
storage.initialize(DB)

def save(kind, payload):
    owner=require_owner()
    obj={**payload,'id':uuid.uuid4().hex,'created_at':datetime.now(timezone.utc).isoformat()}
    with closing(storage.connect(DB)) as db, db: db.execute('INSERT INTO records (id,kind,payload,owner) VALUES (?,?,?,?)',(obj['id'],kind,json.dumps(obj),owner))
    return obj

def get(kind, id):
    owner=require_owner()
    with closing(storage.connect(DB)) as db, db: row=db.execute('SELECT payload FROM records WHERE id=? AND kind=? AND owner=?',(id,kind,owner)).fetchone()
    if not row: raise HTTPException(404,f'{kind.title()} not found.')
    return json.loads(row[0])

def listing(kind,compact=False):
    owner=require_owner();expression='payload'
    if compact:
        if kind=='dataset':expression="payload::jsonb - 'text' - 'data'" if storage.is_postgres(DB) else "json_remove(payload,'$.text','$.data')"
        elif kind=='run':expression="jsonb_set(payload::jsonb,'{result}',jsonb_build_object('summary',payload::jsonb->'result'->'summary'))" if storage.is_postgres(DB) else "json_set(payload,'$.result',json_object('summary',json_extract(payload,'$.result.summary')))"
        else:raise ValueError('Unsupported summary projection.')
    with closing(storage.connect(DB)) as db:rows=db.execute('SELECT '+expression+' FROM records WHERE kind=? AND owner=? ORDER BY rowid DESC',(kind,owner)).fetchall()
    return [r[0] if isinstance(r[0],dict) else json.loads(r[0]) for r in rows]

from app.models import *
from app.sources import snapshot_data, install_sources
from app.repositories import install_repositories

app=FastAPI(title='CrossCheck workspace',version='0.3.0')
import sys
install_auth(app,sys.modules[__name__])
from app.mcp_oauth import install_oauth
install_oauth(app,sys.modules[__name__])
sources=install_sources(app,sys.modules[__name__])
repositories=install_repositories(app,sys.modules[__name__])
from app.workspace import install_workspace
workspace=install_workspace(app,sys.modules[__name__])
@app.middleware('http')
async def local_only(request: Request, call_next):
    # Single-user local workspace; reject cross-site browser mutation requests.
    origin=request.headers.get('origin')
    if origin and origin not in (base_url,public_base_url) and not (request.url.path in ('/token','/register','/revoke') or request.url.path.startswith('/.well-known/') or (request.url.path.startswith('/mcp') and request.headers.get('authorization','').lower().startswith('bearer '))):
        return JSONResponse({'error':'Cross-origin access is not allowed.'},status_code=403)
    try: length=int(request.headers.get('content-length','0'))
    except ValueError: return JSONResponse({'error':'Invalid request length.'},status_code=400)
    if length>8_000_000: return JSONResponse({'error':'Request too large.'},status_code=413)
    return await call_next(request)
@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    return JSONResponse({'error':'; '.join('.'.join(str(x) for x in e['loc'])+': '+e['msg'] for e in exc.errors())},status_code=422)
@app.exception_handler(ValueError)
async def value_error(request,exc): return JSONResponse({'error':str(exc)},status_code=400)
@app.get('/')
def home(request:Request): return FileResponse(ROOT/('app/index.html' if request.state.user else 'app/login.html'))
@app.get('/assets/live.js')
def live_script():return FileResponse(ROOT/'app/live.js',media_type='text/javascript')

@app.get('/assets/{name}')
def frontend_asset(name:str):
    allowed={'workspace.js':'text/javascript','workspace.css':'text/css','shell.js':'text/javascript','bricolage-latin.woff2':'font/woff2','FONT_LICENSE.txt':'text/plain'}
    if name not in allowed:raise HTTPException(404)
    return FileResponse(ROOT/'app'/name,media_type=allowed[name])

@app.get('/demo/{name}')
def demo(name:str):
    if name not in ('warehouse.csv','store.csv','recipe.json','employee_expenses.csv','uploaded_invoices.csv','expense_recipe.json'): raise HTTPException(404)
    return FileResponse(ROOT/'demo'/name)
@app.post('/api/datasets')
def upload(p:DatasetInput):
    if len(p.text.encode('utf8'))>3_500_000: raise ValueError('Each file must be under 3.5 MB.')
    data=read_csv(p.text)
    return save('dataset',{'name':p.name,'text':p.text,'profile':profile(data)})
@app.get('/api/datasets/{id}')
def dataset(id:str): return get('dataset',id)
@app.post('/api/profile')
def profiles(p:Pair):
    a=get('dataset',p.left_id);b=get('dataset',p.right_id)
    left=snapshot_data(a);right=snapshot_data(b)
    return {'left':a['profile'],'right':b['profile'],'left_columns':left['columns'],'right_columns':right['columns']}
@app.post('/api/previews')
def preview(p:PreviewInput):
    a=get('dataset',p.left_id);b=get('dataset',p.right_id)
    r=p.recipe.model_dump(mode='json')
    result=reconcile(snapshot_data(a),snapshot_data(b),r)
    obj=save('preview',{'left_id':p.left_id,'right_id':p.right_id,'recipe':r,'result':result})
    return {**result,'preview_id':obj['id']}
@app.post('/api/runs')
def execute(p:ExecuteInput):
    preview=get('preview',p.preview_id)
    # Match only this preview instead of fetching every full historical report.
    expression="payload::jsonb->>'preview_id'" if storage.is_postgres(DB) else "json_extract(payload,'$.preview_id')"
    with closing(storage.connect(DB)) as db:existing=db.execute("SELECT payload FROM records WHERE kind='run' AND owner=? AND "+expression+"=? ORDER BY rowid DESC LIMIT 1",(require_owner(),p.preview_id)).fetchone()
    if existing:return json.loads(existing[0])
    name=p.name.strip() or (Path(get('dataset',preview['left_id'])['name']).stem+' vs '+Path(get('dataset',preview['right_id'])['name']).stem).replace('_',' ')
    return save('run',{k:v for k,v in preview.items() if k not in ('id','created_at')} | {'preview_id':p.preview_id,'name':name})
def legacy_run_name(r):
    return (Path(get('dataset',r['left_id'])['name']).stem+' vs '+Path(get('dataset',r['right_id'])['name']).stem).replace('_',' ')

@app.get('/api/runs')
def runs(): return [{k:r[k] for k in ('id','created_at','left_id','right_id')}|{'summary':r['result']['summary'],'name':(r.get('name') or legacy_run_name(r))} for r in listing('run',compact=True)]
@app.get('/api/runs/{id}')
def run(id:str):
    r=get('run',id)
    return r | {'name':(r.get('name') or legacy_run_name(r))}
@app.get('/api/runs/{id}/export')
def export(id:str):
    saved_run=get('run',id)
    label=(saved_run.get('name') or legacy_run_name(saved_run))
    filename=(re.sub(r'[^a-zA-Z0-9]+','-',label).strip('-')[:100] or 'reconciliation')+'-'+saved_run['created_at'][:10]+'.csv'
    result=saved_run['result']; output=io.StringIO(newline='');w=csv.writer(output)
    def safe(v):
        v=str(v)
        return "'"+v if v.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else v
    w.writerow(['key','status','missing_data','missing_fields','differences','source_a_line_ids','source_b_line_ids','source_a_records','source_b_records'])
    for r in result['results']:
        w.writerow([safe(r['key']),r['status'],r['missing_data'],json.dumps(r['missing_fields']),json.dumps(r['details']),';'.join(str(x['id']) for x in r['left_rows']),';'.join(str(x['id']) for x in r['right_rows']),json.dumps(r['left_rows']),json.dumps(r['right_rows'])])
    return Response('\ufeff'+output.getvalue(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{filename}"'})
@app.get('/api/recipes')
def recipes(): return listing('recipe')
@app.post('/api/recipes')
def recipe_save(p:RecipeInput):
    if not p.name.strip(): raise ValueError('Enter a recipe name.')
    return save('recipe',{'name':p.name.strip(),'recipe':p.recipe.model_dump(mode='json')})
@app.get('/api/drafts')
def drafts(): return listing('draft')

from app.scheduler import install_scheduler
scheduler=install_scheduler(app,sys.modules[__name__])

from app.mcp_tools import install_mcp
import sys
mcp=install_mcp(app,sys.modules[__name__])

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('PORT','8000')),access_log=False)
