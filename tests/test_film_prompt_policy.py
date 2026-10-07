"""Synthetic regression cases; no provider calls or private campaign content."""
import pytest
from panther_journal.film_prompt_policy import h3_reference_prompt, motion_prompt, prompt_blockers


def direction(**changes):
    return dict(setting='', lighting='', mood='', blocking='', action='Three corks lift from their bottles and stay clear of the openings.', camera='Locked close-up.', sound='Three soft cork pops.', **changes)


def test_h3_formats_exact_motion_and_sound_without_cast_bible():
    result = motion_prompt('h3-max-image', direction(), first_frame=True)
    assert result.startswith('For the target video, at 0.00 seconds')
    assert 'integrated_multimodal_description: [Shot 1]' in result
    assert 'stay clear of the openings.' in result
    assert 'overall_soundscape: Three soft cork pops.' in result
    assert 'non_diegetic_music: N/A' in result
    assert 'faces' not in result


def test_known_empty_insert_cast_collision_is_blocked():
    assert prompt_blockers('No people in this insert. Match the same adult faces and costumes.')
    assert not prompt_blockers('An empty room. Dust crosses the floor. Locked camera.')


def test_overlong_motion_is_not_silently_truncated():
    value = direction()
    value['action'] = 'A deliberate motion. ' * 200 + 'Finish with the lid shut.'
    with pytest.raises(ValueError, match='provider limit'):
        motion_prompt('h3-max-image', value, first_frame=True)


def test_other_profiles_do_not_receive_h3_alignment_tokens():
    result = motion_prompt('kling-3-pro-image', direction(), first_frame=True)
    assert 'Action:' in result and '<Picture 1>' not in result


def test_h3_reference_mode_keeps_frame_and_portrait_numbering_distinct():
    prompt = motion_prompt('h3-max-image', direction(), first_frame=True)
    result = h3_reference_prompt(prompt, ['Example actor'], first_frame=True)
    for section in ('subject_definitions:', 'summary:', 'retention_analysis:', 'detailed_description:',
                    'overall_soundscape:', 'non_diegetic_music:'):
        assert section in result
    assert 'Image 1 only for identity' in result
    assert 'separate image_url' in result
    assert 'integrated_multimodal_description:' not in result
    assert '<Picture 1>' not in result
    assert 'stay clear of the openings.' in result
