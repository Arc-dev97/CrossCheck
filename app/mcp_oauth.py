"""MCP OAuth authorization server built on the official SDK handlers (PKCE/DCR)."""
import hashlib,json,secrets,time,html
from contextlib import closing
from urllib.parse import urlsplit,urlencode
from pydantic import AnyHttpUrl
from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse,Response
from mcp.server.auth.routes import create_auth_routes
from mcp.server.auth.settings import ClientRegistrationOptions,RevocationOptions
from mcp.server.auth.provider import AuthorizationCode,RefreshToken,AccessToken,TokenError,AuthorizeError,RegistrationError
from mcp.shared.auth import OAuthClientInformationFull,OAuthToken
from app.auth import require_owner

SCOPES=['reconcile']
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
class Provider:
    def __init__(self,b):self.b=b
    def init_db(self):
        with closing(self.b.sqlite3.connect(self.b.DB)) as db,db:
            db.execute('CREATE TABLE IF NOT EXISTS oauth_store (kind TEXT,key TEXT,payload TEXT,PRIMARY KEY(kind,key))')
    def put(self,kind,key,value):
        with closing(self.b.sqlite3.connect(self.b.DB)) as db,db:db.execute('INSERT OR REPLACE INTO oauth_store VALUES (?,?,?)',(kind,key,json.dumps(value)))
    def read(self,kind,key):
        with closing(self.b.sqlite3.connect(self.b.DB)) as db:
            row=db.execute('SELECT payload FROM oauth_store WHERE kind=? AND key=?',(kind,key)).fetchone()
        return json.loads(row[0]) if row else None
    def consume(self,kind,key):
        with closing(self.b.sqlite3.connect(self.b.DB)) as db,db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT payload FROM oauth_store WHERE kind=? AND key=?',(kind,key)).fetchone()
            if row:db.execute('DELETE FROM oauth_store WHERE kind=? AND key=?',(kind,key))
        return json.loads(row[0]) if row else None
    async def get_client(self,id):
        data=self.read('client',id)
        return OAuthClientInformationFull.model_validate(data) if data else None
    async def register_client(self,client):
        if not client.redirect_uris or len(client.redirect_uris)>10:raise RegistrationError('invalid_redirect_uri','Register 1 to 10 exact redirect URIs.')
        for uri in client.redirect_uris:
            u=urlsplit(str(uri))
            if u.username or u.password or u.fragment or (u.scheme!='https' and not(u.scheme=='http' and u.hostname in ('localhost','127.0.0.1','::1'))):
                raise RegistrationError('invalid_redirect_uri','HTTPS or loopback redirect required.')
        self.put('client',client.client_id,client.model_dump(mode='json'))
    async def authorize(self,client,params):
        resource=self.b.public_base_url+'/mcp/'
        if params.resource and params.resource.rstrip('/')!=resource.rstrip('/'):raise AuthorizeError('invalid_request','Unexpected resource audience.')
        if not params.scopes or set(params.scopes)!=set(SCOPES):raise AuthorizeError('invalid_scope','Only reconcile scope is supported.')
        id=secrets.token_urlsafe(32)
        self.put('pending',digest(id),{'client_id':client.client_id,'params':params.model_dump(mode='json'),'expires':time.time()+600,'csrf':secrets.token_urlsafe(32)})
        return self.b.public_base_url+'/oauth/consent?request_id='+id
    async def load_authorization_code(self,client,code):
        data=self.read('code',digest(code))
        if not data or data['client_id']!=client.client_id:return None
        return AuthorizationCode(code=code,**data)
    def mint(self,owner,client_id,scopes,resource,family=None):
        family=family or secrets.token_urlsafe(24);access=secrets.token_urlsafe(40);refresh=secrets.token_urlsafe(48);now=int(time.time())
        base={'subject':owner,'client_id':client_id,'scopes':scopes,'resource':resource,'family':family}
        self.put('access',digest(access),base|{'expires_at':now+3600})
        self.put('refresh',digest(refresh),base|{'expires_at':now+30*86400})
        return OAuthToken(access_token=access,refresh_token=refresh,expires_in=3600,scope=' '.join(scopes))
    async def exchange_authorization_code(self,client,code):
        data=self.consume('code',digest(code.code))
        if not data or data['expires_at']<time.time() or data['client_id']!=client.client_id:raise TokenError('invalid_grant','Code expired or already used.')
        return self.mint(data['subject'],client.client_id,code.scopes,code.resource)
    async def load_refresh_token(self,client,refresh):
        data=self.read('refresh',digest(refresh))
        if not data or data['client_id']!=client.client_id or self.read('revoked',data['family']):return None
        return RefreshToken(token=refresh,**{k:v for k,v in data.items() if k!='family'})
    async def exchange_refresh_token(self,client,refresh,scopes):
        data=self.consume('refresh',digest(refresh.token))
        if not data or data['expires_at']<time.time() or data['client_id']!=client.client_id or self.read('revoked',data['family']):raise TokenError('invalid_grant','Refresh token expired, revoked or already used.')
        if not set(scopes).issubset(data['scopes']):raise TokenError('invalid_scope','Cannot expand granted scopes.')
        return self.mint(data['subject'],client.client_id,scopes,data['resource'],data['family'])
    async def load_access_token(self,token):
        data=self.read('access',digest(token))
        if not data or data['expires_at']<=time.time() or self.read('revoked',data['family']):return None
        if data['resource'].rstrip('/')!=(self.b.public_base_url+'/mcp/').rstrip('/'):return None
        with closing(self.b.sqlite3.connect(self.b.DB)) as db:
            if not db.execute('SELECT id FROM users WHERE id=?',(data['subject'],)).fetchone():return None
        return AccessToken(token=token,claims={'grant_family':data['family']},**{k:v for k,v in data.items() if k!='family'})
    async def revoke_token(self,token):
        kind='refresh' if isinstance(token,RefreshToken) else 'access'
        data=self.read(kind,digest(token.token))
        if data:self.put('revoked',data['family'],{'revoked_at':time.time()})

