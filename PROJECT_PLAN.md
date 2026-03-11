# Who-Is-Rat (CatchingRat v2) — Complete Project Plan

## 1. Project Overview

**Who-Is-Rat** is a production-ready rewrite of CatchingRat — a Chinese novel content protection platform that converts text into anti-OCR images, embeds dual watermarks (blind + visible) for each reader, and provides tools to identify leakers from captured screenshots.

**Target**: 10 concurrent users, fully Dockerized, pushed to `j7johnny/who-is-rat`.

---

## 2. What We Keep (Core Value)

These are the **architectural pillars** from the original project that are proven and well-designed:

| Component | Rationale |
|-----------|-----------|
| Novel → Chapter → ChapterVersion → BasePage → DailyPageCache hierarchy | Immutable versioned snapshots with SHA256 hash — clean and reliable |
| Three-tier access control (Site/Novel/Chapter grants) | Granular, efficient, minimal query overhead |
| Dual watermark pipeline (blind + visible) with daily rotation | Core business value — reader-specific images |
| anti7ocr pipeline with preset snapshots | Ensures rendering consistency across versions |
| Signed URL page serving (TimestampSigner) | 15-min TTL tokens prevent direct access |
| ChapterPublishJob async model | Background publishing with progress tracking |
| Celery queue separation (publish vs extract) | Prevents mutual blocking |
| Argon2 password hashing + IP rate limiting | Solid security baseline |

---

## 3. What We Fix / Improve

### 3.1 Security Fix: Nginx Media Bypass

**Problem**: Nginx serves `/media/base_pages/` and `/media/daily_pages/` directly, bypassing Django's signed URL validation.

**Solution**: Use `X-Accel-Redirect` pattern:
- Nginx marks these locations as `internal`
- Django validates the signed URL, then sends `X-Accel-Redirect` header
- Nginx serves the file only when instructed by Django

```nginx
location /protected-media/daily_pages/ {
    internal;
    alias /var/www/media/daily_pages/;
}
location /protected-media/base_pages/ {
    internal;
    alias /var/www/media/base_pages/;
}
```

### 3.2 Dead Code Cleanup

- Remove duplicate function definitions in backoffice/views.py (lines 560-710 are dead code, overwritten by lines 713+)
- Remove 4 legacy `/admin/` routes from config/urls.py (lines 14-21)
- Remove duplicate `publish_chapter_view` definitions in library/views.py
- Update base.html nav to reflect unified watermark tool

### 3.3 Polling → SSE (Server-Sent Events)

**Problem**: Frontend uses `setInterval` to poll publish/extraction status.

**Solution**: Use Django `StreamingHttpResponse` with `text/event-stream`:
- Server pushes progress updates every 2 seconds
- Client uses native `EventSource` API
- Nginx config adds `proxy_buffering off` and `X-Accel-Buffering: no`
- Gunicorn with `--workers=4 --threads=2` handles SSE + normal requests for 10 users

### 3.4 HTMX Progressive Enhancement

Add HTMX to Django templates for:
- No-reload form submissions (font toggle, preset save)
- Inline publish progress display
- Partial page updates for watermark extraction results
- Toast-style message updates via `hx-swap-oob`

Zero build step needed — vendor `htmx.min.js` in static files.

### 3.5 Worker Concurrency

| Service | Current | New |
|---------|---------|-----|
| worker (celery+extract queues) | concurrency=1 | concurrency=3, max-tasks-per-child=16 |
| worker_publish (publish queue) | concurrency=1 | concurrency=2, max-tasks-per-child=16 |

### 3.6 Docker Health Checks

Add `healthcheck` to **every** service:
- postgres: `pg_isready`
- redis: `redis-cli ping`
- web: HTTP GET `/health/`
- worker/beat: `celery inspect ping`

Use `depends_on: { condition: service_healthy }` for proper startup ordering.

### 3.7 Configurable Ports

All host-exposed ports configurable via `.env`:
```
WEB_PORT=8080
POSTGRES_PORT=15432   # only exposed in dev
REDIS_PORT=16379      # only exposed in dev
```

### 3.8 Test Infrastructure

Add `pytest-django` + `factory-boy` with priority targets:
1. `library/services/access.py` — security-critical access control
2. `library/services/signing.py` — token signing/verification
3. `accounts/views.py` — login rate limiting
4. `library/services/publishing.py` — job lifecycle
5. `reader/views.py` — access enforcement

Target: 80% coverage on `library/services/` and `accounts/`.

---

## 4. Technology Stack

