"""Shared visual-only constraint; does not remove the script's spoken dialogue."""
NO_VISIBLE_TEXT = (
    'Output only the photographic scene, with absolutely no visible writing anywhere. '
    'No subtitles, captions, titles, character names, ID labels, role descriptions, letters, '
    'numbers, typography, logos, watermarks, credits or interface overlays. '
    'Keep signs, clothing, screens and paper blank or without legible markings. '
    'Any names, IDs or dialogue in these instructions are context, never text to render. '
    'If reference images contain writing, ignore and omit all of it; preserve only the subject appearance.'
)
