# Dockerfile — heredoc-free, Render-friendly
FROM python:3.9-bullseye

# System libs for ffmpeg/OpenCV/MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Keep pip stable & avoid source builds
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100
RUN python -m pip install --upgrade "pip==24.2"

# Core deps
COPY requirements.txt .
RUN pip install -r requirements.txt

# Heavy wheels as binaries only (no source build surprises)
RUN pip install --only-binary=:all: "opencv-python-headless==4.9.0.80"
RUN pip install --only-binary=:all: "mediapipe==0.10.21"

# App code
COPY server.py .

# Render provides $PORT
ENV PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["bash", "-lc", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-7860}"]
