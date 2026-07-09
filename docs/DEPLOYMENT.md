# DEPLOYMENT.md — Running cis in Docker & Beyond

> **Status:** v1.0 · **Audience:** Reviewer, operator of the demo (5 commands to running dashboard), future contributor scaling to production
> **Related:** [ROADMAP.md §0](./ROADMAP.md) · [ARCHITECTURE.md §3](./ARCHITECTURE.md) · [PERFORMANCE.md](./PERFORMANCE.md) · [ADR-005 why Redis](./adr/005-why-redis.md) · [EVOLUTION.md](./EVOLUTION.md)
> **Purpose:** Reproducible deployment guide from docker-compose to production containerization.

---

## 1. Local Dev (One Command)

```powershell
docker compose up -d
```

Brings up:
- **Redis 7** on `localhost:6379`, with AOF persistence.
- **Postgres 16** on `localhost:5432`, db `cis`, user `cis`, pass `cis_dev`.

### 1.1 docker-compose.yml

```yaml
version: "3.9"
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: ["redis-server", "--appendonly", "yes"]
    volumes: ["redis_data:/data"]
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: cis
      POSTGRES_PASSWORD: cis_dev
      POSTGRES_DB: cis
    ports: ["5432:5432"]
    volumes: ["pg_data:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U cis -d cis"]
      interval: 5s
      retries: 3

  # Optionally, the cis app itself (when not running via uvicorn --reload)
  app:
    build: .
    ports: ["3000:3000"]
    environment:
      REDIS_URL: redis://redis:6379/0
      POSTGRES_URL: postgres://cis:cis_dev@db:5432/cis
      CIS_API_KEY: demo-key
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started

volumes:
  redis_data:
  pg_data:
```

### 1.2 Launch the backend

```powershell
# Development (hot reload)
uv run uvicorn app.main:app --reload --port 3000

# OR via docker-compose if you add the 'app' service above
docker compose up -d app
```

### 1.3 Launch the dashboard

```powershell
cd web
npm install
npm run dev
# Opens http://localhost:5173
```

---

## 2. Environment Variables Reference

| Variable | Required | Default | Notes |
|---|---|---|---|
| `REDIS_URL` | yes | `redis://localhost:6379/0` | |
| `POSTGRES_URL` | yes | `postgres://cis:cis_dev@localhost:5432/cis` | |
| `CIS_API_KEY` | yes | `demo-key` (dev) | Bearer token shared by all routes |
| `LLM_PROVIDER` | yes | `openai-compatible` | or `ollama` |
| `OPENAI_BASE_URL` | depends on LLM_PROVIDER | `http://localhost:1234/v1` | Qwen/LM Studio/llama.cpp endpoint |
| `OPENAI_API_KEY` | depends on LLM_PROVIDER | `local-dev` | |
| `ZOOM_CLIENT_ID` | for zoom platform | — | |
| `ZOOM_CLIENT_SECRET` | for zoom platform | — | |
| `ZOOM_ACCOUNT_ID` | for zoom platform | — | |
| `ZOOM_WEBHOOK_SECRET` | for zoom platform | — | HMAC SHA-256 shared secret |
| `GOOGLE_APPLICATION_CREDENTIALS` | for meet (Workspace path) | — | Path to service-account JSON (gitignored) |
| `GOOGLE_DELEGATED_ADMIN` | for meet (Workspace path) | — | user@yourdomain.com for domain-wide delegation |
| `WHISPER_MODEL` | yes | `large-v3-turbo` | For faster-whisper local; cloud mode ignored |
| `WHISPER_DEVICE` | yes | `cpu` | `cpu` or `cuda` |
| `SECRET_STRIP` | no | `false` (dev) | In production, force all emails → SHA256 before hitting bus |
| `SESSION_MAX_DURATION_MIN` | no | `120` | Watchdog that terminates sessions after max duration |

---

## 3. Production-Grade Environment Considerations

### 3.1 Container images

