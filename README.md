# ClipCut

Paste a YouTube link, pick start and end, download only that part.

- `web/` static frontend (deploy on Vercel, root directory `web`)
- `server/` FastAPI + yt-dlp + ffmpeg backend (Docker; deploy on Hugging Face Spaces, Render, Fly, etc.)

## How it saves data
The backend runs `yt-dlp --download-sections "*start-end"`, which uses ffmpeg HTTP range requests to fetch only that slice of the stream.

## Setup
1. Deploy `server/` as a Docker service. Set `ALLOWED_ORIGINS` to your site URL.
2. In `web/index.html`, set `window.CLIPCUT_API` (add `<script>window.CLIPCUT_API="https://your-backend"</script>` before the main script).
3. Deploy `web/` to Vercel.

## Notes
- YouTube often blocks datacenter IPs. If downloads fail, export cookies to a file and set `YT_COOKIES_FILE`.
- Keep yt-dlp updated (rebuild the image regularly).
- Downloading may violate YouTube's Terms of Service. Use only for content you have rights to.
