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
submitted destination revision. Cloud writes retain reverse source references;
local writes atomically commit owned records, history and stage completion.
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
approval. AI approval never authorizes an unseen script revision, automatic paid
retry, provider fallback or additional budget.

Planning does not fabricate footage, speech or an assembled master. Existing
explicit scene/narration generation and Episode assembly consume actual selected
immutable outputs. A pending/rejected AI storyboard blocks footage generation in
the UI, submission API and worker. Provider/model/input/cost facts remain recorded
by the respective generation worker.

This is a prototype contract cutover. There is no legacy-plan migration or read-time
fallback. Existing source artifacts are retained without rewriting their bytes.
