"""Pinned official H3 writing guide and workbench format boundary."""
from pathlib import Path
import hashlib
import re
import video_modes
import h3_dialogue

ROOT=Path(__file__).resolve().parent/'studio'/'h3-prompt-writing'
REVISION='d21241f0a4b3acbb34c97dae47fa417b7065e438'
FIELDS=('integrated_multimodal_description','overall_soundscape','non_diegetic_music')
EDITOR_FIELDS=('description','camera','dialogue')


def bind_editor_source(shot):
    """Record a paired Chinese/English result, only after its caller validates it."""
    shot['h3_editor_source']={
        'fields':{k:shot.get(k,'') for k in EDITOR_FIELDS},
        'duration':shot.get('duration',10),
        'english_sha256':hashlib.sha256(shot.get('motion_prompt','').encode()).hexdigest(),
    }


def editor_notes(shot):
    """Avoid re-sending a translated table; retain subsequent edits and legacy text."""
    saved=shot.get('h3_editor_source') or {}
    paired=(saved.get('duration')==shot.get('duration',10) and
            saved.get('english_sha256')==hashlib.sha256(shot.get('motion_prompt','').encode()).hexdigest())
    labels={'description':'Scene','camera':'Camera','dialogue':'Spoken/sung words'}
    return '\n'.join(f'{labels[k]}: {shot.get(k, "")}' for k in EDITOR_FIELDS
                     if not paired or saved.get('fields',{}).get(k)!=shot.get(k,''))


def instructions(duration):
    return ('\n必须严格遵循以下官方 H3 SKILL 与基础模式指南。外层仍为约定的分镜 JSON；'
            '每个 motion_prompt 是包含三个字段的完整英文提示词字符串，不是额外 JSON 对象。'
            '当前是分镜规划阶段，参考图尚可改变，因此先使用 T2VA 三段格式，不编造任何图片、视频或音频编号。'
            f'每段只有 [Shot 1] 一个连续镜头，动作覆盖恰好 {duration} 秒；不要添加 [Shot 2] 或剪切。'
            '每个任务只写该段的起始状态、逐秒动作、镜头与实际台词；不得复制整片梗概、其他段落或完整角色成长过程。'
            '本段必需的外貌和空间规则简述一次，不在每秒重复；静止状态沿用，变化时再说明，不删掉任何一秒或实际台词。'
            '对白原文保留在 <d>[语言] 原文</d> 中，无对白不要发明对白。'
            '画面禁止字幕、标注、水印和其他文字；音乐服从剧本，无配乐写 N/A。'
            'description、camera、title 保持中文供用户编辑。渲染时工作台按实际参考图顺序转为 Ref2VA 六段格式。\n'
            + (ROOT/'SKILL.md').read_text()+'\n'+(ROOT/'references/base-en.txt').read_text()
            + h3_dialogue.instructions())


def parse(text):
    if not isinstance(text,str):raise ValueError('motion_prompt 必须是字符串')
    matches=list(re.finditer(r'(?m)^([a-z_]+):[ \t]*',text.strip()))
    if tuple(m[1] for m in matches)!=FIELDS or not text.strip().startswith(FIELDS[0]+':'):
        raise ValueError('H3 提示词须按顺序包含 integrated_multimodal_description、overall_soundscape、non_diegetic_music 三段')
    text=text.strip()
    parts={m[1]:text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip() for i,m in enumerate(matches)}
    if not all(parts.values()):raise ValueError('H3 三段内容不能为空；无配乐请写 N/A')
    body=parts[FIELDS[0]]
    if not body.startswith('[Shot 1]') or re.findall(r'\[Shot \d+\]',text)!=['[Shot 1]']:
        raise ValueError('每段 H3 任务必须以 [Shot 1] 开始且仅包含一个连续镜头')
    if re.search(r'<(?:Picture|Video|Audio|Subject)\s+\d+>',text):
        raise ValueError('分镜阶段不得编造参考编号，实际参考图由渲染阶段绑定')
    if text.count('<d>')!=text.count('</d>'):raise ValueError('对白标签未闭合')
    return parts


