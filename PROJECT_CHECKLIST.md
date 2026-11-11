# CSV reconciliation MVP

Status: local CSV comparison MVP implemented and verified. FastAPI + SQLite; 24 tests pass. Browser upload, preview, execute, saved recipes/runs, download, refresh and backend restart verified. Local MCP implemented and protocol-tested; actual Claude/ChatGPT account connection pending. Deployment prohibited until user authorizes.

Legend: [x] complete, [ ] pending. Items marked DECISION need agreement before implementation.

## Scope and decisions
- [x] Choose deterministic execution with external LLM access through MCP; no model API keys in the app.
- [x] Choose two CSV inputs as the initial file scope.
- [ ] DECISION: Confirm primary demo: inventory reconciliation.
- [ ] DECISION: Confirm file handoff: website upload first; chat attachment import only if verified feasible.
- [ ] DECISION: Confirm supported recipe operations and hosting approach.

## Data import and profiling
- [x] Upload and persist two CSVs with size and row limits.
- [x] Preserve original values and assign stable source row IDs.
- [x] Show headers, sample rows, null counts, and candidate key duplicates.
- [x] Report malformed input and conversion failures clearly.
- [x] Provide realistic demo files with known expected results.

## Recipe and execution engine
- [x] Define a versioned, validated recipe schema.
- [x] Support one exact matching key per source, with optional trim and case normalization.
- [x] Support selected field comparisons: text and numeric values with explicit tolerance.
- [x] Preserve unmatched records; isolate null keys and duplicate/normalized-key collisions.
- [x] Implement deterministic execution using DuckDB or equivalent.
- [x] Classify matched, mismatched, left-only, right-only, and invalid/ambiguous records.
- [x] Preserve links from results to original source rows.
- [x] Account for every source row without silent losses or duplicate matches.

## Web review workflow
- [x] Show and edit mappings, normalization, comparisons, and tolerances.
- [x] Show a plain-language recipe summary.
- [x] Validate and preview a draft recipe with warnings.
- [x] Require explicit user execution of the reviewed recipe version.
- [x] Show result counts and filterable exception details.
- [x] Download results as CSV with safe handling of spreadsheet formula-like cells.
- [x] Save a recipe and reuse it with new compatible files.
- [x] Invalidate stale previews when the recipe or source files change.

## MCP integration
- [x] Expose dataset listing and profiling tools.
- [x] Expose validated draft creation tools; revisions create new editable drafts.
- [x] Draft creation validates and previews; read-only inspection exposes preview results.
- [x] Expose result summaries and paginated exception inspection.
- [x] Return explicit errors for unsupported operations or missing information.
- [x] Keep final execution under user control in the web app for the MVP.
- [ ] Verify authentication and isolate access to the intended demo workspace.
- [ ] Connect and test the deployed endpoint in Claude.
- [ ] Document connection steps and test credentials if needed.

## Verification and deployment
- [x] Test exact matches, mismatches, unmatched records, nulls, and duplicates.
- [x] Test normalization collisions, invalid numeric values, and identifier leading zeros.
- [x] Verify repeatability and source-row accounting against expected results.
- [x] Verify recipe edits invalidate previews and change results as expected.
- [ ] Deploy the app and remote MCP endpoint. ON HOLD: user explicitly requires authorization before deployment.
- [ ] Verify persistence and the complete Claude-to-web review flow online.
- [x] Confirm no AI API keys or AI inference calls in the app.

## Submission
- [ ] Prepare concise business positioning, pricing assumptions, and customer acquisition hypothesis.
- [ ] Prepare the required founder/background and best-work segments.
- [ ] Record a demo and pitch within five minutes.
- [ ] Verify app link, MCP instructions, and reviewer access.
- [ ] Assemble submission material for the user to send.

## Deferred
- Excel, PDFs, and direct database integrations.
- Fuzzy/entity matching, composite keys, and many-to-many reconciliation.
- Arbitrary SQL, executable LLM-generated code, and arbitrary formulas.
- Automatic writes back to source systems.
- Scheduling, extensive collaboration, and production-scale infrastructure.


## Latest changes
- [x] Flag missing selected values, with explicit locations and missing_data classification when otherwise matched.
- [x] Include/exclude missing-data groups in recipe execution and exported results, with exclusion counts.
- [x] Browser-local saved recipe selector plus built-in inventory recipe.
- [x] Verify reconciliation against unrelated employee/account CSV headers.
- [x] Browser interaction verification of missing-data controls and saved recipes.

## Generic interface update
- [x] Replace domain-specific upload and result labels with Source A / Source B.
- [x] Show source filenames, column samples, and empty-cell counts.
- [x] Explain matching vs comparison and render a live recipe summary.
- [x] Retain inventory as an optional example, not an input requirement.
- [x] Verify the new layout and interactions in a real browser.

