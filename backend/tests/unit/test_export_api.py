import json
from pathlib import Path

from app.core.config import Settings
from app.main import create_app
from app.tools.export_api import postman

DOCS = Path(__file__).resolve().parents[3] / "docs" / "api"


def test_postman_collection_covers_every_endpoint() -> None:
    spec = create_app(Settings()).openapi()
    collection = postman(spec)
    requests = {
        (i["request"]["method"], "/" + "/".join(i["request"]["url"]["path"]))
        for folder in collection["item"]
        for i in folder["item"]
    }
    for path, methods in spec["paths"].items():
        if path.startswith("/api/v1"):
            for method in methods:
                postman_path = path.replace("{", ":").replace("}", "")
                assert (method.upper(), postman_path) in requests


def test_committed_spec_is_up_to_date() -> None:
    committed = json.loads((DOCS / "openapi.json").read_text())
    assert committed == create_app(Settings()).openapi(), "docs/api is stale: run `make api-docs`"
