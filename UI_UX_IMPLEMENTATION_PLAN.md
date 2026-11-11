# CrossCheck UI/UX implementation plan

Status: implemented and validated. Recoverable reset was exercised only in the isolated QA workspace; the user workspace was not cleared.
Goal: a clean, Volopay-inspired demo interface using the existing reconciliation, source, scheduling and MCP behavior.

## Design reference
- [x] Review the live official Volopay homepage: https://www.volopay.com/
- [x] Inspect rendered typography and primary CTA styles.
Observed primary CTA: #4B4EFC, white text, 4px corner radius. Observed heading text: #17191D, Bricolage Grotesque, weight 700. The site uses white surfaces, generous spacing and clear dark headings.
Proposed app tokens: primary #4B4EFC; text #17191D; white panels; a very light neutral workspace background; restrained borders; green/amber/red semantic statuses. App headings will be smaller than the marketing site's 60px hero. Bundle the chosen font locally with its license and a system-font fallback.
CrossCheck gets its own wordmark and identity using this visual language.

## Scope boundaries
- Preserve the deterministic engine, recipe format, saved snapshot format, Supabase reads, scheduler, login, account isolation, OAuth and existing MCP tool contracts.
- Reorganize the frontend into separate tab panels; preserve DOM IDs and shared loaders where practical.
- The reset action requires a small owner-scoped backend addition: there is currently no clear/reset endpoint. It must not change reconciliation logic or source database records.
- Removing GitHub from the app means removing the setup panel and job repository selectors. GPT uses its independent GitHub connection. Leave legacy backend repository APIs/tool contracts intact in this pass so existing MCP sessions are not broken; avoid discarding opaque legacy job configuration during ordinary UI edits.
- No permanent app deployment and no automatic reset during implementation.

## Navigation and screen map
Persistent CrossCheck header: wordmark, account menu, sign out and a small notifications count. Five clearly separated tabs; only the selected panel is shown.

| Tab | Contents | Main action |
| --- | --- | --- |
| Run once | Source selection, rules, review and execution in three clear steps | New comparison / Preview / Execute |
| Scheduled jobs | Compact jobs table with sources, interval, next run, last status; separate create/edit form or drawer | New scheduled job |
| Run history | Readable completed-run table; selected immutable report with filters, source rows and export | Open report |
| Data sources | Saved CSV data, Supabase connections and live table definitions; advanced setup collapsed | Add source |
| Notifications | Existing paginated events with human-readable counts, failure stages and new/resolved discrepancy badges | Open related run |

Saved recipes sit inside the Run once rules step. Assistant drafts are in a compact expandable card available before sources are chosen, so a new assistant draft can supply both sources and rules. Source-column profiles are expandable and appear only when useful. Detailed technical metadata and raw JSON belong in optional details.

## Phase 1: safe frontend separation
- [x] Record the current endpoint/payload shapes and the existing 36-test baseline.
- [x] Move inline styling and navigation behavior into small frontend assets without adding a framework/build migration.
- [x] Add accessible tab navigation, selected-state styling, keyboard support and responsive overflow handling.
- [x] Keep unsaved source/recipe inputs intact while switching tabs.
- [x] Preserve assistant draft links and saved-run opening behavior; opening a run activates the correct tab before scrolling/focusing its heading.
- [x] Preserve the selected history entry and notification page during polling.

## Phase 2: CrossCheck brand and visual system
- [x] Rename the visible application, browser title and sign-in UI to CrossCheck.
- [x] Apply the sampled primary colour, heading style, white panels, consistent spacing, buttons, inputs and status badges.
- [x] Replace the oversized landing-page hero with a compact page title and useful description for each tab.
- [x] Use clear empty, loading, success, validation-error and disabled states with plain-language copy.
- [x] Keep technical limits and controls available without filling the primary workflow with implementation details.
- [x] Keep existing Google/OAuth identifiers, scopes, callback URLs and MCP tool names unchanged. Connector display-name metadata can be renamed separately without reconnecting authentication.

## Phase 3: remove app GitHub controls
- [x] Remove the Code context for debugging section and repository credential inputs.
- [x] Remove application/source-pipeline repository selectors from job creation/editing.
- [x] Remove browser requests and handlers that only populate the removed GitHub controls; guard against null-element JavaScript failures.
- [x] Keep existing jobs editable and executable with the same source/recipe/interval semantics.
- [x] Document CrossCheck MCP for run evidence plus GPT's independent GitHub connector for code review. That independent connector is not exposed to this Codex chat, so its availability in the user's ChatGPT session must be checked there; this redesign does not claim to verify it.

## Phase 4: tidy the actual workflows
- [x] Run once: Step 1 choose CSV or a saved live-table pair; Step 2 load/edit rules; Step 3 preview then execute. Display which snapshot is being compared.
- [x] Scheduled jobs: list first, New job opens its own form/drawer. Distinguish Create from Save changes and make the editing state explicit.
- [x] Show Source A and Source B labels with filenames/table names near recipe selection so accidental reversal is easier to spot.
- [x] Run history: render a table with readable name/time/source type/result counts and working Open/Export actions.
- [x] Reports: display summary, discrepancy filters and expandable original rows; clearly identify historical snapshots.
- [x] Notifications: retain server pagination, use human labels and expandable details, and distinguish webhook receipt from assistant response generation.

