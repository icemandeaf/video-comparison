FROM python:3.10-bullseye

# System deps for ffmpeg/OpenCV/MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: fail early if a wheel is missing required libs
RUN python - <<'PY'\nimport cv2, mediapipe as mp, numpy as np, pose_format\nprint('Imports OK')\nPY

COPY server.py .

# Render sets $PORT at runtime
ENV PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["bash", "-lc", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-7860}"]
