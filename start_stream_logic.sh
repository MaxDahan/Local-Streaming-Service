# actual stream logic. Work done by ffmpeg library. The rest is shuffling the playlist and 
# file checks.
#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: $0 <channel_name>"
  exit 1
fi

CHANNEL="$1"
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
CHANNEL_DIR="$BASE_DIR/channels/$CHANNEL"
CONVERTED_DIR="$CHANNEL_DIR/converted"
OUTPUT_DIR="$CHANNEL_DIR/output"
PLAYLIST_FILE="$CHANNEL_DIR/current_playlist.txt"
OUTPUT_PLAYLIST="$OUTPUT_DIR/$CHANNEL.m3u8"
SEGMENT_PREFIX="$OUTPUT_DIR/${CHANNEL}_"

# initial clean incase it didn't happen on stop
echo "🧹 Cleaning old HLS segments..."
rm -f "$OUTPUT_DIR"/*.ts "$OUTPUT_DIR"/*.m3u8

if [ ! -d "$CONVERTED_DIR" ]; then
  echo "Error: Converted channel folder '$CONVERTED_DIR' does not exist."
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "🚀 Starting infinite streaming loop for channel: $CHANNEL"
echo "Output path: $OUTPUT_PLAYLIST"

while true; do
  echo "🔀 Shuffling playlist for '$CONVERTED_DIR'..."

  # find "$CONVERTED_DIR" -maxdepth 1 -type f \( -iname "*.mp4" \) ! -name "._*" | shuf | while read -r f; do
  #   echo "file '$(realpath "$f")'"
  

  find "$CONVERTED_DIR" -maxdepth 1 -type f -iname "*.mp4" ! -name "._*" | shuf | while read -r f; do
    escaped_path=$(realpath "$f" | sed "s/'/'\\\\''/g")
    echo "file '$escaped_path'"
  done > "$PLAYLIST_FILE"

  if [ ! -s "$PLAYLIST_FILE" ]; then
    echo "⚠️ No video files found in $CONVERTED_DIR. Retrying in 10 seconds..."
    sleep 10
    continue
  fi

  echo "🎬 Launching FFmpeg for channel: $CHANNEL"

  # non encoding ffmpeg, must pre-encode videos (saves so much cpu, like 200%)
  # set to 30, 6 second segments. Stale segments deleted automatically after 4
  # minutes by cleanup.sh
  ffmpeg -nostdin -re -f concat -safe 0 -i "$PLAYLIST_FILE" \
    -c copy \
    -f hls \
    -hls_time 6 \
    -hls_list_size 30 \
    -hls_flags program_date_time \
    -hls_segment_filename "${SEGMENT_PREFIX}%03d.ts" \
    "$OUTPUT_PLAYLIST" 2>&1

  # changed hls_flags append_list+program_date_time to what it is \


  echo "🔁 FFmpeg finished. Restarting with a new shuffled playlist in 2 seconds..."
  sleep 2
done

