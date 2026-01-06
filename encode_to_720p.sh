#!/bin/bash
# encode_to_720p.sh
# Converts all videos in media/raw/<show>/ to H.264 + AAC 720p for streaming
# Output goes to media/converted/<show>/

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
RAW_DIR="$BASE_DIR/media/raw"
CONVERTED_DIR="$BASE_DIR/media/converted"

# Encoding settings
TARGET_RESOLUTION="720"
TARGET_FRAMERATE="30"
AUDIO_SAMPLE_RATE="48000"

# Ensure converted directory exists
mkdir -p "$CONVERTED_DIR"

echo "📼 Starting batch encoding from '$RAW_DIR' to '$CONVERTED_DIR'..."

# Loop through all folders in media/raw/
find "$RAW_DIR" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r folder; do
    folder_name="$(basename "$folder")"
    output_folder="$CONVERTED_DIR/$folder_name"
    mkdir -p "$output_folder"

    echo "🎬 Processing folder: '$folder_name'"

    # Loop through all video files in the folder
    find "$folder" -maxdepth 1 -type f \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.avi" \) ! -name ".*" | while IFS= read -r input; do
        filename="$(basename "$input")"
        basename_no_ext="${filename%.*}"
        output="$output_folder/${basename_no_ext}.mp4"

        if [ -f "$output" ]; then
            echo "⏩ Skipping '$filename' (already converted)"
            continue
        fi

        echo "🔹 Encoding '$filename' → '$output'"

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
            echo "✅ Finished encoding '$filename'"
        else
            echo "❌ Failed to encode '$filename'"
        fi
    done
done

echo "🎉 All folders processed!"
