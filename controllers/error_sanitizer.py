"""Client-facing error sanitization for the native MCP endpoint (Odoo 13).

Single chokepoint that decides what an MCP client may see when something goes
wrong: never leak tracebacks, source paths, SQL/driver internals, constraint
names or memory addresses to clients.
"""

import logging
import re

try:
    from psycopg2 import errors as pg_errors
except ImportError:
    from ..compat import pg_errors

from odoo import _
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError

_logger = logging.getLogger(__name__)

SAFE_EXCEPTIONS = (UserError, AccessError, ValidationError, MissingError)

GENERIC_ERROR_MESSAGE = "Internal server error"
UNIQUE_ERROR_MESSAGE = "A record with the same unique values already exists."

_TRACEBACK_MARKER = "Traceback (most recent call last)"
_EXCEPTION_LINE_RE = re.compile(
    r"^[A-Za-z_][\w.]*(?:Error|Exception|Warning|Violation)\b"
)
_POSTGRES_DIAG_RE = re.compile(r"^(DETAIL|HINT|CONTEXT|LINE \d)", re.IGNORECASE)

_SCRUB_PATTERNS = (
    (re.compile(r'^\s*File "[^"]+", line \d+.*$', re.MULTILINE), ""),
    (re.compile(r"Traceback \(most recent call last\):"), ""),
    (
        re.compile(
            r"^[ \t]*(?:DETAIL|HINT|CONTEXT|QUERY|LINE \d+):.*$",
            re.IGNORECASE | re.MULTILINE,
        ),
        "",
    ),
    (re.compile(r"(?:/[^/\s]+)+/[^/\s]+\.py\b"), ""),
    (re.compile(r'"[^"]+\.py"'), ""),
    (re.compile(r",?\s*line\s+\d+"), ""),
    (re.compile(r"<class '[^']+'>"), ""),
    (re.compile(r"\b[Oo]bject at 0x[0-9a-fA-F]+"), "object"),
    (re.compile(r"\bat 0x[0-9a-fA-F]+"), ""),
    (re.compile(r"\b(?:odoo|mcp_server)\.[A-Za-z0-9_.]+:"), ""),
    (re.compile(r"\bpsycopg2(?:\.[A-Za-z0-9_.]+)?\b", re.IGNORECASE), ""),
)


def sanitize_exception(exc, log_context=None):
    """Return a client-safe message for ``exc`` (the public entry point)."""
    if isinstance(exc, SAFE_EXCEPTIONS):
        return sanitize_message(_exc_message(exc))
    _logger.error(log_context or "Unhandled MCP error", exc_info=exc)
    return GENERIC_ERROR_MESSAGE


def sanitize_integrity_error(env, exc, log_context=None):
    """Client-safe message for a database constraint failure."""
    _logger.warning(log_context or "MCP database constraint error", exc_info=exc)
    try:
        table = getattr(exc.diag, "table_name", None)
        model = env["base"]
        if table:
            for rclass in env.registry.values():
                if table == getattr(rclass, "_table", None):
                    model = env[rclass._name]
                    break
        message = _insert_fk_message(model, exc)
        if not message and _is_translated_by_core(env, exc):
            try:
                from odoo.service.model import _as_validation_error
                message = _as_validation_error(env, exc).args[0]
            except Exception:
                if isinstance(exc, pg_errors.NotNullViolation):
                    message = _("A required field is missing.")
                elif getattr(exc.diag, "constraint_name", None):
                    constraint = exc.diag.constraint_name
                    for model_name in env.registry.keys():
                        for def_name, _sql, msg in getattr(env[model_name], "_sql_constraints", []):
                            if def_name == constraint:
                                message = msg
                                break
                        if message:
                            break
        if not message:
            if isinstance(exc, pg_errors.UniqueViolation):
                return UNIQUE_ERROR_MESSAGE
            return GENERIC_ERROR_MESSAGE
        return sanitize_message(message)
    except Exception:  # noqa: BLE001
        _logger.exception("Could not translate database constraint error")
        return GENERIC_ERROR_MESSAGE


