#!/bin/bash

if [ -z "$1" ]; then
  echo "Usage: $0 <channel_name>"
  exit 1
fi

CHANNEL="$1"
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
CHANNEL_DIR="$BASE_DIR/channels/$CHANNEL"
CONVERTED_DIR="$CHANNEL_DIR/converted"
OUTPUT_DIR="$BASE_DIR/output"

mkdir -p "$CONVERTED_DIR" "$OUTPUT_DIR"

echo "📼 Starting encoding for channel: $CHANNEL"
echo "📁 Source directory: $CHANNEL_DIR"
echo "💾 Output directory: $CONVERTED_DIR"

# Set standard encoding profile
TARGET_RESOLUTION="720"
TARGET_FRAMERATE="30"
AUDIO_SAMPLE_RATE="48000"

find "$CHANNEL_DIR" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.avi" \) ! -name ".*" -print0 | while IFS= read -r -d '' input; do
  filename="$(basename "$input")"
  basename_no_ext="${filename%.*}"
  output="$CONVERTED_DIR/${basename_no_ext}.mp4"

  if [ -f "$output" ]; then
    echo "⏩ Skipping '$filename' (already converted to ${basename_no_ext}.mp4)"
    continue
  fi

  echo "🎞️ Encoding '$filename'..."

  ffmpeg -y -nostdin -i "$input" \
    -vf "scale=-2:${TARGET_RESOLUTION},fps=${TARGET_FRAMERATE}" \
    -map 0:v:0 -map 0:a:0 \
    -c:v libx264 -preset veryfast -crf 23 \
    -pix_fmt yuv420p \
    -r ${TARGET_FRAMERATE} \
    -c:a aac -ac 2 -b:a 128k -ar ${AUDIO_SAMPLE_RATE} \
    -movflags +faststart \
    -map_metadata 0 \
    "$output"

  if [ $? -eq 0 ]; then
    echo "✅ Finished encoding '$filename'"
  else
    echo "❌ Failed to encode '$filename'"
  fi

done

echo "🎉 All encoding completed for channel: $CHANNEL"

