# CrossCheck free deployment

CrossCheck runs as one Python web service on Render Free. Its durable application state lives in separate Supabase PostgreSQL schemas, so a sleeping or restarted service does not erase recipes, account records, snapshots or run history. No paid disk or always-on plan is required for this demo.

## Runtime settings

- Python 3.12 from .python-version. Install requirements.lock.txt; pywin32 is Windows-only.
- Build: pip install -r requirements.lock.txt
- Start: uvicorn server:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips '*'
- Singapore region, Free compute, one worker, no persistent disk. Auto-deploy disabled during validation.
- Health check: /api/auth/me.
- Private environment: CROSSCHECK_DATABASE_URL, APP_SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET.
- The assigned Render HTTPS address is read from RENDER_EXTERNAL_URL. Optional APP_BASE_URL/PUBLIC_BASE_URL overrides must equal that address; do not copy localhost or old tunnel overrides to Render.
- RENDER_GIT_COMMIT provides the deployed source revision in diagnostic records.

The app fails startup on Render if durable storage or a stable APP_SECRET_KEY is missing. Local development still defaults to the original SQLite database and local signing-key file. Only trust forwarded headers from the hosting provider's managed proxy.

## Storage and migration

The dedicated state role owns crosscheck_state and the isolated crosscheck_qa schemas. It has no privileges on reconcile_demo source tables. Runtime reads of those tables still use the separate encrypted SELECT-only source connection. App-state schemas are not public API schemas; public/anon/authenticated grants are revoked and RLS is enabled.

Run tools/setup_hosted_storage.py locally for the one-time setup. The existing database admin password is entered using getpass, never stored. The helper creates limited app credentials, takes a consistent SQLite backup, bulk-copies records/users/reset archives, and pauses migrated jobs. Old browser sessions, MCP OAuth grants and webhook subscriptions are not migrated to the new public origin.

Ignored files under data/ contain the migration status, private setup metadata and render-secrets.env. They are never Git-tracked. APP_SECRET_KEY must match the original local signing material so saved source credentials can still be decrypted. Do not regenerate it on restart.

PostgreSQL transactions and advisory locks retain write serialization, one-use token consumption and scheduler leases. Owner filters remain enforced at every app API boundary. Lists fetch metadata rather than full historical snapshots; reset archives and restoration execute inside PostgreSQL to avoid large transfers through the free web server.

## Verification and handover

1. Run the local regression suite: .venv/Scripts/python.exe -m unittest discover -s tests -q.
2. After private setup, run tools/verify_postgres.py against crosscheck_qa only. It covers API behavior, data isolation, reconnection persistence, one-use OAuth consumption, rollback/reset/undo and overlapping scheduler calls.
3. Publish source, configure the free Render form and private environment values, then deploy. Do not add a payment method, disk or paid instance.
4. Add the assigned <service-url>/auth/google/callback to the existing Google OAuth client. Keep old callbacks until the new origin is verified.
5. Verify real Google sign-in, retained source connections, live reads and one scheduled job at the new origin.
6. Reconnect the assistant at <service-url>/mcp/ with fresh authorization. Old connector grants have the previous resource audience and are not reused.
7. Restart the Render instance and confirm sign-in/state/credential decryption remain valid. Keep migrated schedules paused until the selected demo job is explicitly enabled.

## Free-service limits

Render Free sleeps after inactivity; scheduled jobs stop while asleep and resume after the service wakes. This is suitable for an interactive demo, not unattended daily monitoring. Supabase project quotas and pause rules also apply. No paid hosting has been authorized.

References: https://render.com/docs/free ; https://render.com/docs/deploy-fastapi ; https://render.com/docs/python-version ; https://www.psycopg.org/psycopg3/docs/basic/transactions.html

## Deployed service

- App: https://crosscheck-demo.onrender.com
- MCP: https://crosscheck-demo.onrender.com/mcp/
- Render service: srv-dbqiu06c6qcc73ffrogg, Singapore, Free, no disk or paid plan.
- Live application commit: e07acd558b0b02c7d1ac930274eb36d96a36a8af. Later verification/docs-only commits do not change that deployed code.
- Real Google login, retained encrypted Supabase connection/table discovery and migrated workspace access verified.
- Public MCP and 15-second synthetic scheduled-job checks passed; the synthetic workspace was removed.
- Separate service restart test was skipped to meet the user's five-minute wrap-up limit. User ChatGPT reconnection to the new origin is still required.
