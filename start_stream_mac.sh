# for running a stream in the background so it doesn't take up your terminal

CHANNEL="$1"

nohup ./cleanup.sh "$1" 2>&1 | tr -cd '\11\12\15\40-\176' >> "channels/$1/output/cleanup.log" &
nohup ./start_stream_logic.sh "$1" 2>&1 | tr -cd '\11\12\15\40-\176' >> "channels/$1/output/ffmpeg.log" &
