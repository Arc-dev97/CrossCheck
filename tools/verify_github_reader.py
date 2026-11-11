"""Read-only network check against GitHub's public MCP repository; saves no app data."""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.repositories import RepositoryManager,RepositoryInput
records={}
def save(kind,payload):
    obj=payload|{'id':'public-network-fixture'};records[obj['id']]=obj;return obj
backend=SimpleNamespace(save=save,get=lambda kind,id:records[id])
manager=RepositoryManager(backend)
r=manager.create(RepositoryInput(name='Public network check',repository='github/github-mcp-server',paths=['docs/']))
f=manager.file(r['id'],'docs/server-configuration.md')
assert len(f['commit_sha'])==40 and 'Read-Only' in f['content']
branches=manager.branches(r['id']);assert branches['branches']
print('PASS: actual GitHub API branch resolution, bounded UTF-8 file read, evidence SHA and branch listing. No workspace records changed.')
