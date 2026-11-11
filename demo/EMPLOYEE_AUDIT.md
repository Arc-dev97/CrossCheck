# Employee expense audit demo

All people, transactions and tax identifiers are synthetic fixtures, not real employee records. The files resemble an expense-management export and an invoice-attachment registry exported into CSV. The app does not read actual invoice PDFs or run OCR.

## Inputs

- employee_expenses.csv: 92 rows, 16 columns; 15 employees with six normal expense lines each plus intentional duplicate/missing-ID rows.
- uploaded_invoices.csv: 91 rows, 15 columns; employee uploads associated with claims, plus duplicate/unlinked/orphan attachments.
- expense_recipe.json: matching and comparison recipe.

Use **Try employee expenses** in the app to load both files and the recipe without local uploads.

Match by expense_id / claim_reference. Employee IDs are comparison fields, not join keys: one employee has multiple expense lines. Invoice currencies are compared directly, never converted.

Compare claimed amount with invoice total (tolerance 1), employee ID, currency, receipt/invoice number, and merchant/vendor name.

## Expected default output

| Status | Groups |
|---|---:|
| Matched | 71 |
| Mismatch | 12 |
| Invalid number | 1 |
| Duplicate key | 2 |
| Missing key | 1 |
| Claim only | 4 |
| Invoice only | 3 |

All 183 source rows are accounted for. Group counts differ from source-row counts.

## Inspect these examples

- EXP-2026-0002: invoice differs by 0.50; matches at tolerance 1 but differs at tolerance 0.
- EXP-2026-0004: invoice total is 150 higher than the claim.
- EXP-2026-0010: receipt number differs from invoice number.
- EXP-2026-0016: invoice total is 'not readable'; invalid number.
- EXP-2026-0019 and 0044: INR claim vs USD invoice; currency mismatch.
- EXP-2026-0020: duplicate claim reference; no match guessed.
- EXP-2026-0029: wrong employee ID on the invoice upload.
- EXP-2026-0032: blank invoice vendor; missing-data flag plus mismatch.
- EXP-2026-0040: duplicate invoice upload.
- EXP-2026-0061: different vendor.
- EXP-2026-0087 through 0090: claims without corresponding invoices.
- EXP-2026-0091 through 0093: invoices without corresponding claims.

This is line-level evidence comparison. It does not validate tax arithmetic, determine reimbursement eligibility, identify fraud, sum spending per employee, or resolve split/combined invoices. Those require additional explicit features and rules.