def install_oauth(app,b):
    provider=Provider(b);provider.init_db();b.mcp_oauth=provider
    # SDK 1.x revocation model requires a client_secret even for public clients.
    # Keep SDK client authentication while accepting RFC7009 public-client requests.
    from mcp.server.auth.middleware.client_auth import ClientAuthenticator,AuthenticationError
    authenticator=ClientAuthenticator(provider)
    @app.post('/revoke')
    async def revoke(request:Request):
        try:client=await authenticator.authenticate_request(request)
        except AuthenticationError:return JSONResponse({'error':'invalid_client'},status_code=401)
        form=await request.form();raw=form.get('token')
        if not raw:return JSONResponse({'error':'invalid_request'},status_code=400)
        token=await provider.load_refresh_token(client,str(raw))
        if token is None:token=await provider.load_access_token(str(raw))
        if token and token.client_id==client.client_id:await provider.revoke_token(token)
        return Response(status_code=200,headers={'Cache-Control':'no-store'})
    app.router.routes.extend(create_auth_routes(provider,AnyHttpUrl(b.public_base_url),client_registration_options=ClientRegistrationOptions(enabled=True,valid_scopes=SCOPES,default_scopes=SCOPES),revocation_options=RevocationOptions(enabled=True)))
    @app.get('/.well-known/oauth-protected-resource')
    @app.get('/.well-known/oauth-protected-resource/mcp')
    @app.get('/.well-known/oauth-protected-resource/mcp/')
    def protected_resource():return {'resource':b.public_base_url+'/mcp/','authorization_servers':[b.public_base_url],'scopes_supported':SCOPES,'bearer_methods_supported':['header']}
    @app.get('/oauth/consent')
    async def consent(request:Request,request_id:str):
        pending=provider.read('pending',digest(request_id))
        if not pending or pending['expires']<time.time():raise HTTPException(400,'Authorization request expired. Reconnect from the assistant.')
        if not request.state.user:return RedirectResponse('/auth/google?'+urlencode({'next':'/oauth/consent?request_id='+request_id}),status_code=303)
        client=await provider.get_client(pending['client_id'])
        name=html.escape(client.client_name or 'MCP client');uri=html.escape(pending['params']['redirect_uri'])
        # Bind consent to the signed-in browser and owner, independently of OAuth client state.
        request.session['consent_request']=request_id
        request.session['consent_owner']=request.state.user['id']
        return HTMLResponse(f'''<!doctype html><html><head><meta charset="utf-8"><title>Connect Reconcile</title><style>body{{font:16px Segoe UI;background:#f5f7fa;color:#193139;max-width:600px;margin:80px auto;padding:24px}}main{{background:white;border:1px solid #dde5ea;border-radius:12px;padding:32px}}button{{padding:12px 20px;background:#087c70;border:0;border-radius:6px;color:white;margin-right:10px}}p{{line-height:1.7}}code{{word-break:break-all}}</style></head><body><main><h1>Connect {name}?</h1><p>Signed in as <b>{html.escape(request.state.user['email'])}</b>.</p><p>This client can read your uploaded data, reconciliation results and scheduled-job events, upload CSV data you supply, and create editable drafts. It cannot execute final runs or change schedules through MCP tools.</p><p>Return destination: <code>{uri}</code></p><form method="post" action="/oauth/consent"><input type="hidden" name="request_id" value="{html.escape(request_id)}"><input type="hidden" name="csrf" value="{pending['csrf']}"><button name="decision" value="allow">Allow connection</button><button name="decision" value="deny">Cancel</button></form></main></body></html>''')
    @app.post('/oauth/consent')
    async def decide(request:Request):
        owner=require_owner();form=await request.form();id=str(form.get('request_id',''));pending=provider.read('pending',digest(id))
        if not pending or pending['expires']<time.time() or request.session.get('consent_request')!=id or request.session.get('consent_owner')!=owner or not secrets.compare_digest(str(form.get('csrf','')),pending['csrf']):raise HTTPException(400,'Invalid or expired consent.')
        provider.consume('pending',digest(id));request.session.pop('consent_request',None);request.session.pop('consent_owner',None)
        params=pending['params'];query={'state':params['state']} if params.get('state') is not None else {}
        if form.get('decision')=='allow':
            code=secrets.token_urlsafe(40)
            provider.put('code',digest(code),{'scopes':params['scopes'],'expires_at':time.time()+120,'client_id':pending['client_id'],'code_challenge':params['code_challenge'],'redirect_uri':params['redirect_uri'],'redirect_uri_provided_explicitly':params['redirect_uri_provided_explicitly'],'resource':b.public_base_url+'/mcp/','subject':owner})
            query['code']=code
        else:query['error']='access_denied'
        target=params['redirect_uri']+('&' if '?' in params['redirect_uri'] else '?')+urlencode(query)
        return RedirectResponse(target,status_code=303)
    return provider
