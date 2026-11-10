# -*- coding: utf-8 -*-
"""提示词遵从度（prompt adherence）——「写了提示词，就必须按它走」。

## 问题

让 LLM 按提示词生成时，跑偏是**全静默**的：产物照样出、进度条照样走完，
只是内容跟你说的不是一回事。没有度量就没法验收，也没法回答
「我明明写了，它为什么拍成别的」。

## 口径（刻意朴素、可复核）

1. 把提示词拆成**关键要素**：引号里的专名（人名/地名/道具名）优先级最高，
   其次按标点/空白/虚词切出来的实词（2-12 字）。
2. 在最终文本（分镜的 visual/action/dialogue/… 字段）里逐条找**原样出现**。
3. 命中率 = 命中条数 / 要素条数；缺哪几条一并列出。

## 取舍

* **只做原样匹配，不做语义相似。** 语义相似要模型，成本高且不可复核；
  「要素都被原样写上」是硬底线。
* 命中率高**不等于**写得好，只等于「没跑题」。所以它只做**告警**，永不阻断。
* 空提示词 = 不适用（返回 `terms=0 / ratio=None`），绝不误判成"跑偏"。

## 用法

    >>> from dfg import key_terms, coverage
    >>> key_terms('深夜便利店，女主叫「林小满」，手里有枚青铜戒指')
    ['林小满', '深夜便利店', '青铜戒指']
    >>> r = coverage('雨天 油纸伞', '雨天她撑着一把油纸伞')
    >>> r['ratio'], r['ok']
    (1.0, True)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# 切成碎块时要去掉的连接词/虚词（避免「然后」「因为」被当成要素）
_STOP = {
    "一个", "一种", "然后", "但是", "所以", "因为", "如果", "而且", "并且",
    "我们", "你们", "他们", "她们", "这个", "那个", "什么", "怎么", "这样",
    "那样", "可以", "需要", "应该", "一定", "非常", "特别", "已经", "还是",
    "就是", "不是", "没有", "有些", "这些", "那些", "自己", "时候", "地方",
}

# 硬分隔符：标点、箭头、竖线、各类引号（引号本身不是内容）。
# ★ 不含空白：中文里空白是分隔；英文里空白是短语**内部**的空格，
#   "rainy night" 是一个要素，拆成 "rainy" + "night" 会让 "red" 在
#   "red umbrella" 里也算命中 —— 假命中最难查，所以英文整块保留。
_SEP = re.compile(r"[，。；、：！？,.;:!?\-—…/|｜~～（）()\[\]【】<>《》「」『』“”‘’\"'`]+")
# 英文短语开头常挂的冠词/介词：剥掉才可能命中正文
_ARTICLES = re.compile(r"^(?:a|an|the|of|in|on|at|with|and|or|to|for|from|that|this|her|his|their)\s+",
                       re.I)
_CJK = re.compile(r"[\u4e00-\u9fff]")
# 英文长句（超过要素长度上限）退化成逐词，丢掉这些纯功能词。
# 为什么要有这条：整块超长 → 被 _push 丢弃 → terms 为空 → 上层判定「不适用」→
# **静默放行**。英文长句提示词因此完全不设防，这比漏检更危险。
_EN_STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "with", "to",
            "for", "from", "that", "this", "these", "those", "her", "his", "their",
            "by", "as", "is", "are", "was", "were", "be", "it", "its", "she", "he",
            "they", "there", "here", "into", "onto", "over", "under", "very", "some"}
# 切词用的虚词/介词/常见动作：整句原样出现几乎不可能，先切成短语。
# 动作也切掉 —— 提示词里真正该被「照做」的是**名词要素**（人/地/物/氛围）；
# 动作交给正文去演绎，留在要素里只会制造假警报。
_CUT = re.compile(r"[的地得了着过和与或及从而并就让把被给对向在为上下里中之内外前后面边"
                  r"映照洒投落打穿戴握拿站坐走跑看望笑哭说喊叫唱跳推拉开关抱抬转回]")
# 短语开头常挂的动词/称谓/量词，去掉才可能命中正文
_LEAD = re.compile(r"^(?:有|是|叫|叫做|名叫|名为|带着|拿着|穿上|女主|男主|主角"
                   r"|一个|一位|一枚|一只|一条|一把|一张|一根|一块|一片|一件|一套|一双|一顶"
                   r"|枚|把|张|条|只|个|位|名|根|块|片|件|套|双|顶)")
# 引号里的内容视为专名（人名/地名/道具名/招式名/品牌名）
_QUOTED = re.compile(r"[「『“\"']([^」』”\"']{1,16})[」』”\"']")

# 分镜里承载「内容」的字段（prompt_en 也算：它是真正送去出图的那句话）
TEXT_FIELDS = ("title", "logline", "narration",
               "visual", "action", "dialogue", "subtitle", "prompt_en")

# 「没跑题」的经验线：低于它通常意味着换了一套设定
DEFAULT_FLOOR = 0.6


def key_terms(prompt: str, max_terms: int = 14) -> list:
    """把提示词拆成关键要素（保持原始顺序，去重）。空提示词返回 []。

    拆法：先取引号里的专名（最硬的约束），再把句子按标点/虚词切成短语，
    去掉开头的动词/称谓。**短要素优先**：若「林小满」已收，就不再收
    「女主叫林小满」——后者几乎不可能在正文里原样出现，只会制造假警报。
    """
    p = (prompt or "").strip()
    if not p:
        return []
    terms = []

    def _push(t):
        t = (t or "").strip()
        # 前缀可能叠着来（「有枚青铜戒指」→ 剥「有」→ 再剥「枚」），剥到稳定为止
        for _ in range(4):
            n = _LEAD.sub("", t)
            if n == t:
                break
            t = n
        t = t.strip()
        # 英文短语本来就比中文要素长（"oil paper umbrella" 18 字符），
        # 单独放宽；中文要素超过 12 基本不可能在正文里原样出现。
        limit = 28 if not _CJK.search(t) else 12
        if len(t) < 2 or len(t) > limit:
            return
        if t in _STOP:
            return
        # 已有更短的要素被它包含 ⇒ 它只是同一件事的长写法，跳过（降噪的关键）
        if any(x in t for x in terms):
            return
        # 反过来：新要素更短且被旧的包含 ⇒ 用短的替换（更可能命中）
        for i, x in enumerate(terms):
            if t in x:
                terms[i] = t
                return
        terms.append(t)

    for m in _QUOTED.finditer(p):
        _push(m.group(1))
    # 连字符当空格：中文「深夜-公寓」等价于「深夜 公寓」，
    # 英文 "oil-paper umbrella" 才能整块保留成 "oil paper umbrella"。
    p = p.replace("-", " ").replace("—", " ").replace("–", " ")
    for chunk in _SEP.split(p):
        if not chunk.strip():
            continue
        if not _CJK.search(chunk):
            # 纯英文块：整块当一个要素，只剥掉开头的冠词/介词
            t = chunk.strip()
            for _ in range(3):
                n = _ARTICLES.sub("", t)
                if n == t:
                    break
                t = n
            if len(t) > 28:
                # 长句退化成逐词（否则整块被丢 → terms 空 → 静默放行）
                for w in re.split(r"\s+", t):
                    w = re.sub(r"[^\w']+$", "", w)
                    if len(w) >= 3 and w.lower() not in _EN_STOP:
                        _push(w)
                continue
            _push(t)
            continue
        # 中文块：空白先切（「深夜 公寓 浴室」是三个要素），再按虚词切
        for w in chunk.split():
            for piece in _CUT.split(w):
                _push(piece)
    return terms[:max_terms]


def text_of_storyboard(data) -> str:
    """把分镜板里所有「内容字段」拼成一段可搜索文本。

    接受：分镜 dict（含 scenes）、场景 list、或直接一段字符串。
    """
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        scenes = data.get("scenes") or []
        head = " ".join(str(data.get(k) or "") for k in ("title", "logline", "narration"))
    else:
        head = ""
        scenes = data or []
    parts = [head]
    for s in scenes:
        if not isinstance(s, dict):
            parts.append(str(s))
            continue
        for k in TEXT_FIELDS:
            v = s.get(k)
            if isinstance(v, (list, tuple)):
                v = " ".join(str(x) for x in v)
            if v:
                parts.append(str(v))
    return "\n".join(parts)


def coverage(prompt: str, text: str, floor: float = DEFAULT_FLOOR,
             max_terms: int = 14) -> dict:
    """提示词要素在文本里的原样命中情况。

    返回::

        {"terms": 3, "hit": 2, "ratio": 0.667, "hit_terms": [...],
         "miss_terms": [...], "ok": True, "floor": 0.6}

    提示词为空时 ``terms=0 / ratio=None``（没有提示词 = 不适用，不算失败）。
    """
    terms = key_terms(prompt, max_terms=max_terms)
    if not terms:
        return {"terms": 0, "hit": 0, "ratio": None, "hit_terms": [],
                "miss_terms": [], "ok": True, "floor": floor,
                "note": "未给提示词，不适用"}
    # 归一化必须两边一起做：要素那边把 "oil-paper" 拆成 "oil paper"，
    # 正文这边不拆就永远匹配不上 —— 单向归一化等于给自己制造假警报。
    hay = (text or "").replace("-", " ").replace("—", " ").replace("–", " ")
    hit = [t for t in terms if t in hay]
    miss = [t for t in terms if t not in hay]
    ratio = len(hit) / len(terms)
    return {"terms": len(terms), "hit": len(hit), "ratio": round(ratio, 3),
            "hit_terms": hit, "miss_terms": miss, "floor": floor,
            "ok": ratio >= floor}


def coverage_of_storyboard(prompt: str, storyboard_path, floor: float = DEFAULT_FLOOR) -> dict:
    """读分镜文件算遵从度；文件缺失/坏掉返回 ok=True + note（不误伤）。"""
    p = Path(str(storyboard_path or ""))
    if not p.is_file():
        return {"terms": 0, "hit": 0, "ratio": None, "hit_terms": [], "miss_terms": [],
                "ok": True, "floor": floor, "note": f"分镜不存在：{p}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                                  # noqa: BLE001
        return {"terms": 0, "hit": 0, "ratio": None, "hit_terms": [], "miss_terms": [],
                "ok": True, "floor": floor, "note": f"分镜解析失败：{type(e).__name__}: {e}"}
    out = coverage(prompt, text_of_storyboard(data), floor=floor)
    out["storyboard"] = str(p)
    return out


def report_line(res: dict) -> str:
    """一行中文结论（日志/界面共用）。没有提示词时返回空串。"""
    if not res or not res.get("terms"):
        return ""
    miss = res.get("miss_terms") or []
    head = f"遵从度 {res['hit']}/{res['terms']}（{int(round((res.get('ratio') or 0) * 100))}%）"
    if not miss:
        return f"[提示词] {head} ✅ 要素全部落地"
    tail = "、".join(miss[:4]) + ("…" if len(miss) > 4 else "")
    mark = "⚠" if not res.get("ok") else "·"
    return f"[提示词] {head} {mark} 未落地：{tail}"
