# CrossCheck

Google login is now required. Follow GOOGLE_LOGIN_SETUP.md to add your Google Web OAuth client credentials locally in .env and restart the server. The user has verified real Google sign-in and cross-account isolation. No development bypass exists in server.py.

Run `.\.venv\Scripts\python.exe server.py` and open http://localhost:8000. Keep localhost as the canonical host. API docs at /docs also require login.

Install with `python -m venv .venv` then `.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt`. Run tests with `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.

43 engine/API/auth/scheduler/OAuth/event/live-source/GitHub/recoverable-reset tests pass. Browser QA verified the timer, pause/manual run, job editing and failed-run handling using a mocked provider and temporary database. Real Google login/isolation and ChatGPT tool flows were verified separately. Claude testing is deferred. Automatic ChatGPT responses remain unverified.

## Architecture

FastAPI + Authlib Google OpenID Connect + opaque server sessions + owner-scoped SQLite storage. Python CSV/dictionary/Decimal reconciliation remains deterministic. No DuckDB or AI inference is required. Preserved source rows, reusable recipe versions, immutable previews and runs, CSV exports, and assistant draft review are implemented.

## Scheduling

Scheduled jobs select two fixed saved versions or two live Supabase table sources, a saved recipe, and an interval. Live jobs fetch a consistent new snapshot on every attempt. Minimum 15 seconds; maximum 7 days. The server process owns the scheduler. SQLite leases prevent overlap. Jobs persist across restart but cannot run while the server is offline. Overdue jobs run once when it returns. Each attempt creates a completion/discrepancy/failure event; no assistant push notification is claimed as delivered.

## Data and isolation

All datasets, recipes, drafts, previews, runs, jobs and events are scoped to verified Google identities. Original anonymous prototype records remain in the database with no owner and are not assigned to the first account. New users can reload demo examples in their own workspace. Uploaded files, snapshots and sessions are stored in data/workspace.sqlite3. Session-signing material is stored under ignored data/. .env is ignored. Do not commit these files.

## Demos

Inventory: 62 + 61 rows. Employee audit: 92 + 91 rows, 15 synthetic employees. See demo/EMPLOYEE_AUDIT.md. Files are CSV exports; PDF/OCR and employee-level aggregation are not implemented.

## MCP and access

See MCP_CONNECTIONS.md and CURRENT_CONNECTION.md. Standard MCP tools, remote OAuth, native MCP Events subscriptions and signed webhook delivery are implemented. Real ChatGPT OAuth, tool reads, editable draft creation, event subscription and HTTP-accepted delivery have been tested. The generated automatic task response is still being verified; do not conflate webhook acceptance with a visible ChatGPT notification. Claude account testing is deferred at user request. Claude Code Channels is not implemented.

An authorized temporary HTTPS tunnel proxies to the updated app on port 8002. The stale localhost:8000 process was stopped during the live-source upgrade. Use the HTTPS endpoint for the current integration demo. No permanent deployment has been made.

## Limitations

Two CSV or Supabase table sources, one exact matching key each, text/numeric comparisons. No fuzzy matching, many-to-many matching, arbitrary SQL/code, automatic source writes, automatic retention policies, or direct cloud storage integration. Numeric inputs are limited to 100 digits and exponent magnitude 100; each CSV is capped at 3.5 MB and 50,000 rows. Exported results include source records and escape formula-like key cells. File jobs pin saved versions; database jobs fetch fresh tables on each run. See LIVE_SOURCES_SETUP.md and IMPLEMENTATION_PLAN.md for the new workflow and remaining live setup checks.

## Workspace navigation and demo reset

CrossCheck uses five tabs: Run once, Scheduled jobs, Run history, Data sources and Notifications. Unsaved comparison inputs survive tab switches. Historical reports open separately from the current comparison. Assistant-created drafts can be loaded from Run once or their review links.

Use the account menu → Reset demo data to review and clear only your generated datasets/snapshots, previews, runs, jobs, events and drafts. Connections, live sources, saved recipes, sign-in and actual Supabase tables are retained. The UI requires explicit confirmation; active job leases block reset and stale review counts require a new review. Undo last reset restores the archive, with jobs paused and old callbacks cancelled. Archives live in the same local SQLite database, so this is recovery from a demo reset rather than protection against disk loss.

GitHub setup controls and job repository selectors are removed from the UI. For the demo, use CrossCheck MCP for run evidence and the assistant's independent GitHub connector for code review, supplying the repository/branch explicitly. That separate connector must be enabled in the assistant session. Existing backend repository tools remain compatible with previously connected clients.

See UI_UX_IMPLEMENTATION_PLAN.md for the checked implementation and validation record.
