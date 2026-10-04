# Install Python and JavaScript dependencies.
setup:
    uv sync
    cd device && bun install
    cd web && bun install

# Run Python checks and tests, plug tests, and dashboard checks.
check:
    uv run ruff check .
    uv run ruff format --check .
    uv run ty check
    uv run pytest -q
    cd device && bun test
    cd web && bun run check

# Test Firestore against the emulator; requires Java 21+ and Node.
test-firestore:
    npx -y firebase-tools@15 emulators:exec --only firestore --project demo-solar-farm \
        "uv run pytest -q server/tests/test_firestore.py"

# Save the API schema used to generate dashboard types.
api:
    uv run python -m solar_server.openapi > web/openapi.json

# Format Python and dashboard code and apply safe lint fixes.
fmt:
    uv run ruff format .
    uv run ruff check --fix .
    cd web && bun run fmt

# Run the dashboard locally with synthetic readings.
web:
    cd server && uv run uvicorn solar_server.dev:app --port 8000 & cd web && bun run dev

# Deploy the script and settings to the plug.
deploy *args:
    uv run tools/deploy.py {{args}}

# Show plug status.
status:
    uv run tools/status.py

# Simulate fixed windows from the live plan.
sim *args:
    bun device/sim.js {{args}}

# Regenerate provider locks for Linux CI and Apple silicon.
lock:
    tofu -chdir=infra providers lock -platform=linux_amd64 -platform=darwin_arm64
    tofu -chdir=infra/bootstrap providers lock -platform=linux_amd64 -platform=darwin_arm64
