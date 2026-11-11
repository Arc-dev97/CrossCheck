import csv, json
from pathlib import Path
root = Path(__file__).parent
left_headers = ['SKU','Product Name','Category','Available Units','Reserved Units','Warehouse','Unit Cost','Currency','Supplier','Last Counted','Internal Notes','Legacy Code']
right_headers = ['item_code','title','collection','stock_count','committed','fulfillment_site','cost_price','currency_code','vendor_name','snapshot_date','listing_status','unused_field']
left=[]; right=[]
products=['Camera Body','Prime Lens','Tripod','Wireless Mic','Studio Light','Memory Card','Camera Bag','Battery Pack']
for i in range(1,61):
    sku=f'{i:05d}'; name=products[(i-1)%8]+f' Model {i}'; qty=10+i*3; cost=f'{12+i*2}.50'
    left.append([sku,name,'Video' if i%2 else 'Audio',qty,i%4,'BLR-MAIN',cost,'INR','Supplier '+str(i%5),'2026-11-10','Cycle count verified' if i%7==0 else '', ''])
    if i<=55:
        right.append([sku,name,'Video' if i%2 else 'Audio',qty,i%4,'Bangalore',cost,'INR','Supplier '+str(i%5),'2026-11-10','active',''])
# Real differences and quality exceptions; these are intentionally not auto-corrected.
for i in [3,8,14,22,31,45]: right[i-1][3]=int(right[i-1][3])+5
for i in [11,28]: right[i-1][1]+=' Revised'
right[17][3]='unknown'
right[23][3]=''
right[6][0]='  00007  '
right[35][0]=' 00036 '
left.append(left[19].copy()); right.append(right[39].copy())
left.append(['','Unidentified warehouse item','Accessories',7,0,'BLR-MAIN','20.00','INR','Unknown','2026-11-10','Needs SKU',''])
right.append(['','Unidentified listing','Accessories',4,0,'Bangalore','20.00','INR','Unknown','2026-11-10','draft',''])
for i in range(61,65): right.append([f'{i:05d}','Store-only product '+str(i),'Accessories',12,0,'Bangalore','25.00','INR','New supplier','2026-11-10','active',''])
for name,headers,rows in [('warehouse.csv',left_headers,left),('store.csv',right_headers,right)]:
    with (root/name).open('w',newline='',encoding='utf8') as f:
        w=csv.writer(f); w.writerow(headers); w.writerows(rows)
recipe={'left_key':'SKU','right_key':'item_code','trim':True,'ignore_case':True,'comparisons':[{'left':'Available Units','right':'stock_count','type':'number','tolerance':0},{'left':'Product Name','right':'title','type':'text','tolerance':0}]}
(root/'recipe.json').write_text(json.dumps(recipe,indent=2))
(root/'expected.json').write_text(json.dumps({'matched':43,'mismatch':8,'invalid_value':2,'duplicate_key':2,'invalid_key':1,'left_only':5,'right_only':4},indent=2))
