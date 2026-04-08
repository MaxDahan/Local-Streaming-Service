#!/usr/bin/env bash
# start_stream_logic_fixed.sh

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

mkdir -p "$OUTPUT_DIR"

echo "🔹 Base dir: $BASE_DIR"
echo "🔹 Channel dir: $CHANNEL_DIR"
echo "🔹 Output playlist: $OUTPUT_PLAYLIST"

# Load folders from channels.json safely
mapfile -t FOLDERS < <(jq -r --arg id "$CHANNEL" '.[] | select(.id==$id) | .folders[]' "$BASE_DIR/channels.json")

echo "🔹 Folders for channel $CHANNEL:"
for f in "${FOLDERS[@]}"; do
  echo "   -> [$f]"
done

if [ ${#FOLDERS[@]} -eq 0 ]; then
  echo "❌ No folders found for channel $CHANNEL"
  exit 1
fi

while true; do
  PLAYLIST_FILE="$CHANNEL_DIR/current_playlist.txt"
  : > "$PLAYLIST_FILE"
  ALL_FILES=()

  for folder in "${FOLDERS[@]}"; do
    MEDIA_DIR="$BASE_DIR/media/converted/$folder"
    echo "🔹 Checking folder: '$MEDIA_DIR'"

    if [ -d "$MEDIA_DIR" ]; then
      echo "   ✅ Folder exists. Collecting mp4 files..."
      while IFS= read -r -d '' file; do
        ALL_FILES+=("$file")
        echo "      -> Adding file: $file"
      done < <(find "$MEDIA_DIR" -type f \( -iname "*.mp4" -o -iname "*.MP4" \) ! -name "._*" -print0)
    else
      echo "⚠️ Folder '$MEDIA_DIR' does not exist, skipping"
    fi
  done

  if [ ${#ALL_FILES[@]} -eq 0 ]; then
    echo "⚠️ No video files found. Retrying in 10s..."
    sleep 10
    continue
  fi

  echo "🔹 Total files collected: ${#ALL_FILES[@]}"
  printf "   -> %s\n" "${ALL_FILES[@]}"

  # Shuffle safely
  mapfile -t SHUFFLED_FILES < <(printf '%s\0' "${ALL_FILES[@]}" | shuf -z | xargs -0 -n1)

  echo "🔹 Shuffled files:"
  printf "   -> %s\n" "${SHUFFLED_FILES[@]}"

  # Write playlist
  : > "$CHANNEL_DIR/current_playlist.txt"
  for f in "${SHUFFLED_FILES[@]}"; do
    escaped=$(printf "%s" "$f" | sed "s/'/'\\\\''/g")
    echo "file '$escaped'" >> "$CHANNEL_DIR/current_playlist.txt"
  done

  echo "🎬 Launching FFmpeg..."
  ffmpeg -nostdin -re -f concat -safe 0 -i "$CHANNEL_DIR/current_playlist.txt" \
    -c copy \
    -f hls \
    -hls_time 6 \
    -hls_list_size 30 \
    -hls_flags program_date_time \
    -hls_segment_filename "${SEGMENT_PREFIX}%03d.ts" \
    "$OUTPUT_PLAYLIST" 2>&1

  echo "🔁 Restarting loop in 2 seconds..."
  sleep 2
done
