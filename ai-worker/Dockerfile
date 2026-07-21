FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-bake IS-Net model at build time to avoid runtime network dependency
RUN python -c "from rembg import new_session; new_session('isnet-general-use')"

COPY . .

CMD ["python", "worker.py"]
