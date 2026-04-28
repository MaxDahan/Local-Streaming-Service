#!/bin/bash

# File: start_all_streams.sh

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANNELS_FILE="$(cd "$SRC_DIR/.." && pwd)/channels.json"

if [ ! -f "$CHANNELS_FILE" ]; then
  echo "❌ Cannot find $CHANNELS_FILE"
  exit 1
fi

echo "Starting all channels listed in $CHANNELS_FILE..."

# Extract only non-virtual channel IDs recursively
jq -r '.. | objects | select(.id? and .folders? and (.virtual? | not)) | .id' "$CHANNELS_FILE" | while read -r channel_id; do
  echo "🔻 Starting stream for channel: $channel_id"
  "$SRC_DIR/start_stream.sh" "$channel_id"
done

echo "✅ All channels attempted to start."

