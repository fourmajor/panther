# Local, subscription-backed character models

AWS owns durable coordination, not inference. GitHub owns the generalized code, CDK, tests, and
modeling guidance. Private references, jobs, candidates, renders, and provenance never belong in Git.
This supersedes the paid-provider starting point in issue #35; full appearance timelines remain #37.

## Trigger and reference contract

Upload eight labeled PNG/JPEG/WebP views (up to 8 MiB each) through Panther. Use kind
`character-turnaround-view`; ordinary portraits, expression sheets, or unrelated images are not
automatically eligible. Prepare one private `character-turnaround` manifest and commit it with:

```sh
panther character show --game GAME_ID --character CHARACTER_ID
panther model references /private/path/turnaround.json
panther model jobs
panther model jobs --job-id JOB_ID
```

The manifest includes `kind`, `gameId`, `characterId`, `appearanceId`, `revisionId`,
`expectedRevision` (the exact quoted profile revision), and `views`. The eight view labels are
`front`, `front-right`, `right`, `back-right`, `back`, `back-left`, `left`, `front-left`.
Each maps to a distinct existing immutable Panther image key. The server checks type, size,
checksum, game, completeness, and current profile revision before committing anything.

The completed-set commit is the event trigger: no separate generation command is needed.
Individual image uploads deliberately do not trigger partial builds. Updated images require a
new complete set revision; immutable old images may be reused. Do not silently switch a job's
inputs while it runs. An identical submission returns its original job rather than running twice.
This first release supports the current profile's appearance only (`original` for legacy profiles).
It does not infer in-story transformations or implement the full appearance-selection UI.

## Coordination

The API atomically writes an immutable input snapshot/job and advances the character's latest
reference pointer in a retained, on-demand DynamoDB table. Its stream is a durable outbox that
starts a named Step Functions **Standard** execution. Duplicate stream deliveries are harmless.
The state machine invokes a callback task that queues the work and waits up to 30 days; it does
not execute a polling loop, Lambda renderer, or AI API call. Callback tokens stay in AWS and
are never given to the laptop or included in public job responses/logs.

The owner/DM can register references and inspect jobs. Only the CDK-configured owner worker
(configured privately at deployment) can claim jobs. Workers use Panther authentication, 10-minute exclusive leases,
and one-minute heartbeats. A stopped machine can reclaim expired work; checkpoints stay on disk.
Usage-limit pauses defer a job for at least an hour and do not consume its crash retry allowance.
Three crashed attempts fail the job. A set expires after 30 days waiting/running; deliberately
register a new revision to restart expired/failed work. No automatic cloud compute fallback.

## Laptop worker

Requirements: native Blender, Codex CLI signed in using ChatGPT, a current Panther CLI sign-in,
Docker Desktop, and a reviewed Panther checkout. Build the credential-free browser QA image:

The image includes the editorial stage contract used while synthesizing the viewer's security
policy. Its build must successfully collect the viewer tests before it is installed or pinned;
missing runtime inputs must fail image preparation rather than consume a character job's retries.

```sh
bash ops/model-worker/build-qa.sh
panther model worker --repo /absolute/trusted/panther \
  --work-dir /absolute/private/panther-model-jobs --once --allow-unsandboxed-blender
```

Without `--once`, the worker polls every five minutes while awake. Run only one worker per work
directory; an OS lock enforces this. A macOS LaunchAgent can run `--once` at five-minute intervals
after user login. The installer below provides this. Keep it separate from the GitHub Actions runner. A stopped/asleep laptop is
expected; AWS waits. Do not mount personal directories, AWS/Codex credentials, or the Docker socket
into browser QA. Only the private candidate directory is mounted; its tests have networking disabled.
Keep QA screenshots private, never upload them to GitHub Actions artifacts.

Browser QA must validate embedded texture loading, not just the model-viewer `loaded` flag.
A GLB can load successfully with white surfaces after CSP blocks its embedded image blobs.
The viewer tests compare declared base-color textures with loaded materials, check CSP/texture
errors, and verify colored pixels using an embedded-image synthetic fixture. Desktop exercises
ImageBitmap fetch; mobile exercises the HTML image fallback. Both `connect-src` and `img-src`
need local `blob:` permission; script policy stays unchanged. Inspect the private candidate's
desktop/mobile screenshots before claiming visual readiness. Rebuild/reinstall the pinned QA
image after changing these tests or the hosting policy.

