"""Versioned public-rate estimates, distinct from unchanged actual billed-cost evidence."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import re

VERSION = 1
AS_OF = '2026-10-03'
TEXT_RATES = {'gpt-5-mini': ('0.25', '0.025', '2')}
IMAGE_RATES = {
    'gpt-image-1': ('5', '10', '40', '0.042'),
    'gpt-image-1.5': ('5', '8', '32', '0.034'),
    'gpt-image-1-mini': ('2', '2.5', '8', '0.011'),
}


def number(value):
    if isinstance(value, bool):
        raise ValueError('Boolean is not pricing data')
    try:
        value = Decimal(str(value))
    except InvalidOperation:
        raise ValueError('Invalid pricing data') from None
    if not value.is_finite() or value < 0:
        raise ValueError('Invalid pricing data')
    return value


def result(amount, url, inputs, *, scope='generation', assumptions=()):
    return {'schemaVersion': VERSION, 'status': 'estimated', 'amount': format(amount.quantize(Decimal('0.00000001')), 'f').rstrip('0').rstrip('.') or '0',
            'currency': 'USD', 'scope': scope, 'rateAsOf': AS_OF, 'evidence': {'url': url, 'inputs': inputs},
            'assumptions': list(assumptions), 'billingStatus': 'not-reconciled'}


def openai(model, usage=None, request=None):
    request, usage = request or {}, usage or {}
    canonical = next((name for name in [*TEXT_RATES, *IMAGE_RATES] if model == name or re.fullmatch(re.escape(name) + r'-\d{4}-\d{2}-\d{2}', model or '')), None)
    if not canonical:
        return None
    url = 'https://developers.openai.com/api/docs/models/' + canonical
    try:
        if canonical in TEXT_RATES:
            if 'input_tokens' not in usage or 'output_tokens' not in usage:
                return None
            incoming, outgoing = number(usage['input_tokens']), number(usage['output_tokens'])
            cached = number(usage.get('input_tokens_details', {}).get('cached_tokens', 0))
            if cached > incoming:
                return None
            rate, cache_rate, output_rate = map(number, TEXT_RATES[canonical])
            amount = ((incoming - cached) * rate + cached * cache_rate + outgoing * output_rate) / 1000000
            return result(amount, url, {'model': model, 'usage': usage, 'usdPerMillionTokens': {'input': str(rate), 'cachedInput': str(cache_rate), 'output': str(output_rate)}},
                          assumptions=() if 'cached_tokens' in usage.get('input_tokens_details', {}) else ('Unreported input caching is estimated at the uncached rate.',))
        text_rate, image_rate, output_rate, fixed_output = map(number, IMAGE_RATES[canonical])
        details = usage.get('input_tokens_details', {})
        if all(name in details for name in ('text_tokens', 'image_tokens')) and 'output_tokens' in usage:
            amount = (number(details['text_tokens']) * text_rate + number(details['image_tokens']) * image_rate + number(usage['output_tokens']) * output_rate) / 1000000
            return result(amount, url, {'model': model, 'usage': usage, 'usdPerMillionTokens': {'textInput': str(text_rate), 'imageInput': str(image_rate), 'imageOutput': str(output_rate)}},
                          assumptions=('Input tokens are estimated at uncached rates where modality-specific cache usage is unavailable.',))
        if request.get('size') == '1024x1024' and request.get('quality') == 'medium' and request.get('n', 1) == 1:
            return result(fixed_output, url, {'model': model, 'size': '1024x1024', 'quality': 'medium', 'images': 1}, scope='image-output',
                          assumptions=('Output-only public tariff; unreported input-token and title-generation costs are excluded.',))
    except (ValueError, TypeError, AttributeError):
        return None
    return None


def fal(model, request, api_base=None):
    """Reviewed settings estimate; live base is evidence, never an automatic settings quote."""
    profiles = {
        'veo-3.1-fast': ('fal-ai/veo3.1/fast', '0.15', '0.15', '1'),
        'veo-3.1-fast-image': ('fal-ai/veo3.1/fast/image-to-video', '0.15', '0.15', '1'),
        'veo-3.1-fast-image-silent': ('fal-ai/veo3.1/fast/image-to-video', '0.10', '0.15', '1'),
        'h3-max': ('minimax/h3-max/text-to-video', '0.128', '0.08', '1.6'),
        'h3-max-image': ('minimax/h3-max/image-to-video', '0.128', '0.08', '1.6'),
        'kling-3-pro': ('fal-ai/kling-video/v3/pro/text-to-video', '0.315', '0.21', '1.5'),
        'kling-3-pro-image': ('fal-ai/kling-video/v3/pro/image-to-video', '0.315', '0.21', '1.5'),
    }
    if model not in profiles or not isinstance(request, dict):
        return None
    endpoint, settings_rate, reviewed_base, multiplier = profiles[model]
    duration = str(request.get('duration', '')).removesuffix('s')
    try:
        duration = number(duration)
        if duration != 8:
            return None
        if model.startswith('veo') and (request.get('resolution') != '720p' or request.get('generate_audio') is not (not model.endswith('silent'))):
            return None
        if model.startswith('h3') and request.get('resolution') != '768P':
            return None
        if model.startswith('kling') and request.get('generate_audio') is not True:
            return None
        base = number(api_base) if api_base is not None else number(reviewed_base)
        rate = number(settings_rate)
        if model.startswith('veo') and base != number(reviewed_base):
            return None  # A changed base invalidates the reviewed audio/settings rate.
        if not model.startswith('veo'):
            rate = max(rate, base * number(multiplier))
        return result(rate * duration, 'https://fal.ai/models/' + endpoint,
                      {'model': model, 'durationSeconds': str(duration), 'settings': {k: request[k] for k in ('resolution', 'generate_audio', 'aspect_ratio', 'shot_type') if k in request},
                       'usdPerSecond': str(rate), 'pricingApiBaseUsdPerSecond': str(base) if api_base is not None else None},
                      assumptions=('Settings-adjusted public-rate estimate; no budget headroom or upstream media charges included.',
                                   'Current public rates are applied to historical requests; this is not historical billing reconciliation.'))
    except (ValueError, TypeError):
        return None


def eleven(response):
    credits = (response or {}).get('character-cost')
    if credits is None:
        return None
    try:
        credits = number(credits)
    except ValueError:
        return None
    return {'schemaVersion': VERSION, 'status': 'estimated', 'credits': int(credits) if credits == credits.to_integral_value() else str(credits), 'unit': 'credits', 'scope': 'narration',
            'rateAsOf': AS_OF, 'evidence': {'url': 'https://elevenlabs.io/pricing', 'inputs': {'providerCharacterCost': str(credits)}},
            'assumptions': ['USD depends on the actual subscription and included-credit allocation; no USD amount inferred.'], 'billingStatus': 'not-reconciled'}


def annotate(metadata, request=None, response=None, api_base=None):
    metadata = deepcopy(metadata)
    extra = metadata.setdefault('extra', {})
    generation = extra.get('generation', {})
    provider, model = generation.get('provider'), generation.get('model', '')
    response = response or {}
    evidence = generation.get('evidence') if isinstance(generation.get('evidence'), dict) else {}
    estimate = None
    if provider == 'OpenAI':
        usage = response.get('usage') or evidence.get('usage')
        estimate = openai(model, usage, request)
    elif provider == 'fal':
        aliases = {'Veo 3.1 Fast': 'veo-3.1-fast', 'MiniMax H3 Max': 'h3-max', 'MiniMax H3 Max (post-trained by fal)': 'h3-max', 'Kling 3 Pro': 'kling-3-pro'}
        profile = (request or {}).get('model') or aliases.get(model)
        payload = (request or {}).get('payload', request or {})
        estimate = fal(profile, payload, api_base)
    elif provider == 'ElevenLabs':
        estimate = eleven(response or evidence)
    if estimate:
        extra['costEstimate'] = estimate
    title_generation = extra.get('titleGeneration')
    if isinstance(title_generation, dict):
        title_evidence = title_generation.get('evidence')
        title = openai(title_generation.get('model'), title_evidence.get('usage') if isinstance(title_evidence, dict) else title_generation.get('usage'))
        if title:
            extra['titleCostEstimate'] = title
    return metadata


def live_fal_price(client, model):
    """Read-only pricing evidence. Never submits media or grants spending permission."""
    from datetime import datetime, timezone
    from panther_journal import video
    endpoint = video.PROFILES[model]['endpoint']
    url = video.PLATFORM + '/models/pricing'
    response = client.request('GET', url, params={'endpoint_id': endpoint})
    matches = [item for item in response.get('prices', []) if item.get('endpoint_id') == endpoint]
    if len(matches) != 1 or matches[0].get('currency') != 'USD' or matches[0].get('unit') != 'seconds':
        raise ValueError('Pricing has unknown currency or units')
    rate = number(matches[0]['unit_price'])
    if rate <= 0:
        raise ValueError('Pricing has no positive rate')
    return {'schemaVersion': 1, 'model': model, 'endpoint': endpoint, 'rate': str(rate),
            'url': url, 'checkedAt': datetime.now(timezone.utc).isoformat(), 'response': response}


def fal_image(price, width, height):
    """Estimate only the provider base units measured from a verified output image."""
    if not isinstance(price, dict) or price.get('status') != 'estimated' or price.get('currency') != 'USD':
        return None
    try:
        rate = number(price['amount'])
        unit = price.get('unit')
        if unit in {'image', 'images'}:
            quantity = Decimal(1)
        elif unit == 'megapixels' and type(width) is int and type(height) is int and width > 0 and height > 0:
            quantity = Decimal(width * height) / Decimal(1000000)
        else:
            return None
        estimate = deepcopy(price)
        estimate.update(amount=format(rate * quantity, 'f'), quantity=str(quantity), baseUnitRate=str(rate),
                        scope='Measured output base-rate estimate; provider rounding, settings surcharges and title generation excluded',
                        billingStatus='not-reconciled', measuredOutput={'width': width, 'height': height})
        estimate['assumptions'] = ['Quantity uses verified original image dimensions; no provider rounding or minimum-unit rule inferred.']
        return estimate
    except (ValueError, KeyError):
        return None
