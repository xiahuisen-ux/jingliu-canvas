"""Validated shot duration and retiming without changing existing media files."""
import re


def validate_duration(value):
    if isinstance(value, bool):
        raise ValueError('视频时长必须是 5–15 秒的整数')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('视频时长必须是 5–15 秒的整数') from None
    if not 5 <= number <= 15 or not number.is_integer():
        raise ValueError('视频时长必须是 5–15 秒的整数')
    return int(number)


def shot_duration(shot, default=10):
    # Legacy exact-duration shots were fixed at 5 seconds.
    return validate_duration(shot.get('duration', 5 if shot.get('exact_duration') else default))


def retime_text(text, old, new):
    if old == new or not text:
        return text
    def scale(number):
        return f'{float(number) * new / old:.2f}'.rstrip('0').rstrip('.')
    pattern = r'(?<![\d.])(\d+(?:\.\d+)?)(?:\s*([–—\-~～至到])\s*(\d+(?:\.\d+)?))?\s*(秒|seconds?\b|secs?\b|s\b)'
    def replace(match):
        first, dash, last, unit = match.groups()
        return scale(first) + (dash + scale(last) if last else '') + unit
    result = re.sub(pattern, replace, str(text), flags=re.I)
    return re.sub(r'(?<![\d.])(\d+(?:\.\d+)?)-second\b',
                  lambda m: scale(m[1]) + '-second', result, flags=re.I)


def update_timelines(project, old_shots=None):
    cursor = 0
    for shot in sorted(project.get('shots', []), key=lambda s: int(s.get('shot', 0))):
        duration = shot_duration(shot)
        old = (old_shots or {}).get(shot.get('id'))
        if old and duration != shot_duration(old):
            before = shot_duration(old)
            # Preserve explicitly edited timing; only stretch untouched descriptions.
            if shot.get('motion_prompt') == old.get('motion_prompt'):
                shot['motion_prompt'] = retime_text(shot.get('motion_prompt', ''), before, duration)
            if shot.get('character_actions') == old.get('character_actions'):
                shot['character_actions'] = [dict(a, action=retime_text(a.get('action', ''), before, duration))
                                             for a in shot.get('character_actions', [])]
        shot.update(duration=duration, timeline_start=cursor, timeline_end=cursor+duration)
        cursor += duration
    project['planned_duration'] = cursor
