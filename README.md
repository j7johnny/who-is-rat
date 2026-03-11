# Who-Is-Rat v2.0

中文小說內容保護平台 — 將文字渲染為抗 OCR 圖片、為每位讀者嵌入雙重浮水印（頻域盲浮水印 + 可見浮水印），並提供工具從截圖中追蹤洩漏者。

## 核心功能

- **Anti-OCR 渲染** — 透過 `anti7ocr` 將小說文字轉為不可 OCR 的圖片
- **雙重浮水印** — 頻域盲浮水印 + 可見浮水印，每日按讀者輪換
- **三層存取控制** — 站台 / 小說 / 章節級別的讀者授權
- **浮水印提取工具** — 從截圖中提取浮水印，識別洩漏來源
- **X-Accel-Redirect** — nginx 內部轉發，確保所有圖片經 Django 驗證後才提供
- **Server-Sent Events** — 即時推送發佈與提取進度（取代輪詢）

## 技術架構

| 元件 | 技術 |
|------|------|
| Web 框架 | Django 6.0 (split settings) |
| 前端互動 | HTMX（無 SPA） |
| API | Django REST Framework + drf-spectacular |
| 任務佇列 | Celery (publish + extract 分離佇列) |
| 資料庫 | PostgreSQL 17 |
| 快取/Broker | Redis 7 |
| Web 伺服器 | Gunicorn (4 workers + 2 threads) → nginx |
| 容器化 | Docker Compose（7 服務含健康檢查） |
| 密碼 | Argon2 + IP 速率限制 |

## 快速開始

### Docker Compose（推薦）

```bash
# 1. 複製環境設定
cp .env.example .env
# 編輯 .env 修改密碼與密鑰

# 2. 啟動所有服務
docker compose up -d --build

# 3. 開啟瀏覽器
#    http://localhost:8080
#    首次訪問會引導建立管理員帳號
```

預設埠號（可在 `.env` 中修改）：
- Web: `8080`
- PostgreSQL: `15432`（僅外部存取）
- Redis: `16379`（僅外部存取）

### 本地開發

```bash
# 建立虛擬環境
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 安裝依賴
pip install -e ".[dev]"
pip install -e packages/anti7ocr

# 執行 migrate 與開發伺服器
python manage.py migrate
python manage.py runserver
```

開發模式使用 SQLite + LocMemCache + `CELERY_TASK_ALWAYS_EAGER`，無需外部服務。

## 測試

```bash
# 安裝測試依賴
pip install -e ".[dev]"

# 執行測試
pytest

# 65 tests passing
```

## 專案結構

```
├── accounts/          # 使用者認證、登入速率限制
├── backoffice/        # 後台管理（小說/章節/讀者/浮水印）
├── reader/            # 讀者前台（閱讀介面）
├── library/           # 核心模型與服務
│   ├── models.py      # Novel, Chapter, Watermark, Access 等
│   ├── services/      # 業務邏輯層
│   │   ├── access.py        # 三層存取控制
│   │   ├── publishing.py    # 章節發佈流程
│   │   ├── watermark.py     # 盲浮水印嵌入/提取
│   │   ├── visible_watermark.py  # 可見浮水印
│   │   ├── signing.py       # URL 簽名
│   │   └── antiocr.py       # anti7ocr 整合
│   ├── api/           # DRF API + SSE endpoints
│   └── tasks.py       # Celery 任務
├── config/            # Django 設定（base/dev/prod/test）
├── packages/anti7ocr/ # Anti-OCR 渲染引擎
├── docker/            # nginx.conf, entrypoint.sh
├── templates/         # Django templates (HTMX)
└── static/            # htmx.min.js, site.css
```

## 環境變數

參見 [.env.example](.env.example) — 包含所有可設定項目。

## License

Private — All rights reserved.
