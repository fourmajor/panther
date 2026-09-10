# Asset generation metadata v1

Every asset stores `extra.generation` with `schemaVersion: 1`, `method`, and `cost.status`.
Normal uploads default to an explicit unknown record. This is not permission for producers to
omit known facts: the video, editorial, Blender-worker, recording and playback producers record
their actual tools and execution paths. Manual image-generation uploads must do the same.
Existing assets use the same stored contract after the versioned backfill, not a legacy reader.

Optional facts are `model` (actual model/version, not the assistant or tool's name), `provider`
(service through which inference was obtained), `inference` and `execution` (`local`, `remote`,
`unknown`, `not-applicable`), `tool`, and `evidence` (short source attribution). An omitted fact is
unknown. Do not infer a model version from a file name, today's default, or a generic tool name.
For Codex + Blender: OpenAI inference is remote, Blender/coordination execute locally. For a
locally loaded speech model both inference and processing are local. Fal is the provider even
when an underlying model vendor hosts the actual compute; do not invent its datacenter.

Methods: `ai`, `ai-assisted`, `procedural`, `capture`, `human`, `unknown`. An uploaded photograph,
reference drawing or PDF is not presumed AI-generated or human-created merely from its format.

Cost statuses:

- `billed`: actual provider billing evidence, with decimal-string `amount` and ISO `currency`.
- `estimated`: explicitly labeled estimate with its source; never displayed as a charge.
- `subscription`: covered by a subscription; no invented per-asset allocation or $0 claim.
- `not-applicable`: no metered generation charge (e.g. local FFmpeg); excludes hardware,
  electricity, storage and other shared expenses.
- `unknown`: not recorded/reconciled. Missing billing events do not establish zero cost.

Only billed/estimated costs have amounts and require `evidence`. Reservations are not costs.
These figures describe the recorded creation operation, not an all-in sum of upstream assets,
failed candidates or shared subscription fees. Paired exports must not be summed twice. Use a
separate provenance artifact for complex multi-step/shared-cost breakdowns; keep immutable
inputs and original evidence intact. Never derive consent, rights or canon from these fields.

Example (synthetic):

```json
{"extra":{"generation":{"schemaVersion":1,"method":"ai","model":"Example model v1",
"provider":"Example provider","inference":"remote","cost":{"status":"billed",
"amount":"1.234","currency":"USD"},"evidence":"Provider billing event example-request"}}}
```

The web asset preview shows Generation details below the media; chapter generation details live
in Details, never manuscript text. All values are inert text. Previewing does no paid work and
does not fetch provider billing APIs from the browser. No secrets enter metadata or CI.

## Backfill and ongoing reconciliation

1. Inspect `panther assets catalog` and `panther info`; retain a private original inventory.
2. `panther video costs` reads request-scoped fal billing events using the stored admin key,
   only via GET. It neither generates content nor modifies/releases the spending ledger.
   Failed attempts can have explicit zero billing; that does not unblock an unresolved job.
   Current API queries cover the last 89 days; absent/older records remain unknown.
3. Prepare a private JSON object mapping exact asset keys to evidence-backed generation records.
   Use actual recorded provenance and authenticated billing; retain unknown model versions.
4. `panther assets generation-plan --facts FACTS.json --output NEW_PLAN.json` inventories every
   game, pins versions and retains all existing metadata. Without a fact override it preserves
   a current generation record or supplies the explicit unknown record. No cloud writes occur.
5. Dry-run then apply with `panther assets migrate`, using distinct create-only report files.
   The existing owner-only, serialized migration retains original bytes, lineage, uploader,
   timestamps and prior versions. Metadata-size conflicts stop the run; never silently drop
   provenance to fit. Reuse the exact plan after uncertain responses, not fresh version pins.
6. Re-inventory every game, validate every record, and compare SHA-256, byte length, stable keys,
   sourceKeys and original creation times against the initial inventory. Keep/upload private
   audit reports as intermediate assets. No regeneration or storage relocation is necessary.

New video downloads attempt a read-only billing lookup and preserve unknown cost if unavailable
or delayed. Later reconciliation uses this same migration; it never rewrites the downloaded video.
Upgrade pinned local workers from the reviewed merged release to adopt the new producer metadata.
