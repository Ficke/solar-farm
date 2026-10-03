# Server image for both Cloud Run services (solar-web and solar-edge).
# SOLAR_ROLE, set per service in infra/run.tf, picks which routes it serves.

FROM mirror.gcr.io/library/python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
COPY planner/pyproject.toml planner/
COPY server/pyproject.toml server/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-workspace --package solar-farm-server

COPY planner planner
COPY server server
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package solar-farm-server

FROM mirror.gcr.io/library/python:3.14-slim
RUN useradd --system --no-create-home app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 SOLAR_WEB_DIST=/app/web/dist
USER app
CMD ["sh", "-c", "exec uvicorn solar_server.app:main --factory --host 0.0.0.0 --port ${PORT:-8080}"]
