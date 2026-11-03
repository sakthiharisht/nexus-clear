FROM python:3.12-slim

# Install uv (pinned) via its official static-binary image layer.
COPY --from=ghcr.io/astral-sh/uv:0.5.2 /uv /uvx /usr/local/bin/

WORKDIR /app

# Install deps first so code edits don't bust the layer cache.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Call the venv's own binaries directly rather than `uv run`, which would
# otherwise notice the dev dependency-group is absent (per --no-dev above)
# and silently reinstall it into the image on every container start.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
