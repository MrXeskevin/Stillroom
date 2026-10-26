"""Stillroom — local visual asset register. Run: python app.py"""
from __future__ import annotations
import io
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("STILLROOM_DATA", str(ROOT / "data")))
UPLOADS = DATA / "uploads"
DB = DATA / "stillroom.sqlite3"
UPLOADS.mkdir(parents=True, exist_ok=True)
MAX_BYTES = 12 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 24_000_000

app = FastAPI(title="Stillroom", version="1.0.0", docs_url="/api/docs")
app.mount("/assets", StaticFiles(directory=str(ROOT / "static")), name="assets")
app.mount("/media", StaticFiles(directory=str(UPLOADS)), name="media")


@contextmanager
def connection():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
            location TEXT NOT NULL, notes TEXT NOT NULL, image TEXT NOT NULL,
            created_at TEXT NOT NULL)""")

initialize()


def json_item(row):
    value = dict(row)
    value["image_url"] = "/media/" + value["image"]
    return value


def all_items():
    with connection() as db:
        return [json_item(r) for r in db.execute("SELECT * FROM items ORDER BY created_at DESC").fetchall()]


async def read_image(upload: UploadFile):
    data = await upload.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(400, "Please choose an image smaller than 12 MB.")
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            source = ImageOps.exif_transpose(source)
            source.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            image = source.convert("RGB")
    except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError):
        raise HTTPException(400, "This file is not a valid supported image.")
    if min(image.size) < 48:
        raise HTTPException(400, "Image must be at least 48 pixels wide and high.")
    return image


def bgr(pil):
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def load_saved(item):
    img = cv2.imread(str(UPLOADS / item["image"]))
    if img is None:
        raise HTTPException(500, "A catalog image is missing on disk.")
    return img


def features(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=1800, scaleFactor=1.2, nlevels=8)
    kp, desc = orb.detectAndCompute(gray, None)
    hist = cv2.calcHist([cv2.cvtColor(image, cv2.COLOR_BGR2HSV)], [0, 1], None, [24, 16], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return kp, desc, hist


def descriptor_matches(d1, d2):
    if d1 is None or d2 is None or len(d1) < 2 or len(d2) < 2:
        return []
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2)
    return [a for pair in pairs if len(pair) == 2 for a, b in [pair] if a.distance < 0.75 * b.distance]


def image_similarity(reference, query):
    k1, d1, h1 = features(reference)
    k2, d2, h2 = features(query)
    matches = descriptor_matches(d1, d2)
    # This is a relevance score, NOT measured model accuracy or a calibrated probability.
    local = min(len(matches) / 45.0, 1.0)
    color = max(0, cv2.compareHist(h1, h2, cv2.HISTCMP_CORREL))
    r1 = cv2.resize(cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY), (32, 32))
    r2 = cv2.resize(cv2.cvtColor(query, cv2.COLOR_BGR2GRAY), (32, 32))
    structure = max(0.0, (cv2.matchTemplate(r1, r2, cv2.TM_CCOEFF_NORMED)[0][0] + 1.0) / 2.0)
    score = 0.67 * local + 0.23 * color + 0.10 * structure
    return {"score": round(score * 100), "matched_keypoints": len(matches),
            "color_similarity": round(color * 100), "pattern_similarity": round(structure * 100)}


def locate(reference, scene):
    k1, d1, _ = features(reference)
    k2, d2, _ = features(scene)
    good = descriptor_matches(d1, d2)
    if len(good) < 10:
        return None
    src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
    if H is None or mask is None:
        return None
    inliers = int(mask.sum())
    if inliers < 20 or inliers / len(good) < 0.25:
        return None
    rh, rw = reference.shape[:2]
    sh, sw = scene.shape[:2]
    corners = np.float32([[0, 0], [rw, 0], [rw, rh], [0, rh]]).reshape(-1, 1, 2)
    projected = cv2.perspectiveTransform(corners, H).reshape(4, 2)
    if not np.isfinite(projected).all():
        return None
    area = abs(float(cv2.contourArea(projected.astype(np.float32))))
    if area < 0.0015 * sw * sh or area > 0.93 * sw * sh:
        return None
    # Reject obviously folded / degenerate quadrilaterals.
    if not cv2.isContourConvex(projected.astype(np.float32)):
        return None
    minx, miny = projected.min(axis=0)
    maxx, maxy = projected.max(axis=0)
    if maxx < 0 or maxy < 0 or minx > sw or miny > sh:
        return None
    return {"polygon": [[round(float(x / sw), 4), round(float(y / sh), 4)] for x,y in projected],
            "inliers": inliers, "matches": len(good), "inlier_ratio": round(inliers / len(good), 2)}


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/items")
def get_items():
    return {"items": all_items()}


@app.post("/api/items", status_code=201)
async def create_item(name: str = Form(...), category: str = Form("Other"),
                      location: str = Form("Not specified"), notes: str = Form(""),
                      image: UploadFile = File(...)):
    name, category, location, notes = [v.strip() for v in (name, category, location, notes)]
    if not name or len(name) > 100 or len(category) > 60 or len(location) > 100 or len(notes) > 500:
        raise HTTPException(400, "Please check the item details and field lengths.")
    pil = await read_image(image)
    item_id = uuid.uuid4().hex[:12]
    filename = item_id + ".jpg"
    pil.save(UPLOADS / filename, format="JPEG", quality=88, optimize=True)
    now = datetime.now(timezone.utc).isoformat()
    with connection() as db:
        db.execute("INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (item_id, name, category or "Other", location or "Not specified", notes, filename, now))
    return {"item": next(item for item in all_items() if item["id"] == item_id)}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    with connection() as db:
        row = db.execute("SELECT image FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Item not found.")
        db.execute("DELETE FROM items WHERE id=?", (item_id,))
    (UPLOADS / row["image"]).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/search")
async def search(image: UploadFile = File(...)):
    query = bgr(await read_image(image))
    result = []
    for item in all_items():
        result.append({"item": item, **image_similarity(load_saved(item), query)})
    return {"results": sorted(result, key=lambda x: x["score"], reverse=True),
            "note": "Similarity scores are ranking indicators, not accuracy measurements."}


@app.post("/api/scan")
async def scan(image: UploadFile = File(...)):
    scene = bgr(await read_image(image))
    found = []
    for item in all_items():
        match = locate(load_saved(item), scene)
        if match:
            found.append({"item": item, **match})
    return {"found": sorted(found, key=lambda x: x["inliers"], reverse=True),
            "width": scene.shape[1], "height": scene.shape[0],
            "note": "Local feature matching works best for textured, flat items like printed covers and posters. Missing results are not proof an item is absent."}


@app.get("/api/health")
def health():
    return {"ok": True, "items": len(all_items())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8787")))
