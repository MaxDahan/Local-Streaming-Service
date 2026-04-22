# MaxiStreams

Local network streaming server with:
- always-on channel streams
- on-demand file/folder playback
- account login and live chat

Designed for home servers and Raspberry Pi style setups.

## Quick Start (Fresh Clone)

### 1. Install dependencies

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y python3 ffmpeg jq
```

Why these are needed:
- `python3`: web server and API
- `ffmpeg`: encoding + HLS stream generation
- `jq`: starts all channels from `channels.json`

### 2. Clone and enter the project

```bash
git clone <your-repo-url>
cd Streaming
```

### 3. Add media

Put source media into:

`media/raw/<Show or Folder Name>/...`

Then encode to streaming-friendly 720p:

```bash
./encode_to_720p.sh
```

Encoded files are written to `media/converted/` with matching folder structure.

### 3b. Fetch cover art (optional)

After encoding, download cover art for each show from TVMaze (free, no API key needed):

```bash
python3 fetch_covers.py
```

This scans every folder in `media/converted/` and downloads a `cover.jpg` (or `.png`/`.webp`) into any folder that doesn't already have one. It uses TVMaze for TV shows; a name override map inside the script handles common naming mismatches (e.g. `Bobs Burgers` → `Bob's Burgers`). Folders like `Movies` or `Music-Videos` are skipped by default.

To add a manual override for a show TVMaze can't find, add an entry to `TVMAZE_OVERRIDES` at the top of `fetch_covers.py`:

```python
"Your Folder Name": "Exact TVMaze Show Title",
```

### 4. Configure channels

Edit `channels.json` so each channel points to folders that exist under `media/converted/`.

### 5. Start the service

```bash
sudo ./start_server.sh
```

Then open:
- `http://maxistreams.local`
- or `http://<your-server-ip>`

### 6. Stop the service

```bash
sudo ./stop_server.sh
```

## Debugging

Direct HLS URL format:

`http://<your-server-ip>/channels/<channel-id>/output/<channel-id>.m3u8`

Server log:

`output/server.log`

## Notes

- User account data is stored locally in `src/configurations/users.json`.
- That users file is intentionally git-ignored (not committed).
- Paths are repository-relative by default (for example `media_root` uses `media/converted`).
- Use an SSD for better stream performance.
- Long-running outputs/logs rotate and segment files are cleaned up over time.

## Is it easy for someone else to set up?

Yes. A new user can clone, install `python3/ffmpeg/jq`, add media, run one encode command, then start the server. The exact commands are listed above for copy/paste setup.
