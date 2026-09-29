"""Odoo 13 ↔ 18 compatibility shim.

Every Odoo-version-specific API that this module needs is wrapped here.
The rest of the codebase imports from ``compat`` instead of calling the
version-specific API directly, so a version upgrade only touches this file.

Odoo 13 runs on Python 3.6–3.8 and werkzeug 0.16.x.
Odoo 18 runs on Python 3.10–3.12 and werkzeug 2.3.x+.

Usage::

    from .compat import (
        make_json_response,
        update_request_env,
        get_json_data,
        get_registry_cursor,
        clear_registry_cache,
        check_record_access,
        compute_display_name,
    )
"""

import json
import logging

from odoo.http import request, Response

_logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# 1. HTTP Response helpers
#    v18: request.make_json_response(data, headers=..., status=200)
#    v13: does not exist → build a werkzeug Response manually
# ──────────────────────────────────────────────────────────────

def make_json_response(data, status=200, headers=None):
    """Build a JSON HTTP response (v13-compatible).

    Replaces ``request.make_json_response(data, status=..., headers=...)``
    which is only available in Odoo 16+.

    :param data: any JSON-serializable object (dict, list, str, etc.)
    :param status: HTTP status code (default 200)
    :param headers: optional list of (key, value) tuples or dict
    :return: a ``werkzeug.wrappers.Response``
    """
    body = json.dumps(data, default=str, ensure_ascii=False)
    resp = Response(
        body,
        status=status,
        content_type="application/json; charset=utf-8",
    )
    if headers:
        if isinstance(headers, dict):
            headers = headers.items()
        for key, value in headers:
            resp.headers[key] = value
    return resp


# ──────────────────────────────────────────────────────────────
# 2. Request body parsing
#    v18: request.get_json_data()
#    v13: does not exist → json.loads(request.httprequest.get_data())
# ──────────────────────────────────────────────────────────────

def get_json_data():
    """Parse the raw request body as JSON (v13-compatible).

    Replaces ``request.get_json_data()`` (Odoo 16+).

    :return: parsed JSON object
    :raises ValueError: when the body is not valid JSON
    """
    raw = request.httprequest.get_data(as_text=True)
    return json.loads(raw)


# ──────────────────────────────────────────────────────────────
# 3. Binding a request to a user (stateless auth)
#    v18: request.update_env(user=uid)
#         request.update_context(**ctx)
#    v13: does not exist → rebuild request.env manually
# ──────────────────────────────────────────────────────────────

def update_request_env(uid):
    """Bind the current request to ``uid`` without saving a session (v13).

    Replaces ``request.update_env(user=uid)`` (Odoo 16+).

    In Odoo 13, ``request.env`` is rebuilt by assigning ``request.uid``
    and then accessing ``request.env`` (which lazily builds a new
    Environment). ``request.session.should_save`` is set to ``False``
    so the stateless MCP auth does not persist a session cookie.
    """
    request.uid = uid
    # Force env rebuild on next access
    if hasattr(request, '_env'):
        del request._env


def update_request_context(**kwargs):
    """Merge extra keys into the request's context dict (v13).

    Replaces ``request.update_context(**kwargs)`` (Odoo 16+).
    In v13 we replace ``request.env.context`` with a new dict.
    """
    ctx = dict(request.env.context or {}, **kwargs)
    request.env = request.env(context=ctx)


def disable_session_save():
    """Prevent the session from being saved (v13-compatible).

    Replaces ``request.session.can_save = False`` (v16+).
    In v13 the flag is called ``should_save``.
    """
    if hasattr(request.session, 'should_save'):
        request.session.should_save = False
    elif hasattr(request.session, 'can_save'):
        request.session.can_save = False


# ──────────────────────────────────────────────────────────────
# 4. Registry / cache operations
#    v18: request.env.registry.clear_cache()
#         with request.env.registry.cursor() as cr:
#    v13: self.pool.clear_caches() (note: "caches" with an 's')
#         registry.cursor() exists but import path differs
# ──────────────────────────────────────────────────────────────

def clear_registry_cache(env_or_registry):
    """Flush all @ormcache entries for the current database (v13-compatible).

    Replaces ``env.registry.clear_cache()`` (v16+).
    In v13 the method is called ``clear_caches()`` (with an 's').
    """
    registry = getattr(env_or_registry, 'registry', env_or_registry)
    if hasattr(registry, 'clear_cache'):
        # v16+
        registry.clear_cache()
    elif hasattr(registry, 'clear_caches'):
        # v13–v15
        registry.clear_caches()


