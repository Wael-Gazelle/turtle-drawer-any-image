"""Draw My Image - uploads are read into memory, processed, and discarded. Never stored."""
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .processing import process
from .schemas import Settings

MAX_BYTES = 5 * 1024 * 1024
RATE_LIMIT, RATE_WINDOW = 30, 60          # requests per IP per minute (kept in memory only)
STATIC = Path(__file__).resolve().parent.parent / "static"

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": ("default-src 'none'; script-src 'self'; style-src 'self'; "
                                "img-src 'self' blob: data:; connect-src 'self'; "
                                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

app = FastAPI(title="Draw My Image", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


def _rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now, hits = time.monotonic(), _hits[ip]
    while hits and now - hits[0] > RATE_WINDOW:
        hits.popleft()
    if len(hits) >= RATE_LIMIT:
        raise HTTPException(429, "Too many requests. Please wait a minute and try again.")
    hits.append(now)


def _is_image(d: bytes) -> bool:
    return d.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (d[:4] == b"RIFF" and d[8:12] == b"WEBP")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/process")
async def api_process(request: Request, s: Annotated[Settings, Query()]) -> JSONResponse:
    """Body = raw image bytes (read straight into memory, never a temp file)."""
    _rate_limit(request)
    try:
        if int(request.headers.get("content-length", 0)) > MAX_BYTES:
            raise HTTPException(413, "The image is larger than 5 MB.")
    except ValueError:
        raise HTTPException(400, "Invalid request.")
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_BYTES:
            raise HTTPException(413, "The image is larger than 5 MB.")
    data = bytes(buf)
    if not _is_image(data):
        raise HTTPException(415, "Please upload a PNG, JPEG or WebP image.")
    try:
        result = await run_in_threadpool(process, data, s)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return JSONResponse(result)
