from . import auth

# Import the dispatcher first so its routing_type='mcp' registers in
# http._dispatchers before any @mcp_route endpoint is bound (the @route assert
# checks the type is known at decoration time).
from . import mcp_dispatcher
from . import mcp_route
from . import mcp
from . import main
from . import rate_limiting
from . import response_utils
from . import utils
from . import api
from . import oauth_server

# --- MONKEY PATCH FOR X-ODOO-DB (Odoo 18) ---
from odoo.http import Request
orig_get_session = Request._get_session_and_dbname
def _get_session_patched(self):
    session, dbname = orig_get_session(self)
    odoo_db = self.httprequest.headers.get("X-Odoo-DB")
    if odoo_db:
        session.db = odoo_db
        dbname = odoo_db
    return session, dbname
Request._get_session_and_dbname = _get_session_patched
