"""Tests for the dedicated ``mcp`` API-key scope in Odoo 13.

Covers:
* ``mcp.api.key`` model generation and validation with scopes ('mcp' vs 'global').
* ``auth.get_user_from_api_key`` authenticates valid keys on POST /mcp.
* Scope isolation: 'mcp'-scoped key validates under mcp scope but not global scope.
* ``mcp.api.key.wizard`` generates keys with the selected scope.
"""

import json
import time
from unittest.mock import MagicMock, patch

from odoo.tests import common, tagged

from ..controllers import auth, rate_limiting, utils
from .test_helpers import create_test_user, grant_mcp_access

# Must match mcp_server/controllers/mcp.py.
PREFERRED_PROTOCOL_VERSION = "2025-11-25"


@tagged("much_unit", "post_install", "-at_install")
class TestApiKeyScope(common.HttpCase):
    """``mcp``-scoped and global keys at the ``/mcp`` bearer door."""

    def setUp(self):
        super().setUp()
        utils.clear_mcp_caches()
        rate_limiting._api_limiter.clear()

        unique_id = str(int(time.time() * 1000))[-6:]
        self.mcp_user = create_test_user(
            self.env,
            "MCP Scope User",
            f"mcp_scope_user_{unique_id}",
            email=f"mcp_scope_{unique_id}@example.com",
        )
        grant_mcp_access(self.mcp_user)

        # A key minted with the dedicated ``mcp`` scope...
        self.mcp_key = self.env["mcp.api.key"].generate_key(
            "MCP Scoped Key", user_id=self.mcp_user.id, scope="mcp"
        )
        # ...and a global key.
        self.global_key = self.env["mcp.api.key"].generate_key(
            "Global Scope Key", user_id=self.mcp_user.id, scope="global"
        )

        # Enable MCP globally and drop any stale cached toggle value.
        self.env["ir.config_parameter"].sudo().set_param("mcp_server.enabled", "True")
        utils.clear_mcp_caches()

    def _post_rpc(self, body, api_key):
        """POST a JSON-RPC ``body`` dict to ``/mcp`` with a bearer key."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        return self.url_open("/mcp", data=json.dumps(body), headers=headers)

    def _get_rest(self, path, api_key):
        """GET a legacy REST ``path`` with an ``X-API-Key`` header."""
        return self.url_open(
            path, headers={"X-API-Key": api_key, "Accept": "application/json"}
        )

    def test_mcp_scoped_key_authenticates_on_rpc(self):
        """An mcp-scoped key authenticates on ``/mcp``."""
        response = self._post_rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": PREFERRED_PROTOCOL_VERSION},
            },
            api_key=self.mcp_key,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("error", body)
        self.assertEqual(
            body["result"]["protocolVersion"], PREFERRED_PROTOCOL_VERSION
        )

    def test_global_scope_key_authenticates_on_rpc(self):
        """A global-scope key authenticates on ``/mcp``."""
        response = self._post_rpc(
            {"jsonrpc": "2.0", "id": 2, "method": "ping"},
            api_key=self.global_key,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn("error", body)
        self.assertEqual(body["result"], {})

    def test_scope_isolation(self):
        """An mcp-scoped key resolves under mcp scope but NOT global scope."""
        apikeys = self.env["mcp.api.key"].sudo()
        self.assertTrue(
            apikeys._validate_key(self.mcp_key, allowed_scopes=("mcp",)),
            "the mcp-scoped key must resolve under an mcp-scope lookup",
        )
        self.assertFalse(
            apikeys._validate_key(self.mcp_key, allowed_scopes=("global",)),
            "an mcp-scoped key must NOT authenticate under scope='global'",
        )

    def test_rest_routes_authenticate_valid_key(self):
        """Both mcp and global keys authenticate on /mcp/models REST route."""
        for label, key in (("global", self.global_key), ("mcp", self.mcp_key)):
            response = self._get_rest("/mcp/models", key)
            self.assertEqual(
                response.status_code,
                200,
                f"the {label} key must authenticate on /mcp/models",
            )
            self.assertTrue(response.json()["success"])

    def test_helper_scope_filtering(self):
        """auth.get_user_from_api_key obeys the allowed_scopes parameter."""
        mock_request = MagicMock()
        mock_request.env = self.env
        with patch(
            "odoo.addons.mcp_server.controllers.auth.request", mock_request
        ):
            self.assertFalse(
                auth.get_user_from_api_key(
                    self.mcp_key, allowed_scopes=("global",), log_failure=False
                ),
                "an mcp key must not resolve under global-only scope",
            )
            user = auth.get_user_from_api_key(
                self.mcp_key, allowed_scopes=("mcp", "global")
            )
            self.assertEqual(user.id, self.mcp_user.id)


@tagged("much_unit", "post_install", "-at_install")
class TestApiKeyScopeGenerate(common.TransactionCase):
    """Key generation directly via mcp.api.key."""

    def test_generate_mcp_scope(self):
        self.env["mcp.api.key"].generate_key("ctx mcp key", scope="mcp")
        key = self.env["mcp.api.key"].search([], order="id desc", limit=1)
        self.assertEqual(key.scope, "mcp")

    def test_generate_global_scope(self):
        self.env["mcp.api.key"].generate_key("ctx global key", scope="global")
        key = self.env["mcp.api.key"].search([], order="id desc", limit=1)
        self.assertEqual(key.scope, "global")


@tagged("much_unit", "post_install", "-at_install")
class TestApiKeyScopeWizard(common.TransactionCase):
    """The mcp.api.key.wizard generates keys with the selected scope."""

    def setUp(self):
        super().setUp()
        unique_id = str(int(time.time() * 1000))[-6:]
        self.wizard_user = create_test_user(
            self.env,
            "MCP Key Wizard User",
            f"mcp_key_wizard_{unique_id}",
            email=f"mcp_key_wizard_{unique_id}@example.com",
        )
        grant_mcp_access(self.wizard_user)

    def test_wizard_mcp_mode_stores_mcp_scope(self):
        wizard = self.env["mcp.api.key.wizard"].with_user(self.wizard_user).create({
            "name": "Wizard MCP Key",
            "user_id": self.wizard_user.id,
            "scope": "mcp",
        })
        wizard.action_generate()
        self.assertTrue(wizard.generated_key)
        self.assertEqual(wizard.state, "generated")
        key = self.env["mcp.api.key"].search(
            [("user_id", "=", self.wizard_user.id), ("name", "=", "Wizard MCP Key")],
            limit=1,
        )
        self.assertTrue(key)
        self.assertEqual(key.scope, "mcp")

    def test_wizard_global_mode_stores_global_scope(self):
        wizard = self.env["mcp.api.key.wizard"].with_user(self.wizard_user).create({
            "name": "Wizard Global Key",
            "user_id": self.wizard_user.id,
            "scope": "global",
        })
        wizard.action_generate()
        self.assertTrue(wizard.generated_key)
        key = self.env["mcp.api.key"].search(
            [("user_id", "=", self.wizard_user.id), ("name", "=", "Wizard Global Key")],
            limit=1,
        )
        self.assertTrue(key)
        self.assertEqual(key.scope, "global")
