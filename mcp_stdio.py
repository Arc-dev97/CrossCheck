# Local stdio must be explicitly bound to a previously signed-in user's workspace.
import os
from server import mcp, DB, sqlite3
from contextlib import closing
from app.auth import owner_context
if __name__=='__main__':
    owner=os.getenv('RECONCILE_STDIO_OWNER','').strip()
    if not owner:raise SystemExit('Sign in via the web app, then explicitly configure RECONCILE_STDIO_OWNER for local stdio. No shared anonymous workspace is available.')
    with closing(sqlite3.connect(DB)) as db:
        if not db.execute('SELECT id FROM users WHERE id=?',(owner,)).fetchone():raise SystemExit('Unknown workspace owner. Sign in first.')
    token=owner_context.set(owner)
    try:mcp.run(transport='stdio')
    finally:owner_context.reset(token)
