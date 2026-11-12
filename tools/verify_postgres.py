"""Run API and concurrency regression tests against the isolated Supabase QA schema."""
import logging,os,sys,unittest
from pathlib import Path
from dotenv import dotenv_values
ROOT=Path(__file__).resolve().parents[1]
for k,v in dotenv_values(ROOT/'data/postgres-qa.env').items():os.environ[k]=v
if os.getenv('CROSSCHECK_DB_SCHEMA')!='crosscheck_qa':raise SystemExit('Expected the isolated QA schema.')
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
logging.getLogger('httpx').setLevel(logging.WARNING)
import test_postgres_storage
suite=unittest.TestSuite(test_postgres_storage.PostgresTests(name) for name in sys.argv[1:]) if len(sys.argv)>1 else unittest.defaultTestLoader.loadTestsFromTestCase(test_postgres_storage.PostgresTests)
r=unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if r.wasSuccessful() else 1)
