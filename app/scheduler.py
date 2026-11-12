"""Persistent interval scheduler. One local worker; SQLite leases prevent overlapping runs."""
import asyncio,json,time
from contextlib import closing
from typing import Literal
from fastapi import HTTPException, Query
from app.repositories import build_info
from app.sources import snapshot_data
from pydantic import BaseModel, ConfigDict, Field
from app.auth import owner_context, require_owner
from app.models import PreviewInput, Recipe, ExecuteInput

class JobInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    left_id:str
    right_id:str
    recipe_id:str
    interval_seconds:int=Field(ge=15,le=604800)
    enabled:bool=True
    source_mode:Literal["files","database"]="files"
    application_repo_id:str|None=None
    pipeline_repo_id:str|None=None
class ToggleInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool

def compare_runs(previous,current):
    def signatures(result):
        return {r['key']:json.dumps({k:r[k] for k in ('status','details','missing_fields')},sort_keys=True) for r in result['results'] if r['status']!='matched'}
    now=signatures(current)
    if previous is None:return {'baseline':True,'new':len(now),'resolved':0,'changed':0,'unchanged':0}
    old=signatures(previous)
    return {'baseline':False,'new':len(now.keys()-old.keys()),'resolved':len(old.keys()-now.keys()),'changed':sum(now[k]!=old[k] for k in now.keys()&old.keys()),'unchanged':sum(now[k]==old[k] for k in now.keys()&old.keys())}

