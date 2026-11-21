FROM node:22-alpine AS ui-builder
WORKDIR /src
COPY . .
RUN mkdir -p /ui-dist && \
    if [ -f ui/package.json ]; then \
      cd ui && npm ci && npm run build && cp -r dist/. /ui-dist/; \
    else \
      printf '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>DataLogicEngine</title></head><body><h1>DataLogicEngine Middleware</h1><p>Phase 0 container ready. Browser Chat UI lands in Phase 1 (P1-18).</p></body></html>\n' > /ui-dist/index.html; \
    fi

FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /uvx /bin/

RUN useradd --create-home --home-dir /home/dle --shell /bin/sh dle && \
    mkdir -p /app /var/lib/dle/data /var/lib/dle/keys /var/lib/dle/calibration /var/lib/dle/models && \
    chown -R dle:dle /app /var/lib/dle

WORKDIR /app
COPY --chown=dle:dle pyproject.toml .python-version uv.lock* ./
COPY --chown=dle:dle dle ./dle
COPY --chown=dle:dle config ./config
COPY --chown=dle:dle contracts ./contracts
COPY --from=ui-builder --chown=dle:dle /ui-dist /app/ui/dist

USER dle
RUN if [ -f uv.lock ]; then uv sync --frozen --no-dev; else uv sync --no-dev; fi

EXPOSE 8740
CMD ["uv", "run", "--no-sync", "uvicorn", "dle.edge.gateway:app", "--host", "0.0.0.0", "--port", "8740"]