def validate_shots(result):
    for i,shot in enumerate(result.get('shots',[]),1):
        try:parse(shot.get('motion_prompt'))
        except ValueError as error:raise ValueError(f'镜头 {i}：{error}') from error


def performance_schedule(ref,tag,subjects):
    timing=ref.get('timing') or {}
    if not timing:return f'Play {tag} from local time 0.000 seconds and synchronize the assigned visible speaker to its actual vocals.'
    message=(f'Recording synchronization: {tag} is already cut to this {timing["duration"]:g}-second shot, '
             f'covering global {timing["global_start"]:g}–{timing["global_end"]:g} seconds. '
             f'Play {tag} from its beginning at local time 0.000 seconds, at original speed, through the entire shot. '
             'Global and original-recording times are provenance, NOT additional playback delays. '
             'The waveform controls vocal onsets, syllables, held notes, breaths and rests; do not recompose or redub it. ')
    if 'source_start' in timing:
        message+=(f'The original recording excerpt is {timing["source_start"]:g}–{timing["source_end"]:g} seconds; '
                  f'the song enters the full film at {timing["song_global_start"]:g} seconds '
                  f'and is present in this supplied file from local {timing["song_local_start"]:g} seconds. ')
        if timing.get('tail_padding'):message+=f'The file already includes {timing["tail_padding"]:g} seconds of trailing silence; retain it. '
    if timing.get('cues'):
        message+=('Local vocal cue times are '+('verified' if timing.get('timing_verified') else 'automatic estimates; actual recording timing takes precedence')+'. ')
        for cue in timing['cues']:
            speaker=subjects.get(cue['name'],cue['name'] or 'The assigned performer')
            if cue.get('speaker_id'):speaker+=f' ({cue["speaker_id"]})'
            message+=f'At local {cue["start"]:g}–{cue["end"]:g} seconds, {speaker} '+('sings' if cue['type']=='sing' else 'speaks')+f' with {tag}: <d>[Chinese] {cue["text"]}</d>. '
        message+='Animate only the assigned performer mouth with the actual recorded voice; keep other characters silent. During instrumental gaps and silence, do not invent lip movements or extra lyrics. '
    return message


