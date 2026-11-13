#!/usr/bin/env bash
# Prepare and publish a session video so Discord (and similar clients) can inline it.
#
# Discord plays a link only when it points at a direct .mp4 (H.264, AAC 48 kHz,
# +faststart, about 45 MB or smaller). The catalog share's /watch URL is a 302
# to a signed object and does not embed reliably, so this also copies the file,
# a poster, and a small og:video page to the site origin under /videos/.
#
# Site bucket and CloudFront IDs are resolved from the PantherMediaExplorer
# stack (or PANTHER_SITE_BUCKET / PANTHER_DISTRIBUTION_ID). Physical bucket
# names are not hardcoded. This script never touches the private assets bucket,
# DNS, or anything outside videos/<slug>.{mp4,jpg,html}.
#
# Usage:
#   tools/publish-video.sh encode  INPUT.mp4 OUTPUT.mp4 [--max-mb 45]
#   tools/publish-video.sh poster  INPUT.mp4 OUTPUT.jpg [TIME]
#   tools/publish-video.sh page    --title T --mp4-url U --poster-url P --width W --height H
#   tools/publish-video.sh verify  https://panther.place/videos/name.mp4
#   tools/publish-video.sh publish INPUT.mp4 --slug name [--title T] [--poster-time 3]
#                                  [--game GAME --asset ID] [--max-mb 45]
#                                  [--skip-catalog] [--out-dir DIR]
#   tools/publish-video.sh unpublish --slug name
#   tools/publish-video.sh self-test
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DOMAIN="${PANTHER_SITE_DOMAIN:-panther.place}"
STACK="${PANTHER_SITE_STACK:-PantherMediaExplorer}"
MAX_MB_DEFAULT=45
AUDIO_K=192
# Leave a little room under the cap so mux overhead does not push a 90 s
# 1080p30 encode over ~45 MB. 95% of 45 MB at 90 s is about 3800k video.
SAFETY=0.95

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \?//'
  exit 2
}

die() { echo "publish-video: $*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "missing $1"
}

same_path() {
  python3 -c 'import os,sys; raise SystemExit(os.path.samefile(sys.argv[1], sys.argv[2]) if os.path.exists(sys.argv[2]) else 0)' "$1" "$2"
}

slug_ok() {
  python3 -c 'import re,sys; s=sys.argv[1]; raise SystemExit(0 if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", s) and len(s)<=80 else 1)' "$1"
}

video_bitrate_k() {
  # args: duration_seconds max_mb
  python3 -c '
import math, sys
duration, max_mb, audio_k, safety = map(float, sys.argv[1:])
if duration <= 0:
    raise SystemExit("duration must be positive")
bits = max_mb * 1024 * 1024 * 8 * safety
video = bits / duration - audio_k * 1000
if video < 200_000:
    raise SystemExit("duration is too long for the size cap")
print(int(math.floor(video / 1000)))
' "$1" "$2" "$AUDIO_K" "$SAFETY"
}

probe() {
  need ffprobe
  ffprobe -v error -show_entries stream=codec_type,codec_name,sample_rate,width,height,r_frame_rate:format=duration,size \
    -of json "$1"
}

probe_field() {
  python3 -c '
import json,sys
data=json.load(sys.stdin)
want=sys.argv[1]
if want=="duration":
    print(float(data["format"]["duration"]))
elif want=="size":
    print(int(data["format"]["size"]))
elif want in ("width","height"):
    for s in data["streams"]:
        if s.get("codec_type")=="video" and s.get(want):
            print(int(s[want])); break
    else:
        raise SystemExit(f"no video {want}")
elif want=="video_codec":
    print(next(s["codec_name"] for s in data["streams"] if s.get("codec_type")=="video"))
elif want=="audio_codec":
    print(next((s["codec_name"] for s in data["streams"] if s.get("codec_type")=="audio"), ""))
elif want=="sample_rate":
    print(next((int(s.get("sample_rate") or 0) for s in data["streams"] if s.get("codec_type")=="audio"), 0))
' "$1" <<< "$2"
}

