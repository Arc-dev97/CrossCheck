import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.engine import read_csv, reconcile
ROOT=Path(__file__).resolve().parents[1]
class EngineTests(unittest.TestCase):
    def test_demo(self):
        d=ROOT/'demo'
        a=read_csv((d/'warehouse.csv').read_text(encoding='utf8'))
        b=read_csv((d/'store.csv').read_text(encoding='utf8'))
        recipe=json.loads((d/'recipe.json').read_text())
        result=reconcile(a,b,recipe)
        self.assertEqual(result['summary'],json.loads((d/'expected.json').read_text()))
        self.assertEqual(result['accounting'],{'left_input':62,'right_input':61,'left_accounted':62,'right_accounted':61})
        self.assertEqual(result,reconcile(a,b,recipe))
        recipe['comparisons'][0]['tolerance']=5
        changed=reconcile(a,b,recipe)
        self.assertEqual(changed['summary']['mismatch'],2)
    def test_collisions_and_nulls(self):
        a=read_csv('id,n\n a ,1\nA,2\n,4\n')
        b=read_csv('id,n\nA,1\n,4\n')
        r=reconcile(a,b,{'left_key':'id','right_key':'id','comparisons':[{'left':'n','right':'n','type':'number'}]})
        self.assertEqual(r['summary'],{'invalid_key':1,'duplicate_key':1})
    def test_missing_data(self):
        a=read_csv('id,name,note\n1,,unused\n2,Camera,\n')
        b=read_csv('id,name\n1,\n2,Camera\n')
        recipe={'left_key':'id','right_key':'id','comparisons':[{'left':'name','right':'name','type':'text'}]}
        result=reconcile(a,b,recipe)
        self.assertEqual(result['summary'],{'missing_data':1,'matched':1})
        self.assertEqual(len(result['results'][0]['missing_fields']),2)
        recipe['include_missing']=False
        result=reconcile(a,b,recipe)
        self.assertEqual(result['summary'],{'matched':1})
        self.assertEqual(result['excluded_groups'],1)
        self.assertEqual(result['excluded_source_rows'],{'left':1,'right':1})
        self.assertEqual(result['accounting']['left_accounted'],2)

    def test_non_demo_headers(self):
        a=read_csv('employee,email\nE1,a@example.com\nE2,b@example.com\n')
        b=read_csv('staff,login\nE1,a@example.com\nE3,c@example.com\n')
        r=reconcile(a,b,{'left_key':'employee','right_key':'staff','comparisons':[{'left':'email','right':'login','type':'text'}]})
        self.assertEqual(r['summary'],{'matched':1,'left_only':1,'right_only':1})

    def test_expense_demo(self):
        d=ROOT/'demo'
        left=read_csv((d/'employee_expenses.csv').read_text());right=read_csv((d/'uploaded_invoices.csv').read_text())
        r=reconcile(left,right,json.loads((d/'expense_recipe.json').read_text()))
        self.assertEqual(r['summary'],json.loads((d/'expense_expected.json').read_text()))
        self.assertEqual(r['accounting'],{'left_input':92,'right_input':91,'left_accounted':92,'right_accounted':91})
        self.assertEqual(len(set(x['values']['employee_id'] for x in left['rows'])),15)

    def test_large_numbers(self):
        a=read_csv('id,n\n1,1000000000000000000000000000001\n2,1e999999\n')
        b=read_csv('id,n\n1,1000000000000000000000000000000\n2,1\n')
        r=reconcile(a,b,{'left_key':'id','right_key':'id','comparisons':[{'left':'n','right':'n','type':'number'}]})
        self.assertEqual(r['results'][0]['details'][0]['difference'],'1')
        self.assertEqual(r['results'][1]['status'],'invalid_value')

    def test_malformed(self):
        with self.assertRaises(ValueError): read_csv('a,a\n1,2')
        with self.assertRaises(ValueError): read_csv('a,b\n1,2,3')
    def test_invalid_values(self):
        for value in ['NaN','Infinity','oops','']:
            a=read_csv('id,n\n001,'+value+'\n')
            b=read_csv('id,n\n001,2\n')
            r=reconcile(a,b,{'left_key':'id','right_key':'id','comparisons':[{'left':'n','right':'n','type':'number'}]})
            self.assertEqual(r['results'][0]['key'],'001')
            self.assertEqual(r['results'][0]['status'],'invalid_value')
if __name__=='__main__': unittest.main()
