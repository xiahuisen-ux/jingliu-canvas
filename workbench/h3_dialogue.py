"""Separate explicit no-vocal directions from quoted performance text.

This is conservative text parsing, not a general natural-language interpreter.
Unknown quoted content remains required; only explicit exclusions are omitted.
"""
import re
import unicodedata

QUOTES = re.compile(r'“([^”\n]+)”|「([^」\n]+)」|『([^』\n]+)』|‘([^’\n]+)’|"([^"\n]+)"')
TAGS = re.compile(r'<d>\[Chinese\]\s*(.*?)</d>', re.S)
CJK = re.compile(r'[\u3400-\u9fff]')
BOUNDARY = re.compile(r'[。！？!?；;\n，,]')
REMOVE = r'(?:删除|删掉|删去|去掉|移除|取消|禁唱|禁说|(?:不要|别|禁止|不能|不再|不得|不|无需|不用)(?:再)?(?:演唱|唱出|唱|说出|说|念出|念|朗读|播放))'
KEEP = r'(?:(?:不要|别|禁止|不得|不许|不能|不必|无需|不用|不)(?:再)?(?:删除|删掉|删去|去掉|移除|取消)|保留|必须(?:演唱|唱|说)|继续(?:演唱|唱|说))'
BEFORE_REMOVE = re.compile(REMOVE + r'[^“”「」『』‘’"，,。；;\n]{0,24}$')
BEFORE_KEEP = re.compile(KEEP + r'(?P<tail>[^“”「」『』‘’"，,。；;\n]{0,24})$')
AFTER_REMOVE = re.compile(r'^\s*(?:(?:这|那|本|该)(?:一)?(?:句|段)|歌词|台词|对白|人声|的|部分|\s)*' + REMOVE)
AFTER_KEEP = re.compile(r'^\s*(?:(?:这|那|本|该)(?:一)?(?:句|段)|歌词|台词|对白|人声|的|部分|\s)*' + KEEP)
HYPOTHETICAL = re.compile(r'如果|假如|是否|要不要|能否|考虑|可能')
NONVOCAL = re.compile(r'^(?:(?:里|中|内)(?:面)?的?|的)?(?:杂音|噪声|字幕|水印|引号|标点|空格)')


def words(match):
    return next(x for x in match.groups() if x is not None).strip()


def key(text):
    # Ignore punctuation and spacing, never change the actual spoken text.
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if unicodedata.category(c)[0] not in 'PZC')


def contract(dialogue):
    quotes = list(QUOTES.finditer(dialogue or ''))
    masked = QUOTES.sub(lambda m: ' ' * len(m[0]), dialogue or '')
    required, excluded = [], []
    previous_role = None
    for i, quote in enumerate(quotes):
        prior = quotes[i-1].end() if i else 0
        boundary = list(BOUNDARY.finditer(masked, prior, quote.start()))
        start = boundary[-1].end() if boundary else prior
        prefix = dialogue[start:quote.start()].strip()
        next_quote = quotes[i+1].start() if i+1 < len(quotes) else len(dialogue)
        boundary_after = BOUNDARY.search(masked, quote.end(), next_quote)
        suffix = dialogue[quote.end():boundary_after.start() if boundary_after else next_quote].strip()
        # Without a separator, "say 'A.' delete 'B'" must not apply the next
        # quote's leading deletion verb backwards to A.
        own_suffix = boundary_after is not None or next_quote == len(dialogue)
        keep_before = BEFORE_KEEP.search(prefix)
        keep_before = keep_before and not re.search(REMOVE, keep_before['tail'])
        if HYPOTHETICAL.search(prefix):
            role = 'required'
        elif keep_before or (own_suffix and AFTER_KEEP.search(suffix)) or NONVOCAL.search(suffix):
            role = 'required'
        elif BEFORE_REMOVE.search(prefix) or (own_suffix and AFTER_REMOVE.search(suffix)):
            role = 'excluded'
        elif previous_role and not boundary and prefix in ('', '和', '与', '及', '以及', '、'):
            role = previous_role
        else:
            role = 'required'
        (excluded if role == 'excluded' else required).append(words(quote))
        previous_role = role
    required = list(dict.fromkeys(required))
    # A line explicitly sung once and prohibited later needs timed directions;
    # do not interpret its later prohibition as a clip-wide ban.
    required_keys = {key(x) for x in required}
    excluded = list(dict.fromkeys(x for x in excluded if key(x) not in required_keys))
    return {'required': required, 'excluded': excluded}


def instructions():
    return ('\n对白与导演说明必须区分：dialogue 中“删除某句人声”“不唱某句”是排除要求，'
            '即使被引号包裹也不是待演唱台词，禁止补回；“不要删除某句”表示保留。'
            '实际说唱原文仅在 integrated_multimodal_description 的 <d>[Chinese] 原文</d> 中写一次。'
            'overall_soundscape 与 non_diegetic_music 只用英文概述，不重复中文台词，也不再放对白标签；'
            '可用 the previously specified line 指代正文台词。被删除内容仅用英文说明静音或伴奏要求，不写进对白标签。')


def normalize_and_check(parts, dialogue):
    policy = contract(dialogue)
    body = parts['integrated_multimodal_description']
    lines = TAGS.findall(body)
    spoken = [key(line) for line in lines]
    all_spoken = [key(line) for text in parts.values() for line in TAGS.findall(text)]
    for line in policy['excluded']:
        if key(line) and any(key(line) in value for value in all_spoken):
            raise ValueError('对白标签中出现已明确删除或禁唱的内容：' + line)
    for line in policy['required']:
        if key(line) and not any(key(line) in value for value in spoken):
            raise ValueError('未完整保留中文对白或歌词：' + line)

    result = dict(parts)
    known = set(spoken)
    # Only repair a redundant quotation in a sound summary when the same line
    # is already correctly tagged in the action. Never invent or move vocals.
    for section in ('overall_soundscape', 'non_diegetic_music'):
        text = result[section]
        text = TAGS.sub(lambda m: '(the previously specified line)' if key(m[1]) in known else m[0], text)
        text = QUOTES.sub(lambda m: '(the previously specified line)' if CJK.search(words(m)) and key(words(m)) in known else m[0], text)
        result[section] = text
    for section, text in result.items():
        outside = re.sub(r'<d>.*?</d>', '', text, flags=re.S)
        match = CJK.search(outside)
        if match:
            snippet = outside[max(0, match.start()-18):match.start()+38].strip()
            raise ValueError(f'英文叙述中仍有中文（{section}：{snippet}）；实际台词仅放正文对白标签，声音总结用英文指代')
        if section != 'integrated_multimodal_description' and '<d>' in text:
            raise ValueError(f'{section} 不应新增对白标签；实际台词应放在正文并保留发声时间')
    return result
