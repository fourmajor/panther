# Publishing a session video for Discord

Discord (and similar clients) inline a link only when it points straight at an
`.mp4` file: H.264 video, AAC audio at 48 kHz, `-movflags +faststart`, and about
45 MB or smaller. Larger files often refuse to embed.

The catalog share system (`panther share create --confirm-public`) is still
worth creating: it is a revocable anyone-with-link record of the same asset,
with a watch page, a preview frame, and a download link. Its `/watch` URL is a
302 to a signed object and does not embed reliably, so **give Discord the
direct `/videos/` URL**, not the share URL. Treat share tokens as bearer
secrets; do not commit them or post them publicly.

`tools/publish-video.sh` is the repeatable form of this procedure.

## 1. Prepare the file

Check the source with `ffprobe`. If it is already H.264, AAC at 48 kHz,
faststart, and under the size cap, remux with `+faststart` only. Otherwise do a
two-pass H.264 encode at the **same resolution and frame rate**, with the video
bitrate chosen to fit the cap (a 5% margin leaves room for mux overhead). For
90 s at 1080p30 and a 45 MB cap, that is about 3800 kb/s video plus 192 kb/s
AAC. Never overwrite the original.

Extract a poster JPEG from a representative frame (a title card a few seconds
in works well).

```sh
tools/publish-video.sh encode INPUT.mp4 /tmp/out.mp4 --max-mb 45
tools/publish-video.sh poster /tmp/out.mp4 /tmp/out.jpg 3
```

## 2. Catalog the asset and create a share

Upload the encoded file and the poster, then create an anyone-with-link share.
The poster must be a frame of this exact video version (`video-preview`), as in
[asset sharing](asset-sharing.md).

```sh
panther upload /tmp/out.mp4 --game GAME --asset SLUG --kind video
panther upload /tmp/out.jpg --game GAME --asset SLUG-preview --kind video-preview
panther share create VIDEO_KEY --preview-key PREVIEW_KEY --confirm-public
```

Save the share URL somewhere outside Git so it can be revoked. Do not put that
URL in Discord.

## 3. Copy three files to the site origin under `/videos/`

Publish only the `.mp4`, the poster `.jpg`, and a small HTML watch page with
`og:video`, `og:video:type` `video/mp4`, width and height, `og:image` set to
the poster, and a `<video>` tag. Public URLs are:

- `https://panther.place/videos/SLUG.mp4`
- `https://panther.place/videos/SLUG.jpg`
- `https://panther.place/videos/SLUG.html`

The destination is the `SiteBucket` of the `PantherMediaExplorer` stack, in
front of the stack's CloudFront distribution (the same origin the site deploy
already uses). Resolve those physical IDs from the stack at publish time, or
from `PANTHER_SITE_BUCKET` and `PANTHER_DISTRIBUTION_ID`. Do not hardcode
bucket names, and do not write to the private assets bucket.

Site deploys use `prune: false`, so objects under `/videos/` survive an
ordinary website release. Set `Content-Type` (`video/mp4`, `image/jpeg`,
`text/html`) when uploading. After a replace, invalidate the three CloudFront
paths.

## 4. Verify from outside AWS

Do not use a signed URL, an S3 website endpoint, or a path that only works
inside AWS. Against the public `https://panther.place/videos/SLUG.mp4` URL:

- `HEAD` returns 200, `Content-Type: video/mp4`, `Content-Length`, and
  `Accept-Ranges: bytes`.
- A ranged `GET` (`Range: bytes=0-15`) returns 206 and a valid MP4 header
  (`ftyp`).

```sh
tools/publish-video.sh verify https://panther.place/videos/SLUG.mp4
```

## One-shot publish and takedown

```sh
tools/publish-video.sh publish INPUT.mp4 --slug SLUG --title "Title" --game GAME
tools/publish-video.sh unpublish --slug SLUG
```

`publish` encodes if needed, writes the poster and page, optionally uploads to
the catalog and creates a share (when `--game` is set; the share JSON is saved
next to the working files and is not printed), copies the three objects, and
verifies the public `.mp4`.

`panther share revoke` does **not** remove `/videos/` files. Taking a published
video down means deleting those site-bucket objects and invalidating CloudFront
(`unpublish`). Revoke the catalog share separately if one was created.

## Where to run it

Encode and publish from Kiwi, or any machine that already has AWS and Panther
credentials. Kiwi is a 14 GiB household server shared with Home Assistant and
the existing `panther.slice` workers, so keep ffmpeg and pipeline jobs under a
memory cap and do not raise those worker limits. Use a Mac only for
capabilities only it has.