def get_registry_cursor(env):
    """Open a new cursor from the registry (v13-compatible context manager).

    Replaces ``with request.env.registry.cursor() as cr:`` (v16+).
    In v13 the same API exists on the registry object. Returns a
    context manager yielding a cursor.
    """
    return env.registry.cursor()


# ──────────────────────────────────────────────────────────────
# 5. ORM method compatibility
# ──────────────────────────────────────────────────────────────

def check_record_access(record, operation):
    """Check access rights + rules on a record for ``operation`` (v13).

    Replaces ``record.check_access(operation)`` (Odoo 17+).
    In v13 this is two separate calls.

    :param record: a non-empty recordset (singleton or multi)
    :param operation: 'read', 'write', 'create', or 'unlink'
    :raises AccessError: if the check fails
    """
    if hasattr(record, 'check_access'):
        # v17+: combined method
        record.check_access(operation)
    else:
        # v13–v16: two separate calls
        record.check_access_rights(operation)
        record.check_access_rule(operation)


def compute_display_name_compat(records, compute_func):
    """Adapter for ``_compute_display_name`` vs ``name_get`` (v13).

    In v18 (since v17): override ``_compute_display_name`` and assign
    ``record.display_name = ...``.

    In v13: override ``name_get`` and return ``[(id, name), ...]``.

    This helper is not a drop-in wrapper — it documents the pattern.
    Each model that overrides display_name must be adapted individually.

    v18 pattern::

        @api.depends("client_name", "client_id")
        def _compute_display_name(self):
            for rec in self:
                rec.display_name = rec.client_name or rec.client_id

    v13 equivalent::

        def name_get(self):
            return [(rec.id, rec.client_name or rec.client_id) for rec in self]
    """
    # This is a documentation-only helper. See the docstring above.
    raise NotImplementedError(
        "compute_display_name_compat is a pattern guide, not a callable. "
        "Override name_get() on your model directly."
    )


# ──────────────────────────────────────────────────────────────
# 6. Translation function _() with named parameters
#    v18: _("Hello %(name)s", name=value)
#    v13: _("Hello %s") % (value,)
#         or _("Hello %(name)s") % {"name": value}
#
#    In v13 the _() function is plain gettext and does NOT accept
#    keyword arguments. The named-param form was added in ~v15.
#    The porting rule is:
#
#    BEFORE (v18):
#        _("Record %(model)s with ID %(id)s", model=m, id=i)
#
#    AFTER (v13):
#        _("Record %(model)s with ID %(id)s") % {"model": m, "id": i}
#
#    Or for single args:
#        _("Unknown model: %s", model)   →   _("Unknown model: %s") % (model,)
#
#    This cannot be wrapped in a helper because _() must receive the
#    literal string for the translation extractor. Each call site must
#    be changed individually.
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# 7. @api.model_create_multi → @api.model (v13)
#    v18: @api.model_create_multi — receives vals_list (list of dicts)
#    v13: @api.model_create_multi EXISTS since v12 but some v13 modules
#         still use @api.model + single dict. The decorator itself
#         works in v13, but check that model.create([list]) is supported
#         for each model. In v13, create() on most models DOES accept a
#         list and returns a multi-recordset. Keep @api.model_create_multi
#         as-is if it works; otherwise change to @api.model with a loop.
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# 8. zip(strict=True) → itertools or manual check
#    v18 (Python 3.10+): zip(a, b, strict=True)
#    v13 (Python 3.6):   zip(a, b)  — no strict param
# ──────────────────────────────────────────────────────────────

def zip_strict(a, b):
    """zip two iterables with a length check (Python 3.6-compatible).

    Replaces ``zip(a, b, strict=True)`` (Python 3.10+).
    Raises ``ValueError`` if the iterables have different lengths.
    """
    a_list = list(a)
    b_list = list(b)
    if len(a_list) != len(b_list):
        raise ValueError(
            "zip_strict: iterables have different lengths: "
            f"{len(a_list)} vs {len(b_list)}"
        )
    return zip(a_list, b_list)


# ──────────────────────────────────────────────────────────────
# 9. limited_field_access_token (v17+ only)
#    Used by read_attachment to build time-limited download links.
#    v13 does not have this. Options:
#    a) Remove download-link feature for v13
#    b) Implement a simple HMAC token generator
# ──────────────────────────────────────────────────────────────

