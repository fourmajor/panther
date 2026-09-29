# Lessons from the September 2026 local character trial

Generalized observations, not game content or a validated production recipe. The trial
produced an editable, recognizable figure but missed the desired character-quality bar.
Keep failed approaches as warnings rather than defaults to reproduce.

## Form before detail

- Primitive assemblies and ring-based lofts produced a stiff torso, disjoint-looking wrists,
  angular shoulders, and simplified hands. Smooth shading/subdivision did not repair the
  underlying proportions or disconnected surfaces. Judge an untextured model first.
- A face acceptable from the front had an overextended nose and weak cranial/jaw shape in
  profile. Align landmarks in front and profile before adding surface detail.
- An open beard surface looked like a detached bib. Model a fitted volume and inspect its
  jaw connection and underside. Thousands of repeated fibers made a net-like pattern rather
  than convincing hair. Strand count was not the remedy.
- Decorative curves overshot control points and looked like floating wire around collars.
  Inspect evaluated curves and garment thickness, not only control points.
- A properly licensed human base mesh may help when anatomy is the bottleneck. This was
  not tested. Do not present it as a demonstrated solution or download/execute unrelated
  software without considering scope, license, and permissions.

## Reference projection is an approximation

- Full-body images had too few facial pixels. A sharper near-frontal portrait improved
  recognition, but did not solve geometry, skin continuity, or other viewing angles.
- Modeled eyes/lips competed with misaligned features in projected color. Choose a coherent
  geometry/texture treatment and align landmarks. Hiding extra geometry may help a static
  study but does not create functioning eyes or a rig.
- Projection sampled white backgrounds and painted shirt/belt colors onto the wrong parts.
  Correct camera alignment and visibility/region masks first. Color thresholds were a rough
  mitigation, not a general segmentation solution.
- Hard front/back switches produced seams; sides stretched; photographic lighting stayed
  baked into color. A nicer front render was not proof of faithful reconstruction.
- Read actual image dimensions and calibration, not assumed resolutions. Do not treat
  independently generated views as a photogrammetry capture.

## Geometry and memory

- Subdivision solely for vertex-painted detail produced roughly 4.9 million vertices and a
  209 MB `.blend`, with major shape problems still present. This is a cautionary result,
  not a recommended budget. Consider UV textures/baking where appropriate; retain geometry
  for silhouette or deformation rather than treating subdivision as a quality metric.
- Reading vertex normals after changing positions in the same loop can cause repeated
  mesh-wide normal recalculation. One refinement appeared stuck while consuming several CPU
  cores. Snapshot needed normals/coordinates before mutation, or use bulk array reads/writes,
  then update once. Recompute normals when later operations need the changed geometry.
- Inspect the exact process, resource use, output, and elapsed time before stopping a slow
  job. Stopping only the identified job, fixing the loop, and rerunning resolved the trial's
  problem. Do not kill all Blender processes or disturb the user's interactive scene.

## Installation and runtime observations

- The installed Homebrew cask engine failed with an undefined `preflight_steps` method.
  Blender's official mirror installer worked after checking its published checksum. Check
  current official release metadata; do not pin future installs to this trial or disable
  security protections to install software.
- The sandboxed startup failure exited 139 and included a USD `Arch_ValidateAssumptions`
  warning, which did not establish the cause. A permitted normal-access retry worked.
  Later successful renders helped distinguish the old crash notice from a new failure.
- `Material.use_nodes` emitted a deprecation warning but worked in the tested version.
  Check the installed API on upgrade rather than treating a warning as a failed build.
- Packed images initially reported `has_data == False` after reopening because loading was
  lazy. Accessing the pixel buffer materialized it. Verify packing and usable data after
  loading. Unused references may disappear on save; preserve them intentionally if delivering
  an embedded reference library, not just a self-contained appearance.

## What was established

Local scripting, rendering, self-review, and fresh-open checks worked without a paid
3D-generation service. The figure was not rigged, animation-tested, retopologized, exported
as an optimized GLB, or browser-validated. Reopening and finite-coordinate checks established
file integrity, not visual quality, manifoldness, or web readiness. Do not automate publication
or promote the experimental construction method on the strength of those checks alone.

## Automated realistic-character review (September 29)

Two bounded candidates passed fresh-import, triangle/size, render and browser checks but failed
independent visual review. Boxy anatomy, disconnected clothing, simplistic hands, flat materials
and a depth-poor side silhouette remained despite refinements. Technical readiness and visual
acceptance are separate gates; never publish the last attempt merely because retries ran out.

For a realistic human, changing trim, buttons or strand counts is not a method change when the
primary anatomy is still a primitive assembly. Rebuild the connected primary forms, or investigate
an appropriately licensed anatomical base mesh, before another expensive detail pass. Compare
untextured front/profile silhouettes and face proportions first. A base mesh may help anatomy;
it does not reconstruct identity, clothing, hairstyle, textures or a usable animation rig.

The official Blender Studio Human Base Meshes v1.4.1 data bundle was downloaded from Blender's
mirror and its library was readable in native Blender 5.2.1 with auto-execution disabled. This
establishes file availability, **not** a successful character reconstruction. The ZIP SHA-256 was
`811f43accbb31a88266d932f8f5563b2d13586fca0ba2693aad1f5fe582b3515`.
Source: [Blender demo/asset downloads](https://www.blender.org/download/demo-files/).
Recheck license/version and actual file hashes before reuse; data is not an executable add-on.

The automated worker currently supplies the eight pinned image references, not this mesh library.
Do not assume an outside file is available in its sandbox, inject it into an existing checkpoint,
or silently change a queued job's inputs. Any future supplied geometry needs explicit immutable
source/provenance pins and recovery checks before it becomes part of the generalized worker.
Keep downloaded libraries and character experiments outside Git. No paid service is implied.
