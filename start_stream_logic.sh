#!/usr/bin/env bash
# start_stream_logic.sh
# Streams videos for a channel based on folders in media/converted

if [ -z "$1" ]; then
  echo "Usage: $0 <channel_id>"
  exit 1
fi

CHANNEL="$1"
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
CHANNEL_DIR="$BASE_DIR/channels/$CHANNEL"
OUTPUT_DIR="$CHANNEL_DIR/output"
OUTPUT_PLAYLIST="$OUTPUT_DIR/$CHANNEL.m3u8"
SEGMENT_PREFIX="$OUTPUT_DIR/${CHANNEL}_"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Load folders for this channel from channels.json
mapfile -t FOLDERS < <(jq -r --arg id "$CHANNEL" '.[] | select(.id==$id) | .folders[]' "$BASE_DIR/channels.json")

if [ ${#FOLDERS[@]} -eq 0 ]; then
  echo "❌ No folders defined for channel $CHANNEL in channels.json"
  exit 1
fi

echo "🚀 Starting infinite streaming loop for channel: $CHANNEL"
echo "Output path: $OUTPUT_PLAYLIST"

while true; do
  PLAYLIST_FILE="$CHANNEL_DIR/current_playlist.txt"
  : > "$PLAYLIST_FILE"

  # Loop through each folder
  for folder in "${FOLDERS[@]}"; do
    MEDIA_DIR="$BASE_DIR/media/converted/$folder"

    if [ -d "$MEDIA_DIR" ]; then
      # Find all mp4 files, shuffle them, and add to playlist
      while IFS= read -r f; do
        escaped_path=$(realpath "$f" | sed "s/'/'\\\\''/g")
        echo "file '$escaped_path'" >> "$PLAYLIST_FILE"
      done < <(find "$MEDIA_DIR" -maxdepth 1 -type f -iname "*.mp4" ! -name "._*" | shuf)
    else
      echo "⚠️ Folder '$MEDIA_DIR' does not exist, skipping"
    fi
  done

  # If no files found, wait and retry
  if [ ! -s "$PLAYLIST_FILE" ]; then
    echo "⚠️ No video files found for channel '$CHANNEL'. Retrying in 10 seconds..."
    sleep 10
    continue
  fi

  echo "🎬 Launching FFmpeg for channel: $CHANNEL"

  ffmpeg -nostdin -re -f concat -safe 0 -i "$PLAYLIST_FILE" \
    -c copy \
    -f hls \
    -hls_time 6 \
    -hls_list_size 30 \
    -hls_flags program_date_time \
    -hls_segment_filename "${SEGMENT_PREFIX}%03d.ts" \
    "$OUTPUT_PLAYLIST" 2>&1

  echo "🔁 FFmpeg finished. Restarting with a new shuffled playlist in 2 seconds..."
  sleep 2
done
