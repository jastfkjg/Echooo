FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --gid 10001 echooo && useradd --uid 10001 --gid echooo --no-create-home echooo
COPY pyproject.toml README.md ./
COPY src ./src
COPY web ./web
COPY config ./config
COPY deploy/cloud/create_owner.py ./deploy/cloud/create_owner.py
RUN pip install . && mkdir -p /app/data && chown echooo:echooo /app/data
ENV PYTHONPATH=/app/src
USER echooo
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "echooo.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
