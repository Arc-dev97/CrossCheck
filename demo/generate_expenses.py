import csv,json
from decimal import Decimal
from pathlib import Path
p=Path(__file__).parent
employees=[('EMP-'+str(100+i),n,d) for i,(n,d) in enumerate([('Aarav Mehta','Sales'),('Priya Nair','Engineering'),('Rohan Shah','Marketing'),('Ananya Rao','Operations'),('Kabir Singh','Sales'),('Meera Iyer','Finance'),('Dev Patel','Engineering'),('Isha Gupta','People'),('Arjun Das','Customer Success'),('Sara Khan','Marketing'),('Vikram Joshi','Operations'),('Neha Kapoor','Sales'),('Aditya Sen','Engineering'),('Tara Menon','Product'),('Farhan Ali','Customer Success')],1)]
vendors=[('Metro Cabs','Travel'),('City Business Hotel','Accommodation'),('CloudTools India','Software'),('Office Supply Co','Office supplies'),('Client Bistro','Client meals'),('Rail Services','Travel')]
ah=['expense_id','employee_id','employee_name','department','cost_center','expense_date','merchant','category','claimed_amount','currency','receipt_number','project_code','payment_method','manager','submission_status','business_purpose']
bh=['claim_reference','submitted_by_id','uploaded_by','invoice_number','vendor_name','invoice_date','subtotal','tax_amount','invoice_total','currency_code','attachment_name','upload_date','verification_status','supplier_tax_id','source_channel']
a=[];b=[]
for i in range(1,91):
 eid,name,department=employees[(i-1)//6];vendor,category=vendors[(i-1)%6];net=Decimal(250+i*37);tax=(net*Decimal('.18')).quantize(Decimal('.01'));total=net+tax;date=f'2026-10-{1+(i%28):02d}';claim=f'EXP-2026-{i:04d}';invoice=f'BILL-{i:05d}'
 a.append([claim,eid,name,department,'CC-'+str(10+(i%5)),date,vendor,category,str(total),'INR',invoice,'PRJ-'+str(200+(i%4)),'Personal card' if i%2 else 'Corporate card','Manager '+str((i-1)//18+1),'Submitted','Client visit' if category=='Travel' else category+' for project delivery'])
 if i<=86:b.append([claim,eid,name,invoice,vendor,date,str(net),str(tax),str(total),'INR',claim+'.pdf','2026-11-01','Uploaded','SYNTHETIC-GST-'+str(i%6),'Employee portal'])
for i in [4,12,23,37,56,73]:b[i-1][8]=str(Decimal(b[i-1][8])+150)
b[1][8]=str(Decimal(b[1][8])+Decimal('.50'))
for i in [19,44]:b[i-1][9]='USD'
b[28][1]='EMP-999';b[60][4]='Unrelated Vendor';b[9][3]='BILL-99999';b[15][8]='not readable';b[31][4]=''
b[6][0]='  exp-2026-0007  '
a.append(a[19].copy());b.append(b[39].copy())
a.append(['','EMP-101','Aarav Mehta','Sales','CC-10','2026-10-31','Metro Cabs','Travel','1200.00','INR','BILL-MISSING','PRJ-200','Personal card','Manager 1','Submitted','Missing expense identifier'])
b.append(['','EMP-101','Aarav Mehta','BILL-UNLINKED','Metro Cabs','2026-10-31','1000','180','1180','INR','unlinked.pdf','2026-11-01','Uploaded','SYNTHETIC-GST-0','Employee portal'])
for i in range(91,94):b.append([f'EXP-2026-{i:04d}','EMP-115','Farhan Ali',f'BILL-{i:05d}','Metro Cabs','2026-10-31','1000','180','1180','INR',f'orphan-{i}.pdf','2026-11-01','Uploaded','SYNTHETIC-GST-0','Employee portal'])
for filename,headers,rows in [('employee_expenses.csv',ah,a),('uploaded_invoices.csv',bh,b)]:
 with (p/filename).open('w',encoding='utf8',newline='') as f:w=csv.writer(f);w.writerow(headers);w.writerows(rows)
r={'version':1,'left_key':'expense_id','right_key':'claim_reference','trim':True,'ignore_case':True,'include_missing':True,'comparisons':[{'left':'claimed_amount','right':'invoice_total','type':'number','tolerance':1},{'left':'employee_id','right':'submitted_by_id','type':'text'},{'left':'currency','right':'currency_code','type':'text'},{'left':'receipt_number','right':'invoice_number','type':'text'},{'left':'merchant','right':'vendor_name','type':'text'}]}
(p/'expense_recipe.json').write_text(json.dumps(r,indent=2))
(p/'expense_expected.json').write_text(json.dumps({'matched':71,'mismatch':12,'invalid_value':1,'duplicate_key':2,'invalid_key':1,'left_only':4,'right_only':3},indent=2))
