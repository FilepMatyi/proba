FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-bake u2net model at build time to avoid runtime network dependency
RUN python -c "from rembg import new_session; new_session('birefnet-general')"

COPY . .

CMD ["python", "worker.py"]