## Phase 5: reset for a tidy demo
Recommended default action: Reset demo data, under the account/settings menu rather than the main execution controls.

Clear this signed-in workspace's generated records: saved jobs, runs, previews, drafts, notifications, uploaded CSV datasets and database snapshots. Preserve Google access, database connection credentials, saved live-source definitions and saved recipes so the user does not have to repeat setup. Preserve the actual Supabase tables and GitHub repositories. Legacy repository configuration is retained for backward compatibility and is excluded from reset counts. The app UI no longer uses it.

- [x] Add a read-only reset summary showing exact owner-scoped counts and what will remain.
- [x] Show a confirmation dialog describing those counts; the user performs the final reset action.
- [x] Reject reset while a scheduled-job lease is active; the SQLite transaction prevents a scheduler claim from racing the deletion. Undo restores jobs paused.
- [x] Implement the narrow reset endpoint as one database transaction, with rollback on failure.
- [x] Archive the affected records server-side before clearing the active workspace and provide an Undo last reset action. Restored jobs stay paused.
- [x] Handle dependent records and pending event deliveries together so no stale run references or queued callbacks survive the reset.
- [x] Keep sessions, OAuth grants and source database credentials out of reset responses and archives of generated records.
- [x] Clear only this account's browser draft/selection state; refresh all counts and empty states after success.
- [x] Do not add a destructive MCP tool or touch another account's data.

The reset summary and confirmation are part of the product UI. No existing records will be cleared merely to test the redesign; verification uses an isolated test workspace.

## Phase 6: verification and rollout
- [x] Run the existing backend suite; add meaningful reset tests for ownership, transactional rollback, active-job races, retained configuration, undo, and pending-delivery handling.
- [x] Verify CSV source selection, recipe editing, preview and execute in browser QA; verify real database source selection and preview in the signed-in app. Export endpoints pass regression tests and report links target the correct run. Browser download-event observation timed out, so a completed native download was not independently observed.
- [x] Verify schedule create/edit/pause/resume/Run now and unchanged snapshot results.
- [x] Verify notification pagination and Open related run across tab boundaries, plus Open from run history.
- [x] Verify tab changes and background polling do not lose unsaved edits or current report selection.
- [x] Verify assistant draft review URLs in browser QA, existing real Google session access, account-isolation/auth/draft regression tests, and the public MCP handshake/read/event discovery.
- [x] Verify there are no frontend references to removed GitHub elements and no browser errors.
- [x] Verify desktop and narrow-screen layouts, keyboard focus and accessible labels.
- [x] Capture review screenshots and update the implementation checklist with actual results.
- [x] Publish the reviewed source changes to CrossCheck and update the existing temporary demo server only. Keep permanent hosting unchanged.

## Completion criteria
1. CrossCheck identity appears throughout the user-facing app.
2. Each workflow has its own tab and a clear primary action.
3. GitHub setup/repository controls are absent from the app UI.
4. Existing reconciliation, database, schedule and MCP behavior passes regression checks.
5. The user can explicitly reset their app demo records while retaining connection/setup and source-table data, with recoverability.
6. Automatic ChatGPT notification generation is still described honestly as unverified; this UI pass does not claim a fix.

Implementation order: navigation and shared loaders -> branding -> remove GitHub controls -> workflow cleanup -> scoped reset -> verification and screenshots.

## Verification record — 12 November 2026

- 43 automated tests pass, including seven recoverable-reset tests covering ownership, rollback, stale review, active job leases, undo, callback cancellation and in-flight delivery serialization.
- JavaScript syntax checks pass; DOM IDs are unique and static ID references resolve. No removed GitHub setup elements or browser repository calls remain.
- Isolated browser QA: CSV employee audit preview and saved execution; unsaved edits survive tabs; independent historical report; live-table fixture fetch; schedule create/edit (including switching source type)/manual run/pause/resume; notification pagination and report opening; reset Cancel/confirm/Undo; retained database configuration; restored jobs paused; assistant draft URL loads and previews.
- Responsive QA at 390×844: controls stack, navigation scrolls inside its own bar, page has no horizontal overflow. Arrow-key tab selection moves focus and the visible panel together. Viewport override restored.
- Real signed-in app: existing account and records remain available; fresh Supabase fetch reads 92 expense rows and 91 invoice rows, matching the expected 71 agrees / 12 different-value groups plus documented exceptions. Reader source-write permission remains denied. Only snapshots/previews were added during validation; no source rows or existing demo records were deleted.
- Public HTTPS MCP smoke check: all 16 existing tools available, dataset read succeeds, events discovery succeeds, invalid bearer returns 401; synthetic test token revoked.
- Actual app process updated on existing port 8002 and existing temporary tunnel. No permanent hosting change. Source published to the existing CrossCheck repository.
- Automatic ChatGPT event-generated responses remain unverified, as before. Claude remains deferred at user request.

Recovery is a local archive in the same SQLite database, not an off-device backup. This MVP runs a single server process. The frontend hides GitHub controls; legacy backend tools/configuration remain for compatibility.
