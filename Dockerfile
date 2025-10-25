FROM python:3.11-slim

# System deps for ffmpeg/OpenCV/MediaPipe
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

# Render sets $PORT — listen on it if present, else 7860 (local)
ENV PORT=7860
EXPOSE 7860

CMD ["bash", "-lc", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-7860}"]
