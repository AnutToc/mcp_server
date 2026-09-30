"""HTTP layer extensions for the native MCP protocol endpoint (Odoo 13).

Adds custom authentication and error handling for MCP routes.
"""

import logging
import re

from werkzeug.exceptions import Forbidden, HTTPException, Unauthorized

from odoo import models
from odoo.http import request, Response

_logger = logging.getLogger(__name__)

from ..compat import (
    disable_session_save,
    make_json_response,
    make_www_authenticate_bearer,
    update_request_context,
    update_request_env,
)
from ..controllers import auth, jsonrpc, utils
from ..controllers.error_sanitizer import GENERIC_ERROR_MESSAGE
from ..controllers.rate_limiting import SlidingWindowLimiter

_BEARER_FAILURE_MAX = 20
_BEARER_FAILURE_WINDOW_SECONDS = 60
_bearer_failure_limiter = SlidingWindowLimiter(_BEARER_FAILURE_WINDOW_SECONDS)

_AUTH_SCHEME_NAMES = {"bearer", "basic", "digest", "negotiate", "ntlm"}


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_mcp(cls):
        """Authenticate an MCP request via ``Authorization: Bearer <token>``."""
        header = request.httprequest.headers.get("Authorization")
        token = cls._extract_bearer_token(header)
        if not token:
            if header:
                auth._log_auth_failure(
                    "Malformed Authorization header", api_key_used=False
                )
            raise cls._mcp_unauthorized(
                "Missing credentials; provide an "
                "'Authorization: Bearer <token>' header."
            )

        user = auth.get_user_from_api_key(
            token, allowed_scopes=("mcp", "global"), log_failure=False
        )
        if user:
            if not auth.user_has_mcp_access(user):
                raise cls._mcp_group_forbidden(user, api_key_used=True)
            request._mcp_auth_method = "api_key"
            cls._bind_mcp_user(user.id)
            return

        if not _bearer_failure_limiter.is_limited(
            (request.db, request.httprequest.remote_addr), _BEARER_FAILURE_MAX
        ):
            auth._log_auth_failure("Invalid or expired credentials", api_key_used=False)
        raise cls._mcp_unauthorized("Invalid or expired credentials.")

    @staticmethod
    def _extract_bearer_token(header):
        """Extract the credential from an ``Authorization`` header value."""
        if not header:
            return None
        match = re.match(r"^bearer\s+(.+)$", header, re.IGNORECASE)
        if match:
            return match.group(1)
        bare = header.strip()
        if (
            bare
            and not re.search(r"\s", bare)
            and bare.lower() not in _AUTH_SCHEME_NAMES
        ):
            return bare
        return None

    @classmethod
    def _bind_mcp_user(cls, uid):
        """Bind the current MCP request to ``uid`` (stateless: no saved session)."""
        update_request_env(uid)
        try:
            update_request_context(**request.env["res.users"].context_get())
        except Exception:
            pass
        disable_session_save()

    @staticmethod
    def _mcp_group_forbidden(user, api_key_used):
        """Build the 403 for a valid credential whose user lacks the MCP group."""
        auth.log_mcp_group_denied(user, api_key_used=api_key_used)
        return Forbidden(
            "Your user is not authorized for MCP access. Ask your Odoo "
            "administrator for the 'MCP User' group."
        )

    @staticmethod
    def _mcp_unauthorized(description):
        """Build a 401 response."""
        return Unauthorized(description)

    @classmethod
    def _handle_exception(cls, exception):
        """Render internal errors on MCP routes as JSON-RPC ``-32603``."""
        if cls._is_mcp_request() and not isinstance(exception, HTTPException):
            _logger.exception("MCP Internal Error: %s", exception)
            return make_json_response(
                jsonrpc.make_error(
                    None,
                    jsonrpc.INTERNAL_ERROR,
                    GENERIC_ERROR_MESSAGE,
                )
            )
        return super()._handle_exception(exception)

    @classmethod
    def _is_mcp_request(cls):
        """Whether the current request is an MCP request."""
        try:
            path = request.httprequest.path or ""
            return path == "/mcp" or path.startswith("/mcp/")
        except Exception:
            return False

    @classmethod
    def _dispatch(cls):
        """Route MCP requests cleanly regardless of incoming Content-Type (Odoo 13)."""
        if cls._is_mcp_request():
            try:
                rule, arguments = cls._match(request.httprequest.path)
                func = rule.endpoint
                auth_method = cls._authenticate(func.routing["auth"])
                request.set_handler(func, arguments, auth_method)
                orig_type = request._request_type
                request._request_type = func.routing.get("type", "http")
                try:
                    result = request._call_function(**request.params)
                    if not result:
                        result = Response(status=204)
                    return result
                finally:
                    request._request_type = orig_type
            except Exception as e:
                return cls._handle_exception(e)

        return super()._dispatch()

