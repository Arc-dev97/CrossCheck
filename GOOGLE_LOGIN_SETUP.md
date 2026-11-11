# Google sign-in setup

The login flow is implemented, but a real Google login cannot complete until you configure your OAuth client. Do not paste the client secret into chat.

## Google Cloud

1. Open https://console.cloud.google.com/ and select/create a project.
2. Configure Google Auth Platform / OAuth consent (Branding, Audience and contact email). Use External testing and add your own Google email to the test-user list.
3. Under Clients / Credentials, create an OAuth client ID of type **Web application**.
4. Register this exact authorized redirect URI:

```
http://localhost:8000/auth/google/callback
```

5. If configuring authorized JavaScript origins, use http://localhost:8000. This server-side login does not need a browser OAuth library.
6. Copy the client ID and client secret into the existing project `.env` file:

```
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
APP_BASE_URL=http://localhost:8000
```

7. Restart the server using `.\.venv\Scripts\python.exe server.py`, open http://localhost:8000 and choose Continue with Google. Use localhost consistently; 127.0.0.1 has a different cookie scope.

Only openid, email and profile scopes are requested. No Gmail, Drive, billing or paid API access is needed for this login flow. Keep the app in testing until its public access is intentionally configured.

## What login protects

Each verified Google subject maps to its own workspace owner. Datasets, recipes, drafts, previews, runs, scheduled jobs and job events are owner-scoped. A signed-in user cannot reference another owner's IDs to read or execute their records. Sessions are opaque, HttpOnly cookies with server-side expiration and logout revocation. The OIDC flow uses Authlib for state, nonce, PKCE and ID-token verification. Secure cookies are enabled for an HTTPS APP_BASE_URL.

The old anonymous prototype records are preserved in SQLite with no owner and are inaccessible to signed-in accounts. They are not automatically assigned to the first person who signs in. Load the synthetic demos again in your own account.

## Important distinction

Google sign-in protects the website. It does not automatically make this app an MCP OAuth authorization server. The MCP endpoint is now also protected and cannot be used anonymously. Remote ChatGPT/Claude authorization still needs to be implemented and verified separately before public exposure.

No production login bypass is included. The tools/ui_test_server.py harness uses an explicitly mocked provider and a temporary database on localhost:8001 for developer UI verification only. It does not verify real Google authentication and is not started by server.py.

Reference: https://developers.google.com/identity/openid-connect/openid-connect
