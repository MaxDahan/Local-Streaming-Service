#!/usr/bin/env bash
# Stops all on-demand streams and cleans their HLS segments.

# Determine project root (assumes script is in project root or src/)
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ON_DEMAND_DIR="$BASE_DIR/on_demand"

echo "🛑 Stopping on-demand sessions..."

for i in $(seq 1 5); do
    SESSION_DIR="$ON_DEMAND_DIR/$i"
    if [ ! -d "$SESSION_DIR" ]; then
        continue
    fi

    # Kill ffmpeg processes running in this session folder
    PIDS=$(ps aux | grep "[f]fmpeg" | grep "$SESSION_DIR" | awk '{print $2}')
    if [ -n "$PIDS" ]; then
        echo "Killing ffmpeg processes in $SESSION_DIR: $PIDS"
        kill -9 $PIDS
    else
        echo "No ffmpeg processes found in $SESSION_DIR"
    fi

    # Remove old HLS segments and playlists
    echo "Cleaning old .ts and .m3u8 files in $SESSION_DIR..."
    find "$SESSION_DIR" -type f \( -name '*.ts' -o -name '*.m3u8' \) -delete
done

echo "✅ On-demand sessions cleaned."
