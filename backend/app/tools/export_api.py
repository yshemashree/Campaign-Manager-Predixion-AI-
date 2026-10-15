"""Write the OpenAPI spec and a Postman collection generated from it.

    cd backend && uv run python -m app.tools.export_api ../docs/api

The Postman collection has a "Log in" request that saves the token for every other request,
and example bodies built from the schemas, so it works straight after import.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.main import create_app

EXAMPLES: dict[str, Any] = {
    "name": "Demo",
    "email": "admin@acme.example.com",
    "password": "acme12345",
    "phone": "+919876543210",
}

# Hand-written bodies for the requests people try first; the rest are generated.
BODIES: dict[str, Any] = {
    "Create Organization": {
        "name": "Acme Lending",
        "sarvam_org_id": "acme-org",
        "max_concurrent_calls": 20,
        "max_calls_per_second": 5,
        "admin_email": "admin@acme.example.com",
        "admin_password": "acme12345",
    },
    "Create Workspace": {
        "name": "Collections",
        "sarvam_workspace_id": "acme-collections",
        "sarvam_api_key": "your-sarvam-api-key",
    },
    "Create User": {
        "email": "agent@acme.example.com",
        "password": "acme12345",
        "role": "member",
        "workspace_ids": ["{{workspace_id}}"],
    },
    "Create Agent": {
        "name": "EMI Reminder",
        "app_id": "emi-reminder-app",
        "app_version": 7,
        "variables": [
            {"name": "customer_name", "type": "string", "required": True, "example": "Priya"},
            {"name": "emi_amount", "type": "number", "required": True, "example": "4500"},
            {"name": "due_date", "type": "date", "required": True, "example": "2026-11-05"},
        ],
    },
    "Create Connection": {
        "name": "Main line",
        "connection_id": "acme-conn-1",
        "caller_numbers": ["+918069000001", "+918069000002"],
    },
}


def _resolve(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in node:
        name = node["$ref"].rsplit("/", 1)[-1]
        node = spec["components"]["schemas"][name]
    return node


def example(spec: dict[str, Any], node: dict[str, Any], name: str = "", depth: int = 0) -> Any:
    # A field's own default sits next to its $ref, so look before resolving.
    if node.get("default") is not None:
        return node["default"]
    node = _resolve(spec, node)
    if depth > 6:
        return None
    if "example" in node:
        return node["example"]
    if node.get("default") is not None:
        return node["default"]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in node:
            options = [o for o in node[key] if _resolve(spec, o).get("type") != "null"]
            return example(spec, options[0], name, depth + 1) if options else None
    if "enum" in node:
        return node["enum"][0]
    kind = node.get("type")
    if kind == "object" or "properties" in node:
        props = node.get("properties", {})
        required = set(node.get("required", []))
        # Leave out optional fields that default to nothing; keep the example short.
        return {
            k: example(spec, v, k, depth + 1)
            for k, v in props.items()
            if k in required or v.get("default") is not None
        }
    if kind == "array":
        return [example(spec, node.get("items", {}), name, depth + 1)]
    if kind == "integer":
        return node.get("minimum", 1)
    if kind == "number":
        return node.get("minimum", 1)
    if kind == "boolean":
        return False
    if node.get("format") == "uuid":
        return "{{" + (name or "id") + "}}"
    if node.get("format") == "date-time":
        return "2026-11-01T09:00:00+05:30"
    for hint, value in EXAMPLES.items():
        if hint in name:
            return value
    return name.replace("_", " ") or "text"


def postman(spec: dict[str, Any]) -> dict[str, Any]:
    folders: dict[str, list[dict[str, Any]]] = {}
    for path, methods in spec["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method, op in methods.items():
            tag = (op.get("tags") or ["other"])[0]
            segments = [re.sub(r"\{(\w+)\}", r":\1", p) for p in path.strip("/").split("/")]
            params = re.findall(r"\{(\w+)\}", path)
            url: dict[str, Any] = {
                "raw": "{{baseUrl}}/" + "/".join(segments),
                "host": ["{{baseUrl}}"],
                "path": segments,
            }
            if params:
                url["variable"] = [{"key": p, "value": "{{" + p + "}}"} for p in params]
            query = [
                {"key": p["name"], "value": "", "disabled": True}
                for p in op.get("parameters", [])
                if p.get("in") == "query"
            ]
            if query:
                url["query"] = query
            request: dict[str, Any] = {
                "method": method.upper(),
                "url": url,
                "description": op.get("description") or "",
            }
            content = op.get("requestBody", {}).get("content", {})
            if "application/json" in content:
                body = example(spec, content["application/json"]["schema"])
                request["header"] = [{"key": "Content-Type", "value": "application/json"}]
                request["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(body, indent=2),
                    "options": {"raw": {"language": "json"}},
                }
            elif "multipart/form-data" in content:
                schema = _resolve(spec, content["multipart/form-data"]["schema"])
                form = []
                for key, prop in schema.get("properties", {}).items():
                    if _resolve(spec, prop).get("format") == "binary" or key == "file":
                        form.append({"key": key, "type": "file", "src": ""})
                    else:
                        form.append({"key": key, "value": "false", "type": "text"})
                request["body"] = {"mode": "formdata", "formdata": form}
            item: dict[str, Any] = {"name": op.get("summary") or path, "request": request}
            if item["name"] in BODIES and "body" in request:
                request["body"]["raw"] = json.dumps(BODIES[item["name"]], indent=2)
            if path.endswith("/auth/login"):
                request["auth"] = {"type": "noauth"}
                request["body"]["raw"] = json.dumps(
                    {"email": "{{email}}", "password": "{{password}}"}, indent=2
                )
                item["name"] = "Log in (saves the token for all other requests)"
                item["event"] = [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                "const body = pm.response.json();",
                                "if (body.access_token) {",
                                "  pm.collectionVariables.set('token', body.access_token);",
                                "}",
                            ],
                        },
                    }
                ]
            folders.setdefault(tag, []).append(item)

    order = ["auth", "organizations", "workspaces", "users", "agents", "campaigns", "contacts"]
    ordered = sorted(folders, key=lambda t: order.index(t) if t in order else len(order))
    variables = [
        "org_id",
        "workspace_id",
        "agent_id",
        "connection_id",
        "campaign_id",
        "cohort_id",
        "contact_id",
    ]
    return {
        "info": {
            "name": "Campaign Manager API",
            "description": (
                "Run 'Log in' first. Set baseUrl, email and password in the collection "
                "variables; ids like campaign_id are collection variables too."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}"}]},
        "variable": [
            {"key": "baseUrl", "value": "http://localhost:8000"},
            {"key": "email", "value": "admin@acme.example.com"},
            {"key": "password", "value": "acme12345"},
            {"key": "token", "value": ""},
            *[{"key": v, "value": ""} for v in variables],
        ],
        "item": [{"name": tag.capitalize(), "item": folders[tag]} for tag in ordered],
    }


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/api")
    out.mkdir(parents=True, exist_ok=True)
    spec = create_app(Settings()).openapi()
    (out / "openapi.json").write_text(json.dumps(spec, indent=2) + "\n")
    (out / "campaign-manager.postman_collection.json").write_text(
        json.dumps(postman(spec), indent=2) + "\n"
    )
    print(f"Wrote {out}/openapi.json and {out}/campaign-manager.postman_collection.json")


if __name__ == "__main__":
    main()
