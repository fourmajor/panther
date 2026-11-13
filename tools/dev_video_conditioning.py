"""Exact shot-scoped visual conditioning for the selected production model.

Reference-to-video is an input mode of the same model, never a model fallback.
No inference, asset writes or automatic frame generation happens here.
"""
from dev_prompt_processor import scaled_image


def condition(store, job, model, body, verifier):
    from panther_journal.video import PROFILES
    endpoint = PROFILES[model]['endpoint']
    composition = job.get('promptComposition') or {}
    if job.get('videoPromptPolicy') != 2 or composition.get('schemaVersion') != 2:
        return endpoint, body, []
    selected = composition['visibleCharacterIds']
    characters = {character['id']: character for character in job.get('characterContext', [])}
    references, labels = [], []
    for identity in selected:
        character = characters[identity]
        pin = character.get('portraitPin')
        if not pin:
            raise ValueError('Select an official portrait for ' + character['name'] + ' before generating this shot')
        references.append(scaled_image(verifier(store, pin, job['gameId'])))
        labels.append({'characterId': identity, 'name': character['name'], 'portraitPin': pin})
    if not references:
        return endpoint, body, labels
    frame = job.get('storyboardFramePin') or job.get('mapPin')
    if model.startswith('h3-max'):
        endpoint = 'minimax/h3-max/reference-to-video'
        body['reference_image_urls'] = references
        if not frame:
            body['aspect_ratio'] = '16:9'
        from panther_journal.film_prompt_policy import h3_reference_prompt
        body['prompt'] = h3_reference_prompt(body['prompt'], [item['name'] for item in labels],
                                             first_frame=bool(body.get('image_url')))
        return endpoint, body, labels
    elif model.startswith('kling-3-pro'):
        if not frame:
            raise ValueError('Prepare a starting frame for this action shot before generating; Kling character references require image-to-video')
        body['elements'] = [{'frontal_image_url': url} for url in references]
        bindings = [f"@Element{i + 1} is {item['name']}." for i, item in enumerate(labels)]
    else:
        raise ValueError('Selected model has no reviewed character-reference input mode')
    body['prompt'] = '\n'.join(bindings) + '\nIdentity images are not opening frames. Apply the selected visual style.\n' + body['prompt']

    return endpoint, body, labels