User constraint: no permanent deployment. Temporary HTTPS testing was subsequently authorized; see the remote OAuth section below.

## FastAPI and persistence
- [x] Install project-local virtual environment and dependencies.
- [x] Save immutable datasets, recipe versions, previews and completed runs in SQLite.
- [x] Export completed snapshots with source records and missing-data flags.
- [x] Verify persistent data survives backend process restart.
- [x] Split recipe explanation across readable lines.
- [x] Verify actual browser-downloaded CSV contents.
- [x] Test malformed schemas, unsupported rules, missing records and cross-origin mutation rejection.

Data stays under data/workspace.sqlite3. Owner-scoped multi-user Google authentication was subsequently implemented and verified; this is still an MVP, not a production deployment.

## Latest user feedback
- [x] Readable names for new runs and readable fallback names for old runs; optional custom run title.
- [x] Place Save recipe next to its name and show timestamped save confirmation.
- [x] Add multi-employee expense/invoice CSV fixtures, default recipe and expected-result test.
- [x] Verify local MCP Streamable HTTP and stdio using official SDK clients.
- [x] Verify MCP-created drafts load into the website and remain editable.
- [x] Write connection guide for both clients, distinguishing local readiness from actual account integration.
- [x] Decide/authorize public reachability and authentication before connecting cloud clients.
- [ ] Test with actual Claude account.
- [x] Test with actual ChatGPT account.

## Google login and scheduled jobs
- [x] Implement Google OpenID Connect login and configuration guide.
- [x] Enforce opaque server-side sessions, expiry and logout.
- [x] Isolate all records and object references by authenticated owner.
- [x] Preserve anonymous legacy records without exposing them to new accounts.
- [x] Add separate Scheduled jobs UI: file/recipe selection, interval, edit, pause/resume and Run now.
- [x] Persist jobs, per-run snapshots and owner-scoped completion/failure events.
- [x] Prevent overlapping scheduled executions with SQLite leases.
- [x] Verify a real 15-second automatic timer in isolated browser QA.
- [x] Verify pause, manual run while paused, job edits, daily interval display and incompatible-rule failure in browser QA.
- [x] Verify Google setup-required login page in the real local app.
- [x] Test signed-in isolation and MCP protocol calls with synthetic fixture identities.
- [x] Configure the user's Google OAuth client ID/secret in .env.
- [x] Verify actual Google sign-in with the user's account.
- [x] Implement remote MCP OAuth authorization; browser login is not connector authorization.
- [x] Implement and test actual ChatGPT Events subscriptions and webhook delivery.
- [ ] Decide whether a Claude Code Channels adapter is in demo scope; ordinary Claude chat push not established.

Current limits: scheduling uses pinned file versions and elapsed intervals; future automatic file refresh is not implemented. Job events persist locally and distinguish webhook acceptance from assistant processing. Temporary public HTTPS exposure is authorized and running.

## Remote OAuth and job events
- [x] User verified real Google login and isolation using different accounts.
- [x] Add official-SDK MCP OAuth discovery, DCR and explicit workspace consent.
- [x] Enforce PKCE, one-use authorization codes, redirect binding and resource audience.
- [x] Rotate refresh tokens and support grant-family revocation.
- [x] Add MCP Events discovery, subscribe/unsubscribe and encrypted persistent subscription secrets.
- [x] Verify callbacks before application-data delivery; pin public destination IPs and verify TLS hostname.
- [x] Sign webhook deliveries, persist attempts, retry transient failures, stop on expiry/revocation/unsubscribe.
- [x] Test consent CSRF/expiry, code replay, refresh, revocation, callback safety, filtering and retry/stop behavior.
- [x] Download official cloudflared binary and verify release SHA-256.
- [x] Start authorized temporary HTTPS tunnel and verify unauthenticated MCP returns 401.
- [x] Verify MCP handshake, tools and event discovery across public HTTPS using a synthetic bearer identity.
- [x] User added public Google callback and completed ChatGPT plugin OAuth consent.
- [x] Verify actual ChatGPT dataset/job reads and editable draft creation.
- [x] Verify actual ChatGPT subscription, callback challenge and four accepted webhook deliveries.
- [ ] Verify the generated asynchronous ChatGPT task response (not yet observed).
- [ ] Claude account test deferred at user request (Skip Claude for now).

Current endpoint and startup details: CURRENT_CONNECTION.md. A temporary tunnel is running with user authorization. No permanent deployment has been made.

Live test note: both app demo jobs are paused. ChatGPT confirmed the native task is disabled; the app database independently confirms its event subscription is inactive. Generated automatic reports remain unverified. No permanent deployment.

- [x] Stop test monitoring and independently verify the persisted subscription is inactive.
- [x] Restart the current public demo server with validated code; retain the same tunnel URL.