# True when the first movie box is moov (faststart), not mdat.
has_faststart() {
  python3 -c '
import sys
path=sys.argv[1]
with open(path,"rb") as f:
    while True:
        hdr=f.read(8)
        if len(hdr)<8:
            raise SystemExit(1)
        size=int.from_bytes(hdr[:4],"big")
        tag=hdr[4:8]
        if tag==b"mdat":
            raise SystemExit(1)
        if tag==b"moov":
            raise SystemExit(0)
        if size==0:
            raise SystemExit(1)
        if size==1:
            ext=f.read(8)
            size=int.from_bytes(ext,"big")
            f.seek(size-16,1)
        else:
            f.seek(size-8,1)
' "$1"
}

compliant() {
  local info codec audio rate size max_mb
  info=$(probe "$1")
  codec=$(probe_field video_codec "$info")
  audio=$(probe_field audio_codec "$info")
  rate=$(probe_field sample_rate "$info")
  size=$(probe_field size "$info")
  max_mb=${2:-$MAX_MB_DEFAULT}
  python3 -c '
import sys
codec, audio, rate, size, max_mb = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), float(sys.argv[5])
ok = codec in ("h264", "avc1") and audio == "aac" and rate == 48000 and size <= max_mb * 1024 * 1024
raise SystemExit(0 if ok else 1)
' "$codec" "$audio" "$rate" "$size" "$max_mb" && has_faststart "$1"
}

cmd_encode() {
  local src out max_mb= info dur vbitrate tmp
  src=${1:-}; out=${2:-}; shift 2 || usage
  max_mb=$MAX_MB_DEFAULT
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --max-mb) max_mb=$2; shift 2 ;;
      *) usage ;;
    esac
  done
  [[ -n "$src" && -n "$out" ]] || usage
  [[ -f "$src" ]] || die "no such file: $src"
  if [[ -e "$out" ]] && same_path "$src" "$out"; then
    die "refusing to overwrite the input; pass a different output path"
  fi
  need ffmpeg
  mkdir -p "$(dirname -- "$out")"
  if compliant "$src" "$max_mb"; then
    echo "already Discord-ready; remuxing with +faststart to $out"
    ffmpeg -hide_banner -y -i "$src" -c copy -movflags +faststart "$out"
    return
  fi
  info=$(probe "$src")
  dur=$(probe_field duration "$info")
  vbitrate=$(video_bitrate_k "$dur" "$max_mb")
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' RETURN
  echo "two-pass H.264 at ${vbitrate}k + ${AUDIO_K}k AAC 48 kHz, +faststart"
  # Keep the source resolution and frame rate. Never overwrite $src.
  ffmpeg -hide_banner -y -i "$src" -c:v libx264 -b:v "${vbitrate}k" -pix_fmt yuv420p \
    -pass 1 -passlogfile "$tmp/ff" -an -f mp4 /dev/null
  ffmpeg -hide_banner -y -i "$src" -c:v libx264 -b:v "${vbitrate}k" -pix_fmt yuv420p \
    -pass 2 -passlogfile "$tmp/ff" -c:a aac -ar 48000 -ac 2 -b:a "${AUDIO_K}k" \
    -movflags +faststart "$out"
  has_faststart "$out" || die "output is missing +faststart"
  local size
  size=$(probe_field size "$(probe "$out")")
  python3 -c '
import sys
size, max_mb = int(sys.argv[1]), float(sys.argv[2])
if size > max_mb * 1024 * 1024:
    raise SystemExit(f"output is {size} bytes, over the {max_mb} MB cap")
' "$size" "$max_mb"
}

