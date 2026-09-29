{
    "name": "MCP Server",
    "version": "13.0.1.0.0",
    "summary": "Connect AI assistants to your Odoo instance via Model Context Protocol",
    "description": """
MCP Server for Odoo
===================

Enable AI assistants like Claude to securely
access your Odoo data through natural language queries.

Key Features
------------
* Native MCP endpoint at POST /mcp (Streamable HTTP, JSON-RPC 2.0) -
  connect MCP clients directly to Odoo, no separate process to install
* Search, retrieve, create, update and delete Odoo records, run aggregations
  and call business methods
* Batch writes: create_records and update_records write many records of one
  model in a single atomic call (capped by a configurable batch size)
* Attachments: read_attachment returns a PDF, image or file attached to a
  record as text, image or a download link;
  list_record_attachments and upload_attachment complete the loop
* User context on connect: the handshake advertises the caller's timezone,
  active and allowed companies (plus a get_current_context tool)
* Custom tools: admins expose curated verbs (e.g. confirm_sale_order) by
  wrapping an Odoo server action, instead of enabling generic create/write
* Per-user opt-in: only members of the "MCP User" security group can use MCP
* Granular permissions control per model and operation
* Secure API key authentication with rate limiting and audit logging
* Easy configuration through Odoo settings

Requirements: Odoo 13.0.
    """,
    "author": "much. Consulting",
    "website": "https://muchconsulting.com/",
    "support": "product@erp.muchconsulting.de",
    "category": "Productivity",
    "depends": ["base", "base_setup", "mail", "web"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "wizard/mcp_model_selection_wizard_views.xml",
        "views/mcp_enabled_models_views.xml",
        "views/mcp_custom_tool_views.xml",
        "views/mcp_log_views.xml",
        "views/mcp_api_key_views.xml",
        "views/res_config_settings_views.xml",
        "views/mcp_menu.xml",
    ],
    "demo": [],
    "images": [
        "static/description/banner.gif",
        "static/description/icon.png",
    ],
    "external_dependencies": {
        "python": [
            "defusedxml",
            "packaging",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "OPL-1",
}
