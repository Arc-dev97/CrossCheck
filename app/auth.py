"""Google OIDC sign-in and opaque server-side sessions. No development login bypass."""
import hashlib, os, secrets, time
from contextvars import ContextVar
from contextlib import closing
from pathlib import Path
from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

owner_context=ContextVar('reconcile_owner',default=None)
def require_owner():
    owner=owner_context.get()
    if not owner: raise HTTPException(401,'Sign in to access your workspace.')
    return owner

def install_auth(app,b):
    load_dotenv(b.ROOT/'.env')
    base=os.getenv('APP_BASE_URL','http://localhost:8000').rstrip('/')
    secure=base.startswith('https://')
    client_id=os.getenv('GOOGLE_CLIENT_ID','').strip();secret=os.getenv('GOOGLE_CLIENT_SECRET','').strip()
    configured=bool(client_id and secret)
    key_path=b.DATA/'session-signing.key'
    if not key_path.exists(): key_path.write_text(secrets.token_urlsafe(48))
    app.add_middleware(SessionMiddleware,secret_key=key_path.read_text().strip(),session_cookie='oidc_flow',max_age=600,same_site='lax',https_only=secure)
    with closing(b.sqlite3.connect(b.DB)) as db,db:
        db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, expires REAL NOT NULL)')
    oauth=OAuth()
    if configured:oauth.register(name='google',client_id=client_id,client_secret=secret,server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',client_kwargs={'scope':'openid email profile','code_challenge_method':'S256'})
    b.oauth=oauth;b.auth_configured=configured;b.base_url=base
    b.public_base_url=os.getenv('PUBLIC_BASE_URL',base).rstrip('/')
    def issue_session(user):
        token=secrets.token_urlsafe(40)
        with closing(b.sqlite3.connect(b.DB)) as db,db:
            db.execute('INSERT OR REPLACE INTO users VALUES (?,?,?)',(user['id'],user['email'],user['name']))
            db.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],time.time()+7*86400))
        return token
    b.issue_session=issue_session
    def resolve_session(token):
        if not token:return None
        with closing(b.sqlite3.connect(b.DB)) as db:
            row=db.execute('SELECT users.id,users.email,users.name FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        return dict(zip(('id','email','name'),row)) if row else None
    b.resolve_session=resolve_session
    @app.middleware('http')
    async def identity(request,call_next):
        user=resolve_session(request.cookies.get('reconcile_session'))
        path=request.url.path
        request.state.mcp_token=None
        if path.startswith('/mcp') and request.headers.get('authorization','').lower().startswith('bearer '):
            access=await b.mcp_oauth.load_access_token(request.headers['authorization'][7:])
            if access:
                user={'id':access.subject,'email':'MCP connection','name':'Authorized MCP client'}
                request.state.mcp_token=access
            else:user=None
        request.state.user=user
        token=owner_context.set(user['id'] if user else None)
        try:
            path=request.url.path
            if (path.startswith('/api/') and path!='/api/auth/me') or path.startswith('/mcp') or path in ('/docs','/openapi.json','/redoc'):
                if not user:
                    headers={'WWW-Authenticate':'Bearer resource_metadata="'+b.public_base_url+'/.well-known/oauth-protected-resource/mcp"'} if path.startswith('/mcp') else {}
                    return JSONResponse({'error':'Authentication required.'},status_code=401,headers=headers)
            response=await call_next(request)
            response.headers['Cache-Control']='no-store'
            if request.url.scheme=='https':
                response.raw_headers=[(k,v+b'; Secure' if k.lower()==b'set-cookie' and b'; secure' not in v.lower() else v) for k,v in response.raw_headers]
            return response
        finally:owner_context.reset(token)
    @app.get('/api/auth/me')
    def me(request:Request):
        return {'authenticated':bool(request.state.user),'user':request.state.user,'google_configured':configured}
    @app.get('/auth/google')
    async def login(request:Request):
        if not configured:return RedirectResponse('/?login_error=setup_required',status_code=303)
        next_path=request.query_params.get('next','/')
        request.session['return_to']=next_path if next_path.startswith('/') and not next_path.startswith('//') else '/'
        public=b.public_base_url
        callback_base=public if str(request.base_url).rstrip('/')==public else base
        return await oauth.google.authorize_redirect(request,callback_base+'/auth/google/callback')
    @app.get('/auth/google/callback')
    async def callback(request:Request):
        if not configured:raise HTTPException(503,'Google sign-in is not configured.')
        try:
            token=await oauth.google.authorize_access_token(request)
            info=token.get('userinfo')
            if not info or not info.get('sub') or info.get('email_verified') is not True:raise ValueError('Unverified identity')
            owner=hashlib.sha256(('google:'+info['sub']).encode()).hexdigest()
            value=issue_session({'id':owner,'email':info['email'],'name':info.get('name') or info['email']})
        except Exception:
            request.session.clear()
            return RedirectResponse('/?login_error=sign_in_failed',status_code=303)
        next_path=request.session.get('return_to','/')
        request.session.clear();response=RedirectResponse(next_path,status_code=303)
        response.set_cookie('reconcile_session',value,httponly=True,secure=(secure or request.url.scheme=='https'),samesite='lax',max_age=7*86400,path='/')
        return response
    @app.post('/auth/logout')
    def logout(request:Request):
        origin=request.headers.get('origin')
        if origin and origin not in (base,b.public_base_url):raise HTTPException(403,'Invalid origin')
        token=request.cookies.get('reconcile_session','')
        with closing(b.sqlite3.connect(b.DB)) as db,db:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(token.encode()).hexdigest(),))
        response=RedirectResponse('/',status_code=303);response.delete_cookie('reconcile_session');return response
