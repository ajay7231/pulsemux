FROM node:22-slim AS dashboard
WORKDIR /source/dashboard
COPY dashboard/package*.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
COPY worker-py/web/call.js worker-py/web/call.d.ts /source/worker-py/web/
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY worker-py/requirements*.txt ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
RUN pip install --no-cache-dir -r requirements.txt
COPY worker-py/ ./
COPY --from=dashboard /source/worker-py/web/dashboard ./web/dashboard
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 PLATFORM_ENV=production PLATFORM_DATA_DIR=/data
RUN useradd --uid 10001 --create-home platform && mkdir -p /data && chown platform:platform /data
USER platform
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.web_server:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
