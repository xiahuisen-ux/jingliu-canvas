"""One continuous master track, with sample-aligned per-shot performance references."""
import math
import hashlib
import json
import uuid
from pathlib import Path
import video_timing


def validate_timeline(p):
    track=p.get('audio_timeline')
    if not track:return
    cursor=0
    for shot in sorted(p.get('shots',[]),key=lambda x:int(x['shot'])):
        segment=shot.get('audio_segment')
        duration=video_timing.shot_duration(shot)
        if not segment or abs(float(segment.get('start',-1))-cursor)>.001 or abs(float(segment.get('end',-1))-(cursor+duration))>.001:
            raise ValueError('镜头已绑定整片音轨，不能直接改变时长或顺序；请先重新剪分音轨与歌词时间码')
        cursor+=duration
    if not math.isfinite(float(track['duration'])) or abs(cursor-float(track['duration']))>.001:
        raise ValueError('音轨总长与镜头总长不一致')


def reference_timing(p,shot):
    """Times in the supplied file are local; project/source offsets are provenance only."""
    segment=shot.get('audio_segment')
    if not segment or segment.get('mode')=='generated':return None
    start=float(segment['start']);end=float(segment['end']);track=p.get('audio_timeline') or {}
    timing={'global_start':start,'global_end':end,'duration':end-start,'playback_start':0,
            'timing_verified':bool(segment.get('timing_verified')),'cues':[]}
    names={c['id']:c.get('name',c['id']) for c in p.get('analysis',{}).get('characters',[])}
    for cue in sorted(segment.get('cues',[]),key=lambda c:float(c['start'])):
        a=float(cue['start']);b=float(cue['end'])
        if not math.isfinite(a) or not math.isfinite(b) or a<0 or b<=a or b>end-start+.001:
            raise ValueError('录音口型时间码必须在本段音频范围内')
        current={k:cue.get(k,'') for k in ('text','speaker','speaker_id','type')}
        current.update(start=a,end=b,name=names.get(cue.get('speaker'),cue.get('speaker','')))
        prior=timing['cues'][-1] if timing['cues'] else None
        if prior and all(prior[k]==current[k] for k in ('speaker','speaker_id','type')) and a-prior['end']<=.5 and not prior['text'].endswith(('，','。','！','？',',','.','!','?')):
            prior.update(text=prior['text']+current['text'],end=b)
        else:timing['cues'].append(current)
    timing['first_vocal_start']=timing['cues'][0]['start'] if timing['cues'] else None
    if track.get('song_source') and 'song_start' in track and 'song_end' in track:
        entry=float(track['song_start']);finish=float(track['song_end'])
        timing['contains_music']=min(end,finish)>max(start,entry)
        if min(end,finish)>max(start,entry):
            timing.update(source_path=track['song_source'],song_global_start=entry,
                          song_local_start=round(max(0,entry-start),6),
                          source_start=round(max(0,start-entry),6),source_end=round(min(end,finish)-entry,6),
                          tail_padding=round(max(0,end-finish),6))
    return timing


def performance_reference(p,shot):
    segment=shot.get('audio_segment')
    if not segment:return None
    validate_timeline(p)
    if segment.get('mode')=='generated':return None
    return {'path':segment['path'],'kind':'audio','source':'performance_audio','label':segment.get('label','本段对白与歌曲原音'),
            'audio_role':'performance','timing':reference_timing(p,shot)}


def prepare_master(st,p):
    """Replace native-dialogue slots with their current video audio; retain the continuous song."""
    track=p.get('audio_timeline') or {}
    if track.get('mode')!='hybrid':return
    validate_timeline(p)
    shots=sorted(p['shots'],key=lambda s:int(s['shot']))
    generated=[s for s in shots if s['audio_segment'].get('mode')=='generated']
    sources={}
    for shot in generated:
        if not shot.get('video') or shot.get('video_stale'):
            raise ValueError(f"镜头 {shot['shot']} 的自然对白待生成，请先生成该段视频")
        source=st.project_path(p['id'],shot['video'])
        if not source.is_file():raise ValueError('自然对白来源视频缺失，请重新生成该段')
        sources[shot['id']]=shot['video']
    backing=st.project_path(p['id'],track['backing_path'])
    if not backing.is_file():raise ValueError('歌曲底轨缺失，请重新制作音轨')
    key=hashlib.sha256(json.dumps([track['backing_path'],sources,[(s['id'],s['audio_segment']) for s in shots]],sort_keys=True).encode()).hexdigest()[:16]
    if track.get('master_revision')==key and track.get('path') and st.project_path(p['id'],track['path']).is_file():return
    target=backing.parent/f'对白与歌曲_{track["duration"]}秒_{key}.wav'
    temporary=target.with_name('.master-'+uuid.uuid4().hex+'.wav')
    args=[st.get_ffmpeg(),'-y','-i',str(backing)]
    indices={}
    for i,shot in enumerate(generated,1):
        args+=['-i',str(st.project_path(p['id'],sources[shot['id']]))];indices[shot['id']]=i
    filters=[]
    for i,shot in enumerate(shots):
        seg=shot['audio_segment'];samples=round((seg['end']-seg['start'])*48000)
        source=indices.get(shot['id'],0)
        trim=f'atrim=end_sample={samples}' if source else f'atrim=start_sample={round(seg["start"]*48000)}:end_sample={round(seg["end"]*48000)}'
        filters.append(f'[{source}:a]aresample=48000,aformat=channel_layouts=stereo,{trim},asetpts=PTS-STARTPTS,apad,atrim=end_sample={samples}[seg{i}]')
    filters.append(''.join(f'[seg{i}]' for i in range(len(shots)))+f'concat=n={len(shots)}:v=0:a=1[master]')
    try:
        st.run_ffmpeg(args+['-filter_complex',';'.join(filters),'-map','[master]','-ar','48000','-ac','2','-c:a','pcm_s24le',str(temporary)])
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    relative=str(target.relative_to(st.project_dir(p['id']).resolve()))
    track.update(path=relative,download_path=relative,status='ready',generated_sources=sources,master_revision=key)


def mux_options(st,p,shot=None):
    track=shot.get('audio_segment') if shot else p.get('audio_timeline')
    if not track:return []
    validate_timeline(p)
    if shot and track.get('mode')=='generated':
        # Audio is required, not an optional map: never report a silent native-dialogue clip as ready.
        return ['-map','0:v:0','-map','0:a:0']
    if not shot:prepare_master(st,p)
    path=st.project_path(p['id'],track['path'])
    if not path.is_file():raise ValueError('绑定的原声音轨缺失，请重新制作音轨')
    return ['-i',str(path),'-map','0:v:0','-map','1:a:0']
