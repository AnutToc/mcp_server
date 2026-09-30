"""Custom MCP API key model for Odoo 13.

Replaces the v14+ ``res.users.apikeys`` system that does not exist in v13.
Stores a SHA-256 hash of each key — the raw key is shown once at creation
and never stored.
"""

import hashlib
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class McpApiKey(models.Model):
    _name = "mcp.api.key"
    _description = "MCP API Key"
    _order = "create_date desc"

    name = fields.Char("Description", required=True)
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        ondelete="cascade",
        default=lambda self: self.env.user,
    )
    raw_key = fields.Char(
        "Generated API Key",
        store=False,
        readonly=True,
        help="Copy this key now. It is only shown once during creation.",
    )
    key_hash = fields.Char("Key Hash", required=True, index=True, copy=False)
    scope = fields.Selection(
        [
            ("global", "All APIs"),
            ("mcp", "MCP only"),
        ],
        string="Access Scope",
        default="global",
        required=True,
        help="Choose what this key can do.\n"
        "- All APIs: full RPC access (XML-RPC, JSON-RPC, MCP).\n"
        "- MCP only: authenticates ONLY on /mcp.",
    )
    active = fields.Boolean(default=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        raw = secrets.token_urlsafe(48)
        res["raw_key"] = raw
        res["key_hash"] = hashlib.sha256(raw.encode()).hexdigest()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("key_hash"):
                raw = secrets.token_urlsafe(48)
                vals["key_hash"] = hashlib.sha256(raw.encode()).hexdigest()
        return super().create(vals_list)

    @api.model
    def generate_key(self, name, user_id=None, scope="global"):
        """Generate a new API key. Returns the raw key (shown once)."""
        raw_key = secrets.token_urlsafe(48)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        self.create({
            "name": name,
            "user_id": user_id or self.env.uid,
            "key_hash": key_hash,
            "scope": scope,
        })
        return raw_key

    @api.model
    def _validate_key(self, raw_key, allowed_scopes=("mcp", "global")):
        """Validate a raw API key. Returns the record or None."""
        if not raw_key:
            return None
        key_hash = hashlib.sha256(raw_key.strip().encode()).hexdigest()
        record = self.search([
            ("key_hash", "=", key_hash),
            ("active", "=", True),
            ("scope", "in", list(allowed_scopes)),
        ], limit=1)
        if record and record.user_id.active:
            return record
        return None


class McpApiKeyWizard(models.TransientModel):
    _name = "mcp.api.key.wizard"
    _description = "Generate MCP API Key"

    name = fields.Char("Description", required=True, default="MCP Key")
    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        default=lambda self: self.env.user,
    )
    scope = fields.Selection(
        [
            ("global", "All APIs (default)"),
            ("mcp", "MCP only"),
        ],
        string="Access",
        default="mcp",
        required=True,
    )
    generated_key = fields.Char("Generated Key", readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("generated", "Generated")],
        default="draft",
    )

    def action_generate(self):
        self.ensure_one()
        raw_key = self.env["mcp.api.key"].generate_key(
            name=self.name,
            user_id=self.user_id.id,
            scope=self.scope,
        )
        self.write({
            "generated_key": raw_key,
            "state": "generated",
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("API Key Generated"),
            "res_model": "mcp.api.key.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class ResUsersApikeysBridge(models.AbstractModel):
    """Compatibility bridge for tests/callers expecting v14+ res.users.apikeys."""

    _name = "res.users.apikeys"
    _description = "API Keys compatibility bridge for Odoo 13"

    @api.model
    def _generate(self, scope, name, expiration_date=None):
        mcp_scope = "mcp" if scope == "mcp" else "global"
        return self.env["mcp.api.key"].generate_key(
            name=name, user_id=self.env.uid, scope=mcp_scope
        )

    @api.model
    def _check_credentials(self, scope, key):
        record = self.env["mcp.api.key"]._validate_key(
            key, allowed_scopes=(scope,) if scope else ("mcp", "global")
        )
        return record.user_id.id if record else None
