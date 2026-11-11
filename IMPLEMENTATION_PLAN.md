# Live-source reconciliation implementation

Status is updated as work is verified. No permanent app deployment is authorized. The user supplied CrossCheck as the GitHub destination for both codebases.

## 1. Foundations
- [x] Add database-neutral snapshot records while retaining CSV compatibility.
- [x] Add the Postgres driver in the project virtual environment.
- [x] Store connection credentials encrypted, scoped to the signed-in owner, and never return them through APIs or MCP.

## 2. Supabase sources
- [x] Add connection setup, test/discovery, saved table selections and optional date filtering.
- [x] Fetch both tables in one read-only repeatable-read transaction.
- [x] Preserve primary-key provenance, Decimal values, nulls, schema, fetch time and source definitions.
- [x] Enforce row, byte and execution-time limits; reject incomplete input.
- [x] Add source setup and snapshot preview to the website.
- [x] Create and seed the actual free Supabase project; a restricted encrypted reader is configured in the primary workspace.

## 3. Scheduling and diagnosis
- [x] Support file-version jobs and live-table jobs.
- [x] Fetch new snapshots on every live-table run, preserving old runs.
- [x] Track failure stage, previous-run changes, source lineage and application build fingerprint.
- [x] Expose owner-scoped diagnostic evidence through MCP.

## 4. GitHub context
- [x] Register both application and source-pipeline repositories and relevant paths/branches.
- [x] Add bounded read-only GitHub file/branch-diff access; resolve branch reads to commit SHAs.
- [x] Associate repositories with jobs and include code provenance in diagnostic evidence.
- [x] Prepare a synthetic source-update script with a controlled amount-conversion bug.
- [ ] Verify real repositories after URLs/access are provided. Publishing requires an explicit destination.

## 5. Notifications
- [x] Add a collapsed notifications panel with an event count.
- [x] Add server-side pagination and per-notification expandable details.
- [x] Keep webhook receipt distinct from assistant-generated response.

## 6. Verification
- [x] Run existing regressions.
- [x] Test source access isolation, secret redaction, query construction, typed conversion, transaction consistency and input limits.
- [ ] Test fresh scheduled snapshots, immutable history, schema/fetch failures and comparison deltas.
- [x] Test GitHub path/ref restrictions, commit resolution and error handling.
- [x] Test notification pagination and isolation.
- [x] Verify the UI in an isolated browser session.
- [ ] Verify actual Supabase integration when project access is configured; report pending external setup honestly.

## External setup
Supabase project qiejcpkceecwhhdnxvll was created through the signed-in dashboard. The interactive local helper configured the SELECT-only connection without exposing the admin password. GitHub destination supplied by user: https://github.com/Arc-dev97/CrossCheck.git . No permanent app hosting deployment is authorized.

## Verification evidence
- 36 automated tests pass.
- Browser QA: consistent snapshot loading, numeric preview, a real 15-second timer using fixture tables, pause, notifications collapsed initially, pagination and expanded details.
- Actual Supabase: verified TLS, 183 source rows, canonical counts and reader UPDATE denied by PostgreSQL.
- Actual GitHub public API: commit resolution, bounded text file read and branch listing passed against the official GitHub MCP repository. Target repository publication and target-specific reads are next.
