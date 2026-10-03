# Common commands. Needs uv and Bun; `just --list` shows them all.

# Install Python and JS dependencies
setup:
    uv sync
    cd device && bun install
    cd web && bun install

# Lint, format check, type check and test everything (what CI runs)
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run ty check
    uv run pytest -q
    cd device && bun test
    cd web && bun run check

# Format Python and the dashboard and apply safe lint fixes
fmt:
    uv run ruff format .
    uv run ruff check --fix .
    cd web && bun run fmt

# Run the dashboard locally against made-up readings
web:
    cd server && uv run uvicorn solar_server.dev:app --port 8000 & cd web && bun run dev

# Push the script and settings to the plug
deploy *args:
    uv run tools/deploy.py {{args}}

# Show what the plug is doing
status:
    uv run tools/status.py

# Dry-run the plug script against the live plan
sim *args:
    bun device/sim.js {{args}}
