#!/bin/bash

# File: stop_all_streams.sh

CHANNELS_FILE="channels.json"

if [ ! -f "$CHANNELS_FILE" ]; then
  echo "❌ Cannot find $CHANNELS_FILE"
  exit 1
fi

echo "🛑 Stopping all channels listed in $CHANNELS_FILE..."

# Extract "id" fields and loop over them
jq -r '.[].id' "$CHANNELS_FILE" | while read -r channel_id; do
  echo "🔻 Stopping stream for channel: $channel_id"
  ./stop_stream.sh "$channel_id"
done

echo "✅ All channels attempted to stop."

