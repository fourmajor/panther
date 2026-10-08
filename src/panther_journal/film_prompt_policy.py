"""Shot-scoped, provider-aware filmmaking guidance; never a spending approval."""

import re


POLICY_VERSION = 1

# Kept separate from provider prompts: this is direction for preparation/review.
REVIEW_GUIDANCE = (
    "Audit the exact generation prompt against the actual starting frame and this shot only. "
    "The continuity bible is review evidence, not a paragraph to append to every request. "
    "Object/landscape inserts must not request offscreen cast, faces, costumes or weapons. "
    "Opening/ending states must not introduce creatures, injuries or effects from other beats. "
    "Check subject-target binding, prop ownership, action onset and required end state. "
    "Check that depicted poses and implied motion permit the requested action. "
    "Prefer one achievable dominant beat and one camera move per single-shot request; "
    "split complex interactions into establishing, action, insert and reaction coverage. "
    "Use positive visible outcomes instead of long lists of unwanted transformations. "
    "Do not pass a shot merely because its artwork looks attractive. Contradictions fail "
    "movement/object-positions; wrong visible cast fails face/clothing. Uncertainty blocks preparation. "
    "Provider specifics: H3 image conditioning uses explicit opening-frame alignment followed by "
    "integrated_multimodal_description, overall_soundscape and non_diegetic_music; reference-to-video "
    "is a different mode and must not pretend portraits were supplied as first frames. "
    "Runway-style motion-only guidance is a heuristic, not H3's required syntax. "
    "Veo and Kling use their verified adapter capabilities, not imagined reference/end-frame controls. "
    "Separate diegetic effects/ambience from score and tie each spoken line to its visible speaker. "
    "Identity must persist throughout the action, not just the first tile. Compare actual closing "
    "state with the next opening; flag spatial/prop/creature-count jumps explicitly."
)


def prompt_blockers(prompt):
    """Small deterministic tripwires, not a substitute for semantic/image review."""
    blockers = []
    if len(prompt) > 2500:
        blockers.append("Prompt exceeds the provider limit; revise it without truncating approved action")
    empty = re.search(r"\b(no people|no characters|unoccupied|empty (?:room|insert))\b", prompt, re.I)
    cast = re.search(r"\b(same (?:adult )?faces|all (?:four|five|\d+) (?:adventurers|characters|heroes)|exactly (?:four|five|\d+) (?:adult )?adventurers)\b", prompt, re.I)
    if empty and cast:
        blockers.append("Empty insert conflicts with a full-cast/face instruction")
    return blockers


def motion_prompt(model, direction, *, first_frame=False):
    """Render already-reviewed direction without global cast injection or silent clipping.

    This is a formatting step, not an AI semantic rewrite or authorization decision.
    Inputs must already reflect the exact approved shot and visible subset.
    """
    if model.startswith('h3-max'):
        opening = ("For the target video, at 0.00 seconds into the target video, "
                   "<Picture 1> (from [Shot 1]) is fully referenced.\n\n") if first_frame else ''
        visual = ' '.join(direction[k] for k in ('setting', 'lighting', 'mood', 'blocking', 'action', 'camera') if direction[k].strip())
        prompt = (opening + 'integrated_multimodal_description: [Shot 1] ' + visual
                  + '\n\noverall_soundscape: ' + (direction['sound'].strip() or 'N/A')
                  + '\n\nnon_diegetic_music: N/A')
    else:
        prompt = '\n'.join(k.title() + ': ' + v for k, v in direction.items() if v.strip())
    errors = prompt_blockers(prompt)
    if errors:
        raise ValueError('; '.join(errors))
    return prompt


def h3_reference_prompt(prompt, names, *, first_frame=False):
    """Bind actual fal reference-list indices separately from its image_url frame."""
    body = prompt
    if body.startswith('For the target video, at 0.00 seconds'):
        sections = body.split('\n\n', 1)
        if len(sections) != 2:
            raise ValueError('Opening-frame alignment must be followed by shot direction')
        body = sections[1]
    body = body.replace('integrated_multimodal_description:', 'detailed_description:', 1)
    if not body.startswith('detailed_description:'):
        body = 'detailed_description: [Shot 1] ' + body
    definitions = '\n'.join(f'<Subject {i}> is {name}, using Image {i} only for identity, wardrobe and equipment.'
                            for i, name in enumerate(names, 1))
    if first_frame:
        definitions += '\nThe separate image_url is the opening composition, not Image 1 from the identity list.'
    retention = '\n'.join(f'<Subject {i}>: fully_preserved for visible identity, wardrobe and equipment.'
                          for i in range(1, len(names) + 1))
    result = ('subject_definitions:\n' + definitions
              + '\n\nsummary: [reference generation' + (' + keyframe completion' if first_frame else '')
              + '] Perform the approved shot sequence with these visible subjects.'
              + '\n\nretention_analysis:\n' + retention + '\n\n' + body)
    if 'overall_soundscape:' not in result:
        result += '\n\noverall_soundscape: N/A'
    if 'non_diegetic_music:' not in result:
        result += '\n\nnon_diegetic_music: N/A'
    errors = prompt_blockers(result)
    if errors:
        raise ValueError('; '.join(errors))
    return result
