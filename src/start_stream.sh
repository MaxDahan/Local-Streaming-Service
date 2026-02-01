#!/bin/bash
# File: start_stream.sh
# Runs a single channel stream in the background

CHANNEL="$1"

if [ -z "$CHANNEL" ]; then
    echo "❌ No channel specified!"
    exit 1
fi

# Absolute project root
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHANNEL_DIR="$BASE_DIR/channels/$CHANNEL"
OUTPUT_DIR="$CHANNEL_DIR/output"

# Ensure output directory exists
mkdir -p "$OUTPUT_DIR"

# Run cleanup and streaming in the background
nohup "$BASE_DIR/src/cleanup.sh" "$CHANNEL" 2>&1 | tr -cd '\11\12\15\40-\176' >> "$OUTPUT_DIR/cleanup.log" &
nohup "$BASE_DIR/src/start_stream_logic.sh" "$CHANNEL" 2>&1 | tr -cd '\11\12\15\40-\176' >> "$OUTPUT_DIR/ffmpeg.log" &