The native execution flag is an explicit authorization gate, not a default sandbox bypass.
Blender 5.2.1 crashes during macOS GPU initialization inside Codex's sandbox. Codex therefore
writes a build script in its sandbox; the separately authorized worker runs that script in
native Blender outside the sandbox. Generated scripts have the macOS user's file access, so
run this only on trusted jobs under the owner's explicit authorization. Timeouts, a clean
environment, and dedicated work directories reduce mistakes but are not an OS security boundary.
Without that authorization the worker refuses to claim jobs. Codex itself remains sandboxed.

The worker uses `codex exec`, forces `forced_login_method=chatgpt` and the OpenAI provider, removes
API keys/AWS credentials/proxies from the child environment, ignores user configuration for the
agent run, and uses a workspace-write sandbox with shell networking disabled. It does not bypass
permissions. Credentials remain in the existing local Codex login. Blender runs on this machine;
OpenAI still performs inference remotely under the user's subscription. The CLI/runtime may need
user reauthentication when that login expires. Subscription capacity is shared with other work.
No reset redemption, credit purchase, other provider, or API-key fallback is authorized.

### Install the macOS background worker

After merging, deploying, and verifying CLI authentication, use clean `main` matching fetched
`origin/main`. This creates a fixed source snapshot and non-editable virtual environment in
`~/Library/Application Support/Panther/model-worker/releases/<commit>`, builds its QA image,
and pins the image by immutable ID. Working-tree edits and later image-tag changes do not
change a running release. No AWS credentials are used by the installed worker.

```sh
.venv/bin/python ops/model-worker/install.py --repo "$PWD" --allow-unsandboxed-blender --start
```

Omit `--start` to prepare without activating. Its plist stays in the private state directory,
outside macOS LaunchAgents, so it cannot auto-start at a later login. The user-scoped service is
`place.panther.model-worker`; it processes at most one job every five minutes while logged in
and awake. Docker must be running and Panther/Codex must be signed in. Missing prerequisites
fail before claiming work. Private logs and job checkpoints are under the state directory.
It neither wakes a sleeping computer nor runs an always-on cloud worker.

Inspect with `launchctl print gui/$(id -u)/place.panther.model-worker`. Stop with
`launchctl bootout gui/$(id -u)/place.panther.model-worker`; stopping during work lets its lease
expire for recovery. To upgrade, stop the old service, preserve its plist, and install reviewed
main again. The installer refuses to overwrite a differing service or incomplete release.
Old releases and logs are retained for explicit cleanup, not silently deleted.

## Candidate, checks, and publication

1. Download and checksum-verify the eight pinned references into a private job directory.
2. Codex writes a native Blender build script using the saved lessons. The authorized worker
   executes it locally. It saves editable source, scripts,
   modeling notes, and a self-contained GLB. Each agent stage is limited to 30 minutes.
3. Trusted code reopens the source with auto-execution disabled, fresh-imports the GLB, checks
   finite geometry/dimensions/embedded dependencies, enforces 200,000 triangles and 5 MiB, and
   renders the actual GLB from eight angles. Blender validation is limited to 15 minutes.
4. An isolated owned Docker environment runs the actual Panther viewer regression tests against
   this GLB at desktop/mobile sizes, including loading, rotation, reset, and failure fallback.
5. A separate subscription-backed Codex visual review compares the references and inspection
   renders. At most two candidates are tried; failed quality leaves the old model current.
6. Upload candidate files, inspection renders, evidence, and provenance through Panther. The broker
   verifies the evidence matches the candidate, locks reference advancement briefly, checks that
   this is still the latest job and the original profile revision, then publishes through the
   existing conditional model-selection logic. It preserves portrait, prior profile, and assets.

The quality judgment remains fallible. Successful rendering alone is not proof of likeness.
Input contradictions, structural failures, browser failures, or low visual quality stop publication.
No routine human approval gate is added. Profile conflicts produce a retained candidate, not an
automatic overwrite. Interrupted publication retries reconcile exact output keys before writing.

## Operations and cost

No EC2, NAT, provisioned database, hosted runner, or always-on inference service is introduced.
Costs are retained storage, API/queue activity, and state transitions. Laptop polling is usage,
not literally zero; stop the worker to eliminate idle polls. Step Functions waiting itself does
not add duration charges for Standard workflows. Retain referenced job/artwork history; do not
apply automatic asset expiry. Cloud resources are entirely CDK-managed in `us-west-2`.

Inspect job status through Panther, private worker logs/checkpoints for local failures, and AWS
deployment/stream health administratively. Stream records last 24 hours; persistent outbox
delivery failures require operator recovery, not blind creation of duplicate generation jobs.

Sources: [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
[Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference),
[Step Functions callback tasks](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html),
[Step Functions pricing](https://aws.amazon.com/step-functions/pricing/).
