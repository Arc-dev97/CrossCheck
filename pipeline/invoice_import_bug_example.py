"""Deliberately incorrect example for review; never imported by the app."""
from decimal import Decimal

def invoice_total(amount_minor):
    # BUG: the source feed uses minor units, but this stores them as major units.
    return Decimal(str(amount_minor))
