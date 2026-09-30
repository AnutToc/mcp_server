from . import auth
from . import mcp_route
from . import mcp
from . import main
from . import rate_limiting
from . import response_utils
from . import utils
from . import api

# --- MONKEY PATCH FOR MCP ROUTES IN ODOO 13 ---
# In Odoo 13, Root.get_request converts any request with mimetype='application/json'
# into a JsonRequest. However, /mcp endpoints are declared as type='http' so they
# can handle CORS OPTIONS preflight, custom headers, and direct JSON-RPC responses.
# Without this patch, Odoo raises:
# "BadRequest: Function declared as capable of handling request of type 'http' but called with a request of type 'json'"
from odoo.http import Root, HttpRequest

orig_get_request = Root.get_request


def _mcp_get_request(self, httprequest):
    path = httprequest.path or ""
    if path == "/mcp" or path.startswith("/mcp/"):
        return HttpRequest(httprequest)
    return orig_get_request(self, httprequest)


Root.get_request = _mcp_get_request
