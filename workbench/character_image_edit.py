"""Qwen edit graph retained for explicit multi-image workflows and historical metadata."""
from pathlib import Path
from media_prompts import NO_VISIBLE_TEXT

MODEL = 'Qwen-Image-Edit-2511'
DEFAULTS = {
    'diffusion_model': 'qwen-image-edit-2511-Q5_K_M.gguf',
    'text_encoder': 'qwen_2.5_vl_7b_fp8_scaled.safetensors',
    'vae': 'qwen_image_vae.safetensors',
    'lora': 'Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors',
}
FOLDERS = {'diffusion_model': 'diffusion_models', 'text_encoder': 'text_encoders', 'vae': 'vae', 'lora': 'loras'}
CONDITIONING = 'qwen_image_edit_plus'


def status(cfg):
    root = Path(cfg['qwen_image_root']) / 'models'
    missing = [name for key, name in DEFAULTS.items()
               if not (root / FOLDERS[key] / name).is_file()
               or (root / FOLDERS[key] / name).stat().st_size < 1024 * 1024]
    enabled = cfg.get('character_image_edit_enabled') is True
    ready = enabled and not missing
    reason = '' if ready else (
        '人物图生图需要专用图像编辑模型。当前缺少 Qwen-Image-Edit-2511 权重，'
        '原来的 Z-Image 局部重绘无法可靠地把单人照片变成四视图，已停止使用这条路径。'
        if missing else '人物图像编辑模型尚未启用。')
    return {'ready': ready, 'model': MODEL, 'missing': missing, 'message': reason,
            'steps': 8, 'reference_conditioning': CONDITIONING}


def require_ready(cfg):
    result = status(cfg)
    if not result['ready']:
        raise ValueError(result['message'])
    return result


def legacy_redraw(version):
    from single_image_edit import CONDITIONING as SINGLE_CONDITIONING
    settings = version.get('generation_settings', {})
    valid = settings.get('reference_conditioning') == CONDITIONING or (settings.get('reference_conditioning') == SINGLE_CONDITIONING and settings.get('separate_view_generation'))
    return version.get('mode') == 'image' and not valid


def graph(cfg, reference_name, prompt, width, height, seed):
    require_ready(cfg)
    # The complete reference is encoded independently; the output starts on a new canvas.
    # EditPlus preserves the reference aspect ratio in both its vision and VAE branches.
    positive = ('Render the requested view of the character from Picture 1. '
                'Preserve the person\'s facial identity, body shape, clothing and accessories. '
                'The input photograph is an identity reference, not the output composition.\n'
                + prompt + '\n' + NO_VISIBLE_TEXT)
    negative = 'text, watermark, extra people, duplicate panels, missing feet, incorrect views'
    def encode(text):
        return {'class_type': 'TextEncodeQwenImageEditPlus', 'inputs': {
            'clip': ['2', 0], 'vae': ['3', 0], 'image1': ['12', 0], 'prompt': text}}
    return {
        '1': {'class_type': 'UnetLoaderGGUF', 'inputs': {'unet_name': DEFAULTS['diffusion_model']}},
        '2': {'class_type': 'CLIPLoader', 'inputs': {'clip_name': DEFAULTS['text_encoder'], 'type': 'qwen_image', 'device': 'default'}},
        '3': {'class_type': 'VAELoader', 'inputs': {'vae_name': DEFAULTS['vae']}},
        '4': {'class_type': 'ModelSamplingAuraFlow', 'inputs': {'model': ['1', 0], 'shift': 3.0}},
        '5': {'class_type': 'LoraLoaderModelOnly', 'inputs': {'model': ['4', 0], 'lora_name': DEFAULTS['lora'], 'strength_model': 1.0}},
        '6': encode(positive), '7': encode(negative),
        '8': {'class_type': 'EmptySD3LatentImage', 'inputs': {'width': width, 'height': height, 'batch_size': 1}},
        '9': {'class_type': 'KSampler', 'inputs': {'model': ['5', 0], 'positive': ['6', 0], 'negative': ['7', 0], 'latent_image': ['8', 0], 'seed': seed, 'steps': 8, 'cfg': 1.0, 'sampler_name': 'euler', 'scheduler': 'simple', 'denoise': 1.0}},
        '10': {'class_type': 'VAEDecode', 'inputs': {'samples': ['9', 0], 'vae': ['3', 0]}},
        '11': {'class_type': 'SaveImage', 'inputs': {'images': ['10', 0], 'filename_prefix': 'story_pipeline/character_edit'}},
        '12': {'class_type': 'LoadImage', 'inputs': {'image': reference_name}},
    }
