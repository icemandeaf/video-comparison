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

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: quick import check (no heredoc)
RUN python -c "import cv2, mediapipe as mp, numpy as np, pose_format; print('Imports OK')"

# App
COPY server.py .

# Render sets $PORT at runtime
ENV PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["bash", "-lc", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-7860}"]
