"""Route decorator preset for native MCP protocol endpoints (Odoo 13).

Pins type='http' and auth='none' for stateless JSON-RPC endpoints.
"""

from odoo import http

MCP_MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MiB


def mcp_route(*args, **kwargs):
    """Bind a route for MCP in Odoo 13.

    Pins type='http' / auth='none' with manual authentication, CORS and JSON
    handling in the controller. Removes v16+ kwargs (save_session, max_content_length).
    """
    kwargs.setdefault("type", "http")
    kwargs.setdefault("auth", "none")
    kwargs.setdefault("csrf", False)
    kwargs.setdefault("cors", "*")
    kwargs.pop("max_content_length", None)
    kwargs.pop("save_session", None)
    return http.route(*args, **kwargs)
