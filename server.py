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
    fps: str = Form("keep"),           # <-- string: "keep" (no downsample) or "10"/"15"/etc
    debug: int = Form(0)               # keep if you added debug earlier; else remove this
):
    """
    Multipart:
      - file: short video (.mp4/.mov/.webm…)
      - model_name: default
      - fps: "keep" (preserve native fps) or a number-as-string, e.g., "10"
      - debug: 1 to include pose component summary (optional)
    """
    import os, base64, tempfile, shlex

    with tempfile.TemporaryDirectory() as td:
        in_path   = os.path.join(td, "clip_in")
        norm_path = os.path.join(td, "clip_norm.mp4")
        out_pose  = os.path.join(td, "clip.pose")

        ext = os.path.splitext(file.filename or "")[1] or ".mp4"
        in_path += ext

        # 1) Save upload
        video_bytes = await file.read()
        with open(in_path, "wb") as f:
            f.write(video_bytes)

        # 2) Normalize container & pixel format; optionally downsample fps
        try:
            vf_filter = ""
            if fps and fps.lower() != "keep":
                # only apply -vf fps=… if caller asked for it
                try:
                    fps_val = int(fps)
                    if fps_val > 0:
                        vf_filter = f"-vf fps={fps_val} "
                except ValueError:
                    pass  # ignore bad fps values -> keep native fps

            cmd_ffmpeg = (
                f"ffmpeg -y -i {shlex.quote(in_path)} "
                f"{vf_filter}-an -pix_fmt yuv420p -movflags +faststart "
                f"-preset veryfast {shlex.quote(norm_path)}"
            )
            run(cmd_ffmpeg)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"ffmpeg failed: {e}")

        # 3) Extract pose (mediapipe layout)
        try:
            cmd_pose = f"video_to_pose -i {shlex.quote(norm_path)} --format mediapipe -o {shlex.quote(out_pose)}"
            run(cmd_pose)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"video_to_pose failed: {e}")

        # 4) (optional) debug block you may already have — keep or remove
        pose_debug = None
        # if debug: ... (omit here for brevity)

        # 5) Read .pose, call UZH, return embeddings (and debug if present)
        try:
            with open(out_pose, "rb") as f:
                pose_bytes = f.read()
            b64 = base64.b64encode(pose_bytes).decode("ascii")
            r = call_uzh({"pose": [b64], "model_name": model_name}, prefer_get=True)
            if r.status_code != 200:
                return Response(content=r.text, status_code=r.status_code, media_type=r.headers.get("content-type","application/json"))
            payload = r.json()
            # if debug: payload = {"debug": pose_debug, **payload}
            return JSONResponse(payload, status_code=200)
        except Exception as e:
            return JSONResponse({"error": "Upstream fetch failed", "detail": str(e)}, status_code=502)
