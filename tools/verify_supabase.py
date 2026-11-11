"""Verify the configured demo database without exposing credentials or mutating source data."""
import sys,json,hashlib
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server,psycopg
from app.auth import owner_context
from app.sources import root_certificate
from app.models import PreviewInput,Recipe

def main():
    with closing(server.sqlite3.connect(server.DB)) as db:
        rows=db.execute("SELECT owner,payload FROM records WHERE kind='connection'").fetchall()
    candidates=[(o,json.loads(p)) for o,p in rows if json.loads(p)['name']=='Supabase employee audit']
    if len(candidates)!=1:raise ValueError('Expected one configured demo connection; choose an explicit workspace before testing.')
    owner,connection=candidates[0];token=owner_context.set(owner)
    try:
        sources={s['table']:s for s in server.listing('source') if s['connection_id']==connection['id']}
        pair=server.sources.snapshot_pair(sources['employee_expenses']['id'],sources['uploaded_invoices']['id'])
        recipe=json.loads((server.ROOT/'demo/expense_recipe.json').read_text())
        result=server.preview(PreviewInput(left_id=pair['left_id'],right_id=pair['right_id'],recipe=Recipe.model_validate(recipe)))
        expected=json.loads((server.ROOT/'demo/expense_expected.json').read_text())
        assert result['summary']==expected,(result['summary'],expected)
        credentials=server.sources.decrypt(connection['credentials'])
        try:
            with psycopg.connect(**credentials,sslmode='verify-full',sslrootcert=root_certificate(),connect_timeout=8) as conn:
                conn.execute("UPDATE reconcile_demo.uploaded_invoices SET updated_at=updated_at WHERE false")
            raise AssertionError('Reader unexpectedly has source write privileges.')
        except psycopg.errors.InsufficientPrivilege:pass
        print(json.dumps({'real_supabase_snapshot':True,'tls_verify_full':True,'source_rows':pair['profiles']['left']['rows']+pair['profiles']['right']['rows'],'summary':result['summary'],'reader_write_denied':True},indent=2))
        return owner,sources
    finally:owner_context.reset(token)
if __name__=='__main__':main()
