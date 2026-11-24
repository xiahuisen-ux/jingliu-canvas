#!/usr/bin/env python3
"""文字 -> Qwen3.8 分镜 -> Qwen-Image 关键帧 -> MiniMax H3 视频。"""

from __future__ import annotations

import json
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
import http.client
import local_http
from pathlib import Path
from media_prompts import NO_VISIBLE_TEXT

HERE = Path(__file__).resolve().parent
CFG = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
from portable_paths import BACKENDS, DATA
overrides = DATA / 'backends.json'
if overrides.is_file():
    CFG.update(json.loads(overrides.read_text(encoding='utf-8')))
for key in ('qwen_image_root','qwen_image_python'):
    CFG[key] = str(BACKENDS / Path(CFG[key]).expanduser())
TASK_CONTEXT = threading.local()


def check_cancelled():
    callback=getattr(TASK_CONTEXT,"check",None)
    if callback:callback()


def request_json(url: str, payload=None, timeout=120):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with local_http.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def plan_story(text: str, shot_count: int, aspect: str, duration: float):
    schema = {
        "type": "object",
        "required": ["title", "global_style", "character_bible", "shots"],
        "properties": {
            "title": {"type": "string"},
            "global_style": {"type": "string"},
            "character_bible": {"type": "string"},
            "shots": {
                "type": "array",
                "minItems": shot_count,
                "maxItems": shot_count,
                "items": {
                    "type": "object",
                    "required": ["shot", "keyframe_prompt", "video_prompt"],
                    "properties": {
                        "shot": {"type": "integer"},
                        "summary": {"type": "string"},
                        "keyframe_prompt": {"type": "string"},
                        "video_prompt": {"type": "string"},
                        "dialogue": {"type": "string"}
                    }
                }
            }
        }
    }
    instruction = f"""你是电影导演和 AI 视频提示词专家。把用户需求拆成恰好 {shot_count} 个连续镜头。
画幅：{aspect}；每镜头约 {duration} 秒。
输出严格 JSON。global_style 与 character_bible 必须让人物、服装、场景跨镜头一致。
keyframe_prompt 用英文，描述镜头第一帧，必须完整复述人物外貌、服装、场景、构图、镜头、光线和风格；不要描述动作过程。
video_prompt 用英文，供 MiniMax H3 图生视频，必须写清时间段、主体动作、镜头运动、环境运动、物理约束；若有台词，写出准确台词及声音要求。
不得使用“同上”“same character”等依赖上下文的缩写。

用户需求：{text}"""
    result = request_json(CFG["ollama_url"] + "/api/chat", {
        "model": CFG["ollama_model"],
        "stream": False,
        "keep_alive": 0,
        "format": schema,
        "options": {"temperature": 0.45, "num_ctx": 16384},
        "messages": [{"role": "user", "content": instruction}]
    }, timeout=900)
    return json.loads(result["message"]["content"])


def qwen_image_graph(prompt: str, width: int, height: int, seed: int, steps: int = 4):
    prompt=prompt+'\n'+NO_VISIBLE_TEXT
    m = CFG["qwen_image"]
    negative = "low resolution, low quality, malformed anatomy, extra fingers, bad hands, distorted face, text, watermark, logo, blur, noise"
    return {
        "1": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": m["diffusion_model"]}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["text_encoder"], "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.1}},
        "5": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["4", 0], "lora_name": m["lora"], "strength_model": 1.0}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["5", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0], "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": "story_pipeline/keyframe"}}
    }


def z_image_graph(prompt: str, width: int, height: int, seed: int, steps: int = 8):
    prompt=prompt+'\n'+NO_VISIBLE_TEXT
    m = CFG["z_image"]
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": m["diffusion_model"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": m["text_encoder"], "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": m["vae"]}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["6", 0]}},
        "8": {"class_type": "EmptySD3LatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "9": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["8", 0], "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "11": {"class_type": "SaveImage", "inputs": {"images": ["10", 0], "filename_prefix": "story_pipeline/z_image"}}
    }


def image_graph(prompt, width, height, seed, steps=None):
    if CFG.get("image_backend", "qwen_image") == "z_image":
        return z_image_graph(prompt,width,height,seed,8 if steps is None else steps)
    return qwen_image_graph(prompt,width,height,seed,4 if steps is None else steps)


def queue_and_wait(base_url: str, graph: dict, label: str):
    check_cancelled()
    response = request_json(base_url + "/prompt", {"prompt": graph, "client_id": "local-story-director"}, timeout=60)
    if "error" in response:
        raise RuntimeError(json.dumps(response, ensure_ascii=False, indent=2))
    prompt_id = response["prompt_id"]
    callback=getattr(TASK_CONTEXT,"prompt",None)
    if callback:callback(base_url,prompt_id)
    print(f"  {label} 已入队：{prompt_id}")
    failures = 0
    while True:
        check_cancelled()
        try:
            history = request_json(base_url + "/history/" + prompt_id, timeout=10)
            failures = 0
        except (OSError, http.client.HTTPException) as error:
            # Only retry reads; submitting /prompt twice would create duplicate GPU jobs.
            if isinstance(error, urllib.error.HTTPError) and error.code not in {408, 429, 500, 502, 503, 504}:
                raise
            failures += 1
            if failures >= 6:
                raise RuntimeError(f'{label} 进度连接连续失败，停止本次任务并释放模型') from error
            print(f'  {label} 进度连接中断，正在重连（{failures}/6）', flush=True)
            for _ in range(min(failures * 4, 20)):
                check_cancelled(); time.sleep(.25)
            continue
        if prompt_id in history:
            item = history[prompt_id]
            status = item.get("status", {})
            if status.get("status_str") == "error" or not status.get("completed", True):
                raise RuntimeError(f"{label} 失败：{json.dumps(status, ensure_ascii=False)}")
            return item
        for _ in range(10):
            check_cancelled();time.sleep(.25)


def first_output(history: dict, kind: str):
    for output in history.get("outputs", {}).values():
        for item in output.get(kind, []):
            return item
        # ComfyUI 0.37 的 SaveVideo 会把 MP4 放在 images 字段中。
        if kind == "videos":
            for item in output.get("images", []):
                if Path(item.get("filename", "")).suffix.lower() in {".mp4", ".webm", ".mov", ".mkv"}:
                    return item
    raise RuntimeError(f"ComfyUI 历史记录中没有 {kind} 输出")


def free_models(base_url: str):
    try:
        request_json(base_url + "/free", {"unload_models": True, "free_memory": True}, timeout=30)
    except Exception:
        pass


def dimensions(aspect: str):
    table = {
        "portrait": ((928, 1664), (352, 608)),
        "landscape": ((1664, 928), (608, 352)),
        "square": ((1328, 1328), (448, 448)),
    }
    return table[aspect]



if __name__ == "__main__":
    raise SystemExit("旧命令行视频流程已并入网页工作台，请运行 启动_AI影视工作台.command；视频仅使用 h3.c Metal。")
