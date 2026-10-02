# Map, blueprint and location images

The Assets workspace offers upload and generation for three explicit image types:
`map`, `blueprint` and `location`. A map is a top-down illustrated geographic map;
a blueprint is a floor plan; a location is an environment illustration. The worker
never substitutes a procedural diagram for a requested illustration.

`POST /asset-generation` accepts `{gameId,type,name,prompt,operationId}`. Its version 1
request records a persisted `QUEUED` job. Repeating the same operation returns the
same job; changing its inputs under the same operation fails. `GET /asset-generation`
requires `gameId`, optionally `jobId`; without an ID it returns bounded same-game
job pages and a scoped cursor. Reloading the page retains progress. The browser
never receives inference credentials or treats a queued request as a completed image.

## Subscription worker

```sh
panther assets worker --work-dir /private/path/asset-generation --once
panther assets worker --work-dir /private/path/asset-generation
panther assets worker --work-dir /private/path/asset-generation --resume-job JOB_ID
```

Sign in to Panther and to Codex with ChatGPT on the laptop. The CDK-managed broker
leases a queued job to a configured worker. AWS stores job state with pay-per-request
DynamoDB; it performs no inference. The worker runs a fresh subscription-backed
Codex session with only built-in image generation enabled, without API keys,
shell tools, apps, browsing or external generation. No paid-provider fallback,
credit purchase, usage-reset redemption or automatic generation retry exists.

A checkpoint is persisted **before** inference. A stopped request with an unknown
outcome needs attention rather than another image call. Once output exists, resuming
copies/reuses that exact PNG and retries publication only. `--resume-job` requires a
saved output/result and the original worker identity. Generation limits preserve
local checkpoints; do not reset them to force another attempt. A separately explicit
new Generate action creates a new operation, not an inferred retry.

The image tool's local output must be newly created inside its generated-image
store. The worker rejects symlinks, malformed PNGs, incorrect CRCs, excessive
sizes/dimensions and earlier images. It preserves the tool log and response locally,
then uploads through the supported Panther CLI without overwriting anything.
The image has current semantic version metadata from the normal upload contract.
Its full creative request is stored in hidden `generation-provenance` JSON; the
finished image's `sourceKeys` links that immutable record. Both use the shared
storage layout and normal materialized browse projection. Model identity stays
unknown when the actual tool response does not establish it. Subscription usage
is recorded as subscription, never as a zero billed charge.

The broker publishes `assetKey` only after verifying the exact immutable image in
storage, explicit job/type metadata and actual SHA-256. Publication does not wait
for the asynchronous materialized browse projection. `generationAuthorized` on
these jobs authorizes only the user-requested subscription-backed image operation,
not API spending, video generation, voice synthesis or automatic retries.
Ordinary existing image kinds remain valid. The new typed request/output contract
is additive: no prior asset is reclassified or given fabricated generation history.
No asset-storage scan or static sample asset is used to populate the workspace.

The production API/routes require a CDK deployment. Actual production generation
also needs a running, authenticated laptop worker. An offline worker leaves the
request queued honestly; no hosted compute or API inference is started as a fallback.
