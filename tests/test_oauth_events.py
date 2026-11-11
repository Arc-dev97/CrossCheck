import asyncio,base64,hashlib,json,secrets,time,unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs
from fastapi.testclient import TestClient
from app.auth import owner_context
from app.mcp_events import callback_destination,key_bytes,EVENT
from app.mcp_oauth import digest
import test_api,server
class OAuthEventTests(unittest.TestCase):
    upload=test_api.ApiTests.upload
    preview=test_api.ApiTests.preview
    tearDown=test_api.ApiTests.tearDown
    def setUp(self):
        test_api.ApiTests.setUp(self)
        self.verifier=secrets.token_urlsafe(48);self.challenge=base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip('=')
        self.original_send=server.event_hub.send
        self.sent=[]
        def fake(url,secret,event_id,body,sub,*args):
            data=json.loads(body);self.sent.append((event_id,data))
            return 200,json.dumps({'challenge':data['challenge']}).encode() if data.get('type')=='verification' else b'{}'
        server.event_hub.send=fake
    def tearDown(self):server.event_hub.send=self.original_send;test_api.ApiTests.tearDown(self)
    def register(self):
        r=self.client.post('/register',json={'client_name':'QA assistant','redirect_uris':['https://client.example/callback'],'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':'reconcile'})
        self.assertEqual(r.status_code,201,r.text);return r.json()['client_id']
    def code(self,client):
        params={'client_id':client,'redirect_uri':'https://client.example/callback','response_type':'code','scope':'reconcile','code_challenge':self.challenge,'code_challenge_method':'S256','resource':server.public_base_url+'/mcp/','state':'opaque-user-state'}
        r=self.client.get('/authorize',params=params,follow_redirects=False)
        self.assertIn(r.status_code,[302,303,307],r.text)
        location=r.headers['location'];id=parse_qs(urlsplit(location).query)['request_id'][0]
        consent=self.client.get('/oauth/consent?request_id='+id)
        self.assertEqual(consent.status_code,200)
        pending=server.mcp_oauth.read('pending',digest(id))
        done=self.client.post('/oauth/consent',data={'request_id':id,'csrf':pending['csrf'],'decision':'allow'},follow_redirects=False)
        query=parse_qs(urlsplit(done.headers['location']).query)
        self.assertEqual(query['state'],['opaque-user-state']);return query['code'][0]
    def exchange(self,client,code,verifier=None):
        return self.client.post('/token',data={'grant_type':'authorization_code','client_id':client,'code':code,'code_verifier':verifier or self.verifier,'redirect_uri':'https://client.example/callback','resource':server.public_base_url+'/mcp/'})
    def access(self):
        client=self.register();response=self.exchange(client,self.code(client));self.assertEqual(response.status_code,200,response.text)
        tokens=response.json();access=asyncio.run(server.mcp_oauth.load_access_token(tokens['access_token']))
        self.assertEqual(access.subject,'test-user-a');return client,tokens,access
    def test_pkce_replay_refresh_and_revocation(self):
        client=self.register();code=self.code(client)
        self.assertEqual(self.exchange(client,code,'wrong').status_code,400)
        tokens=self.exchange(client,code).json()
        self.assertEqual(self.exchange(client,code).status_code,400)
        self.assertEqual(self.client.post('/token',data={'grant_type':'refresh_token','client_id':client,'refresh_token':tokens['refresh_token'],'scope':'admin'}).status_code,400)
        refresh=self.client.post('/token',data={'grant_type':'refresh_token','client_id':client,'refresh_token':tokens['refresh_token']})
        self.assertEqual(refresh.status_code,200,refresh.text)
        self.assertNotEqual(refresh.json()['access_token'],tokens['access_token'])
        self.assertEqual(self.client.post('/token',data={'grant_type':'refresh_token','client_id':client,'refresh_token':tokens['refresh_token']}).status_code,400)
        revoked=self.client.post('/revoke',data={'client_id':client,'token':refresh.json()['refresh_token'],'token_type_hint':'refresh_token'})
        self.assertEqual(revoked.status_code,200,revoked.text)
        self.assertIsNone(asyncio.run(server.mcp_oauth.load_access_token(tokens['access_token'])))
        self.assertIsNone(asyncio.run(server.mcp_oauth.load_access_token(refresh.json()['access_token'])))
    def test_redirect_code_binding_and_metadata(self):
        client=self.register();other=self.register();code=self.code(client)
        self.assertEqual(self.exchange(other,code).status_code,400)
        bad=self.client.get('/authorize',params={'client_id':client,'redirect_uri':'https://evil.example/callback','response_type':'code','scope':'reconcile','code_challenge':self.challenge,'code_challenge_method':'S256'},follow_redirects=False)
        self.assertEqual(bad.status_code,400)
        for uri in ['http://evil.example/callback','https://client.example/cb#fragment','file:///bad']:
            self.assertEqual(self.client.post('/register',json={'redirect_uris':[uri],'token_endpoint_auth_method':'none'}).status_code,400)
        anon=TestClient(server.app)
        meta=anon.get('/.well-known/oauth-protected-resource/mcp').json()
        self.assertEqual(meta['resource'],server.public_base_url+'/mcp/')
        self.assertIn('resource_metadata',anon.get('/mcp/').headers['www-authenticate'])
    def test_subscribe_deliver_filter_stop(self):
        client,tokens,access=self.access();hub=server.event_hub;owner=owner_context.set('test-user-a')
        try:
            params={'name':EVENT,'arguments':{'statuses':['failed']},'delivery':{'mode':'webhook','url':'https://receiver.example/events','secret':'whsec_'+base64.b64encode(secrets.token_bytes(32)).decode()}}
            first=hub.subscribe(params,access);again=hub.subscribe(params,access)
            self.assertEqual(first['id'],again['id'])
            event=server.save('event',{'job_id':'test-job','job_name':'Daily check','status':'failed','run_id':None,'summary':{},'error':'Unknown column','delivery_status':'not_connected'})
            server.save('event',{'job_id':'test-job','job_name':'Daily check','status':'completed','run_id':'r','summary':{'matched':1},'error':None,'delivery_status':'not_connected'})
            hub.deliver_pending();events=[d for id,d in self.sent if 'eventId'in d]
            self.assertEqual(len(events),1);self.assertEqual(events[0]['eventId'],event['id'])
            self.assertEqual(server.get('event',event['id'])['delivery_status'],'accepted')
            hub.deliver_pending();self.assertEqual(len([d for _,d in self.sent if 'eventId'in d]),1)
            hub.unsubscribe(params,access)
            server.save('event',{'job_id':'test-job','job_name':'Daily','status':'failed','run_id':None,'summary':{},'error':'Bad','delivery_status':'not_connected'})
            hub.deliver_pending();self.assertEqual(len([d for _,d in self.sent if 'eventId'in d]),1)
        finally:owner_context.reset(owner)
    def test_revoked_subscription_and_retry(self):
        client,tokens,access=self.access();hub=server.event_hub;owner=owner_context.set('test-user-a')
        try:
            params={'name':EVENT,'arguments':{},'delivery':{'mode':'webhook','url':'https://receiver.example/events','secret':'whsec_'+base64.b64encode(secrets.token_bytes(32)).decode()}}
            sub=hub.subscribe(params,access)
            event=server.save('event',{'job_id':'j','job_name':'Daily','status':'failed','run_id':None,'summary':{},'error':'Bad','delivery_status':'not_connected'})
            hub.send=lambda *args:(503,b'{}')
            hub.deliver_pending()
            self.assertEqual(server.get('event',event['id'])['delivery_status'],'retrying')
            key=sub['id']+':'+event['id'];state=server.mcp_oauth.read('delivery',key);state['next_at']=0;server.mcp_oauth.put('delivery',key,state)
            hub.send=lambda *args:(410,b'{}');hub.deliver_pending()
            self.assertTrue(server.mcp_oauth.read('delivery',key)['done'])
            asyncio.run(server.mcp_oauth.revoke_token(access))
            self.assertFalse(hub.active(server.mcp_oauth.read('subscription',sub['id'])))
        finally:owner_context.reset(owner)

    def test_consent_csrf_and_expiry(self):
        client=self.register()
        r=self.client.get('/authorize',params={'client_id':client,'redirect_uri':'https://client.example/callback','response_type':'code','scope':'reconcile','code_challenge':self.challenge,'code_challenge_method':'S256'},follow_redirects=False)
        id=parse_qs(urlsplit(r.headers['location']).query)['request_id'][0]
        self.client.get('/oauth/consent?request_id='+id)
        self.assertEqual(self.client.post('/oauth/consent',data={'request_id':id,'csrf':'wrong','decision':'allow'}).status_code,400)
        p=server.mcp_oauth.read('pending',digest(id));p['expires']=0;server.mcp_oauth.put('pending',digest(id),p)
        self.assertEqual(self.client.get('/oauth/consent?request_id='+id).status_code,400)

    def test_callback_safety(self):
        for uri in ['http://example.com/x','https://user:password@example.com','https://example.com:8443/cb']:
            with self.assertRaises(ValueError):callback_destination(uri)
        for ip in ['127.0.0.1','10.0.0.1','169.254.169.254','::1','192.168.1.1']:
            with patch('app.mcp_events.socket.getaddrinfo',return_value=[(2,1,6,'',(ip,443))]):
                with self.assertRaises(ValueError):callback_destination('https://receiver.example/events')
        for secret in ['bad','whsec_abc','whsec_'+base64.b64encode(b'short').decode()]:
            with self.assertRaises(ValueError):key_bytes(secret)
