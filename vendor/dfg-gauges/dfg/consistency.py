# -*- coding: utf-8 -*-
"""一致性检测器：这两张图是同一个人吗？跨视角漂了多少？

## 为什么单独做这个

文本模型的"跑偏"还能通读发现，**画面的一致性漂移是肉眼迟滞的**：
单张看都不错，连着 20 集看才发现"这个人每集在换脸"。而且它恰恰是开源生态里
最缺、演示效果最直观的一环 —— 一张滑条、一个分数，比一万字说明有说服力。

## 口径（必须先说清，否则分数没有意义）

**不同 backbone 的余弦分不可比。** 同一个动漫角色，CLIP-L 给 0.86、CLIP-H 给 0.92、
ArcFace 直接不适用（它对画风不敏感、只认人脸）。所以本模块的每条结论都带
`backend` 与 `floor`，跨次比较只在**同后端 + 同预处理**下成立。

| backend | 适合 | 不适合 | 典型强一致线 |
|---|---|---|---|
| `hf`（OpenAI CLIP-L） | 动漫 / 3D / 写实全身 | 精细五官差异 | 0.80 |
| `comfy`（CLIP-ViT-H-14 laion2B） | 与 ComfyUI 出图同源，口径最贴 | 需要本地权重 | 0.70 |
| `arcface`（InsightFace） | 真人脸 | 动漫、非人脸视角（背影/全身） | 0.45 |

## 用法

    >>> from dfg.consistency import compare, verdict_line
    >>> rep = compare("cast/a/anchor.png", ["cast/a/v_side.png", "cast/a/v_back.png"])
    >>> print(verdict_line(rep))
    [一致性] backend=hf median=0.872 min=0.755（2 张）✅ 一致

    # 拿单个分数（自建流水线时）
    >>> from dfg.consistency import similarity
    >>> similarity("a.png", "b.png")            # 0..1
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_BACKEND = "auto"
DEFAULT_FLOOR = {
    "hf": 0.80,          # OpenAI CLIP-L：动漫/写实在 0.80 以上算稳
    "comfy": 0.70,       # 与 DreamForge 出图同源口径（P1#4 实测线）
    "arcface": 0.45,     # 真人脸（ArcFace cosine，量纲完全不同）
}

# 按视角分级的强一致线 —— **一刀切是错的**，这是实测出来的，不是拍脑袋。
#
# 用 419 张真实角色卡（comfy / CLIP-ViT-H-14）逐视角量过：
#
#   视角             median   p5     低于 0.70 的占比
#   three_quarter    0.872    0.760   0.5%
#   side             0.865    0.776   1.2%
#   full             0.755    0.547  24.8%   ← 一刀切会把四分之一的卡误判成漂移
#   back             0.812    0.593  16.5%
#
# 换成下面这组分级线后，全部 419 张里只有 16 张真的报警（3.8%），
# 而这 16 张确实该重绘。原因不神秘：全身和背影的**构图占比变化最大**，
# 全局 CLIP 特征被背景和人体姿态稀释，同样一个人分数天然就低。
# 拿正面的尺子量全身，只会让人习惯性忽略告警 —— 那比没有量具更糟。
FLOOR_BY_VIEW = {
    "three_quarter": 0.70,
    "side": 0.70,
    "full": 0.48,
    "back": 0.50,
}

_DISCLAIMER = ("分数只在**同 backend、同预处理**下可比。跨 backbone 直接比大小没有意义"
               "（CLIP-L 0.87 与 CLIP-H 0.92 可能描述的是同一张图）。")


class BackendMissing(RuntimeError):
    """所需依赖/权重不在。**明确报错，绝不静默返回 0** —— 假 0 分比没有分更危险。"""


# ============================================================ 向量与相似度
def _l2norm(x):
    import numpy as np
    n = np.linalg.norm(x, axis=-1, keepdims=True)
    return x / np.clip(n, 1e-12, None)


def cosine(a, b) -> float:
    """两个向量的余弦 —— **纯 Python，不需要 numpy**。

    这是"是不是同一个人"的最后一环。不该因为没装 numpy 就让整个量具不可用：
    1024 维点积用循环算，单次成本可以忽略，而 numpy 是可选依赖。
    """
    import math

    va, vb = list(a), list(b)
    n = min(len(va), len(vb))
    if n == 0:
        return 0.0
    dot = na = nb = 0.0
    for i in range(n):
        x = float(va[i])
        y = float(vb[i])
        dot += x * y
        na += x * x
        nb += y * y
    den = math.sqrt(na) * math.sqrt(nb)
    return dot / den if den > 1e-12 else 0.0


def score_matrix(embs):
    """`(N, D)` 归一化向量 → `(N, N)` 余弦矩阵（诊断用：一眼看出谁离群）。"""
    import numpy as np
    e = _l2norm(np.asarray(embs, dtype="float32"))
    return e @ e.T


# ============================================================ 后端
def _embed_hf(images, device="auto"):
    """OpenAI CLIP（ViT-L/14）。通用性最好，pip 装得上。"""
    try:
        import torch
        from PIL import Image
        from transformers import CLIPModel, CLIPProcessor
    except Exception as e:                                  # noqa: BLE001
        raise BackendMissing(
            "hf 后端需要 torch + transformers + pillow：\n"
            "  pip install torch transformers pillow\n"
            f"原始错误：{type(e).__name__}: {e}") from e

    dev = device
    if dev == "auto":
        dev = "cuda" if torch.cuda.is_available() else "cpu"
    model_id = "openai/clip-vit-large-patch14"
    try:
        model = CLIPModel.from_pretrained(model_id).to(dev).eval()
        proc = CLIPProcessor.from_pretrained(model_id)
    except Exception as e:                                  # noqa: BLE001
        raise BackendMissing(
            f"加载 {model_id} 失败（首次需联网下载，或先把权重放本地）：\n"
            f"{type(e).__name__}: {e}") from e

    out = []
    with torch.inference_mode():
        for p in images:
            img = Image.open(str(p)).convert("RGB")
            inputs = proc(images=img, return_tensors="pt").to(dev)
            feats = model.get_image_features(**inputs)
            out.append(feats[0].float().cpu().numpy())
            del img, inputs, feats                       # 批量几百张时不回收会吃满显存
    import numpy as np
    return _l2norm(np.stack(out))


def find_clip_vision() -> str:
    """在常见位置找 CLIP-ViT-H-14 权重，找不到返回空串。

    老用户手上这份权重通常已经在 `ComfyUI/models/clip_vision/` 里了 ——
    让人为了跑一个分数再下一份 3.9G 是没道理的。查找顺序：
      ① 环境变量 `COMFYUI_PATH` / `COMFYUI_ROOT` 指向的 ComfyUI 根；
      ② 从已导入的 `comfy` 包位置反推（`.../ComfyUI/comfy/clip_vision.py` 的上上级）。
    """
    roots = []
    for env in ("COMFYUI_PATH", "COMFYUI_ROOT"):
        v = os.environ.get(env)
        if v:
            roots.append(Path(v))
    try:
        import comfy.clip_vision as _cv
        roots.append(Path(_cv.__file__).resolve().parent.parent)
    except Exception:                                       # noqa: BLE001
        pass

    pats = ("CLIP-ViT-H-14*.safetensors", "*CLIP*ViT*H*.safetensors",
            "*clip*vision*.safetensors")
    for root in roots:
        d = root / "models" / "clip_vision"
        if not d.is_dir():
            continue
        for pat in pats:
            hits = sorted(d.glob(pat))
            if hits:
                return str(hits[0])
    return ""


def _embed_comfy(images, device="auto", clip_path=None):
    """复用 ComfyUI 的 CLIP-ViT-H-14（与出图同源，口径最贴本地流水线）。"""
    try:
        import numpy as np
        import torch
        from PIL import Image
        import comfy.clip_vision
    except Exception as e:                                  # noqa: BLE001
        raise BackendMissing(
            "comfy 后端需要在 ComfyUI 的运行环境里跑（依赖 comfy / torch）：\n"
            f"{type(e).__name__}: {e}\n"
            "提示：路径用 --clip 指定，或放到 ComfyUI/models/clip_vision/ 下自动找。") from e

    if not clip_path:
        clip_path = find_clip_vision()                      # 手上已有就别再下一份
    if not clip_path:
        raise BackendMissing(
            "comfy 后端需要 CLIP-ViT-H-14 的 safetensors：\n"
            "  ① --clip 指到具体文件；或\n"
            "  ② 放到 <ComfyUI>/models/clip_vision/ 下（设 COMFYUI_PATH 或在本环境装 comfy）；或\n"
            "  ③ 干脆用 --backend hf（会自动下载 openai/clip-vit-large-patch14）。")

    # 模型按路径缓存 —— 权重是 3.9G，反复 load 会把这套量具从"能批量用"
    # 变成"只能单张玩"。进程内同一份权重只加载一次。
    key = str(Path(str(clip_path)).resolve())
    model = _COMFY_CACHE.get(key)
    if model is None:
        model = comfy.clip_vision.load(key)
        _COMFY_CACHE[key] = model

    # device="cpu" 必须真生效：16G 卡上 ComfyUI / Ollama 常驻十几 G 时，
    # 量具去抢显存的结果是自己 OOM 或者把出图任务挤死。量具是旁路，
    # 不该有资格影响产线。ComfyUI 用全局 cpu_state 表达这个意思。
    try:
        import comfy.model_management as _mm
    except Exception:                                       # noqa: BLE001
        _mm = None
    if device == "cpu" and _mm is not None:
        try:
            _mm.cpu_state = _mm.CPUState.CPU
        except Exception:                                   # noqa: BLE001
            pass

    # 逐张回收显存 —— 这不是保险，是必需。2026-10-30 的日志实证：不带
    # inference_mode、也不回收缓存时，逐张累积到第 4 张就 CUDA OOM
    # （51GB allocated）。批量测几百张卡时这一条决定能不能跑完。

    out = []
    with torch.inference_mode():
        for p in images:
            img = Image.open(str(p)).convert("RGB")
            arr = np.asarray(img).astype("float32") / 255.0
            t = torch.from_numpy(arr)[None, ..., :3]
            res = model.encode_image(t)                     # comfy 的 Output 包装
            e = res["image_embeds"]                         # [1, D] —— 不是 res[0]
            out.append(e[0].float().cpu().numpy().reshape(-1))
            del img, arr, t, res, e
            try:
                if _mm is not None:
                    _mm.soft_empty_cache()
                elif torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:                               # noqa: BLE001
                pass
    return _l2norm(np.stack(out))


def _embed_arcface(images, device="auto"):
    """InsightFace ArcFace —— **只对人脸**。背影/全身/动漫会直接不适用。"""
    try:
        import numpy as np
        from insightface.app import FaceAnalysis
    except Exception as e:                                  # noqa: BLE001
        raise BackendMissing(
            "arcface 后端需要 insightface + onnxruntime：\n"
            "  pip install insightface onnxruntime\n"
            f"原始错误：{type(e).__name__}: {e}") from e

    app = FaceAnalysis(name="buffalo_l",
                       providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0 if device != "cpu" else -1, det_size=(640, 640))
    out = []
    for p in images:
        import cv2
        img = cv2.imread(str(p))
        faces = app.get(img) if img is not None else []
        if not faces:
            raise BackendMissing(
                f"这张图里没检出人脸：{Path(p).name}。\n"
                "arcface 只适用于正面/近景真人脸；背影、全身、动漫请用 hf/comfy 后端。")
        e = faces[0].normed_embedding
        out.append(np.asarray(e, dtype="float32"))
    return _l2norm(np.stack(out))


_BACKENDS = {"hf": _embed_hf, "comfy": _embed_comfy, "arcface": _embed_arcface}

# comfy 权重缓存：路径 → 已加载模型。3.9G 的权重整进程复用一份。
_COMFY_CACHE: dict = {}

# auto 探测的「真可用」判据：光能 import 顶层包不算（例如装了 transformers
# 但没 torch，`import transformers` 会成功却跑不了任何模型 —— 假阳）。
_PROBE = {
    "hf": ("transformers", "torch", "PIL"),
    "comfy": ("comfy.clip_vision", "torch", "PIL"),
    "arcface": ("insightface", "cv2"),
}


def pick_backend(prefer: str = DEFAULT_BACKEND) -> str:
    """选后端：`auto` 时按 hf → comfy → arcface 探一遍真可用性，全不行就抛。"""
    import importlib

    if prefer and prefer not in ("auto", ""):
        if prefer not in _BACKENDS:
            raise BackendMissing(f"未知后端 {prefer!r}，可选：{sorted(_BACKENDS)}")
        mods = _PROBE.get(prefer, ())
        absent = []
        for m in mods:
            try:
                importlib.import_module(m)
            except Exception:                               # noqa: BLE001
                absent.append(m)
        if absent:
            raise BackendMissing(
                f"{prefer} 后端缺依赖：{absent}。\n"
                + ("  pip install torch transformers pillow\n" if prefer == "hf" else "")
                + ("  pip install insightface onnxruntime\n" if prefer == "arcface" else ""))
        return prefer

    for name in ("hf", "comfy", "arcface"):
        try:
            for m in _PROBE[name]:
                importlib.import_module(m)
            return name
        except Exception:                                   # noqa: BLE001
            continue
    raise BackendMissing(
        "没有可用后端（要能真跑，不只看 import）。至少装一个：\n"
        "  pip install torch transformers pillow   # hf（推荐，最通用）\n"
        "  pip install insightface onnxruntime      # arcface（真人脸）\n"
        "  comfy 后端需在 ComfyUI 环境中运行（需 comfy + torch）。\n"
        "（不静默返回 0 分 —— 假分数比没有分数更危险。）")


def embed(images, backend=DEFAULT_BACKEND, device="auto", clip_path=None):
    """把若干图片编码成 L2 归一化向量矩阵 `(N, D)`。"""
    imgs = [Path(str(x)) for x in images]
    missing = [str(p) for p in imgs if not p.is_file()]
    if missing:
        raise FileNotFoundError(f"图片不存在：{missing}")
    name = pick_backend(backend)
    fn = _BACKENDS[name]
    if name == "comfy":
        return fn(imgs, device=device, clip_path=clip_path)
    return fn(imgs, device=device)


# ============================================================ 比较
def _floor_for(name, floor, backend, default_floor):
    """给某一张参考图定阈值。

    `floor` 三种写法：
      * `None` / 数字  —— 一律用这个（默认 = DEFAULT_FLOOR[backend]），老行为不变；
      * `"auto"`       —— 按视角名查 FLOOR_BY_VIEW（认不出就回到默认值）；
      * `dict`         —— 自己给 `{"full": 0.45, ...}`，缺的键用默认值。
    """
    if isinstance(floor, dict):
        return float(floor.get(Path(name).stem, default_floor))
    if isinstance(floor, str) and floor.strip().lower() == "auto":
        return float(FLOOR_BY_VIEW.get(Path(name).stem, default_floor))
    if floor is None:
        return float(default_floor)
    return float(floor)


def compare(anchor, refs, backend=DEFAULT_BACKEND, floor=None,
            device="auto", clip_path=None) -> dict:
    """锚图 vs 若干参考图：逐张分数 + median/min/max + 漂移判定。

    `floor` 默认 `None` = 用该后端的统一强一致线；传 `"auto"` 则**按视角分级**
    （全身/背影给更低的下限，见 FLOOR_BY_VIEW 里的实测数据）。测跨视角一致性
    时强烈建议用 `"auto"` —— 一刀切在全身视角上会有约四分之一的假警报。

    返回::

        {"backend": "hf", "floor": 0.8, "count": 3,
         "scores": {"v_side.png": 0.905, ...},
         "floors": {"v_side.png": 0.8, ...},   # 每张图各自用的阈值
         "median": 0.872, "min": 0.755, "max": 0.913,
         "drift": ["v_back.png"],            # 低于各自 floor 的那几张
         "verdict": "consistent" | "drifted",
         "disclaimer": "..."}
    """
    refs = [Path(str(x)) for x in (refs or [])]
    if not refs:
        raise ValueError("refs 为空：没什么可比")
    imgs = [Path(str(anchor))] + refs
    embs = embed(imgs, backend=backend, device=device, clip_path=clip_path)
    name = pick_backend(backend)
    base_floor = float(DEFAULT_FLOOR[name])

    base = embs[0]
    scores = {}
    floors = {}
    for i, p in enumerate(refs, start=1):
        scores[p.name] = round(cosine(base, embs[i]), 4)
        floors[p.name] = _floor_for(p.name, floor, name, base_floor)

    vals = sorted(scores.values())
    mid = (vals[len(vals) // 2] if len(vals) % 2
           else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2)
    drift = [k for k, v in scores.items() if v < floors[k]]
    # `floor` 字段：分级时给 "auto"（避免把 0.48 当成全局阈值误读），
    # 单值时给数字（老调用方直接拿它做比较，保持兼容）。
    grad = isinstance(floor, dict) or (isinstance(floor, str)
                                       and floor.strip().lower() == "auto")
    return {
        "backend": name,
        "floor": "auto" if grad else float(floor) if floor is not None else base_floor,
        "floors": floors,
        "count": len(refs),
        "scores": scores,
        "median": round(mid, 4),
        "min": vals[0],
        "max": vals[-1],
        "drift": drift,
        "verdict": "drifted" if drift else "consistent",
        "disclaimer": _DISCLAIMER,
    }


def similarity(a, b, backend=DEFAULT_BACKEND, device="auto", clip_path=None) -> float:
    """两张图的相似度（0..1）。自定义流水线里最常用的那个函数。"""
    name = pick_backend(backend)
    embs = embed([a, b], backend=name, device=device, clip_path=clip_path)
    return round(cosine(embs[0], embs[1]), 4)


def verdict_line(rep: dict) -> str:
    """一行中文结论。"""
    if not rep:
        return ""
    mark = "✅ 一致" if rep.get("verdict") == "consistent" else "⚠ 漂移"
    s = (f"[一致性] backend={rep.get('backend')} "
         f"median={rep.get('median')} min={rep.get('min')}（{rep.get('count')} 张）{mark}")
    if rep.get("drift"):
        fl = rep.get("floors") or {}
        detail = "、".join(
            f"{k}({v:.2f}<{fl.get(k, rep.get('floor'))})" if k in fl else k
            for k in rep["drift"][:4])
        s += f" · 低于该视角阈值：{detail}"
    return s
