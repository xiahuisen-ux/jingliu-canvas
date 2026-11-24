"""Pinned image-to-image references, including references inherited by video frames."""
import copy
import math
from PIL import Image, ImageOps, ImageDraw


def from_video(st,p,node_id,seen=None):
    import canvas_videos,video_workflow
    seen=set() if seen is None else seen
    if node_id in seen:return []
    seen.add(node_id)
    try:shot=copy.deepcopy(canvas_videos.node(p,node_id))
    except ValueError:return []
    if shot.get('canvas_origin',{}).get('operation')=='upscale':
        return from_video(st,p,shot['canvas_origin']['node_id'],seen)
    shot.update(inherit_previous=False,inherit_previous_manual=True)
    shot.pop('opening_reference_image',None)
    rows,_=video_workflow.image_references(st,copy.deepcopy(p),shot)
    result=[];used=set()
    for row in rows:
        path=row.get('preview_path') or row['path'];eid=row.get('entity_id')
        if not eid:
            link=next((x for x in shot.get('canvas_image_links',[]) if x['path']==path),None)
            eid=link['node_id'][6:] if link else None
        if not eid or (eid,path) in used:continue
        try:kind,item=st.entity_from_project(p,eid)
        except ValueError:continue
        if kind not in ('characters','locations'):continue
        result.append({'entity_id':eid,'path':path,'kind':kind,'label':item['name']});used.add((eid,path))
    return result


def links(st,p,item):
    if 'canvas_redraw_links' in item:return copy.deepcopy(item['canvas_redraw_links'])
    origin=item.get('canvas_origin',{})
    return from_video(st,p,origin['node_id']) if origin.get('operation')=='extract_frame' else []


def validate_link(st,p,item,eid,path):
    import canvas_images
    canvas_images.candidate(st,p,eid,path)
    target=item['id'];seen=set()
    def reaches(current):
        if current==target:return True
        if current in seen:return False
        seen.add(current);_,other=st.entity_from_project(p,current)
        ids=[r['entity_id'] for r in links(st,p,other)]
        if other.get('canvas_parent'):ids.append(other['canvas_parent']['entity_id'])
        if other.get('canvas_reference',{}).get('node_id','').startswith('asset:'):ids.append(other['canvas_reference']['node_id'][6:])
        return any(reaches(x) for x in ids)
    if reaches(eid):raise ValueError('参考连线不能连接自身或形成循环')


def inputs(st,p,item,base):
    import canvas_images
    rows=links(st,p,item);paths=list(base)
    for row in rows:
        canvas_images.candidate(st,p,row['entity_id'],row['path'])
        if row['path'] not in paths:paths.append(row['path'])
    return paths


def prepare(st,p,item,paths,folder):
    """Qwen has three image slots. Keep the base whole; pack extras into labeled boards."""
    rows=links(st,p,item);by_path={r['path']:r for r in rows}
    if not rows:return paths,''
    lines=['Picture 1 is the primary image. Preserve its camera, composition, pose, subject count and spatial arrangement unless the requested edit explicitly changes them.',
           'Additional pictures are references only: match visible character identities and clothing, and match scene geometry and materials. Never add absent characters or copy reference panels into the output.']
    if len(paths)<=3:
        for i,path in enumerate(paths[1:],2):
            row=by_path.get(path,{})
            lines.append(f"Picture {i}: {row.get('kind','image')} reference, {row.get('label','reference image')}.")
        return paths,'\n'.join(lines)
    extra=paths[1:]
    groups=[[x for x in extra if by_path.get(x,{}).get('kind')=='characters'],[x for x in extra if by_path.get(x,{}).get('kind')!='characters']]
    actual=[paths[0]]
    for group in groups:
        if not group:continue
        index=len(actual)+1
        if len(group)==1:
            actual.append(group[0]);row=by_path.get(group[0],{});lines.append(f"Picture {index}: {row.get('kind','image')} reference, {row.get('label','reference image')}.");continue
        cols=math.ceil(math.sqrt(len(group)));rows_count=math.ceil(len(group)/cols);tile=min(768,2048//max(cols,rows_count))
        board=Image.new('RGB',(cols*tile,rows_count*tile),(35,35,35));draw=ImageDraw.Draw(board)
        for j,path in enumerate(group):
            with Image.open(st.project_path(p['id'],path)) as source:
                thumb=ImageOps.contain(ImageOps.exif_transpose(source).convert('RGB'),(tile-12,tile-32))
            x=(j%cols)*tile;y=(j//cols)*tile;board.paste(thumb,(x+(tile-thumb.width)//2,y+26+(tile-26-thumb.height)//2));draw.text((x+8,y+6),str(j+1),fill='white')
            row=by_path.get(path,{})
            lines.append(f"Picture {index}, numbered reference {j+1}: {row.get('kind','image')} {row.get('label','reference image')}.")
        target=folder/f'reference-board-{index}.png';board.save(target);actual.append(str(target.relative_to(st.project_dir(p['id']).resolve())))
        lines.append(f'Picture {index} is a reference board, not the output layout. Ignore all numbers, borders and reference poses.')
    return actual,'\n'.join(lines)
