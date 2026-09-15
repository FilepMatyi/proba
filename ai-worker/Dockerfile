FROM python:3.11-slim

WORKDIR /app

# ONNX Runtime uses OpenMP. The headless OpenCV wheel does not need libGL.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --no-cache-dir --upgrade pip
RUN python -m pip install --no-cache-dir -r requirements.txt

# Fail the image build early if the configured model name is unsupported and
# cache the model so production workers never depend on a first-request download.
ARG REMBG_MODEL=birefnet-general-lite
ENV REMBG_MODEL=${REMBG_MODEL}
RUN python -c "import os; from rembg import new_session; new_session(os.environ['REMBG_MODEL']); print('Cached rembg model:', os.environ['REMBG_MODEL'])"

COPY . .

CMD ["python", "worker.py"]