### Keep Unchanged
- **Django 6.0** — mature ORM, admin as emergency fallback
- **PostgreSQL 17** — JSONB for preset snapshots
- **Redis 7** — cache + Celery broker
- **Celery 5.6** — background task processing
- **Gunicorn + Nginx** — proven production stack
- **Pillow 12.1** — image processing
- **blind-watermark 0.4.4** — frequency-domain watermarking
- **Argon2** — password hashing

### Add
| Package | Purpose |
|---------|---------|
| `htmx` 2.x (JS, vendored) | Progressive enhancement, no-reload UI |
| `djangorestframework` ~3.16 | API layer for status endpoints + future extensibility |
| `drf-spectacular` ~0.28 | Auto-generated OpenAPI schema |
| `factory-boy` ~3.4 | Test factories |
| `coverage` ~7.7 | Test coverage reporting |
| `ruff` ~0.11 | Fast linter + formatter |
| `pre-commit` ~4.2 | Git hooks |

### Do NOT Add
- **ASGI/Channels/WebSocket** — Overkill for 10 users. SSE via StreamingHttpResponse works with sync Gunicorn.
- **React/Vue SPA** — HTMX + Django templates is the right fit.
- **Kubernetes** — Docker Compose is appropriate.

### anti7ocr
- Copy anti7ocr source code as an internal package: `packages/anti7ocr/`
- Install as editable local package in Dockerfile: `pip install -e ./packages/anti7ocr`
- This gives us full control without external dependency.

---

## 5. Project Structure

```
who-is-rat/
├── .github/
│   └── workflows/
│       └── ci.yml                    # Lint + test + Docker build
├── packages/
│   └── anti7ocr/                     # Internal anti7ocr package
│       ├── pyproject.toml
│       └── anti7ocr/
│           ├── __init__.py
│           ├── api.py
│           ├── pipeline/
│           └── ...
├── config/
│   ├── __init__.py
│   ├── settings/
│   │   ├── __init__.py               # Auto-select based on env
│   │   ├── base.py                   # Common settings
│   │   ├── dev.py                    # DEBUG=True, SQLite, eager Celery
│   │   ├── prod.py                   # PostgreSQL, Redis, Gunicorn
│   │   └── test.py                   # SQLite, eager Celery, memory cache
│   ├── celery.py
│   ├── urls.py                       # Clean: no legacy routes
│   ├── wsgi.py
│   ├── versioning.py
│   └── context_processors.py
├── accounts/
│   ├── models.py                     # User model (unchanged)
│   ├── views.py                      # Login/logout/password change
│   ├── urls.py
│   ├── forms.py
│   ├── admin.py
│   └── tests/
│       ├── factories.py
│       ├── test_login.py
│       └── test_rate_limiting.py
├── library/
│   ├── models.py                     # All domain models
│   ├── tasks.py                      # Celery tasks
│   ├── admin.py
│   ├── services/
│   │   ├── access.py                 # 3-tier permission checks
│   │   ├── antiocr.py                # anti7ocr rendering pipeline
│   │   ├── anti7ocr_config.py        # Preset configuration
│   │   ├── anti7ocr_diagnostics.py   # OCR diagnostic tools
│   │   ├── audit.py                  # Audit logging
│   │   ├── font_library.py           # Font management
│   │   ├── publishing.py             # Chapter publish workflow
│   │   ├── signing.py                # Signed URL tokens
│   │   ├── storage.py                # Media file utilities
│   │   ├── visible_watermark.py      # Visible watermark embed/extract
│   │   ├── watermark.py              # Blind watermark embed/extract
│   │   └── watermark_records.py      # Extraction record management
│   ├── api/
│   │   ├── serializers.py            # DRF serializers
│   │   ├── views.py                  # Health, publish status, extraction status
│   │   └── urls.py
│   └── tests/
│       ├── factories.py
│       ├── test_access.py
│       ├── test_signing.py
│       ├── test_publishing.py
│       └── test_watermark.py
├── backoffice/
│   ├── views.py                      # Cleaned up: no duplicates
│   ├── forms.py
│   ├── urls.py
│   └── tests/
│       └── test_views.py
├── reader/
│   ├── views.py                      # X-Accel-Redirect for media
│   ├── urls.py
│   └── tests/
│       ├── test_views.py
│       └── test_access.py
├── templates/
│   ├── base.html                     # + htmx.js, unified nav
│   ├── _partials/
│   │   └── messages.html             # HTMX OOB message updates
│   ├── accounts/
│   ├── backoffice/
│   │   ├── _partials/
│   │   │   ├── publish_progress.html # SSE-driven progress
│   │   │   └── extraction_progress.html
│   │   └── ...existing templates...
│   └── reader/
├── static/
│   ├── site.css
│   └── htmx.min.js                   # Vendored
├── docker/
│   ├── nginx.conf                    # Fixed: X-Accel-Redirect
│   └── entrypoint.sh
├── docker-compose.yml                # Production with healthchecks
├── docker-compose.override.yml       # Dev overrides
├── Dockerfile
├── pyproject.toml                    # All deps + tool configs
├── .env.example
├── .pre-commit-config.yaml
├── .gitignore
└── VERSION
```

