FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 HF_HUB_DISABLE_TELEMETRY=1 TOKENIZERS_PARALLELISM=false
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*
COPY worker-py/requirements-rag.txt ./requirements-rag.txt
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
RUN pip install --no-cache-dir -r requirements-rag.txt
ENV PYTHONPATH=/app RAG_MODEL_CACHE=/models HF_HOME=/models/huggingface
CMD ["python", "tests/test_rag.py"]
