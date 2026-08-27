#!/usr/bin/env bash
# start_stream_logic_fixed.sh

if [ -z "$1" ]; then
  echo "Usage: $0 <channel_id>"
  exit 1
fi

CHANNEL="$1"
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHANNEL_DIR="$BASE_DIR/channels/$CHANNEL"
OUTPUT_DIR="$CHANNEL_DIR/output"
OUTPUT_PLAYLIST="$OUTPUT_DIR/$CHANNEL.m3u8"
SEGMENT_PREFIX="$OUTPUT_DIR/${CHANNEL}_"

mkdir -p "$OUTPUT_DIR"
PLAYLIST_FILE="$CHANNEL_DIR/current_playlist.txt"
CONFIG_FILE="$BASE_DIR/src/configurations/config.json"
# Load media roots: supports media_roots array and legacy media_root string.
mapfile -t MEDIA_ROOTS_ARRAY < <(jq -r '
  if (.media_roots | type) == "array" then .media_roots[]
  elif .media_root then .media_root
  else empty end
' "$CONFIG_FILE" 2>/dev/null)

if [ ${#MEDIA_ROOTS_ARRAY[@]} -eq 0 ]; then
  MEDIA_ROOTS_ARRAY=("$BASE_DIR/media/converted")
fi

# Resolve any relative paths against BASE_DIR
for i in "${!MEDIA_ROOTS_ARRAY[@]}"; do
  root="${MEDIA_ROOTS_ARRAY[$i]}"
  if [[ "$root" != /* ]]; then
    MEDIA_ROOTS_ARRAY[$i]="$BASE_DIR/$root"
  fi
done

MEDIA_ROOT="${MEDIA_ROOTS_ARRAY[0]}"

echo "🔹 Base dir: $BASE_DIR"
echo "🔹 Media root: $MEDIA_ROOT"
echo "🔹 Channel dir: $CHANNEL_DIR"
echo "🔹 Output playlist: $OUTPUT_PLAYLIST"
echo "🔹 Playlist file: $PLAYLIST_FILE"

# Load folders from channels.json safely (search all nesting levels)
mapfile -t FOLDERS < <(jq -r --arg id "$CHANNEL" '.. | objects | select(.id==$id) | .folders[]?' "$BASE_DIR/channels.json")

echo "🔹 Folders for channel $CHANNEL:"
for f in "${FOLDERS[@]}"; do
  echo "   -> [$f]"
done

if [ ${#FOLDERS[@]} -eq 0 ]; then
  echo "❌ No folders found for channel $CHANNEL"
  exit 1
fi

# Collect and shuffle playlist once
# Clean old .ts files
rm -f "$OUTPUT_DIR"/*.ts
echo "🧹 Cleaned old .ts files"
declare -a show_names=()
for folder in "${FOLDERS[@]}"; do
  MEDIA_DIR=""
  for root in "${MEDIA_ROOTS_ARRAY[@]}"; do
    candidate="$root/$folder"
    if [ -d "$candidate" ]; then
      MEDIA_DIR="$candidate"
      break
    fi
  done

  echo "🔹 Checking folder: '$folder' -> '${MEDIA_DIR:-NOT FOUND}'"

  if [ -n "$MEDIA_DIR" ]; then
    echo "   ✅ Folder exists. Collecting mp4 files..."
    declare -a files=()
    while IFS= read -r -d '' file; do
      files+=("$file")
    done < <(find "$MEDIA_DIR" -type f \( -iname "*.mp4" -o -iname "*.MP4" \) ! -name "._*" -print0)
    if [ ${#files[@]} -gt 0 ]; then
      show_names+=("$folder")
      folder_var=$(echo "$folder" | tr ' ' '_' | tr -c 'a-zA-Z0-9_' '_')
      eval "show_files_$folder_var=(\"\${files[@]}\")"
    fi
  else
    echo "⚠️ Folder '$MEDIA_DIR' does not exist, skipping"
  fi
done

if [ ${#show_names[@]} -eq 0 ]; then
  echo "⚠️ No video files found for channel $CHANNEL"
  exit 1
fi

while true; do
  # Reshuffle playlist on every restart so each cycle has a new order
  blocks=()
  for show in "${show_names[@]}"; do
    show_var=$(echo "$show" | tr ' ' '_' | tr -c 'a-zA-Z0-9_' '_')
    eval "show_array=(\"\${show_files_$show_var[@]}\")"
    mapfile -t shuffled < <(printf '%s\0' "${show_array[@]}" | shuf -z | xargs -0 -n1)
    i=0
    while [ $i -lt ${#shuffled[@]} ]; do
      num=$(( RANDOM % 3 + 1 ))
      if [ $((i + num)) -gt ${#shuffled[@]} ]; then num=$(( ${#shuffled[@]} - i )); fi
      block=""
      for ((j=0; j<num; j++)); do
        block="${block}${shuffled[$((i + j))]}"
        if [ $j -lt $((num - 1)) ]; then
          block+=$'\n'
        fi
      done
      blocks+=("$block")
      i=$((i + num))
    done
  done
  mapfile -t shuffled_blocks < <(printf '%s\0' "${blocks[@]}" | shuf -z | xargs -0 -n1)
  SHUFFLED_FILES=()
  for block in "${shuffled_blocks[@]}"; do
    while IFS= read -r ep; do
      [ -n "$ep" ] && SHUFFLED_FILES+=("$ep")
    done <<< "$block"
  done

  echo "🔹 Total files in playlist: ${#SHUFFLED_FILES[@]}"
  printf "   -> %s\n" "${SHUFFLED_FILES[@]}"

  # Write playlist
  TEMP_PLAYLIST="/tmp/temp_playlist_$$.txt"
  : > "$TEMP_PLAYLIST"
  for f in "${SHUFFLED_FILES[@]}"; do
    escaped=$(printf "%s" "$f" | sed "s/'/'\\\\''/g")
    echo "file '$escaped'" >> "$TEMP_PLAYLIST"
  done
  mv "$TEMP_PLAYLIST" "$PLAYLIST_FILE"
  echo "Playlist written to $PLAYLIST_FILE"

  echo "🎬 Launching FFmpeg..."
  if [ "$2" != "dry" ]; then
    ffmpeg -nostdin -re -f concat -safe 0 -i "$CHANNEL_DIR/current_playlist.txt" \
      -c:v copy -bsf:v h264_mp4toannexb \
      -c:a aac -b:a 192k -ac 2 \
      -af "aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000,aresample=async=1000" \
      -f hls \
      -hls_time 6 \
      -hls_list_size 30 \
      -hls_flags program_date_time+delete_segments \
      -hls_segment_filename "${SEGMENT_PREFIX}%d.ts" \
      "$OUTPUT_PLAYLIST" 2>&1
  else
    echo "Dry run: skipping FFmpeg"
    break
  fi

  echo "🔁 Restarting loop in 2 seconds..."
  sleep 2
done
