---
name: panther-blender-local
description: Build, refine, inspect, and render editable 3D assets with local Blender for Panther. Use for Blender modeling experiments and character or prop work, not for frontend viewer implementation or cloud workflow deployment.
---

# Panther local Blender

Use local Blender through its Python API and CLI. This is an execution and review method,
not a proven automatic character-reconstruction pipeline.

## Scope and assets

- Keep game references, character-specific scripts, models, renders, and provenance outside
  Panther's repository. Only generalized instructions and synthetic helpers belong here.
- Follow `AGENTS.md` and `panther instructions` when discovering or uploading Panther assets.
  Missing CLI authorization is not permission to borrow credentials or bypass Panther via S3.
  Existing local references can support local work, which does not imply publication.
- Match the requested experiment. Do not introduce a paid generation service, persistent
  bridge, plugin installation, rigging project, or deployed workflow merely to use this skill.
  A local script is sufficient for the baseline. Respect explicitly requested tools.

## Reference and quality target

Inspect actual references before building. Use whole-body front/profile/back views for
proportions and a detailed portrait for facial landmarks. Record sources, their influence on
geometry/color, and inferred details alongside the asset. Generated turnarounds may disagree;
do not assume calibrated cameras or consistent anatomy.

Resolve routine style/output choices from context. Do not silently downgrade a compelling
character request to a low-poly placeholder. A static `.blend` and inspected renders can
satisfy a local trial; animation and browser-ready export are separate deliverables.

For characters or reference-projected color, read
[the experiment lessons](references/local-modeling-lessons.md) before choosing a method.
Also consult them for slow geometry loops, image validation, or installation failures.

## Local execution

The owner's Mac had `/Applications/Blender.app/Contents/MacOS/Blender`, version 5.2.1 LTS,
on 2026-09-08. Verify the executable/version on the current host. Run `bpy` with Blender's
bundled Python, not Panther's Python environment.

Replace this example's script path with the actual outside-repo working file:

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background --threads 6 \
  --python-exit-code 1 --python /absolute/outside-repo/work/create_asset.py
```

Choose threads for the host; do not assume GPU rendering is configured. Cycles with denoising
and roughly 32–48 samples worked for previews in the trial, not as a universal quality preset.

Keep reproducible source, named parts, and deliberate output paths. Preserve earlier candidates
when changing direction. Load saved scenes for focused edits; clear only for an intentional
rebuild. Save the `.blend` before rendering to preserve work if rendering fails.

Poll the existing process when given a session ID; quiet output alone is not a hang. Check
exit status and saved files. An initial sandboxed startup exited 139 before script execution
in the trial; an approved normal-access retry worked. Inspect failures and use the environment's
permission mechanism when warranted, not automatic sandbox bypasses or blind retries.

## Model, inspect, revise

Start with untextured primary forms. Compare matched front/profile views before spending time
on buttons, keys, hair strands, or scenery. Then refine anatomy, garment fit, connections, and
materials in coherent passes. Review your own work and continue without routine human approval
unless the user requested a gate or a substantive decision needs input.

Open rendered evidence at each visual milestone: a three-quarter presentation, front/profile/back
views, and relevant close-ups. Check silhouette, facial landmarks, hands, feet, garment joins,
beard volume, intersections, floating parts, and texture transitions. Do not let photographic
texture or a flattering camera conceal unresolved geometry.

When more detail does not fix the observed defect, revisit the method or primary forms.
More polygons and successful renders are not evidence of better likeness.

## Validation and handoff

Reopen the final scene in a fresh Blender process. Check finite geometry, intended scale,
and missing dependencies. Pack needed images or provide a portable dependency bundle; load lazy
image data before judging it missing. Inspect evidence from the final revision, not an earlier one.

If GLB is requested, export and fresh-import it, then inspect its appearance and size.
Blender procedural shading, hair curves, and lighting are not automatically portable.
Follow the repository's self-hosted Playwright gate when integrating into the frontend;
a Blender render does not verify Panther's viewer. Local-only studies do not require web tests.

Deliver the editable file and an inline inspected render with absolute paths. Report quality
gaps, rig/export/test status, and any publication. Distinguish local execution working from
the model being compelling or the pipeline being reliable.

## Sources

Original Panther guidance informed by local experiments and the following sources; no upstream
skill or executable code is vendored:

- [Simon Willison's macOS Blender guide](https://til.simonwillison.net/llms/blender-coding-agents-macos)
  and [local skill](https://github.com/simonw/gpt-6-astra-blender-pelican-bicycle/blob/main/outputs/blender-local/SKILL.md): local execution, saved scenes, visual iteration.
- [Blender Agent Studio](https://github.com/ifBars/blender-agent-studio): staged form/fit review
  and export inspection, not an installed dependency or proof of character quality.
- [OpenAI's architecture example](https://developers.openai.com/blog/architectural-visualization-with-astra):
  scripted Blender iteration, not evidence of equivalent human-likeness quality.
