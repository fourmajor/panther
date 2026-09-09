# Panther CLI

The CLI uses your existing Panther account. You do not need an AWS account, AWS CLI, access keys,
or the repository's development setup. Python 3.11+ and Git are needed for installation.

## Install and sign in

With [pipx](https://pipx.pypa.io/stable/installation/) installed:

```sh
pipx install 'git+https://github.com/fourmajor/panther.git'
panther login --username other_stu
panther instructions
```

The password prompt is hidden. Use the same password as the website. Authenticator MFA and a
required initial password change are supported. Session tokens are saved in macOS Keychain,
Windows Credential Manager, or a supported Linux credential store, not a plaintext config file.
On Linux, enable/unlock Secret Service or KWallet first. There is deliberately no plaintext fallback.
Passwords are never saved. New sessions refresh automatically for up to **3,650 days (10 years)**,
the Cognito maximum. Refresh credentials rotate on use and the CLI saves replacements in the OS
credential store. Update older CLI installations (`pipx upgrade panther-journal`) before deployment
of rotation, then sign in once to obtain the longer lifetime; existing sessions keep their original
expiration. Revocation, account disablement, or removal of local credentials can end sign-in sooner.
`panther logout` removes local tokens and revokes the refresh token. Already issued
API tokens can remain valid until their expiry (up to one hour).

The web app remembers sign-in with a Secure, HttpOnly, SameSite cookie, renews automatically after
an hour or a browser restart, and keeps long-lived refresh credentials out of JavaScript storage.
The cookie is renewed for up to 400 days at each successful refresh, subject to browser limits;
it does not extend Cognito's original 10-year lifetime. Clearing cookies, private browsing, browser
eviction policies, long inactivity, or signing out can require another login. These are trusted-device
defaults: sign out on shared computers. Logout clears other open Panther tabs and revokes the
remembered session; if the network is down it stays locally signed out and offers a revocation retry.

These Panther sessions are separate from AWS deployment SSO. See the
[AWS runbook](aws-foundation-runbook.md#long-lived-sign-in-and-session-limits).

References: [Cognito refresh/rotation limits](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-refresh-token.html),
[browser cookie lifetime limits](https://developer.chrome.com/blog/cookie-max-age-expires).

For agents, read `panther instructions` before organizing or uploading assets. The full guide is
bundled with the installed CLI and available without logging in or accessing this repository.
It covers categories, extensible kinds, metadata, provenance, and ambiguity handling.

## Upload

Discover the game ID first:

```sh
panther ls
panther ls games/YOUR_GAME_ID/assets/
```

Then upload a file (replace placeholders with your actual paths and lowercase IDs):

```sh
panther upload /path/to/portrait.png --game YOUR_GAME_ID --asset captain-portrait --kind portrait
```

The file is private and appears in the web media library under:

```text
games/<game-id>/assets/<asset-id>/original/<filename>
```

Kinds are extensible: portraits, maps, documents, music, video, transcripts, stories, 3D models,
and additional kinds can all use this layout. The original uploaded bytes are retained; nothing
is compressed or transformed. `--asset` can be omitted to generate a unique ID.

For categorization and links, save a small JSON file **outside the source repository**:

```json
{
  "title": "Captain portrait",
  "category": "reference",
  "characterIds": ["captain"],
  "tags": ["crew", "portrait"],
  "extra": {"reviewStatus": "awaiting-dm-review"}
}
```

This is a synthetic example: use real, confirmed IDs and truthful metadata, not these placeholder
facts. Upload it with `--metadata /path/to/metadata.json`. Run `panther instructions` for the complete
schema, category definitions, and source-reference rules.

```sh
panther upload /path/to/portrait.png --game YOUR_GAME_ID --asset captain-portrait \
  --kind portrait --metadata /path/to/metadata.json --json
panther info games/YOUR_GAME_ID/assets/captain-portrait/original/portrait.png
```

`info` reports content type, size, kind, and metadata without exposing an access URL. `ls --json`
and `upload --json` support machine-readable output. All commands return a nonzero exit status on
failure. Data files and metadata stay out of Git. Metadata association does not yet create or update
character pages, session records, or media-library filters.

## Limits and troubleshooting

- One file per command, at most 1 GiB. Streaming uploads; no multipart/resume or folder command yet.
- Upload links expire after five minutes. Re-run for a fresh link if storage rejects an expired one.
- Existing files cannot be overwritten, even during concurrent uploads. For a revision, use a new
  asset ID or filename and link the prior object via `sourceKeys` in metadata.
- Integrity and byte length are enforced by S3. If the file changes while uploading, it is rejected.
- A connection failure can be ambiguous. Check `panther info` on the intended key before retrying.
- Metadata has a small size budget (about 1 KiB JSON). Upload long notes/provenance separately and
  reference their keys; extra fields belong inside the `extra` object.
- To update after new releases: `pipx upgrade panther-journal`. This is the legacy Python package
  name; the app and executable are both called Panther.

## Maintainer notes

CDK creates the dedicated public Cognito CLI client, adds its audience to the API authorizer,
publishes `/cli-config.json`, and adds the authenticated upload-signing route. The API signs a
single private `PutObject` with size, checksum, metadata, and `If-None-Match: *`. Its IAM write
permission is limited to `games/*/assets/*/original/*` with the conditional header. It cannot delete
assets or arbitrarily edit character profiles. The narrow model-selection operation below is supported.
No client AWS credentials or always-on resources are needed.
Object metadata is committed with the file, avoiding partially uploaded sidecar manifests.

## Publish a replacement character model

`panther character list` discovers character IDs. Inspect a character and its revision:

```sh
panther character show --game example-game --character captain
```

Upload the editable source, a separately optimized and browser-tested GLB (5 MiB maximum), and
optional provenance with `panther upload`, using fresh asset IDs/filenames. GLB files imported this
way live under `original/`, even though they were derived locally. Then publish explicitly:

```sh
panther character set-model --game example-game --character captain \
  --web-key games/example-game/assets/captain-v2/original/model.glb \
  --source-key games/example-game/assets/captain-v2/original/model.blend \
  --expected-revision '"REVISION_FROM_CHARACTER_SHOW"' \
  --reason 'Replace the prototype with the tested model'
```

The owner and DM can publish; other accounts cannot. The API validates same-game assets, file size,
content type, and GLB header, but does not establish visual quality. The portrait stays unchanged.
The previous profile is saved immutably under the character's `history/` prefix before a conditional
profile update. Old model files are never overwritten/deleted. The response includes the new
revision and `previousProfileKey`; actor, time, and reason are recorded on the profile. A concurrent
edit returns a conflict: re-inspect it, do not blindly retry. An uncertain network response also
requires inspection. A failed race may leave an unused history snapshot, which is safe to retain.

This is not yet general character editing, appearance timelines, or a history UI (issue #37).

Implementation reference: [AWS conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

The public configuration contains only public client/endpoint identifiers, never secrets. Do not
log signed URLs, passwords, or tokens. Credential operations and actual object uploads are runtime
application operations, not infrastructure bootstrap work.
