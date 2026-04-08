# for running a stream in the background so it doesn't take up your terminal

if [ -z "$1" ]; then
  echo "Usage: $0 <channel>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHANNEL="$1"

mkdir -p "$BASE_DIR/channels/$CHANNEL/output"

nohup "$SCRIPT_DIR/cleanup.sh" "$CHANNEL" 2>&1 | tr -cd '\11\12\15\40-\176' >> "$BASE_DIR/channels/$CHANNEL/output/cleanup.log" &
nohup "$SCRIPT_DIR/start_stream_logic.sh" "$CHANNEL" 2>&1 | tr -cd '\11\12\15\40-\176' >> "$BASE_DIR/channels/$CHANNEL/output/ffmpeg.log" &
