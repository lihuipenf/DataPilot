FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/app/.cache/matplotlib
WORKDIR /app
COPY requirements-lock.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements-lock.txt \
    && useradd --create-home --uid 10001 datapilot \
    && mkdir -p /app/outputs /app/.cache \
    && chown -R datapilot:datapilot /app
COPY --chown=datapilot:datapilot . .
USER datapilot
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2)"
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log"]
