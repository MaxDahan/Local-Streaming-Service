#!/bin/bash

OUTPUT_DIR="channels/$1/output"
FFMPEG_LOG="$OUTPUT_DIR/ffmpeg.log"
CLEANUP_LOG="$OUTPUT_DIR/cleanup.log"

# Start fresh: ensure main logs exist but do NOT truncate them
: > "$FFMPEG_LOG"
: > "$CLEANUP_LOG"

# Remove any previous rotated logs if you don’t want .gz files either
rm -f "${FFMPEG_LOG}".*.gz
rm -f "${CLEANUP_LOG}".*.gz

echo "Starting cleanup in $OUTPUT_DIR"

# Use neutral location for logrotate state file
LOGROTATE_CONF="/mnt/usb/Streaming/logrotate.conf"
LOGROTATE_STATE="/tmp/logrotate_channels.status"

while true; do
  sleep 60

  echo "$(date): Running logrotate..."
  /usr/sbin/logrotate -s "$LOGROTATE_STATE" "$LOGROTATE_CONF"

  echo "$(date): Cleaning up .ts files older than 4 minutes..."
  find "$OUTPUT_DIR" -name '*.ts' -type f -mmin +4 -print -delete
done
