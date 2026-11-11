"""Authenticated protocol smoke test through the temporary public HTTPS URL.
Uses a synthetic fixture owner; does not impersonate a real Google user.
"""
import asyncio,json,os,sys
from pathlib import Path
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull
BASE='https://course-clinton-ruled-intermediate.trycloudflare.com'
os.environ['PUBLIC_BASE_URL']=BASE
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server
async def main():
    server.issue_session({'id':'public-protocol-fixture','email':'public-qa@example.test','name':'Public protocol QA'})
    provider=server.mcp_oauth
    await provider.register_client(OAuthClientInformationFull(client_id='public-protocol-qa',client_name='Protocol QA',redirect_uris=['https://client.example/callback'],token_endpoint_auth_method='none'))
    tokens=provider.mint('public-protocol-fixture','public-protocol-qa',['reconcile'],BASE+'/mcp/')
    headers={'Authorization':'Bearer '+tokens.access_token}
    async with streamablehttp_client(BASE+'/mcp/',headers=headers) as (reader,writer,_):
        async with ClientSession(reader,writer) as session:
            result=await session.initialize()
            assert getattr(result.capabilities,'events',None) is not None
            tools=await session.list_tools();assert {'list_database_sources','snapshot_database_sources','inspect_job_diagnostics','inspect_repository_file','compare_repository_branches'}<={t.name for t in tools.tools}
            datasets=await session.call_tool('list_datasets',{})
            assert not datasets.isError
    async with httpx.AsyncClient() as client:
        r=await client.post(BASE+'/mcp/',headers=headers,json={'jsonrpc':'2.0','id':9,'method':'events/list','params':{}})
        assert r.status_code==200,r.text
        assert r.json()['result']['events'][0]['name']=='reconciliation.finished'
        rejected=await client.post(BASE+'/mcp/',headers={'Authorization':'Bearer invalid'},json={'jsonrpc':'2.0','id':10,'method':'events/list'})
        assert rejected.status_code==401
    access=await provider.load_access_token(tokens.access_token);await provider.revoke_token(access)
    print(json.dumps({'public_https_handshake':True,'tool_count':len(tools.tools),'events_capability':True,'events_discovery':True,'invalid_bearer_rejected':True,'fixture_token_revoked':True},indent=2))
if __name__=='__main__':asyncio.run(main())
