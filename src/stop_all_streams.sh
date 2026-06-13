#!/bin/bash

# File: stop_all_streams.sh

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANNELS_FILE="$(cd "$SRC_DIR/.." && pwd)/channels.json"

if [ ! -f "$CHANNELS_FILE" ]; then
  echo "❌ Cannot find $CHANNELS_FILE"
  exit 1
fi

echo "🛑 Stopping all channels listed in $CHANNELS_FILE..."

# Extract ALL channel IDs recursively and stop each
while read -r channel_id; do
  echo "🔻 Stopping stream for channel: $channel_id"
  "$SRC_DIR/stop_stream.sh" "$channel_id"
done < <(jq -r '.. | objects | select(.id? and .folders?) | .id' "$CHANNELS_FILE")

echo "✅ All channels attempted to stop."

