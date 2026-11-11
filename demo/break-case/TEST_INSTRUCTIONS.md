# Unfixed case: missing names are reported as matched

1. Open the local app. Upload warehouse.csv and store.csv from this directory.
2. Load recipe.json from this directory using Load recipe.
3. Click Validate & preview.
4. Inspect key 00002 and expand its source records.

Observed: 2 matched, 1 mismatch. Key 00002 is matched although both product names are blank.
Expected IF product name is required: 1 matched, 1 incomplete/invalid record, 1 mismatch.
This exposes a missing product requirement: text null/blank handling and required fields. The current equality engine treats two blank strings as equal. This is not an incorrect equality calculation, but can be a misleading business result.
No fix has been applied. Decide whether names are required or blanks can match after testing.
