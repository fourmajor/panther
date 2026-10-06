# Episode production contract

The screen branch of the editorial pipeline publishes into the same Episode and
Scene records edited by the application. There is no separate movie project,
storyboard inbox, or alternate episode library.

An Episode owns an ordered `sceneIds` list. Each Scene belongs to exactly one
Episode and owns an ordered `storyboard.shots` list. A shot contains its stable
identity, composition/action, camera direction, duration, optional immutable
frame asset and narration. Scene narration and selected footage remain separately
editable. A storyboard is a revision of this scene-owned plan, not a peer of the
Episode.

## Canonical storage

Cloud records use the existing materialized browse table:

- Episode: `pk=episode-scenes-v1#episode#GAME`, `sk=EPISODE`.
- Scene: `pk=episode-scenes-v1#scene#EPISODE#GAME`, `sk=SCENE`.
- Immutable history: `episode-scenes-v1-history#KIND#GAME#ID`, with the exact
  revision as `sk`; Scene KIND includes its owning Episode.

Local development uses the equivalent `episode`, `scene`, `episode-history` and
`scene-history` SQLite record kinds. UI edits and pipeline publication share
these stores. `episode_destination.py` builds and validates the publication;
`episode_storyboards.py` owns authorship and approval transitions.

Pipeline evidence and original requests remain immutable workflow assets using
the shared asset storage path builder. `productionSource.artifact` pins the exact
validated packet by key, checksum and size. Original shot definitions and input
references remain pinned in `productionSource`; the application does not rewrite
those documents to maintain its editable scene state. Finished frames, narration,
scene clips and episode masters retain their independent immutable asset identities.

## Submission and publication

`Create TV Episode` in a chapter and `Create Episode → Create from Novel…` send
one schema-4 request containing only the selected same-game chapter identity.
The server reads and pins its actual manuscript bytes. It atomically creates the
job and its owned Episode placeholder. The same chapter revision/workflow version
is idempotent. No browser-supplied manuscript or fabricated output is accepted.

Workflow version 5 reuses the existing treatment, screenplay, breakdown, casting,
shot-list, storyboard and production-packet stages. Its production packet includes
an Episode manifest partitioning every locked shot into an ordered owned Scene.
Validators reject reordered, duplicated, missing or foreign shots and references.
Raw-session screen workflows publish to the same destination. Scene-directed
planning publishes a new revision into the exact submitted Scene, preserving its
owner rather than creating another Episode.

Publication requires the validated packet, current worker lease and unchanged
submitted destination revision. Cloud writes retain reverse source references.
Raw-session casts come from the exact completed context artifact, checksum-pinned
in the packet and checked against the durable context task. Explicitly selected
casts stay restricted to those selections. Neither a current catalog read nor
generated character names can expand a publication's allowed cast.
Local writes atomically commit owned records, history and stage completion.
Conflicting human edits preserve the completed plan and fail publication rather
than overwrite the edit. Cloud callback replay recognizes exact published history
and never overwrites a later user revision.

## States and approval

The Episode production placeholder starts at `planning`; successful packet
publication makes it `planned`. The UI shows a stable preparation placeholder,
then loads the published owned Scenes through TanStack Query. Failure preserves
the source and completed steps and links to the workflow; it does not automatically
submit another paid request.

Scene storyboard planning states are:

- `unplanned`: no storyboard revision.
- `needs-approval`: AI revision without an exact approval.
- `changes-requested`: the owner requested changes to that exact AI revision.
- `ready`: human-authored revision, or the exact approved AI revision.

Only an authenticated owner can approve an AI revision. Human-authored storyboards
require no approval. A no-op save preserves AI authorship and its pending decision.
A real human edit creates a new human-authored revision in the same Scene history.
The request body cannot declare its own authorship or copy another revision's
approval. The owner-only `storyboardProposalShots` operation explicitly publishes
AI-authored replacements instead of passing them through the human-edit path.
Use `panther videos propose-storyboard PRIVATE_JSON` with the guarded scene envelope
(`gameId`, `episodeId`, `id`, `name`, optional `description`, exact `expectedRevision`,
retained `operationId`, and normalized `storyboardProposalShots`). Each shot keeps
its stable ID, direction, camera, duration, narration and immutable `frameKey`.
An identical proposal is a no-op; changed proposals clear the current decision and
take selections while preserving immutable scene history and original media.
Prepared `shot-frame` intermediates are accepted only as storyboard frames, not maps
or finished footage. The UI uses the existing native shot cards and review controls;
a PDF export is not the storyboard's storage or approval surface.
AI approval never authorizes an unseen script revision, automatic paid
retry, provider fallback or additional budget.

Planning does not fabricate footage, speech or an assembled master. Existing
explicit scene/narration generation and Episode assembly consume actual selected
immutable outputs. A pending/rejected AI storyboard blocks footage generation in
the UI, submission API and worker. Provider/model/input/cost facts remain recorded
by the respective generation worker.

## Shot footage and scene assembly

Each storyboard item owns its takes through asset `extra.storyboardShotRef`
(`revision`, `shotId`) and the existing `sceneRef`. The Scene stores explicit
`shotTakes[shotId]` selections: immutable asset, board revision, generation scene
revision, trim start and storyboard duration. Original takes stay unchanged.
Changing the storyboard clears current cuts and scene output; history retains them.

Generation targets one approved shot with its action, camera, cast and source
context. A prepared frame is pinned as the image-to-video input. Current local
profiles generate eight-second takes; longer storyboard items require shorter
approved shot plans. Short footage is never stretched, looped or called complete.
Multi-shot provider requests can be added explicitly without changing ownership.

The local assembler validates real probed durations, trims each selected take,
and concatenates every cut in storyboard order. Finished output records exact
`extra.sceneAssembly` clips/revision and immutable `sourceKeys`. Only an assembly
matching every current selection completes a planned scene for Episode assembly.
Cloud planning and selections share this contract; cloud browser dispatch of scene
assembly is not yet available.

Run the authenticated all-game cutover with `panther videos migrate-workspace
--storyboard-cuts`, then `--apply --inventory-hash HASH`. Review private dry-run
output and verify a fresh complete inventory reports every scene already migrated.
Exact current history is required; guarded updates preserve original records and
selections in immutable history/audit. Old scene-level takes are not guessed into
shot slots. SQLite startup performs the equivalent atomic all-game migration.
This does not change AI authorship/approval or authorize new paid requests.