---

## 6. Split Settings Strategy

### base.py (common)
All current settings from config/settings.py except DB/cache/debug conditionals.

### dev.py
```python
DEBUG = True
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", ...}}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
CELERY_TASK_ALWAYS_EAGER = True
```

### prod.py
```python
DEBUG = False
DATABASES = {"default": {"ENGINE": "django.db.backends.postgresql", ...}}
CACHES = {"default": {"BACKEND": "django_redis.cache.RedisCache", ...}}
# All env vars required
```

### test.py
```python
DEBUG = False
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", ...}}
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # Fast tests
```

---

## 7. Docker Architecture

### docker-compose.yml (Production)
```yaml
services:
  web:
    build: .
    env_file: .env
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.prod
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')"]
      interval: 30s
      timeout: 5s
      retries: 3
    command: gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 4 --threads 2 --timeout 300

  worker:
    build: .
    command: celery -A config worker -l info -Q celery,extract --concurrency=3 --max-tasks-per-child=16
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "celery", "-A", "config", "inspect", "ping", "--timeout", "5"]

  worker_publish:
    build: .
    command: celery -A config worker -l info -Q publish --concurrency=2 --max-tasks-per-child=16
    depends_on: [postgres, redis]

  beat:
    build: .
    command: celery -A config beat -l info

  postgres:
    image: postgres:17
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-catchingrat}"]
    volumes: [postgres_data:/var/lib/postgresql/data]

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]

  nginx:
    image: nginx:1.29-alpine
    depends_on:
      web: { condition: service_healthy }
    ports: ["${WEB_PORT:-8080}:80"]
```

### docker-compose.override.yml (Dev)
```yaml
services:
  web:
    volumes: [.:/app]
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.dev
    command: python manage.py runserver 0.0.0.0:8000
  postgres:
    ports: ["${POSTGRES_PORT:-15432}:5432"]
  redis:
    ports: ["${REDIS_PORT:-16379}:6379"]
```

---

## 8. API Design (DRF)

Existing JSON endpoints formalized as DRF views:

```
GET  /health/                                   # No auth, service health
GET  /api/v1/chapters/{id}/publish-status/      # Admin, JSON status
GET  /api/v1/chapters/{id}/publish-progress/    # Admin, SSE stream
GET  /api/v1/extraction/{id}/status/            # Admin, JSON status
GET  /api/v1/extraction/{id}/progress/          # Admin, SSE stream
POST /api/v1/extraction/{id}/stop/              # Admin, cancel
GET  /api/schema/                               # OpenAPI schema
```

Template views remain primary UI. API supplements HTMX requests + future extensibility.

---

## 9. SSE Implementation Detail

```python
# backoffice/views.py
@admin_required
def publish_progress_sse(request, chapter_id):
    def event_stream():
        while True:
            job = _latest_publish_job(chapter_id)
            data = json.dumps(_serialize_publish_job(chapter, job))
            yield f"data: {data}\n\n"
            if job is None or not job.is_active:
                yield "event: done\ndata: {}\n\n"
                return
            time.sleep(2)

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
```

Frontend:
```javascript
const source = new EventSource('/manage/chapters/{{ chapter.id }}/publish-progress/');
source.addEventListener('message', (e) => updateProgressUI(JSON.parse(e.data)));
source.addEventListener('done', () => source.close());
```

Nginx:
```nginx
location /manage/ {
    proxy_pass http://web:8000;
    proxy_buffering off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
}
```

---

## 10. Nginx Security Fix (X-Accel-Redirect)

```nginx
# Only serve static files directly
location /static/ {
    alias /var/www/static/;
    add_header Cache-Control "public, max-age=31536000, immutable";
}

# Protected media — internal only, Django controls access
location /protected-media/ {
    internal;
    alias /var/www/media/;
    add_header Cache-Control "private, no-store";
}

# All other requests go to Django
location / {
    proxy_pass http://web:8000;
    proxy_buffering off;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Django reader view:
```python
def reader_page_image(request, signed_key, page_index):
    # ... validate signed key, check access ...
    page = build_daily_page(...)
    response = HttpResponse()
    response["X-Accel-Redirect"] = f"/protected-media/{page.relative_path}"
    response["Content-Type"] = "image/png"
    response["Cache-Control"] = "private, no-store"
    return response
