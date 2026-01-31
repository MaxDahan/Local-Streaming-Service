#!/bin/bash
# encode_to_720p.sh
# Converts all videos in media/raw/ recursively to H.264 + AAC 720p for streaming
# Mirrors the folder structure in media/converted/

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
RAW_DIR="$BASE_DIR/media/raw"
CONVERTED_DIR="$BASE_DIR/media/converted"

# Encoding settings
TARGET_RESOLUTION="720"
TARGET_FRAMERATE="30"
AUDIO_SAMPLE_RATE="48000"

echo "📼 Starting recursive batch encoding from '$RAW_DIR' to '$CONVERTED_DIR'..."

# Loop through all video files recursively
find "$RAW_DIR" -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.avi" \) ! -name ".*" | while IFS= read -r input; do
    # Determine relative path from RAW_DIR
    rel_path="${input#$RAW_DIR/}"
    rel_dir="$(dirname "$rel_path")"

    # Create equivalent folder in converted
    output_folder="$CONVERTED_DIR/$rel_dir"
    mkdir -p "$output_folder"

    filename="$(basename "$input")"
    basename_no_ext="${filename%.*}"
    output="$output_folder/${basename_no_ext}.mp4"

    if [ -f "$output" ]; then
        echo "⏩ Skipping '$rel_path' (already converted)"
        continue
    fi

    echo "🔹 Encoding '$rel_path' → '$output'"

    ffmpeg -y -nostdin -i "$input" \
        -vf "scale=-2:${TARGET_RESOLUTION},fps=${TARGET_FRAMERATE}" \
        -map 0:v:0 -map 0:a:0? \
        -c:v libx264 -preset veryfast -crf 23 \
        -pix_fmt yuv420p \
        -r ${TARGET_FRAMERATE} \
        -c:a aac -b:a 128k -ac 2 -ar ${AUDIO_SAMPLE_RATE} \
        -movflags +faststart \
        -map_metadata 0 \
        "$output"

    if [ $? -eq 0 ]; then
        echo "✅ Finished encoding '$rel_path'"
    else
        echo "❌ Failed to encode '$rel_path'"
    fi
done

echo "🎉 All files processed!"
