"""MCP Events webhook subscriptions and persistent, signed delivery.
Callbacks use pinned public IPs with TLS hostname verification, no redirects.
"""
import base64,hashlib,hmac,html,http.client,ipaddress,json,secrets,socket,ssl,time
from datetime import datetime,timezone
from contextlib import closing
from urllib.parse import urlsplit
from cryptography.fernet import Fernet
from fastapi import HTTPException,Request
from fastapi.responses import JSONResponse
from app.auth import require_owner,owner_context

EVENT='reconciliation.finished'
def iso(epoch):return datetime.fromtimestamp(epoch,timezone.utc).isoformat()
def key_bytes(secret):
    if not isinstance(secret,str) or not secret.startswith('whsec_'):raise ValueError('A whsec_ signing secret is required.')
    try:key=base64.b64decode(secret[6:],validate=True)
    except Exception:raise ValueError('Invalid webhook signing secret.')
    if not 24<=len(key)<=64:raise ValueError('Webhook key must contain 24 to 64 bytes.')
    return key

def callback_destination(url):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or (parsed.port and parsed.port!=443):raise ValueError('Callback must be HTTPS on port 443, without credentials or fragment.')
    addresses=list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise ValueError('Callback must resolve only to public IP addresses.')
    return parsed,addresses

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,hostname,ip):super().__init__(hostname,443,timeout=5,context=ssl.create_default_context());self.ip=ip
    def connect(self):
        raw=socket.create_connection((self.ip,443),self.timeout)
        self.sock=self._context.wrap_socket(raw,server_hostname=self.host)

def send_webhook(url,secret,event_id,body,subscription_id,old_secret=None):
    parsed,addresses=callback_destination(url);timestamp=str(int(time.time()))
    message=event_id.encode()+b'.'+timestamp.encode()+b'.'+body
    signatures=['v1,'+base64.b64encode(hmac.new(key_bytes(s),message,hashlib.sha256).digest()).decode() for s in [secret,old_secret] if s]
    conn=PinnedHTTPS(parsed.hostname,addresses[0])
    try:
        conn.request('POST',(parsed.path or '/')+('?' + parsed.query if parsed.query else ''),body=body,headers={'Content-Type':'application/json','webhook-id':event_id,'webhook-timestamp':timestamp,'webhook-signature':' '.join(signatures),'X-MCP-Subscription-Id':subscription_id})
        response=conn.getresponse();status=response.status;data=response.read(65537)
        if len(data)>65536:raise ValueError('Callback response too large.')
        return status,data
    finally:conn.close()

