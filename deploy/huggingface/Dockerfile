# Everything in one container, for hosts that run a single image (Hugging Face Spaces).
# Postgres, Redis, the API, a worker, the mock Sarvam and nginx run side by side under
# supervisord. The source is cloned from GitHub at build time, so the Space only needs
# this file and its README.

FROM alpine/git:2.47.2 AS source
ARG REPO=https://github.com/yshemashree/Campaign-Manager-Predixion-AI-.git
ARG REF=main
# Changes whenever main moves, so a rebuild picks up new commits instead of a cached clone.
ADD https://api.github.com/repos/yshemashree/Campaign-Manager-Predixion-AI-/commits/main /tmp/head.json
RUN git clone --depth 1 --branch "$REF" "$REPO" /src

FROM node:22-alpine AS web
WORKDIR /web
COPY --from=source /src/frontend/package.json /src/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY --from=source /src/frontend/ ./
RUN npm run build

FROM python:3.13-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql redis-server nginx supervisor \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /app/backend
COPY --from=source /src/backend/pyproject.toml /src/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --from=source /src/backend/ ./
COPY --from=source /src/mock_sarvam/main.py /app/mock_sarvam/main.py
COPY --from=web /web/dist /app/web
COPY --from=source /src/deploy/huggingface/supervisord.conf /app/supervisord.conf
COPY --from=source /src/deploy/huggingface/nginx.conf /app/nginx.conf
COPY --from=source /src/deploy/huggingface/start.sh /app/start.sh

# Spaces run the container as uid 1000.
RUN useradd -m -u 1000 user && mkdir -p /data && chown -R user /app /data
USER user
EXPOSE 7860
CMD ["/app/start.sh"]