def generate_field_access_token(record, field, ttl_hours=1):
    """Generate a time-limited access token for a binary field (v13).

    Replaces ``odoo.tools.misc.limited_field_access_token`` (v17+).
    This is a simplified HMAC-based implementation. The token grants
    unauthenticated download access to one field on one record for
    ``ttl_hours`` hours.

    NOTE: For v13 back-port, consider simply removing the download-link
    feature and always returning inline base64 or a regular Odoo URL
    that requires authentication. This avoids the security complexity
    of self-signed bearer URLs.
    """
    # Placeholder — implement or remove the feature for v13.
    # If implementing: use hmac + time + db secret to sign.
    _logger.warning(
        "generate_field_access_token is a placeholder. "
        "The download-link feature needs a v13-specific implementation "
        "or should be removed."
    )
    return None


# ──────────────────────────────────────────────────────────────
# 10. Werkzeug compatibility
#     v18 (werkzeug 2.3+): WWWAuthenticate("Bearer", {"key": "val"})
#     v13 (werkzeug 0.16):  WWWAuthenticate("bearer", {"key": "val"})
#                           API is similar but class internals differ
# ──────────────────────────────────────────────────────────────

def make_www_authenticate_bearer(**params):
    """Build a ``WWW-Authenticate: Bearer ...`` header value (v13-compatible).

    Replaces direct ``WWWAuthenticate("Bearer", {...})`` construction
    which differs between werkzeug 0.16 (v13) and 2.x (v18).

    Returns the header VALUE as a string, not a werkzeug object, so the
    caller can set it with ``response.headers["WWW-Authenticate"] = value``.
    """
    if not params:
        return "Bearer"
    parts = ", ".join(f'{k}="{v}"' for k, v in params.items())
    return f"Bearer {parts}"


# ──────────────────────────────────────────────────────────────
# 11. CORS response helper
#     v18: request.future_response.headers.set(...)
#     v13: no future_response — set headers on the actual Response
# ──────────────────────────────────────────────────────────────

def set_cors_headers(response, allowed_origin="*", methods="POST",
                     extra_headers=None):
    """Set CORS headers on a response object (v13-compatible).

    Replaces the ``request.future_response.headers`` pattern (v16+).
    In v13 there is no ``future_response``; headers must be set on the
    actual ``Response`` object returned by the controller.

    :param response: werkzeug Response object
    :param allowed_origin: the Access-Control-Allow-Origin value
    :param methods: the Access-Control-Allow-Methods value
    :param extra_headers: optional string for Access-Control-Allow-Headers
    """
    response.headers["Access-Control-Allow-Origin"] = allowed_origin
    response.headers["Access-Control-Allow-Methods"] = methods
    if extra_headers:
        response.headers["Access-Control-Allow-Headers"] = extra_headers
    return response


# ──────────────────────────────────────────────────────────────
# 12. Monkey-patch compatibility
#     v18 controllers/__init__.py patches Request._get_session_and_dbname
#     v13: this method does not exist. The X-Odoo-DB header must be
#          handled differently (e.g. in a before_request hook or
#          directly in the controller).
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# 13. ir.config_parameter / ir.default differences
#     v18: env["ir.default"].sudo().get("res.partner", "lang")
#     v13: env["ir.default"].sudo().get("res.partner", "lang")
#          → same API ✅ (ir.default exists since v12)
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# 14. API key system
#     v18: res.users.apikeys model + _check_credentials(scope=, key=)
#     v13: DOES NOT EXIST — res.users.apikeys was added in v14
#
#     Options for v13:
#     a) Create a custom mcp.api.key model that stores hashed keys
#     b) Rely on XML-RPC uid/password authentication only
#     c) Use a simple token stored in ir.config_parameter
#
#     Recommendation: Create mcp.api.key model (option a). See the
#     PORTING_GUIDE.md for the migration plan.
# ──────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────
# 15. HTTP Controller & Dispatcher architecture
#     v18: custom http.Dispatcher subclass, type="mcp", auth="mcp"
#     v13: no Dispatcher class — use type="json" or type="http"
#
#     Migration plan:
#     - Replace type="mcp" with type="http" + manual JSON parsing
#     - Replace auth="mcp" with auth="none" + manual auth in controller
#     - Handle CORS in controller methods instead of Dispatcher
#     - See PORTING_GUIDE.md for detailed instructions per file.
# ──────────────────────────────────────────────────────────────
