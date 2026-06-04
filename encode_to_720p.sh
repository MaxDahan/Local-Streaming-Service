#!/bin/bash
# encode_to_720p.sh
# Converts all videos in media/raw/ recursively to H.264 + AAC 720p for streaming.
# Mirrors the folder structure into media/converted/.
#
# All output files share identical stream properties so FFmpeg concat works seamlessly:
#   codec:  h264 (yuv420p)
#   audio:  aac 128k stereo 48000Hz
#   timescale: 1/15360  ← critical for DTS continuity across concat boundaries

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
RAW_DIR="$BASE_DIR/media/raw"
CONFIG_FILE="$BASE_DIR/src/configurations/config.json"
CONVERTED_DIR="$(jq -r 'if (.media_roots | type) == "array" and (.media_roots | length) > 0 then .media_roots[0] elif .media_root and .media_root != "null" then .media_root else empty end' "$CONFIG_FILE" 2>/dev/null)"
if [ -z "$CONVERTED_DIR" ] || [ "$CONVERTED_DIR" = "null" ]; then
  CONVERTED_DIR="$BASE_DIR/media/converted"
fi
if [[ "$CONVERTED_DIR" != /* ]]; then
  CONVERTED_DIR="$BASE_DIR/$CONVERTED_DIR"
fi
LOG_FILE="$BASE_DIR/output/encode.log"

# Encoding settings — must stay in sync with stream output format
TARGET_RESOLUTION="720"
TARGET_TIMESCALE="15360"   # matches HLS stream timescale; do not change
TARGET_FRAMERATE="30"
AUDIO_BITRATE="128k"
AUDIO_SAMPLE_RATE="48000"
PARALLEL_JOBS=2            # lower to 1 if USB drive stutters

mkdir -p "$BASE_DIR/output"
export RAW_DIR CONVERTED_DIR TARGET_RESOLUTION TARGET_TIMESCALE TARGET_FRAMERATE AUDIO_BITRATE AUDIO_SAMPLE_RATE LOG_FILE

process_file() {
    input="$1"
    rel_path="${input#$RAW_DIR/}"
    rel_dir="$(dirname "$rel_path")"
    output_folder="$CONVERTED_DIR/$rel_dir"
    mkdir -p "$output_folder"

    filename="$(basename "$input")"
    basename_no_ext="${filename%.*}"
    output="$output_folder/${basename_no_ext}.mp4"

    if [ -f "$output" ]; then
        echo "⏩ Skipping (already converted): $rel_path"
        return 0
    fi

    # Probe source
    vcodec=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 "$input" 2>/dev/null)
    acodec=$(ffprobe -v quiet -select_streams a:0 -show_entries stream=codec_name -of csv=p=0 "$input" 2>/dev/null)
    height=$(ffprobe -v quiet -select_streams v:0 -show_entries stream=height -of csv=p=0 "$input" 2>/dev/null)
    a_rate=$(ffprobe -v quiet -select_streams a:0 -show_entries stream=sample_rate -of csv=p=0 "$input" 2>/dev/null)

    # Determine if video and audio are already stream-copy compatible
    local video_ok=false audio_ok=false video_kf_ok=false
    [[ "$vcodec" == "h264" && "${height:-0}" -le "$TARGET_RESOLUTION" ]] && video_ok=true
    [[ "$acodec" == "aac" && "$a_rate" == "$AUDIO_SAMPLE_RATE" ]] && audio_ok=true

    # Check keyframe interval: must be ≤ hls_time (6s) so HLS can segment cleanly.
    # A large GOP (e.g. libx264 default 250 frames ≈ 8–10s) causes the player to
    # stall every segment boundary when using -c:v copy in the stream.
    if $video_ok; then
        local kf_max
        kf_max=$(ffprobe -v quiet -read_intervals "%+60" -select_streams v:0 \
            -show_frames -skip_frame noref -show_entries frame=pict_type,pts_time \
            -of default "$input" 2>/dev/null \
            | awk '/pts_time/{t=substr($0,10)+0} /pict_type=I/ && prev!=""{d=t-prev; if(d>max)max=d} /pict_type=I/{prev=t} END{printf "%.2f", max+0}')
        if [[ -n "$kf_max" ]] && (( $(echo "$kf_max <= 6.5" | bc -l) )); then
            video_kf_ok=true
        else
            echo "   ⚠️  Keyframe interval ${kf_max}s > 6s — video will be re-encoded to fix GOP"
        fi
    fi

    local tmp="${output}.tmp.mp4"

    if $video_ok && $video_kf_ok && $audio_ok; then
        # Video and audio are already compatible — remux only, normalizing timescale
        echo "⚡ Remuxing (h264+aac @ ${height}p): $rel_path"
        ffmpeg -y -nostdin -i "$input" \
            -c:v copy \
            -video_track_timescale "$TARGET_TIMESCALE" \
            -c:a copy \
            -map 0:v:0 -map 0:a:0? \
            -movflags +faststart \
            -map_metadata 0 \
            "$tmp" 2>>"$LOG_FILE"

    elif $video_ok && $video_kf_ok && ! $audio_ok; then
        # Video fine, audio needs re-encode (wrong codec or sample rate)
        echo "⚡ Remux video + re-encode audio (${acodec} ${a_rate}Hz → aac ${AUDIO_SAMPLE_RATE}Hz): $rel_path"
        ffmpeg -y -nostdin -i "$input" \
            -c:v copy \
            -video_track_timescale "$TARGET_TIMESCALE" \
            -c:a aac -b:a "$AUDIO_BITRATE" -ac 2 -ar "$AUDIO_SAMPLE_RATE" \
            -map 0:v:0 -map 0:a:0? \
            -movflags +faststart \
            -map_metadata 0 \
            "$tmp" 2>>"$LOG_FILE"

    elif $video_ok && ! $video_kf_ok; then
        # Video codec/size is fine but keyframe interval is too large — re-encode video
        # to fix GOP while preserving quality. Audio copied if already compatible.
        local audio_flags
        if $audio_ok; then
            audio_flags="-c:a copy"
        else
            audio_flags="-c:a aac -b:a ${AUDIO_BITRATE} -ac 2 -ar ${AUDIO_SAMPLE_RATE}"
        fi
        echo "🔑 Re-encoding video (GOP fix, ${acodec} ${a_rate}Hz audio ${audio_flags}): $rel_path"
        ffmpeg -y -nostdin -i "$input" \
            -map 0:v:0 -map 0:a:0? \
            -c:v libx264 -preset veryfast -crf 23 \
            -g 48 -keyint_min 48 -sc_threshold 0 \
            -pix_fmt yuv420p \
            -video_track_timescale "$TARGET_TIMESCALE" \
            $audio_flags \
            -movflags +faststart \
            -map_metadata 0 \
            "$tmp" 2>>"$LOG_FILE"

    else
        # Full re-encode needed (wrong video codec or oversized)
        echo "🔹 Encoding (${vcodec}/${acodec} @ ${height:-?}p → h264/aac @ ${TARGET_RESOLUTION}p): $rel_path"
        ffmpeg -y -nostdin -i "$input" \
            -vf "scale=-2:${TARGET_RESOLUTION}:flags=lanczos,fps=${TARGET_FRAMERATE}" \
            -map 0:v:0 -map 0:a:0? \
            -c:v libx264 -preset veryfast -crf 23 \
            -g 48 -keyint_min 48 -sc_threshold 0 \
            -pix_fmt yuv420p \
            -video_track_timescale "$TARGET_TIMESCALE" \
            -c:a aac -b:a "$AUDIO_BITRATE" -ac 2 -ar "$AUDIO_SAMPLE_RATE" \
            -movflags +faststart \
            -map_metadata 0 \
            "$tmp" 2>>"$LOG_FILE"
    fi

    if [ $? -eq 0 ] && [ -s "$tmp" ]; then
        mv "$tmp" "$output"
        echo "✅ Done: $rel_path"
    else
        rm -f "$tmp"
        echo "❌ Failed: $rel_path  (see $LOG_FILE)"
        return 1
    fi
}

export -f process_file

echo "📼 Encoding from '$RAW_DIR' → '$CONVERTED_DIR' (${PARALLEL_JOBS} parallel jobs)"
echo "   Log: $LOG_FILE"

find "$RAW_DIR" -type f \
    \( -iname "*.mp4" -o -iname "*.mkv" -o -iname "*.avi" \
       -o -iname "*.mov" -o -iname "*.wmv" -o -iname "*.flv" \
       -o -iname "*.m4v" -o -iname "*.ts"  -o -iname "*.webm" \) \
    ! -name ".*" -print0 \
    | xargs -0 -P "$PARALLEL_JOBS" -I{} bash -c 'process_file "$@"' _ {}

echo "🎉 All files processed!"
