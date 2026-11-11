"""Recoverable owner-scoped reset of generated demo records; never touches source DBs."""
import hashlib,json,threading,time,uuid
from contextlib import closing,contextmanager
from collections import Counter
from fastapi import HTTPException
from pydantic import Field
from typing import Literal
from app.auth import require_owner
from app.models import StrictModel

GENERATED=('dataset','preview','run','job','event','draft')
class ResetInput(StrictModel):
    revision:str=Field(min_length=64,max_length=64)
    confirmation:Literal['RESET_DEMO']
class UndoInput(StrictModel):
    archive_id:str=Field(min_length=1,max_length=80)

class WorkspaceManager:
    def __init__(self,b):self.b=b;self.locks={};self.lock_guard=threading.Lock()
    def lock(self,owner):
        with self.lock_guard:return self.locks.setdefault(owner,threading.RLock())
    def ensure(self,db):
        db.execute('CREATE TABLE IF NOT EXISTS workspace_archives(id TEXT PRIMARY KEY,owner TEXT NOT NULL,payload TEXT NOT NULL,created_at REAL NOT NULL,undone_at REAL)')
    def rows(self,db,owner):
        return db.execute("SELECT id,kind,payload FROM records WHERE owner=? AND kind IN ("+','.join('?' for _ in GENERATED)+") ORDER BY rowid",(owner,*GENERATED)).fetchall()
    def revision(self,owner,rows):
        h=hashlib.sha256(owner.encode())
        for row in rows:h.update(json.dumps(row,separators=(',',':')).encode())
        return h.hexdigest()
    def running(self,rows):
        return any(kind=='job' and json.loads(payload).get('lease_until',0)>time.time() for _,kind,payload in rows)
    def summary(self):
        owner=require_owner()
        with closing(self.b.sqlite3.connect(self.b.DB,timeout=10)) as db:
            self.ensure(db);rows=self.rows(db,owner)
            kept=dict(db.execute("SELECT kind,count(*) FROM records WHERE owner=? AND kind IN ('connection','source','recipe') GROUP BY kind",(owner,)))
            archive=db.execute('SELECT id,created_at FROM workspace_archives WHERE owner=? AND undone_at IS NULL ORDER BY created_at DESC LIMIT 1',(owner,)).fetchone()
        return {'counts':dict(Counter(r[1] for r in rows)),'total':len(rows),'retained':kept,'revision':self.revision(owner,rows),'running':self.running(rows),'undo':{'id':archive[0],'created_at':archive[1]} if archive else None}
    @contextmanager
    def delivery_guard(self,event_id):
        owner=require_owner()
        with self.lock(owner):
            with closing(self.b.sqlite3.connect(self.b.DB)) as db:
                alive=bool(db.execute("SELECT 1 FROM records WHERE id=? AND kind='event' AND owner=?",(event_id,owner)).fetchone())
            yield alive
    def cancel_deliveries(self,db,owner,rows,archive_id):
        # Keep cancellation tombstones across undo, so restored history is never replayed as new alerts.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='oauth_store'").fetchone():return
        subs=[json.loads(r[0]) for r in db.execute("SELECT payload FROM oauth_store WHERE kind='subscription'")]
        ids=[id for id,kind,_ in rows if kind=='event']
        for sub in subs:
            if sub['owner']!=owner:continue
            for id in ids:
                key=sub['id']+':'+id
                found=db.execute("SELECT payload FROM oauth_store WHERE kind='delivery' AND key=?",(key,)).fetchone()
                old=json.loads(found[0]) if found else {}
                state={**old,'done':True,'cancelled_by_reset':archive_id,'next_at':0}
                db.execute("INSERT OR REPLACE INTO oauth_store(kind,key,payload) VALUES ('delivery',?,?)",(key,json.dumps(state)))
    def reset(self,p):
        owner=require_owner()
        with self.lock(owner),closing(self.b.sqlite3.connect(self.b.DB,timeout=10)) as db,db:
            self.ensure(db);db.execute('BEGIN IMMEDIATE');rows=self.rows(db,owner)
            if self.running(rows):raise HTTPException(409,'A job is running. Wait for it to finish, then review the reset again.')
            if p.revision!=self.revision(owner,rows):raise HTTPException(409,'Workspace records changed. Review the updated counts before resetting.')
            if not rows:raise HTTPException(409,'There are no demo records to clear.')
            archive_id=uuid.uuid4().hex
            db.execute('INSERT INTO workspace_archives VALUES (?,?,?,?,NULL)',(archive_id,owner,json.dumps(rows),time.time()))
            self.cancel_deliveries(db,owner,rows,archive_id)
            db.execute("DELETE FROM records WHERE owner=? AND kind IN ("+','.join('?' for _ in GENERATED)+")",(owner,*GENERATED))
        return {'archive_id':archive_id,'cleared':dict(Counter(r[1] for r in rows)),'message':'Demo records cleared. Connections, live sources, recipes and sign-in are retained.'}
    def undo(self,p):
        owner=require_owner()
        with self.lock(owner),closing(self.b.sqlite3.connect(self.b.DB,timeout=10)) as db,db:
            self.ensure(db);db.execute('BEGIN IMMEDIATE')
            archive=db.execute('SELECT payload FROM workspace_archives WHERE id=? AND owner=? AND undone_at IS NULL',(p.archive_id,owner)).fetchone()
            if not archive:raise HTTPException(404,'Reset archive not found or already restored.')
            rows=json.loads(archive[0])
            for id,kind,payload in rows:
                if db.execute('SELECT 1 FROM records WHERE id=?',(id,)).fetchone():raise HTTPException(409,'Records already exist; nothing was overwritten.')
                if kind=='job':
                    job=json.loads(payload);job.update(enabled=False,state='paused',lease_until=0,next_run_at=time.time()+job['interval_seconds']);payload=json.dumps(job)
                db.execute('INSERT INTO records(id,kind,payload,owner) VALUES (?,?,?,?)',(id,kind,payload,owner))
            db.execute('UPDATE workspace_archives SET undone_at=? WHERE id=? AND owner=?',(time.time(),p.archive_id,owner))
        return {'restored':dict(Counter(r[1] for r in rows)),'message':'Demo records restored. Scheduled jobs remain paused.'}

def install_workspace(app,b):
    manager=WorkspaceManager(b)
    @app.get('/api/workspace/reset-summary')
    def summary():return manager.summary()
    @app.post('/api/workspace/reset')
    def reset(p:ResetInput):return manager.reset(p)
    @app.post('/api/workspace/undo-reset')
    def undo(p:UndoInput):return manager.undo(p)
    return manager