def _is_translated_by_core(env, exc):
    """Whether the exception can be resolved into a friendly message."""
    if isinstance(exc, (pg_errors.NotNullViolation, pg_errors.ForeignKeyViolation)):
        return True
    constraint_name = getattr(exc.diag, "constraint_name", None)
    sql_constraints = getattr(env.registry, "_sql_constraints", {})
    return bool(constraint_name and constraint_name in sql_constraints)


def _columns_from_diagnostics(cr, diag):
    """Column names behind a constraint failure, from the driver diagnostics."""
    if getattr(diag, "column_name", None):
        return [diag.column_name]
    constraint_name = getattr(diag, "constraint_name", None)
    table_name = getattr(diag, "table_name", None)
    if not constraint_name or not table_name:
        return []
    try:
        query = """
            SELECT ARRAY(
                SELECT attname FROM pg_attribute
                WHERE attrelid = conrelid AND attnum = ANY(conkey)
            ) AS "columns"
            FROM pg_constraint
            JOIN pg_class t ON t.oid = conrelid
            WHERE conname = %s
                AND t.relname = %s
                AND t.relnamespace = current_schema::regnamespace
        """
        cr.execute(query, (constraint_name, table_name))
        row = cr.fetchone()
        return row[0] if row else []
    except Exception:
        return []


def _insert_fk_message(model, exc):
    """Message for a dangling foreign key on INSERT / UPDATE, else ``None``."""
    if not isinstance(exc, pg_errors.ForeignKeyViolation):
        return None
    primary = getattr(exc.diag, "message_primary", "") or ""
    if not primary.startswith("insert or update"):
        return None
    try:
        model_string = model.env["ir.model"]._get(model._name).name or model._description
    except Exception:
        model_string = getattr(model, "_description", model._name)
    columns = _columns_from_diagnostics(model.env.cr, exc.diag)
    field = model._fields.get(columns[0]) if len(columns) == 1 else None
    if field:
        desc = field._description_string(model.env) if hasattr(field, "_description_string") else field.string
        return _(
            "The value for %(field)s refers to a record that does not exist.\n"
            "Model: %(model)s"
        ) % {
            "field": f"'{desc}' ({field.name})",
            "model": f"'{model_string}' ({model._name})",
        }
    return _(
        "A value refers to a record that does not exist.\nModel: %(model)s"
    ) % {
        "model": f"'{model_string}' ({model._name})",
    }


def sanitize_message(text):
    """Scrub internal detail from ``text`` and return a client-safe string."""
    if not text:
        return GENERIC_ERROR_MESSAGE

    text = _reduce_traceback(str(text))
    for pattern, replacement in _SCRUB_PATTERNS:
        text = pattern.sub(replacement, text)

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text or GENERIC_ERROR_MESSAGE


def _exc_message(exc):
    """Best-effort user message from an Odoo exception (its first string arg)."""
    args = getattr(exc, "args", None)
    if args and isinstance(args[0], str):
        return args[0]
    return str(exc)


def _reduce_traceback(text):
    """Reduce a traceback-shaped message to its final exception message."""
    if _TRACEBACK_MARKER not in text:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    while lines and _POSTGRES_DIAG_RE.match(lines[-1]):
        lines.pop()
    if not lines:
        return GENERIC_ERROR_MESSAGE

    last_frame = max(
        (i for i, line in enumerate(lines) if line.startswith('File "')),
        default=-1,
    )
    tail = lines[last_frame + 1 :]
    exc_idx = next(
        (i for i, line in enumerate(tail) if _EXCEPTION_LINE_RE.match(line)),
        len(tail) - 1,
    )
    final = "\n".join(tail[exc_idx:])
    final = re.split(r"\s+DETAIL:", final)[0].strip()
    if not re.search(r"[A-Za-z]", final):
        return GENERIC_ERROR_MESSAGE
    return final
