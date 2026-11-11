# Live tables and code-aware investigation

## Supabase setup
Use a new demo project; never point the seed helper at production. The prepared project uses Sydney session-pooler host aws-1-ap-southeast-2.pooler.supabase.com. The public project reference is qiejcpkceecwhhdnxvll.

From the project folder run:

```powershell
.\.venv\Scripts\python.exe tools/setup_supabase.py
```

Press Enter for the prepared host and admin username. Enter the existing project database password privately, then select the correct Google workspace by email. The helper seeds synthetic tables and creates a randomly named SELECT-only database role. Only its reader credential is saved, encrypted, in the selected workspace. The admin password is not saved or printed. Failures are recorded without secrets under ignored data/supabase-setup-status.json.

TLS uses verify-full and Supabase's official CA from the dashboard's Database Settings > Download certificate. Bundled public certificate: app/certs/supabase-prod-ca-2021.crt. SHA256: 700723581420dd1ac98fd7e9ac529f0ef210eadcaf87fc868a3ad7d114c2f3b7.

Synthetic sources retain the complex employee/invoice fixtures: 92 claims and 91 invoices, unique database row IDs, deliberately duplicated claim references, absent values, unmatched records and invalid invoice totals. Invoice totals stay text to demonstrate imported bad numeric values; claim amounts/subtotals/tax use numeric columns. Date columns use date. Extra columns record update time and an optional producer commit SHA.

## Website workflow
1. Refresh Live sources; choose Live employee expense claims and Live uploaded invoices.
2. Fetch current tables & define rules. This creates an immutable snapshot for interactive review.
3. Load the saved Live employee expense audit recipe and preview. Canonical counts: 71 matched, 12 mismatch, 4 A-only, 3 B-only, 2 duplicate groups, 1 missing-key group, 1 invalid-value group.
4. Under Scheduled jobs choose Input type: Live database tables, the two LIVE sources (not saved snapshot IDs), the saved recipe, and an interval.
5. Optionally attach the application and source-pipeline repositories. Create/start or Run now.
6. Each run fetches a fresh consistent pair, saves immutable evidence, computes discrepancy changes, and emits the existing event. Scheduled work requires the server to stay running.

A source definition pins selected columns, filters and schema, but reads fresh records. Schema changes require registration/review of a new source; they do not silently change a job's business rules. Date filters use UTC days with an inclusive through date. Source tables must have primary keys. Both sources must share one connection for snapshot consistency. Limits: 50,000 rows and 20 MB serialized values per source, 10-second SQL statements, bounded connection/lock waits. Exceeding limits fails rather than truncates the comparison. Incremental reads and cross-database consistent snapshots are outside this MVP.

## Changing-data demo
Run tools/simulate_updates.py interactively using a demo writer/admin credential (not the app's reader). Its actions add a claim, add its delayed invoice, introduce a controlled 100x amount discrepancy, then correct it. Wait for a scheduled run between actions. Prior runs remain unchanged. The producer commit field is optional; leave it empty if actual deployment provenance is unknown. The deliberate bug example lives at pipeline/invoice_import_bug_example.py, while pipeline/invoice_import.py is the correct implementation.

## GitHub
Repository target: https://github.com/Arc-dev97/CrossCheck . Register it twice if useful, with distinct names/paths for application (app/, server.py) and pipeline (pipeline/). Public repositories require no token. A private repository needs a fine-grained Contents: read credential for that repository, entered only in the website. Its encrypted value is never returned through APIs/MCP. Connecting a GitHub plugin to ChatGPT does not transfer its token to this app.

Reads always use GET at api.github.com, do not follow redirects, and enforce response/file limits. Registered path restrictions also apply to diff output. Branch references resolve to commit SHAs before reading. No automatic checkout, code execution, commits, pushes or PR changes are performed by MCP tools. Configured branches are investigation context, not proof of deployed code. Application fingerprints and observed source producer_commit_sha values provide stronger evidence.

## MCP prompt
Using Reconcile Demo, inspect the latest failed job and retrieve its diagnostic evidence. Distinguish source-fetch, schema, comparison and application errors. Inspect the registered application and pipeline repositories, compare relevant branches, and cite file paths and resolved commit SHAs. Explain confirmed evidence separately from suspected causes. Do not modify data, recipes, jobs or code.

Rescan/reconnect the ChatGPT custom MCP plugin after the server's tool list changes. Seven new tools add live-source discovery/snapshotting, job diagnostics, repository discovery, branch listing, file reads and branch comparisons. Existing draft review and final-execution controls remain.

## Notifications
The panel is collapsed initially. Open Job notifications to see its count and page controls; each notification expands independently. Server pagination is scoped to the signed-in user. Webhook accepted means receipt was acknowledged; it does not prove ChatGPT generated a reply. Automatic ChatGPT replies remain independently unverified.
