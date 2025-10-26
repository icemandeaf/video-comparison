# server.py — Video → pose(.pose) → SignCLIP embedding proxy
# Endpoints:
#   GET  /health
#   POST /embed        (JSON: {pose:[base64], model_name?})
#   POST /embed_file   (multipart: file=.pose)
#   POST /video_embed  (multipart: file=<video>; converts to .pose, calls UZH)

import os, json, base64, tempfile, subprocess, shlex
import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse

UPSTREAM_URL = "https://pub.cl.uzh.ch/demo/sign_clip/pose"

app = FastAPI(title="SignCLIP Video Proxy")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to your domain later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def call_uzh(payload: dict, prefer_get: bool = True):
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload)
    if prefer_get:
        r = requests.request("GET", UPSTREAM_URL, headers=headers, data=data, timeout=60)
        if r.status_code == 405:
            r = requests.request("POST", UPSTREAM_URL, headers=headers, data=data, timeout=60)
        return r
    return requests.request("POST", UPSTREAM_URL, headers=headers, data=data, timeout=60)

def run(cmd: str):
    p = subprocess.run(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed ({p.returncode}): {cmd}\n---\n{p.stdout}\n---")
    return p.stdout

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/embed")
def embed_json(body: dict):
    if not isinstance(body, dict) or "pose" not in body or not isinstance(body["pose"], list):
        return JSONResponse({"error": "Expected { pose:[<base64>], model_name? }"}, status_code=400)
    try:
        r = call_uzh({"pose": body["pose"], "model_name": body.get("model_name", "default")}, prefer_get=True)
        ct = r.headers.get("content-type", "application/json")
        return Response(content=r.text, status_code=r.status_code, media_type=ct)
    except Exception as e:
        return JSONResponse({"error": "Upstream fetch failed", "detail": str(e)}, status_code=502)

@app.post("/embed_file")
async def embed_file(file: UploadFile = File(...), model_name: str = Form("default")):
    try:
        raw = await file.read()
        b64 = base64.b64encode(raw).decode("ascii")
        r = call_uzh({"pose": [b64], "model_name": model_name}, prefer_get=True)
        ct = r.headers.get("content-type", "application/json")
        return Response(content=r.text, status_code=r.status_code, media_type=ct)
    except Exception as e:
        return JSONResponse({"error": "Upstream fetch failed", "detail": str(e)}, status_code=502)

@app.post("/video_embed")
async def video_embed(
    file: UploadFile = File(...),
    model_name: str = Form("default"),
    fps: int = Form(10),   # we'll apply this via ffmpeg, not video_to_pose
):
    """
    Multipart:
      - file: short video (.mp4/.mov/.webm…)
      - model_name: default
      - fps: target sampling fps (applied via ffmpeg)
    Flow:
      1) Save upload
      2) ffmpeg -> normalize container & FPS  (-> norm.mp4)
      3) video_to_pose -i norm.mp4 --format mediapipe -o clip.pose
      4) base64 the .pose and call UZH
    """
    import os, base64, tempfile, shlex

    with tempfile.TemporaryDirectory() as td:
        in_path   = os.path.join(td, "clip_in")
        norm_path = os.path.join(td, "clip_norm.mp4")
        out_pose  = os.path.join(td, "clip.pose")

        # keep original extension to help ffmpeg
        ext = os.path.splitext(file.filename or "")[1] or ".mp4"
        in_path += ext

        # 1) Save upload
        video_bytes = await file.read()
        with open(in_path, "wb") as f:
            f.write(video_bytes)

        # 2) Normalize container + FPS using ffmpeg
        #    -vf fps={fps}   : downsample frames to keep things light
        #    -an             : drop audio
        #    -pix_fmt yuv420p: widest compatibility
        #    -movflags +faststart: friendlier streaming start
        #    -preset veryfast: speed
        try:
            cmd_ffmpeg = (
                f"ffmpeg -y -i {shlex.quote(in_path)} "
                f"-vf fps={int(fps)} -an -pix_fmt yuv420p -movflags +faststart "
                f"-preset veryfast {shlex.quote(norm_path)}"
            )
            run(cmd_ffmpeg)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"ffmpeg failed: {e}")

        # 3) Extract pose with the supported CLI flags only
        try:
            cmd_pose = (
                f"video_to_pose -i {shlex.quote(norm_path)} "
                f"--format mediapipe -o {shlex.quote(out_pose)}"
            )
            run(cmd_pose)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"video_to_pose failed: {e}")

        # 4) Read .pose, call UZH
        try:
            with open(out_pose, "rb") as f:
                pose_bytes = f.read()
            b64 = base64.b64encode(pose_bytes).decode("ascii")
            r = call_uzh({"pose": [b64], "model_name": model_name}, prefer_get=True)
            ct = r.headers.get("content-type", "application/json")
            return Response(content=r.text, status_code=r.status_code, media_type=ct)
        except Exception as e:
            return JSONResponse({"error": "Upstream fetch failed", "detail": str(e)}, status_code=502)

