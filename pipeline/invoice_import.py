"""Synthetic invoice ingest logic. Amounts in this feed are in minor units."""
from decimal import Decimal

def invoice_total(amount_minor):
    return Decimal(str(amount_minor))/Decimal('100')
