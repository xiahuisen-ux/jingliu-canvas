"""Explicit, backwards-compatible workbench performance controls (no model load)."""
LAYERS = (45, 50)
REUSE = (1, 2)
VIDEO_CAPS = (0, 147456, 358400, 589824)
D_PROFILE = dict(h3c_steps=15, h3c_layers=45, h3c_reuse=2,
                 h3c_reference_video_max_pixels=358400)


def validate(layers=50, reuse=1, reference_video_max_pixels=0, steps=15):
    for name, value, choices in (('层数', layers, LAYERS), ('reuse', reuse, REUSE),
                                ('参考视频像素预算', reference_video_max_pixels, VIDEO_CAPS)):
        if type(value) is not int or value not in choices:
            raise ValueError(f'H3 {name}必须为 {choices} 中的整数')
    if steps < 8 and reuse != 1:
        raise ValueError('H3 4–7 步预览须使用 reuse 1；reuse 2 请至少设置 8 步')
    return dict(layers=layers, reuse=reuse, reference_video_max_pixels=reference_video_max_pixels)
