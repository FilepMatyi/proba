FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /app

# ── System dependencies ──────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-dev \
    cmake build-essential ninja-build \
    git wget curl unzip \
    libopencv-dev \
    libboost-program-options-dev \
    libboost-graph-dev \
    libboost-system-dev \
    libboost-filesystem-dev \
    libeigen3-dev \
    libflann-dev \
    libfreeimage-dev \
    libmetis-dev \
    libsqlite3-dev \
    libglew-dev \
    libcgal-dev \
    libceres-dev \
    colmap \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# ── Python packages (base) ──────────────────────────────────────────
RUN pip3 install --no-cache-dir \
    pycolmap \
    redis==5.0.1 \
    minio==7.2.0 \
    python-dotenv==1.0.0 \
    requests==2.31.0 \
    numpy>=1.24.0 \
    Pillow>=10.0.0 \
    plyfile>=1.0 \
    opencv-python-headless>=4.8.0

# ── PyTorch CPU ──────────────────────────────────────────────────────
RUN pip3 install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# ── OpenSplat (CPU build) ───────────────────────────────────────────
# Download LibTorch CPU for C++ build
RUN wget -q https://download.pytorch.org/libtorch/cpu/libtorch-cxx11-abi-shared-with-deps-2.1.0%2Bcpu.zip \
    -O /tmp/libtorch.zip \
    && unzip -q /tmp/libtorch.zip -d /opt \
    && rm /tmp/libtorch.zip

# Clone and build OpenSplat
RUN git clone --depth 1 https://github.com/pierotofy/OpenSplat.git /tmp/opensplat \
    && cd /tmp/opensplat \
    && mkdir build && cd build \
    && cmake .. \
        -DCMAKE_PREFIX_PATH=/opt/libtorch \
        -DGPU_RUNTIME=NONE \
        -DCMAKE_BUILD_TYPE=Release \
        -GNinja \
    && ninja -j2 \
    && cp opensplat /usr/local/bin/ \
    && cd / && rm -rf /tmp/opensplat

# ── Copy application code ───────────────────────────────────────────
COPY . .

CMD ["python3", "worker.py"]