```

---

## 11. Implementation Phases

### Phase 1: Project Bootstrap (infrastructure)
- [ ] Init git repo, create pyproject.toml
- [ ] Copy anti7ocr into packages/anti7ocr/
- [ ] Setup split settings (base/dev/prod/test)
- [ ] Create Dockerfile with multi-stage build
- [ ] Create docker-compose.yml + override with healthchecks
- [ ] Create .env.example with configurable ports
- [ ] Verify `docker compose up` boots cleanly

### Phase 2: Core App Migration (port & clean)
- [ ] Port accounts app (models, views, forms, urls)
- [ ] Port library app (models, services, tasks)
- [ ] Port backoffice app — remove dead code, consolidate watermark tool
- [ ] Port reader app — add X-Accel-Redirect
- [ ] Clean config/urls.py — remove legacy /admin/ routes
- [ ] Port & update all templates
- [ ] Fix base.html nav (unified watermark tool link)
- [ ] Verify full publishing flow works end-to-end in Docker

### Phase 3: Security & DRF API
- [ ] Fix nginx.conf — X-Accel-Redirect for media
- [ ] Add DRF + drf-spectacular
- [ ] Create health endpoint
- [ ] Formalize status endpoints as DRF APIViews
- [ ] Add OpenAPI schema generation

### Phase 4: SSE + HTMX Enhancement
- [ ] Add SSE endpoints for publish & extraction progress
- [ ] Update nginx config for SSE (proxy_buffering off)
- [ ] Vendor htmx.min.js
- [ ] Add HTMX to base.html
- [ ] Convert font toggle to HTMX (no reload)
- [ ] Convert publish progress to SSE + HTMX partial
- [ ] Convert extraction progress to SSE + HTMX partial

### Phase 5: Testing & CI
- [ ] Setup pytest-django + factory-boy
- [ ] Write tests for access.py (security-critical)
- [ ] Write tests for signing.py
- [ ] Write tests for login rate limiting
- [ ] Write tests for publishing lifecycle
- [ ] Write tests for reader access enforcement
- [ ] Create .github/workflows/ci.yml (lint + test + Docker build)
- [ ] Add pre-commit hooks (ruff)

### Phase 6: Polish & Deploy
- [ ] Increase Celery worker concurrency
- [ ] Add structured logging
- [ ] Push to GitHub (j7johnny/who-is-rat)
- [ ] Final end-to-end validation with 10-user simulation
- [ ] Write README with setup instructions

---

## 12. Database Schema

**No schema changes needed.** The existing model design is solid:
- Novel, Chapter, ChapterVersion, ChapterPublishJob
- AntiOcrPreset, CustomFontUpload
- BasePage, DailyPageCache
- ReaderSiteGrant, ReaderNovelGrant, ReaderChapterGrant
- AuditLog, WatermarkExtractionRecord

All models are ported as-is with their constraints and indexes.

---

## 13. Key Design Decisions

| Decision | Choice | Why Not Alternative |
|----------|--------|---------------------|
| SSE vs WebSocket | SSE | One-way server→client only. No ASGI needed. Only admins watch progress. |
| HTMX vs SPA | HTMX | 10 users. Django templates already work. Zero build step. |
| DRF vs raw JsonResponse | DRF | Existing code already serializes JSON. DRF adds throttling, permissions, schema for minimal overhead. |
| Split settings vs single file | Split | Eliminates `if os.getenv()` conditionals. Each env gets clean config. |
| Sync Gunicorn vs ASGI | Sync | SSE works with sync workers. No ASGI complexity for 10 users. |
| anti7ocr internal vs pip | Internal | Full control, no external dependency, versioned with main code. |

---

## 14. Environment Cleanliness

- **All services run inside Docker** — no global Python packages, no system PostgreSQL/Redis needed
- **Dev mode**: `docker compose up` uses override file with volume mounts and runserver
- **anti7ocr**: Internal package, no external git dependency at runtime
- **Ports**: All configurable via `.env`, default web port 8080
- **No venv pollution**: Development happens inside Docker containers

For local development without Docker (optional):
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]" -e "./packages/anti7ocr[eval]"
# Uses SQLite + memory cache + eager Celery automatically via dev settings
```