def render(text,refs,duration,no_text,editor_notes=""):
    parts=parse(text)
    body=parts[FIELDS[0]]+f' The continuous shot lasts exactly {duration} seconds. '+no_text
    if editor_notes.strip():body+='\nProduction directions and dialogue (same shot; these user edits take precedence over conflicting prose):\n'+editor_notes+'\nDo not print these directions or dialogue as subtitles.'
    if not refs:
        parts[FIELDS[0]]=body
        return '\n\n'.join(f'{k}: {parts[k]}' for k in FIELDS)
    definitions=[];retention=[];appearance=[];groups={};performances=[];subjects={}
    image_refs=[r for r in refs if r.get('kind','image')=='image']
    for i,(ref,picture) in enumerate(video_modes.numbered(refs),1):
        if ref.get('kind','image')!='image':
            definitions.append(f'{picture} is a supplied '+('sound reference.' if ref['kind']=='audio' else 'motion and visual reference.'))
            relation='fully_copy' if ref.get('audio_role')=='performance' else 'reference' if ref['kind']=='audio' else 'partially_preserved'
            instruction='Preserve the supplied performance, timing, words, rests and music. Align only the specified speaker mouth to this audio, starting at local time zero. The other character remains silent unless assigned dialogue.' if ref.get('audio_role')=='performance' else 'Follow only the relevant motion, style or sound requested in the shot; do not add unrequested dialogue or subjects.'
            retention.append(f'{picture}: {relation} - {instruction}')
            appearance.append(f'Use {picture} according to the action and sound instructions below.')
            if ref.get('audio_role')=='performance':performances.append((ref,picture))
            continue
        if ref['source']=='previous_tail':
            definitions.append(f'{picture} is a continuity and composition reference extracted from the preceding clip, not a forced first-frame anchor.')
            retention.append(f'{picture} ([Shot 1] opening continuity): partially_preserved - follow opening pose, relative positions and spatial layout while advancing the action; retain the supplied exposure and color without progressive darkening. Original character appearance references supply facial identity and clothing; do not propagate blur or malformed details from this continuity frame, and do not copy visible writing.')
            appearance.append(f'At the opening, use {picture} for continuity with the preceding clip.')
        elif ref['source']=='opening_frame':
            definitions.append(f'{picture} is the new shot opening composition reference, not a forced first-frame anchor.')
            retention.append(f'{picture}: partially_preserved - use opening pose, framing, setting and lighting; original character references supply identity and clothing.')
            appearance.append(f'Begin the new composition guided by {picture}, following the action timeline.')
        else:
            key=(ref['source'],ref.get('label','').split(' · ')[0]) if ref['source']=='element' else ('manual',i)
            groups.setdefault(key,[]).append(picture)
    for n,(key,pictures) in enumerate(groups.items(),1):
        subject=f'<Subject {n}>';sources=', '.join(pictures)
        if key[0]=='element':subjects[key[1]]=subject
        definitions.append(f'{subject} is the relevant visible person, object or environment depicted in {sources}; retain its visible identity and appearance, not any writing or reference-sheet layout.')
        if key[0]=='element':
            definitions[-1]+=' These are auxiliary character, object or environment appearance references, not primary composition references or first-frame anchors. Follow the text for positions, actions, framing and camera movement rather than copying the image pose or viewpoint.'
        from asset_views import sheet_usage
        sheet_rules=dict.fromkeys(sheet_usage(ref.get('character_sheet_layout')) for i,ref in enumerate(image_refs,1)
                                  if ref.get('character_sheet') and f'<Picture {i}>' in pictures)
        for rule in sheet_rules:definitions[-1]+=' '+rule
        if any(ref.get('face_only_conditioning') and f'<Picture {i}>' in pictures for i,ref in enumerate(image_refs,1)):
            definitions[-1]+=' The body-reference heads have been removed from the actual conditioning image. ONLY the large left portrait supplies facial identity. Restore the normal complete head in the video; do not copy the blank body-reference head areas.'
        retention.append(f'{subject} (appears in [Shot 1]): partially_preserved - preserve the relevant visual appearance from {sources}, adapting pose and viewpoint to the requested action without duplicating the subject.')
        appearance.append(f'When {subject} appears in [Shot 1], follow the corresponding appearance in {sources}.')
    for ref,tag in performances:
        speakers=dict.fromkeys((c['name'],c['speaker_id']) for c in ref.get('timing',{}).get('cues',[]) if c.get('speaker_id'))
        if speakers:
            definitions.append(f'{tag} supplies the recorded vocal performance'+(' and accompaniment' if ref.get('timing',{}).get('contains_music') is not False else '')+' for '+', '.join(f'{subjects.get(name,name)} ({sid})' for name,sid in speakers)+'.')
        appearance.append(performance_schedule(ref,tag,subjects))
    if performances:
        tags=', '.join(tag for _,tag in performances)
        parts['overall_soundscape']=f'The complete supplied performance track {tags} is fully copied from local time zero. Preserve only sounds already in the recording; add no competing dialogue, ambience or sound effects. Synchronized vocal performance follows the local schedule in detailed_description.'
        parts['non_diegetic_music']=('N/A. This supplied dialogue segment has no music; preserve its silence.' if all(ref.get('timing',{}).get('contains_music') is False for ref,_ in performances) else f'Preserve the existing accompaniment layer of {tags}, with its original entry time, tempo, pauses and ending. Do not add a new score, restart the song, remove the recorded vocal, or replace its melody.')
    sections={
        'subject_definitions':'\n'.join(definitions),
        'summary':f'[reference generation] Generate one continuous {duration}-second shot using the defined visual references and the action timeline below.',
        'retention_analysis':'\n'.join(retention),
        'detailed_description':'Preserve the visual style specified in the shot and the relevant reference appearance.\n'+body+' '+' '.join(appearance),
        'overall_soundscape':parts['overall_soundscape'],
        'non_diegetic_music':parts['non_diegetic_music'],
    }
    return '\n\n'.join(f'{k}:\n{v}' for k,v in sections.items())
