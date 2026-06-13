# for running a stream in the background so it doesn't take up your terminal

if [ -z "$1" ]; then
  echo "Usage: $0 <channel>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHANNEL="$1"

mkdir -p "$BASE_DIR/channels/$CHANNEL/output"

# Use 'bash' explicitly to avoid nohup direct-exec permission issues
# (e.g. VS Code stripping execute bit on save, or AppArmor restrictions).
nohup bash "$SCRIPT_DIR/cleanup.sh" "$CHANNEL" >> "$BASE_DIR/channels/$CHANNEL/output/cleanup.log" 2>&1 &
nohup bash "$SCRIPT_DIR/start_stream_logic.sh" "$CHANNEL" >> "$BASE_DIR/channels/$CHANNEL/output/ffmpeg.log" 2>&1 &
