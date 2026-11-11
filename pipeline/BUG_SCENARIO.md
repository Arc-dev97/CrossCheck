# Intentional demo branch

This branch deliberately removes division by 100 in invoice_import.invoice_total.
An incoming value 12550 (minor INR units) becomes 12550 instead of 125.50.
The BoundaryTests.test_pipeline_minor_unit_conversion test should fail here.
Compare this branch with main to identify and explain the source-data regression.
This branch is not the running reconciliation application and must not be merged as a fix.
A branch diff alone does not prove this code produced a database row; use the producer commit when available.