| Component | Base image | Tag |
|---|---|---|
| cis app | `python:3.12-slim` + `uv` | `:latest` (build from `Dockerfile`) |
| Redis | `redis:7-alpine` | `:7-alpine` |
| Postgres | `postgres:16-alpine` | `:16-alpine` |
| Dashboard web | `node:22-alpine` (static build → nginx serving built dist) | `:latest` |

The cis app Dockerfile (Phase 0 deliverable in [ROADMAP.md §0](./ROADMAP.md)):

```dockerfile
FROM python:3.12-slim

RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app/ app/
COPY data/ data/
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
```

### 3.2 Scale-out topology (v1.1+)

```
┌───────────────────────────────┐
│  Ingest Layer                 │
│  ┌──────────┐  ┌──────────┐  │
│  │ Zoom Adp │  │ Meet Adp │  │
│  └────┬─────┘  └────┬─────┘  │
│       │              │        │
└───────┼──────────────┼────────┘
        │              │
        ▼              ▼
   Redis pub/sub ──── Analyzer containers (k replicas, subscribe to channels)
        │
        ▼
   Ticker container (1 per session)
        │
        ▼
   Redis state ──── Postgres audit
        │
        ▼
   FastAPI ws server  ────  Dashboard (nginx-served static)
```

Cross-process communication uses Redis pub/sub (ADR-001). Ticker containers scale 1:1 with active sessions. Analyzer containers form a homogenous pool; each subscribes to event channels. No extra infra beyond Redis (already running).

### 3.3 Nginx routing (production)

```
upstream cis_api { server cis:3000; }

server {
  listen 80;
  server_name localhost;

  location / {
    proxy_pass http://cis_api;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
  }
  location /ws/ {
    proxy_pass http://cis_api;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 86400s;
  }
  location /dashboard/ {
    root /usr/share/nginx/html;
    index index.html;
  }
}
```

The dashboard is a Vite-built static build, served by nginx. The WebSocket endpoint proxies with no timeout (session may be 60+ min).

---

## 4. Port Map

| Port | Service | External? |
|---|---|---|
| 3000 | cis FastAPI | YES |
| 5173 | React dev server (npm run dev) | YES (dev only) |
| 6379 | Redis | NO (localhost-bounded in docker-compose) |
| 5432 | Postgres | NO (localhost-bounded) |
| 80 | nginx (production) | YES |

---

## 5. Secrets Management (Production)

For a production deployment beyond v1:

- All `.env` secrets move to a KMS (AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager).
- OAuth refresh tokens are stored in KMS; `keyring` Windows/macOS store is dev-only.
- `ZOOM_WEBHOOK_SECRET` is rotated from KMS, not a manual file.
- `SECRET_STRIP=true` is turned on permanently in production to pre-hash emails at adapter level.

---

## 6. CI Deployment Pipeline (Future)

```yaml
deploy:
  needs: test
  runs-on: ubuntu-latest
  steps:
    - run: docker build -t cis:${GITHUB_SHA} .
    - run: docker push ghcr.io/.../cis:${GITHUB_SHA}
    - run: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The prod compose file overrides the `redis` and `postgres` services with managed instances (Cloud Memorystore, Cloud SQL) instead of local images.

---

## 7. Troubleshooting (quick dev tips)

```powershell
# Redis not responding
docker compose logs redis | Select-String "Ready to accept"
docker compose restart redis

# Postgres not ready
docker compose logs db | Select-String "database system is ready"
docker compose restart db

# Docker volume corrupted
docker compose down -v
docker compose up -d

# LLM not responding
# verify Ollama or Qwen endpoint is up
curl -s http://localhost:1234/v1/models | ConvertFrom-Json

# Zoom access_token not refreshing
uv run python -c "from app.ingest.zoom import ZoomAuth; ..."  # manual debug refresh
```

---

> **Related:** [PERFORMANCE.md](./PERFORMANCE.md) for throughput/latency at each deployment tier.