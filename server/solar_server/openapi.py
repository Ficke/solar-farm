"""Print the dashboard API's OpenAPI schema: `just api` saves it to web/openapi.json."""

from __future__ import annotations

import json
from typing import cast

from solar_server.app import create_app
from solar_server.config import Settings
from solar_server.sources import Sources
from solar_server.store import MemoryStore


def schema() -> str:
    # The web role never calls the sources.
    app = create_app(Settings(role="web"), MemoryStore(), cast(Sources, None))
    return json.dumps(app.openapi(), indent=2) + "\n"


if __name__ == "__main__":
    print(schema(), end="")
