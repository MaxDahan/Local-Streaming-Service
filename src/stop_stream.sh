# stops a stream started with start_stream. Kills all the necessary processes and cleans files.
#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: $0 <channel_name>"
  exit 1
fi

CHANNEL="$1"
echo "🔴 Stopping looping stream for channel: $CHANNEL"

# Kill cleanup.sh
CLEANUP_PIDS=$(ps aux | grep "[c]leanup.sh" | grep "$CHANNEL" | awk '{print $2}')
if [ -n "$CLEANUP_PIDS" ]; then
  echo "Killing cleanup.sh PIDs: $CLEANUP_PIDS"
  kill $CLEANUP_PIDS
else
  echo "No cleanup.sh processes found for $CHANNEL"
fi

# Kill start_stream_logic.sh
START_PIDS=$(ps aux | grep "[s]tart_stream_logic.sh" | grep "$CHANNEL" | awk '{print $2}')
if [ -n "$START_PIDS" ]; then
  echo "Killing start_stream_logic.sh PIDs: $START_PIDS"
  kill $START_PIDS
else
  echo "No start_stream_logic.sh processes found for $CHANNEL"
fi

# Kill ffmpeg processes for this channel
FFMPEG_PIDS=$(ps aux | grep "[f]fmpeg" | grep "$CHANNEL" | awk '{print $2}')
if [ -n "$FFMPEG_PIDS" ]; then
  echo "Killing ffmpeg PIDs: $FFMPEG_PIDS"
  kill -9 $FFMPEG_PIDS
else
  echo "No ffmpeg processes found for $CHANNEL"
fi

# remove old HLS segment files and playlist
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$BASE_DIR/channels/$CHANNEL/output"
echo "🧹 Cleaning up old HLS segments and playlists..."
rm -f "$OUTPUT_DIR"/*.ts "$OUTPUT_DIR"/*.m3u8

echo "✅ Done."
