"""Provider-neutral visual direction, not provider/model selection or spending approval."""

STYLES = [
    {
        "id": "photorealistic",
        "previewImage": "/style-previews/photorealistic.webp",
        "label": "Photorealistic",
        "prompt": "Photorealistic live-action imagery; believable anatomy, natural skin and material texture, physically plausible lighting. Do not copy illustration or cartoon rendering from identity references.",
    },
    {
        "id": "anime",
        "previewImage": "/style-previews/anime.webp",
        "label": "Anime",
        "prompt": "Anime-inspired 2D imagery, expressive characters, clean linework and cel shading; preserve character identity and costume.",
    },
    {
        "id": "illustrated-fantasy",
        "previewImage": "/style-previews/illustrated-fantasy.webp",
        "label": "Illustrated fantasy",
        "prompt": "Detailed painted fantasy illustration, expressive brushwork and atmospheric depth; preserve character identity and costume.",
    },
    {
        "id": "comic-book",
        "previewImage": "/style-previews/comic-book.webp",
        "label": "Comic book",
        "prompt": "Comic-book imagery with deliberate ink contours and graphic shading; no panels, lettering or speech bubbles unless explicitly requested.",
    },
    {
        "id": "watercolor",
        "previewImage": "/style-previews/watercolor.webp",
        "label": "Watercolor",
        "prompt": "Watercolor illustration with translucent washes, soft pigment edges and paper texture; preserve readable subjects.",
    },
    {
        "id": "oil-painting",
        "previewImage": "/style-previews/oil-painting.webp",
        "label": "Oil painting",
        "prompt": "Oil-painted imagery with layered pigment, visible brushwork and rich tonal depth; preserve character identity.",
    },
    {
        "id": "stylized-3d",
        "previewImage": "/style-previews/stylized-3d.webp",
        "label": "Stylized 3D",
        "prompt": "Stylized three-dimensional animated-film imagery with sculpted forms and tactile materials, not photorealistic live action.",
    },
    {
        "id": "pixel-art",
        "previewImage": "/style-previews/pixel-art.webp",
        "label": "Pixel art",
        "prompt": "Deliberate pixel-art imagery with a limited palette, crisp pixel clusters and readable silhouettes; no blurry photographic filtering.",
    },
]
BY_ID = {style["id"]: style for style in STYLES}


def validate_style(value):
    if not isinstance(value, str) or value not in BY_ID:
        raise ValueError("Choose a supported visual style")
    return value
