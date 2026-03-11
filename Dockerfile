FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    ANTI_OCR_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        fonts-noto-cjk \
        git \
        libglib2.0-0 \
        libgl1 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender1 \
        tesseract-ocr \
        tesseract-ocr-chi-tra \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY packages/anti7ocr /app/packages/anti7ocr
RUN pip install --upgrade pip setuptools wheel \
    && pip install /app/packages/anti7ocr[eval]

COPY pyproject.toml /app/
RUN pip install .

COPY . /app/

RUN chmod +x /app/docker/entrypoint.sh

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "300", "--graceful-timeout", "30"]