cmd_poster() {
  local src out time=${3:-3}
  src=${1:-}; out=${2:-}
  [[ -n "$src" && -n "$out" ]] || usage
  [[ -f "$src" ]] || die "no such file: $src"
  if [[ -e "$out" ]] && same_path "$src" "$out"; then
    die "refusing to overwrite the input"
  fi
  need ffmpeg
  mkdir -p "$(dirname -- "$out")"
  ffmpeg -hide_banner -y -ss "$time" -i "$src" -frames:v 1 -q:v 2 "$out"
}

cmd_page() {
  local title="" mp4="" poster="" width="" height=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --title) title=$2; shift 2 ;;
      --mp4-url) mp4=$2; shift 2 ;;
      --poster-url) poster=$2; shift 2 ;;
      --width) width=$2; shift 2 ;;
      --height) height=$2; shift 2 ;;
      *) usage ;;
    esac
  done
  [[ -n "$title" && -n "$mp4" && -n "$poster" && -n "$width" && -n "$height" ]] || usage
  python3 -c '
import html, sys
title, mp4, poster, width, height = sys.argv[1:]
t, m, p = html.escape(title, quote=True), html.escape(mp4, quote=True), html.escape(poster, quote=True)
sys.stdout.write(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<meta property="og:type" content="video.other">
<meta property="og:title" content="{t}">
<meta property="og:image" content="{p}">
<meta property="og:video" content="{m}">
<meta property="og:video:secure_url" content="{m}">
<meta property="og:video:type" content="video/mp4">
<meta property="og:video:width" content="{width}">
<meta property="og:video:height" content="{height}">
</head>
<body>
<video controls preload="metadata" width="{width}" height="{height}" poster="{p}">
<source src="{m}" type="video/mp4">
</video>
</body>
</html>
""".format(t=t, m=m, p=p, width=int(width), height=int(height)))
' "$title" "$mp4" "$poster" "$width" "$height"
}

cmd_verify() {
  local url=${1:-}
  [[ -n "$url" ]] || usage
  need curl
  case "$url" in
    https://*) ;;
    *) die "verify the public https://$DOMAIN URL, not an internal or signed URL" ;;
  esac
  local hdr body
  hdr=$(mktemp)
  body=$(mktemp)
  trap 'rm -f "$hdr" "$body"' RETURN
  curl -sS -D "$hdr" -o /dev/null --max-time 30 -I "$url" || die "HEAD failed"
  python3 -c '
import sys
text=open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
# follow the last status in case of HTTP/2 or redirects we refused; we want 200
statuses=[l for l in text if l.lower().startswith("http/")]
if not statuses or not statuses[-1].split()[1].startswith("200"):
    raise SystemExit("HEAD expected 200, got: " + (statuses[-1] if statuses else "no status"))
headers={k.lower(): v.strip() for k,v in (l.split(":",1) for l in text if ":" in l)}
ctype=headers.get("content-type","").split(";")[0].strip().lower()
if ctype!="video/mp4":
    raise SystemExit(f"Content-Type should be video/mp4, got {ctype!r}")
if "accept-ranges" not in headers or "bytes" not in headers["accept-ranges"].lower():
    raise SystemExit("missing Accept-Ranges: bytes")
if int(headers.get("content-length","0") or 0) <= 16:
    raise SystemExit("missing or tiny Content-Length")
' "$hdr"
  curl -sS -D "$hdr" -o "$body" --max-time 30 -H "Range: bytes=0-15" "$url" || die "ranged GET failed"
  python3 -c '
import sys
text=open(sys.argv[1], encoding="utf-8", errors="replace").read().splitlines()
statuses=[l for l in text if l.lower().startswith("http/")]
if not statuses or not statuses[-1].split()[1].startswith("206"):
    raise SystemExit("ranged GET expected 206, got: " + (statuses[-1] if statuses else "no status"))
data=open(sys.argv[2],"rb").read()
if b"ftyp" not in data:
    raise SystemExit("ranged body does not look like an MP4 header")
' "$hdr" "$body"
  echo "ok: $url (HEAD 200 video/mp4 Accept-Ranges, GET 206)"
}

aws_cmd() {
  need aws
  aws "$@"
}

resolve_site() {
  if [[ -n "${PANTHER_SITE_BUCKET:-}" && -n "${PANTHER_DISTRIBUTION_ID:-}" ]]; then
    return
  fi
  local resources
  resources=$(aws_cmd cloudformation describe-stack-resources --stack-name "$STACK" --output json)
  eval "$(python3 -c '
import json,sys
data=json.load(sys.stdin)
bucket=dist=None
for r in data["StackResources"]:
    lid, typ, pid = r["LogicalResourceId"], r["ResourceType"], r["PhysicalResourceId"]
    if typ=="AWS::S3::Bucket" and "SiteBucket" in lid:
        bucket=pid
    elif typ=="AWS::CloudFront::Distribution" and "Distribution" in lid:
        dist=pid
if not bucket or not dist:
    raise SystemExit("could not resolve SiteBucket and Distribution from "+sys.argv[1])
# Export names only; do not print them here.
print("PANTHER_SITE_BUCKET="+json.dumps(bucket))
print("PANTHER_DISTRIBUTION_ID="+json.dumps(dist))
' "$STACK" <<< "$resources")"
  export PANTHER_SITE_BUCKET PANTHER_DISTRIBUTION_ID
}

put_object() {
  local file=$1 key=$2 type=$3
  aws_cmd s3api put-object \
    --bucket "$PANTHER_SITE_BUCKET" \
    --key "$key" \
    --body "$file" \
    --content-type "$type" \
    --cache-control "public, max-age=31536000, immutable" >/dev/null
}

invalidate() {
  aws_cmd cloudfront create-invalidation \
    --distribution-id "$PANTHER_DISTRIBUTION_ID" \
    --paths "$@" >/dev/null
}

cmd_publish() {
  local src="" slug="" title="" poster_time=3 max_mb=$MAX_MB_DEFAULT game="" asset="" skip_catalog=0 out_dir=""
  src=${1:-}; shift || usage
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --slug) slug=$2; shift 2 ;;
      --title) title=$2; shift 2 ;;
      --poster-time) poster_time=$2; shift 2 ;;
      --max-mb) max_mb=$2; shift 2 ;;
      --game) game=$2; shift 2 ;;
      --asset) asset=$2; shift 2 ;;
      --skip-catalog) skip_catalog=1; shift ;;
      --out-dir) out_dir=$2; shift 2 ;;
      *) usage ;;
    esac
  done
  [[ -n "$src" && -n "$slug" ]] || usage
  slug_ok "$slug" || die "slug must be lowercase letters, digits, and internal hyphens"
  [[ -f "$src" ]] || die "no such file: $src"
  title=${title:-$slug}
  out_dir=${out_dir:-$(mktemp -d)}
  mkdir -p "$out_dir"
  local mp4="$out_dir/$slug.mp4" poster="$out_dir/$slug.jpg" page="$out_dir/$slug.html"
  cmd_encode "$src" "$mp4" --max-mb "$max_mb"
  cmd_poster "$mp4" "$poster" "$poster_time"
  local info width height
  info=$(probe "$mp4")
  width=$(probe_field width "$info")
  height=$(probe_field height "$info")
  local public="https://$DOMAIN/videos/$slug"
  cmd_page --title "$title" --mp4-url "$public.mp4" --poster-url "$public.jpg" \
    --width "$width" --height "$height" > "$page"

  if [[ "$skip_catalog" -eq 0 && -n "$game" ]]; then
    need panther
    local video_key preview_key share_file
    asset=${asset:-$slug}
    echo "uploading catalog video and preview (share token will be saved, not printed)"
    video_key=$(panther upload "$mp4" --game "$game" --asset "$asset" --kind video --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')
    preview_key=$(panther upload "$poster" --game "$game" --asset "${asset}-preview" --kind video-preview --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')
    share_file="$out_dir/share.json"
    umask 077
    panther share create "$video_key" --preview-key "$preview_key" --confirm-public > "$share_file"
    chmod 600 "$share_file"
    echo "catalog share written to $share_file (bearer secret; Discord should use the /videos/ URL)"
  elif [[ "$skip_catalog" -eq 0 ]]; then
    echo "skipping catalog share (pass --game GAME, or --skip-catalog)" >&2
  fi

  resolve_site
  put_object "$mp4" "videos/$slug.mp4" "video/mp4"
  put_object "$poster" "videos/$slug.jpg" "image/jpeg"
  put_object "$page" "videos/$slug.html" "text/html; charset=utf-8"
  invalidate "/videos/$slug.mp4" "/videos/$slug.jpg" "/videos/$slug.html"
  echo "published $public.mp4"
  # Give CloudFront a moment only if verify fails; try immediately first.
  if ! cmd_verify "$public.mp4"; then
    echo "verify did not succeed immediately; retrying after 15s" >&2
    sleep 15
    cmd_verify "$public.mp4"
  fi
  echo "poster $public.jpg"
  echo "page   $public.html"
  echo "Give Discord the .mp4 URL. panther share revoke does not remove /videos/ files; use unpublish."
}

cmd_unpublish() {
  local slug=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --slug) slug=$2; shift 2 ;;
      *) usage ;;
    esac
  done
  [[ -n "$slug" ]] || usage
  slug_ok "$slug" || die "slug must be lowercase letters, digits, and internal hyphens"
  resolve_site
  aws_cmd s3api delete-objects --bucket "$PANTHER_SITE_BUCKET" --delete "$(python3 -c '
import json,sys
s=sys.argv[1]
print(json.dumps({"Objects":[{"Key":f"videos/{s}.{ext}"} for ext in ("mp4","jpg","html")],"Quiet":True}))
' "$slug")" >/dev/null
  invalidate "/videos/$slug.mp4" "/videos/$slug.jpg" "/videos/$slug.html"
  echo "removed /videos/$slug.{mp4,jpg,html} and invalidated CloudFront"
  echo "If a catalog share was created, revoke it separately with panther share revoke."
}

cmd_self_test() {
  local k
  k=$(video_bitrate_k 90 45)
  python3 -c '
import sys
k=int(sys.argv[1])
# Documented working point: 90 s 1080p30 under ~45 MB is about 3800k video.
if not (3700 <= k <= 3900):
    raise SystemExit(f"expected ~3800k for 90s/45MB, got {k}k")
print(f"bitrate ok: 90s @ 45MB -> {k}k")
' "$k"
  local page
  page=$(cmd_page --title 'Test "Title"' --mp4-url "https://$DOMAIN/videos/example.mp4" \
    --poster-url "https://$DOMAIN/videos/example.jpg" --width 1920 --height 1080)
  python3 -c '
import sys
page=sys.argv[1]
for needle in (
    "og:video", "og:video:type", "video/mp4", "og:image",
    "og:video:width", "1920", "og:video:height", "1080",
    "<video", "source src=",
    "https://panther.place/videos/example.mp4",
    "https://panther.place/videos/example.jpg",
    "Test &quot;Title&quot;",
):
    if needle not in page:
        raise SystemExit("page missing "+needle)
print("page ok")
' "$page"
  slug_ok "session-recap" && ! slug_ok "../etc" && ! slug_ok "Has Space" && ! slug_ok ""
  echo "slug ok"
  echo "self-test passed"
}

cmd=${1:-}
shift || usage
case "$cmd" in
  encode) cmd_encode "$@" ;;
  poster) cmd_poster "$@" ;;
  page) cmd_page "$@" ;;
  verify) cmd_verify "$@" ;;
  publish) cmd_publish "$@" ;;
  unpublish) cmd_unpublish "$@" ;;
  self-test) cmd_self_test ;;
  -h|--help|help) usage ;;
  *) usage ;;
esac
