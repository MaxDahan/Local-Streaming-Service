#!/usr/bin/env bash
# cleanup.sh

if [ -z "$1" ]; then
  echo "Usage: $0 <channel_id>"
  exit 1
fi

CHANNEL="$1"

# Project root (one level up from src/)
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CHANNEL_DIR="$BASE_DIR/channels/$CHANNEL"
OUTPUT_DIR="$CHANNEL_DIR/output"
FFMPEG_LOG="$OUTPUT_DIR/ffmpeg.log"
CLEANUP_LOG="$OUTPUT_DIR/cleanup.log"

# Ensure output folder exists
mkdir -p "$OUTPUT_DIR"

# Start fresh: ensure main logs exist but do NOT truncate them
: > "$FFMPEG_LOG"
: > "$CLEANUP_LOG"

# Remove any previous rotated logs if you don’t want .gz files either
rm -f "${FFMPEG_LOG}".*.gz
rm -f "${CLEANUP_LOG}".*.gz

# Define on_demand session folders
ON_DEMAND_DIR="$BASE_DIR/on_demand"

echo "Starting cleanup in $OUTPUT_DIR and on_demand sessions..."

# Logrotate config relative to project root
LOGROTATE_CONF="$BASE_DIR/src/configurations/logrotate.conf"
LOGROTATE_STATE="/tmp/logrotate_channels.status"

while true; do
  sleep 60

  echo "$(date): Running logrotate..."
  # cd into BASE_DIR so relative paths in logrotate.conf work
  (cd "$BASE_DIR" && /usr/sbin/logrotate -s "$LOGROTATE_STATE" "$LOGROTATE_CONF")

  # Cleanup per-channel HLS segments older than 4 minutes
  echo "$(date): Cleaning up .ts files older than 4 minutes in $OUTPUT_DIR..."
  find "$OUTPUT_DIR" -name '*.ts' -type f -mmin +4 -print -delete

  # Cleanup on_demand session folders similarly
  for i in $(seq 1 5); do
    SESSION_DIR="$ON_DEMAND_DIR/$i"
    if [ -d "$SESSION_DIR" ]; then
      echo "$(date): Cleaning up old .ts files in $SESSION_DIR..."
      find "$SESSION_DIR" -name '*.ts' -type f -mmin +4 -print -delete
      # Remove any temporary subdirs if FFmpeg created them
      find "$SESSION_DIR" -mindepth 1 -type d -exec rm -rf {} +
    fi
  done
done
