"""Exercise the live local MCP transport with the official SDK; creates synthetic demo sources/draft."""
import asyncio,json,sys
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
async def main():
    # Developer fixture identity only. This tests session-scoped MCP, not Google authentication.
    token=server.issue_session({'id':'protocol-qa-fixture','email':'protocol-qa@example.test','name':'MCP protocol QA'})
    async with streamablehttp_client('http://127.0.0.1:8000/mcp/',headers={'Cookie':'reconcile_session='+token}) as (reader,writer,_):
        async with ClientSession(reader,writer) as session:
            await session.initialize()
            tools=await session.list_tools();names=[t.name for t in tools.tools]
            assert 'create_reconciliation_draft' in names
            assert not any('execute' in n for n in names)
            async def call(name,args):
                result=await session.call_tool(name,args)
                if result.isError: raise RuntimeError(str(result.content))
                return result.structuredContent or json.loads(result.content[0].text)
            sources=[]
            for name in ['employee_expenses.csv','uploaded_invoices.csv']:
                d=await call('upload_csv',{'name':name,'csv_text':(ROOT/'demo'/name).read_text()});sources.append(d['id'])
            inspected=await call('inspect_dataset',{'dataset_id':sources[0],'sample_rows':2})
            assert inspected['profile']['rows']==92
            recipe=json.loads((ROOT/'demo/expense_recipe.json').read_text())
            draft=await call('create_reconciliation_draft',{'name':'October employee expense audit — assistant draft','left_dataset_id':sources[0],'right_dataset_id':sources[1],'recipe':recipe})
            assert draft['summary']==json.loads((ROOT/'demo/expense_expected.json').read_text())
            rows=await call('inspect_results',{'record_id':draft['draft_id'],'record_type':'draft','status':'mismatch','limit':5})
            assert rows['total_filtered']==12 and len(rows['rows'])==5
            bad=await session.call_tool('create_reconciliation_draft',{'name':'Invalid','left_dataset_id':sources[0],'right_dataset_id':sources[1],'recipe':{**recipe,'left_key':'nonexistent'}})
            assert bad.isError
            print(json.dumps({'tools':names,'summary':draft['summary'],'review_url':draft['review_url'],'invalid_rule_rejected':True},indent=2))
if __name__=='__main__':asyncio.run(main())
