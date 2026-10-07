# Draw My Image

Upload a picture and watch it being drawn with a pencil. FastAPI + OpenCV on the server, plain HTML/JS/CSS in the browser.

This work was built to level up my Python skills handling difficult problems. 
Live Demo: https://turtle-drawer-any-image.onrender.com (Hosted on a free tier, so processing might be very slow due to heavy calculations especially after I improved the details up to 1000 you can decrease the details to 50 for faster running), you can clone it and run it locally that will work very fast.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

## Settings you can tweak

- \`app/main.py\`: \`MAX_BYTES\` (upload limit), \`RATE_LIMIT\` / \`RATE_WINDOW\` (requests per IP per minute)
- \`app/processing.py\`: \`MAX_SIDE\` (working size), \`MAX_REGIONS\`, \`MAX_EDGE_POINTS\` (keeps the JSON small), and the slider mappings in \`process()\`
- \`static/app.js\`: \`MAXPX\` (browser-side downscale before upload), \`rate\` in \`build()\` (length of the drawing at 1x)

## Deploy with Docker

\`\`\`dockerfile
FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt . 
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY static static
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
\`\`\`

Put it behind HTTPS (for example a reverse proxy). Check that your host does not log request bodies.

## Privacy design

- The browser shrinks the image and sends the bytes as the raw request body, so the server reads them straight into memory (no multipart upload, which can spool to a temp file).
- The image is decoded, processed in a worker thread and dropped. Nothing is written to disk, a database or a cache, and the app never logs bodies or file names.
- No cookies, sessions, analytics or third-party scripts and fonts. Everything is served from this app.
- Responses carry \`Cache-Control: no-store\`, a strict Content-Security-Policy, \`nosniff\` and \`no-referrer\`.
- Only PNG, JPEG and WebP up to 5 MB are accepted, files are checked by their real signature, and requests are rate limited per IP (counters live in memory only).
