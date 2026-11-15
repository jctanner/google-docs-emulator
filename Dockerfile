FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home emulator && mkdir /data && chown emulator /data
USER emulator
ENV DATABASE_PATH=/data/google-docs.sqlite
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"
CMD ["uvicorn", "google_docs_emulator.app:app", "--host", "0.0.0.0", "--port", "8080"]
