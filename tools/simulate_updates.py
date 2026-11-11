"""Interactive demo writer; the reconciliation app itself uses SELECT-only access.
Run from project root. Password is hidden and never saved.
"""
import sys,re,getpass,time,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import psycopg
from app.sources import ConnectionInput,root_certificate
from pipeline.invoice_import import invoice_total

def main():
    host=input('Supabase session pooler host: ').strip();username=input('Demo writer/admin pooler username: ').strip();password=getpass.getpass('Existing database password: ')
    ConnectionInput(name='validation',host=host,username=username,password=password)
    commit=input('Deployed pipeline commit SHA (optional; leave empty if unknown): ').strip()
    if commit and not re.fullmatch('[0-9a-fA-F]{40}',commit):raise ValueError('A commit SHA must have 40 hex characters.')
    with psycopg.connect(host=host,port=5432,dbname='postgres',user=username,password=password,sslmode='verify-full',sslrootcert=root_certificate(),connect_timeout=10,autocommit=True) as conn:
        print('1: add an expense claim; 2: add its delayed invoice; 3: introduce the minor-unit bug; 4: fix the invoice; q: quit')
        while True:
            choice=input('Action: ').strip()
            if choice=='q':break
            if choice=='1':
                conn.execute("INSERT INTO reconcile_demo.employee_expenses (expense_id,employee_id,employee_name,department,expense_date,merchant,claimed_amount,currency,receipt_number,producer_commit_sha) SELECT 'DEMO-LIVE-001','EMP-104','Synthetic demo employee','Engineering',CURRENT_DATE,'Demo Rail',125.50,'INR','DEMO-BILL-001',%s WHERE NOT EXISTS (SELECT 1 FROM reconcile_demo.employee_expenses WHERE expense_id='DEMO-LIVE-001')",(commit or None,))
            elif choice=='2':
                conn.execute("INSERT INTO reconcile_demo.uploaded_invoices (claim_reference,submitted_by_id,invoice_number,vendor_name,invoice_date,invoice_total,currency_code,producer_commit_sha) SELECT 'DEMO-LIVE-001','EMP-104','DEMO-BILL-001','Demo Rail',CURRENT_DATE,%s,'INR',%s WHERE NOT EXISTS (SELECT 1 FROM reconcile_demo.uploaded_invoices WHERE claim_reference='DEMO-LIVE-001')",(str(invoice_total(12550)),commit or None))
            elif choice in ('3','4'):
                amount='12550' if choice=='3' else str(invoice_total(12550))
                conn.execute("UPDATE reconcile_demo.uploaded_invoices SET invoice_total=%s,updated_at=now(),producer_commit_sha=%s WHERE claim_reference='DEMO-LIVE-001'",(amount,commit or None))
            else:print('Choose 1, 2, 3, 4 or q.');continue
            print('Database updated. The next scheduled run will fetch the new state.')
if __name__=='__main__':main()
