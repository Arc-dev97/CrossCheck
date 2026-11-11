"""Synthetic invoice ingest logic. Amounts in this feed are in minor units."""
from decimal import Decimal

def invoice_total(amount_minor):
    # Deliberate demo regression: upstream minor units are stored as major units.
    return Decimal(str(amount_minor))