class EventHub:
    def __init__(self,b):
        self.b=b;self.store=b.mcp_oauth;self.send=send_webhook
        material=(b.DATA/'session-signing.key').read_bytes()
        self.cipher=Fernet(base64.urlsafe_b64encode(hashlib.sha256(material).digest()))
    def protect(self,s):return self.cipher.encrypt(s.encode()).decode()
    def unprotect(self,s):return self.cipher.decrypt(s.encode()).decode()
    def all(self,kind):
        with closing(self.b.sqlite3.connect(self.b.DB)) as db:rows=db.execute('SELECT payload FROM oauth_store WHERE kind=?',(kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]
    def catalog(self):return {'events':[{'name':EVENT,'description':'A scheduled reconciliation completed, completed with discrepancies, or failed. Use read tools to inspect evidence.','delivery':['webhook'],'inputSchema':{'type':'object','properties':{'job_id':{'type':'string'},'statuses':{'type':'array','items':{'enum':['completed','completed_with_discrepancies','failed']}}},'additionalProperties':False},'payloadSchema':{'type':'object','properties':{'job_id':{'type':'string'},'job_name':{'type':'string'},'status':{'type':'string'},'run_id':{'type':['string','null']},'summary':{'type':'object'},'error':{'type':['string','null']},'url':{'type':'string'}},'required':['job_id','job_name','status','run_id','summary','error','url'],'additionalProperties':False}}]}
    def filters(self,args):
        if not isinstance(args,dict) or set(args)-{'job_id','statuses'}:raise ValueError('Unsupported event filter.')
        if 'job_id' in args:
            if not isinstance(args['job_id'],str) or not args['job_id']:raise ValueError('job_id must be a nonempty string.')
            self.b.get('job',args['job_id'])
        statuses=args.get('statuses',[])
        if not isinstance(statuses,list) or any(s not in ('completed','completed_with_discrepancies','failed') for s in statuses):raise ValueError('Unsupported status filter.')
        return {**({'job_id':args['job_id']} if 'job_id'in args else {}),**({'statuses':sorted(set(statuses))} if statuses else {})}
    def identify(self,owner,client,url,args):return hashlib.sha256(json.dumps([owner,client,url,EVENT,args],sort_keys=True).encode()).hexdigest()
    def subscribe(self,params,access):
        owner=require_owner()
        if not access:raise ValueError('An OAuth bearer token is required to subscribe.')
        if params.get('name')!=EVENT:raise ValueError('Unknown event name.')
        args=self.filters(params.get('arguments',{}));delivery=params.get('delivery',{})
        if not isinstance(delivery,dict):raise ValueError('Invalid webhook delivery settings.')
        if delivery.get('mode')!='webhook':raise ValueError('Only webhook delivery is supported.')
        url=delivery.get('url','');secret=delivery.get('secret');key_bytes(secret)
        id=self.identify(owner,access.client_id,url,args)
        challenge=secrets.token_urlsafe(32);body=json.dumps({'type':'verification','challenge':challenge},separators=(',',':')).encode()
        try:status,data=self.send(url,secret,'verify_'+secrets.token_hex(16),body,id)
        except Exception:raise ValueError('Callback verification could not connect to an approved public HTTPS destination.')
        try:echo=json.loads(data).get('challenge','')
        except Exception:echo=''
        if not 200<=status<300 or not secrets.compare_digest(echo,challenge):raise ValueError('Callback verification failed.')
        now=time.time();previous=self.store.read('subscription',id)
        ttl=params.get('ttlMs',3600000)
        if ttl is not None and (not isinstance(ttl,int) or isinstance(ttl,bool) or ttl<=0):raise ValueError('ttlMs must be a positive integer or null.')
        expires=now+min(max((ttl or 3600000)/1000,60),86400)
        encrypted=self.protect(secret)
        sub={'id':id,'owner':owner,'client_id':access.client_id,'family':access.claims['grant_family'],'name':EVENT,'arguments':args,'url':url,'secret':encrypted,'expires':expires,'active':True,'since':previous['since'] if previous and self.active(previous) else iso(now),'updated_at':iso(now)}
        if previous and self.unprotect(previous['secret'])!=secret:sub.update(old_secret=previous['secret'],old_secret_until=now+60)
        self.store.put('subscription',id,sub)
        return {'id':id,'refreshBefore':iso(expires),'cursor':None,'truncated':False}
    def unsubscribe(self,params,access):
        if not access:raise ValueError('OAuth is required.')
        if params.get('name')!=EVENT:raise ValueError('Unknown event name.')
        args=self.filters(params.get('arguments',{}));delivery=params.get('delivery',{})
        id=self.identify(require_owner(),access.client_id,delivery.get('url',''),args);sub=self.store.read('subscription',id)
        if sub:sub['active']=False;self.store.put('subscription',id,sub)
        return {}
    def active(self,sub):
        if not sub['active'] or sub['expires']<=time.time() or self.store.read('revoked',sub['family']):return False
        with closing(self.b.sqlite3.connect(self.b.DB)) as db:return bool(db.execute('SELECT id FROM users WHERE id=?',(sub['owner'],)).fetchone())
    def public_subscriptions(self):
        owner=require_owner()
        return [{k:s[k] for k in ('id','name','arguments','expires','updated_at')}|{'active':self.active(s)} for s in self.all('subscription') if s['owner']==owner]
    def update_event(self,event,changes):
        event={**event,**changes}
        with closing(self.b.sqlite3.connect(self.b.DB)) as db,db:db.execute("UPDATE records SET payload=? WHERE id=? AND owner=? AND kind='event'",(json.dumps(event),event['id'],require_owner()))
    def deliver_pending(self):
        subs=[s for s in self.all('subscription') if self.active(s)]
        attempted=0
        for sub in subs:
            token=owner_context.set(sub['owner'])
            try:
                for event in reversed(self.b.listing('event')):
                    args=sub['arguments']
                    if event['created_at']<sub['since'] or (args.get('job_id') and args['job_id']!=event['job_id']) or (args.get('statuses') and event['status']not in args['statuses']):continue
                    with self.b.workspace.delivery_guard(event['id']) as alive:
                        if not alive:continue
                        key=sub['id']+':'+event['id'];state=self.store.read('delivery',key) or {'attempts':0,'next_at':0}
                        if state.get('done') or state['next_at']>time.time():continue
                        if attempted>=5:return
                        # Re-check immediately before every delivery, including pending retries.
                        current=self.store.read('subscription',sub['id'])
                        if not current or not self.active(current):break
                        sub=current
                        payload={'eventId':event['id'],'name':EVENT,'timestamp':event['created_at'],'data':{k:event.get(k) for k in ('job_id','job_name','status','run_id','summary','error')}|{'url':self.b.public_base_url+'/#scheduled'},'cursor':None}
                        body=json.dumps(payload,separators=(',',':')).encode()
                        try:
                            if len(body)>262144:raise ValueError('Event exceeds 256 KiB.')
                            status,_=self.send(sub['url'],self.unprotect(sub['secret']),event['id'],body,sub['id'],self.unprotect(sub['old_secret']) if sub.get('old_secret_until',0)>time.time() else None)
                            accepted=200<=status<300
                        except Exception:status=0;accepted=False
                        attempted+=1;attempts=state['attempts']+1;done=accepted or attempts>=5 or status in (400,401,403,404,410,413)
                        state={'attempts':attempts,'next_at':time.time()+min(5*2**attempts,300),'done':done,'status':status,'accepted':accepted}
                        self.store.put('delivery',key,state)
                        previous=event.get('delivery_status')
                        # Never downgrade an event already accepted by another subscribed destination.
                        result='accepted' if accepted or previous=='accepted' else ('failed' if done else 'retrying')
                        self.update_event(event,{'delivery_status':result,'delivery_attempts':attempts,'message':'Webhook accepted; assistant processing is asynchronous.' if accepted else 'Webhook delivery failed.' if done else 'Webhook delivery will retry.'})
            finally:owner_context.reset(token)

class EventGateway:
    def __init__(self,app,hub):self.app=app;self.hub=hub
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['method']!='POST':return await self.app(scope,receive,send)
        request=Request(scope,receive);body=await request.body()
        try:data=json.loads(body)
        except Exception:data={}
        method=data.get('method') if isinstance(data,dict) else None
        if isinstance(method,str) and method.startswith('events/'):
            try:
                require_owner();params=data.get('params')or{};access=scope.get('state',{}).get('mcp_token')
                if not isinstance(params,dict):raise ValueError('Event parameters must be an object.')
                import asyncio
                if method=='events/list':result=self.hub.catalog()
                elif method=='events/subscribe':result=await asyncio.to_thread(self.hub.subscribe,params,access)
                elif method=='events/unsubscribe':result=self.hub.unsubscribe(params,access)
                else:raise ValueError('Unsupported events method.')
                response={'jsonrpc':'2.0','id':data.get('id'),'result':result}
            except (ValueError,HTTPException) as exc:
                response={'jsonrpc':'2.0','id':data.get('id'),'error':{'code':-32602,'message':str(exc.detail)if isinstance(exc,HTTPException)else str(exc)}}
            return await JSONResponse(response)(scope,receive,send)
        sent=False
        async def replay():
            nonlocal sent
            if not sent:sent=True;return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        return await self.app(scope,replay,send)
