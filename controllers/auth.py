"""Authentication utilities for MCP Server (Odoo 13)."""

import functools
import logging

from odoo import SUPERUSER_ID
from odoo.http import request

from . import audit
from .rate_limiting import SlidingWindowLimiter

_logger = logging.getLogger(__name__)

_AUTH_FAILURE_MAX = 20
_AUTH_FAILURE_WINDOW_SECONDS = 60
_auth_failure_limiter = SlidingWindowLimiter(_AUTH_FAILURE_WINDOW_SECONDS)


def _log_auth_failure(error_message, api_key_used=True, user_id=None):
    """Write an authentication-failure audit row via :func:`audit.write_audit_row`."""
    if _auth_failure_limiter.is_limited(
        (request.db, request.httprequest.remote_addr), _AUTH_FAILURE_MAX
    ):
        return
    audit.write_audit_row(
        SUPERUSER_ID,
        lambda mcp_log: mcp_log.log_authentication(
            success=False,
            user_id=user_id,
            api_key_used=api_key_used,
            ip_address=request.httprequest.remote_addr,
            error_message=error_message,
        ),
        "Failed to write MCP auth-failure audit row",
    )


MCP_GROUP_DENIED_MESSAGE = (
    "User is not a member of the MCP User group (mcp_server.group_mcp_user)"
)


def log_mcp_group_denied(user, *, api_key_used):
    """Audit a valid credential refused for lacking the MCP access group."""
    _log_auth_failure(
        MCP_GROUP_DENIED_MESSAGE, api_key_used=api_key_used, user_id=user.id
    )


def user_has_mcp_access(user):
    """Whether ``user`` may use any MCP surface at all.

    Membership in the "MCP User" group (mcp_server.group_mcp_user).
    """
    user_su = user.sudo()
    group = user_su.env.ref("mcp_server.group_mcp_user", raise_if_not_found=False)
    return bool(group) and group.id in user_su.groups_id.ids


def get_user_from_api_key(api_key, *, allowed_scopes=("mcp", "global"), log_failure=True):
    """Get user from API key using mcp.api.key model in Odoo 13."""
    if not api_key:
        return None

    try:
        key_record = request.env["mcp.api.key"].sudo()._validate_key(
            api_key, allowed_scopes=allowed_scopes
        )
        if not key_record:
            if log_failure:
                _log_auth_failure("Invalid API key")
            return None

        user = key_record.user_id
        if user and user.active:
            return user
        else:
            if log_failure:
                _log_auth_failure("User not found or inactive")
            return None
    except Exception as e:
        _logger.exception("Error validating API key")
        if log_failure:
            _log_auth_failure(str(e))
        return None


def validate_api_key(req):
    """Validate API key from request headers."""
    api_key = req.httprequest.headers.get("X-API-Key")
    if not api_key:
        return None

    return get_user_from_api_key(api_key, allowed_scopes=("global", "mcp"))


def get_user_from_session():
    """Get user from the current Odoo session."""
    try:
        user = request.env.user
        if user and user.id and user.id != request.env.ref("base.public_user").id:
            return user
    except Exception as e:
        _logger.debug("Session auth check failed: %s", e)
    return None


def require_auth(func):
    """Decorator for endpoints requiring authentication."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        from . import response_utils

        user = validate_api_key(request)
        api_key_used = user is not None

        if not user:
            user = get_user_from_session()

        if user and not user_has_mcp_access(user):
            log_mcp_group_denied(user, api_key_used=api_key_used)
            return response_utils.error_response(
                "Access denied: your user is not authorized for MCP. Ask your "
                "Odoo administrator for the 'MCP User' group.",
                "E403",
                status=403,
            )

        if not user:
            if not request.httprequest.headers.get("X-API-Key"):
                _log_auth_failure("No valid API key or session", api_key_used=False)
            return response_utils.error_response(
                "Authentication required. Provide a valid API key "
                "(X-API-Key header) or session cookie.",
                "E401",
                status=401,
            )

        kwargs["user"] = user
        return func(*args, **kwargs)

    return wrapper


require_api_key = require_auth
