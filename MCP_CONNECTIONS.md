# MCP connections and job notifications

## Current status

The user verified Google login and account isolation. MCP OAuth is implemented and the real ChatGPT Plus account connected through the temporary HTTPS endpoint. Claude testing was explicitly deferred by the user.

See CURRENT_CONNECTION.md for the current URL and startup commands. This is an authorized temporary Cloudflare tunnel to port 8002, not a permanent deployment. The older localhost:8000 server remains separate; use the HTTPS app for current integration tests.

## MCP OAuth

Implemented using the official Python SDK's OAuth request handlers and a persistent provider:

- RFC9728 protected-resource discovery and authorization-server metadata.
- Dynamic client registration, exact redirect validation and S256 PKCE.
- Google website sign-in followed by an explicit app consent screen.
- Short-lived, single-use authorization codes bound to client/redirect/resource/owner.
- Opaque access tokens, rotated refresh tokens and grant-family revocation.
- Per-user data isolation for bearer-authenticated MCP calls.

The Google web session is not used as a remote client credential. Each client gets its own owner-bound grant after consent. Do not copy browser cookies to a cloud connector.

## Verified actual ChatGPT workflow

The installed Reconcile Demo plugin discovered 9 tools and reconciliation.finished. It listed the signed-in account's two initial files (92 expense rows, 91 invoice rows), created an editable reconciliation draft, and returned real preview counts. The draft was opened in the app and editing normalization changed deterministic results as expected.

The native monitoring task subscribed successfully, the callback challenge was verified, and completion/failure events were accepted by ChatGPT's receiver with HTTP 200. Generated background notifications are still under verification: the Scheduled UI showed Last run but no latest result/delivery details. Do not describe webhook acceptance as proof that an automatic explanation was shown to the user.

## Events implementation

Event methods are exposed on the authenticated Streamable HTTP endpoint: events/list, events/subscribe and events/unsubscribe. The event is reconciliation.finished, optionally filtered by job_id and statuses. Final run execution remains in the website.

Subscriptions persist in SQLite; signing secrets are encrypted using local signing material. Before delivery, callbacks must verify a signed challenge. HTTPS destination IPs are resolved and pinned, private addresses are blocked, TLS hostname verification remains enabled, and redirects are not followed.

Each application event uses a stable ID and Standard Webhooks HMAC headers. Accepted deliveries, retries and terminal failures are recorded independently. Expired, revoked or unsubscribed grants stop delivery. Large data stays behind MCP read tools; events carry a small summary and evidence references. No model inference is performed in the app.

An accepted delivery means only that the receiver acknowledged the webhook. ChatGPT processes events asynchronously and can batch them. The app cannot guarantee instant generation or UI rendering.

## Scheduled jobs

Jobs use pinned file versions and a saved recipe at intervals from 15 seconds to 7 days. Edit updates future inputs; pause prevents automatic starts; Run now works while paused. The worker runs with server.py and uses persistent SQLite leases to prevent overlap. An overdue job runs once after restart rather than replaying every missed interval.

## Claude

The same OAuth/DCR MCP endpoint can be configured in Claude custom connectors. The real account connection has not been tested because the user chose to skip it for now. Anthropic's documented push route is Claude Code Channels, not ordinary Claude web chat; no channel adapter is implemented.

## Tests

Run `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`: 24 tests cover engine behavior, HTTP API, ownership, schedules, PKCE/code replay, consent CSRF/expiry, redirect binding, refresh/revocation, callback safety, filtering and retry/unsubscribe behavior.

The public protocol smoke test in tools/verify_public_mcp.py uses a separate synthetic identity and verifies a real HTTPS handshake, tools/events discovery and invalid-token rejection. It is not a substitute for real account testing.

## References

- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/plugins/build/mcp-events
- https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp
- https://code.claude.com/docs/en/channels
