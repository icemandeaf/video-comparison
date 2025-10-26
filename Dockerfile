FROM python:3.9-bullseye

# System libs needed by ffmpeg/OpenCV/Mediapipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Make pip quieter & faster in CI, and avoid source builds
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100

# Upgrade pip to a stable version that plays nicely with manylinux wheels
RUN python -m pip install --upgrade "pip==24.2"

# 1) Install core deps (these are pure Python wheels)
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) Install the heavy wheels explicitly as binaries (no source builds)
#    Order matters: numpy already installed above.
RUN pip install --only-binary=:all: "opencv-python-headless==4.9.0.80"
RUN pip install --only-binary=:all: "mediapipe==0.10.21"

# Optional: quick import check (kept tiny, no heredoc)
RUN python - <<'PY'\nimport cv2, mediapipe as mp, numpy as np, pose_format\nprint('Imports OK')\nPY

# App code
COPY server.py .

# Render provides $PORT at runtime
ENV PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["bash", "-lc", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-7860}"]