def install_scheduler(app,b):
    def replace(id,changes):
        owner=require_owner()
        with closing(b.storage.connect(b.DB,timeout=10)) as db,db:
            b.storage.begin_write(db)
            row=db.execute("SELECT payload FROM records WHERE kind='job' AND id=? AND owner=?",(id,owner)).fetchone()
            if not row:raise HTTPException(404,'Job not found.')
            job=json.loads(row[0]);job.update(changes)
            db.execute('UPDATE records SET payload=? WHERE id=? AND owner=?',(json.dumps(job),id,owner))
        return job
    def validate_sources(p):
        kind='source' if p.source_mode=='database' else 'dataset'
        left=b.get(kind,p.left_id);right=b.get(kind,p.right_id)
        if p.source_mode=='database' and left['connection_id']!=right['connection_id']:raise ValueError('Both tables must use the same connection.')
        for repo_id in (p.application_repo_id,p.pipeline_repo_id):
            if repo_id:b.get('repository',repo_id)
        recipe=b.get('recipe',p.recipe_id)
        Recipe.model_validate(recipe['recipe'])
        if not p.name.strip():raise ValueError('Enter a job name.')
    def claim(id,manual=False):
        owner=require_owner();now=time.time()
        with closing(b.storage.connect(b.DB,timeout=10)) as db,db:
            b.storage.begin_write(db)
            row=db.execute("SELECT payload FROM records WHERE kind='job' AND id=? AND owner=?",(id,owner)).fetchone()
            if not row:raise HTTPException(404,'Job not found.')
            job=json.loads(row[0])
            if job.get('lease_until',0)>now:raise HTTPException(409,'This job is already running.')
            if not manual and (not job['enabled'] or job['next_run_at']>now):return None
            job.update(lease_until=now+600,state='running',last_started_at=now)
            db.execute('UPDATE records SET payload=? WHERE id=? AND owner=?',(json.dumps(job),id,owner))
        return job
    def perform(id,manual=False):
        job=claim(id,manual)
        if not job:return None
        run_id=None;summary={};error=None;stage='recipe_validation';pair=None;delta=None
        previous_id=job.get('last_successful_run_id') or job.get('last_run_id')
        previous=b.get('run',previous_id) if previous_id else None
        contexts={role:b.repositories.public(b.get('repository',job[key])) for role,key in [('application','application_repo_id'),('source_pipeline','pipeline_repo_id')] if job.get(key)}
        build=build_info(b.ROOT)
        try:
            recipe=b.get('recipe',job['recipe_id'])['recipe']
            validated=Recipe.model_validate(recipe)
            pair={'left_id':job['left_id'],'right_id':job['right_id']}
            if job.get('source_mode')=='database':
                stage='source_fetch';pair=b.sources.snapshot_pair(job['left_id'],job['right_id'])
            stage='comparison'
            p=b.preview(PreviewInput(left_id=pair['left_id'],right_id=pair['right_id'],recipe=validated))
            stage='save_run'
            provenance={side:b.get('dataset',pair[side+'_id']).get('provenance',{'kind':'csv'}) for side in ('left','right')}
            selection={'left':job['left_id'],'right':job['right_id']}
            comparable=previous and previous.get('source_selection')==selection and previous.get('recipe')==validated.model_dump(mode='json') and previous.get('source_mode','files')==job.get('source_mode','files')
            changes=compare_runs(previous['result'] if comparable else None,p)
            metadata={'job_id':id,'source_selection':selection,'source_mode':job.get('source_mode','files'),'sources':provenance,'code_context':contexts,'build':build,'changes':changes}
            with closing(b.storage.connect(b.DB)) as db,db:
                preview=b.get('preview',p['preview_id']);preview.update(metadata)
                db.execute("UPDATE records SET payload=? WHERE id=? AND owner=?",(json.dumps(preview),preview['id'],require_owner()))
            run=b.execute(ExecuteInput(preview_id=p['preview_id'],name=job['name']))
            run_id=run['id'];summary=run['result']['summary'];delta=changes;stage='completed'
            status='completed_with_discrepancies' if any(v for k,v in summary.items() if k!='matched') or p['excluded_groups'] else 'completed'
        except Exception as exc:
            status='failed'
            error=str(exc.detail) if isinstance(exc,HTTPException) else str(exc)
            error=error[:500] or 'Reconciliation could not complete.'
        finished=time.time()
        # Preserve edits/pause made while execution was running; only update execution metadata.
        latest=b.get('job',id)
        event=b.save('event',{'job_id':id,'job_name':job['name'],'status':status,'run_id':run_id,'summary':summary,'error':error,'stage':stage,'source_mode':job.get('source_mode','files'),'snapshot_pair':pair,'code_context':contexts,'build':build,'changes':delta,'delivery_status':'not_connected','message':'Saved in app. No assistant push subscription is connected.'})
        return replace(id,{'lease_until':0,'state':'scheduled' if latest['enabled'] else 'paused','next_run_at':finished+latest['interval_seconds'],'last_finished_at':finished,'last_status':status,'last_run_id':run_id,'last_successful_run_id':run_id or previous_id,'last_error':error,'last_event_id':event['id']})

    class Scheduler:
        task=None
        async def start(self):
            if self.task is None:self.task=asyncio.create_task(self.loop())
        async def stop(self):
            if self.task:
                self.task.cancel()
                try:await self.task
                except asyncio.CancelledError:pass
                self.task=None
        async def loop(self):
            while True:
                try:await asyncio.to_thread(self.tick)
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Scheduler tick failed')
                await asyncio.sleep(1)
        def tick(self,now=None):
            now=time.time() if now is None else now
            with closing(b.storage.connect(b.DB)) as db:rows=db.execute("SELECT owner,payload FROM records WHERE kind='job' AND owner IS NOT NULL").fetchall()
            for owner,text in rows:
                job=json.loads(text)
                if not job['enabled'] or job.get('lease_until',0)>now or job['next_run_at']>now:continue
                token=owner_context.set(owner)
                try:
                    try:perform(job['id'])
                    except HTTPException as exc:
                        if exc.status_code!=409:raise
                finally:owner_context.reset(token)
            if hasattr(b,'event_hub'):b.event_hub.deliver_pending()
        def run(self,id):return perform(id,True)
    scheduler=Scheduler()
    @app.get('/api/datasets')
    def datasets():return [{'id':d['id'],'name':d['name'],'created_at':d['created_at'],'rows':d['profile']['rows'],'kind':'database_snapshot' if 'provenance' in d else 'csv'} for d in b.listing('dataset',compact=True)]
    @app.get('/api/jobs')
    def jobs():return b.listing('job')
    @app.post('/api/jobs')
    def create(p:JobInput):
        validate_sources(p)
        return b.save('job',p.model_dump()|{'name':p.name.strip(),'state':'scheduled' if p.enabled else 'paused','next_run_at':time.time()+p.interval_seconds,'lease_until':0,'last_status':'not_run','last_error':None})
    @app.put('/api/jobs/{id}')
    def update(id:str,p:JobInput):
        validate_sources(p)
        if b.get('job',id).get('lease_until',0)>time.time():raise HTTPException(409,'Wait for the running job to finish before changing its inputs.')
        return replace(id,p.model_dump()|{'name':p.name.strip(),'state':'scheduled' if p.enabled else 'paused','next_run_at':time.time()+p.interval_seconds})
    @app.post('/api/jobs/{id}/enabled')
    def toggle(id:str,p:ToggleInput):
        job=b.get('job',id)
        return replace(id,{'enabled':p.enabled,'state':'running' if job.get('lease_until',0)>time.time() else ('scheduled' if p.enabled else 'paused'),'next_run_at':time.time()+job['interval_seconds']})
    @app.post('/api/jobs/{id}/run')
    def run_now(id:str):return scheduler.run(id)
    @app.get('/api/events')
    def events():return b.listing('event')[:100]
    @app.get('/api/notifications')
    def notifications(page:int=Query(1,ge=1),page_size:int=Query(5,ge=1,le=50)):
        owner=require_owner()
        with closing(b.storage.connect(b.DB)) as db:
            b.storage.begin_read(db)
            total=db.execute("SELECT count(*) FROM records WHERE kind='event' AND owner=?",(owner,)).fetchone()[0]
            pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
            rows=db.execute("SELECT payload FROM records WHERE kind='event' AND owner=? ORDER BY rowid DESC LIMIT ? OFFSET ?",(owner,page_size,(page-1)*page_size)).fetchall()
        return {'items':[json.loads(r[0]) for r in rows],'total':total,'page':page,'pages':pages,'page_size':page_size}
    return scheduler
