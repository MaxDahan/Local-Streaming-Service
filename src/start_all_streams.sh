#!/bin/bash

# Absolute path to project root
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"

CHANNELS_FILE="$BASE_DIR/channels.json"

if [ ! -f "$CHANNELS_FILE" ]; then
  echo "❌ Cannot find $CHANNELS_FILE"
  exit 1
fi

echo "Starting all channels listed in $CHANNELS_FILE..."

# Extract "id" fields and loop over them
jq -r '.[].id' "$CHANNELS_FILE" | while read -r channel_id; do
  echo "🔻 Starting stream for channel: $channel_id"
  "$BASE_DIR/src/start_stream.sh" "$channel_id"
done

echo "✅ All channels attempted to start."
