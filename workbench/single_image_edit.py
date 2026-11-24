"""Fast single-reference asset redraw. Multi-reference tail editing stays separate."""
import hashlib
from pathlib import Path

MODEL = 'Z-Image-Turbo'
CONDITIONING = 'z_image_vae_redraw_v4'
CHARACTER_DENOISE = .85
MATCHED_VIEW_DENOISE = .35
LAYOUTS = ('four-view-headless-front','four-view','face-front-body-back')


def validated_edges(value, layout):
    import math
    count=4 if layout=='face-front-body-back' else 5
    if not isinstance(value,(list,tuple)) or len(value)!=count:raise ValueError('分栏边界数量不正确')
    try:edges=list(map(float,value))
    except (TypeError,ValueError):raise ValueError('分栏边界必须是数字') from None
    if not all(math.isfinite(x) for x in edges) or edges[0]!=0 or edges[-1]!=1 or any(b-a<.03 for a,b in zip(edges,edges[1:])):raise ValueError('分栏边界必须从0递增到1')
    return edges


def detect_panel_edges(source):
    """Recognize three long dividers, not image semantics or character identity.

    A wide aspect ratio alone is insufficient. Explicit 'ordinary image' always
    overrides this heuristic; borderless sheets can be declared in the input UI.
    """
    from PIL import Image,ImageOps
    with Image.open(source) as original:
        im=ImageOps.exif_transpose(original).convert('RGB');w,h=im.size
        if not 2.2<=w/h<=2.8 or w<300 or h<100:return None
        pixels=im.load();ys=range(h//20,h-h//20,max(1,h//60));edges=[0]
        for left,right in ((.34,.44),(.55,.65),(.75,.85)):
            best=(0,0)
            for x in range(int(w*left),int(w*right)):
                values=sorted(sum(abs(pixels[x,y][c]-(pixels[x-1,y][c]+pixels[x+1,y][c])/2) for c in range(3))/3 for y in ys)
                score=values[len(values)//5] # Divider must exist across at least 80% of sampled rows.
                if score>best[0]:best=(score,x)
            if best[0]<8:return None
            edges.append(best[1]/w)
        return edges+[1]


def source_spec(asset, ref, source):
    import asset_views
    explicit=ref in asset.get('source_layouts',{})
    layout=asset.get('source_layouts',{}).get(ref) if explicit else asset_views.sheet_layout(asset,ref)
    edges=asset.get('source_panel_edges',{}).get(ref)
    if layout:
        if layout not in LAYOUTS:raise ValueError('参考图布局不正确')
        if edges is None:
            version=next((v for v in asset.get('versions',[]) if ref in v.get('images',[])),{})
            edges=version.get('source_panel_edges')
        if edges is None and layout in {'four-view','four-view-headless-front'}:edges=detect_panel_edges(source)
        return {'layout':layout,'edges':validated_edges(edges,layout) if edges else None,'detected':False}
    if not explicit:
        edges=detect_panel_edges(source)
        if edges:return {'layout':'four-view','edges':edges,'detected':True}
    return {'layout':None,'edges':None,'detected':False}


def status(cfg):
    root = Path(cfg['qwen_image_root']) / 'models'
    folders = {'diffusion_model': 'diffusion_models', 'text_encoder': 'text_encoders', 'vae': 'vae'}
    missing = [cfg.get('z_image', {}).get(key, key) for key, folder in folders.items()
               if not cfg.get('z_image', {}).get(key)
               or not (root / folder / cfg['z_image'][key]).is_file()]
    return {'ready': not missing, 'model': MODEL, 'missing': missing, 'steps': 8,
            'reference_conditioning': CONDITIONING,
            'message': '缺少 Z-Image-Turbo 模型文件：' + '、'.join(missing) if missing else ''}


def require_ready(cfg):
    result = status(cfg)
    if not result['ready']:
        raise ValueError(result['message'])
    return result


def view_crop(layout, view, edges=None):
    """Known sheet layouts provide a view, never four subjects to one latent."""
    if not layout:return [0,0,1,1]
    if layout=='four-view-headless-front':
        defaults=[0,.4,.6,.8,1];keys=['face','front','side','back']
    elif layout=='four-view':
        defaults=[0,.25,.5,.75,1];keys=['face','front','side','back']
    elif layout=='face-front-body-back':
        defaults=[0,1/3,2/3,1];keys=['face','front','back']
        if view=='side':view='front' # Old three-panel sheets have no side source.
    else:raise ValueError('不支持的角色设定图布局')
    if view not in keys:raise ValueError('参考视角不正确')
    edges=validated_edges(edges,layout) if edges is not None else defaults
    i=keys.index(view);return [edges[i],0,edges[i+1],1]


def prepare_source(source, input_dir, width, height, *, view=None, layout=None, crop=None, edges=None):
    """Fit complete reference pixels to the latent canvas; never crop off the face."""
    from PIL import Image, ImageOps
    source = Path(source)
    import json
    from character_sheet_layout import validated_crop
    panel=view_crop(layout,view,edges) if view else [0,0,1,1]
    crop=validated_crop(crop) if crop is not None else [0,0,1,1]
    # User crop is relative to the isolated panel, for both sheets and ordinary photos.
    box=[panel[0]+crop[0]*(panel[2]-panel[0]),crop[1],panel[0]+crop[2]*(panel[2]-panel[0]),crop[3]]
    digest = hashlib.sha256(source.read_bytes()+json.dumps(box).encode()).hexdigest()[:24]
    target = Path(input_dir) / f'studio_single_{digest}_{width}x{height}.png'
    if not target.exists():
        with Image.open(source) as original:
            original = ImageOps.exif_transpose(original).convert('RGB')
            w,h=original.size
            original=original.crop((round(box[0]*w),round(box[1]*h),round(box[2]*w),round(box[3]*h)))
            if not original.width or not original.height:raise ValueError('原图裁切范围过小')
            fitted = ImageOps.contain(original, (width, height), Image.Resampling.LANCZOS)
            canvas = Image.new('RGB', (width, height), (166, 166, 166))
            canvas.paste(fitted, ((width-fitted.width)//2, (height-fitted.height)//2))
            canvas.save(target)
    return target.name
