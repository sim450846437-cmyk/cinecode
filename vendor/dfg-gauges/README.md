# dfg · AI pipeline gauges

[English](README.en.md) | **简体中文**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)
[![Dependencies](https://img.shields.io/badge/core%20deps-none-brightgreen.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-32%20passing-brightgreen.svg)](tests/test_gauges.py)

**出片链路的四把量具：提示词遵从度 · LLM 通道判活 · 命令对账 · 角色一致性。只度量，不生成。**

AI 视频流水线最容易骗人的地方不是"做不出来"，而是**做出来了但不对，而且没人知道**：

- 命令构造写了 `--force`，脚本根本没注册这个参数 —— 点火才炸，整集白跑；
- 兜底写死了某家 LLM，那家模型早下线了 —— 每次失败先白撞一轮超时；
- 提示词写了"青铜戒指"，成片里没有 —— 产物照样出、进度条照样走完，全静默；
- 同一个角色跨 5 个视角，肉眼看着都像，一量发现侧面漂了 0.15。

这个包把四件事变成**可复核的数字或对错**，零 GPU、零 API、零网络（一致性检测器除外，
它要模型）。

## 安装

```bash
pip install -e .                 # 核心三个量具：纯标准库，无依赖
pip install -e ".[clip]"         # 可选：一致性检测器的 hf 后端（torch + transformers）
pip install -e ".[face]"         # 可选：真人脸后端（insightface）
```

Python ≥ 3.9。

## 60 秒跑通（不需要准备任何素材）

```bash
pip install -e .
dfg selftest                                                    # 24 项自检，零依赖

dfg check --script examples/demo_stage.py --cmd "--force --reroll 2"
dfg check --script examples/demo_stage.py --cmd "--force --nope 3"   # 故意失败，退出码 1

dfg health --ledger examples/demo_ledger.jsonl --pick moonshot,qwen,deepseek,ghost
dfg adherence --prompt "雨夜 木桥 油纸伞 红衣 银戒指" --storyboard examples/demo_storyboard.json
```

`examples/` 里是三个玩具文件（一个假阶段脚本、一份调用账本、一块分镜板），
只为让上面每条命令都能在你机器上原样跑出下面写的输出。
`consistency` 需要你自己的图，放在最后单独说。

## 四个命令

### 1. `dfg check` — 这条命令真能跑吗

```bash
$ dfg check --script examples/demo_stage.py --cmd "--force --reroll 2"
[PASS] demo_stage.py（2 个 flag 对上）

$ dfg check --script examples/demo_stage.py --cmd "--force --nope 3"
[FAIL] demo_stage.py 不认 ['--nope']
$ echo $?
1
```

用 `ast` 静态解析脚本注册过哪些 `add_argument`，再逐项对账你构造的命令。
**不执行被测程序**，没有副作用。适合塞进 CI 或 `pre-commit`。

### 2. `dfg health` — 我在用的通道还活着吗

```bash
$ dfg health --ledger examples/demo_ledger.jsonl --pick moonshot,qwen,deepseek,ghost
活 2 / 死 1 / 未知 0
  ✓ deepseek           alive
  ✗ moonshot           dead
  ✓ qwen               alive

兜底候选（跳过死通道）：['qwen', 'deepseek', 'ghost']
```

双源判活：体检报告（24h 内优先）→ 调用账本（JSONL 尾部 N 条）。
口径保守：**成功过 = 活 / 连续失败 ≥3 = 死 / 没样本 = 未知按活放行**（新通道不误杀）。
`--assert` 在候选里含死通道时退出码 1，可直接当 CI 断言。

### 3. `dfg adherence` — 导演按我写的走了吗

```bash
$ dfg adherence --prompt "雨夜 木桥 油纸伞 红衣 银戒指" --storyboard examples/demo_storyboard.json
[提示词] 遵从度 3/5（60%） · 未落地：红衣、银戒指
```

上面这条用的 `examples/demo_storyboard.json` 里确实**没有**红衣和银戒指 ——
输出不是示意，是真实结果。

把提示词拆成关键要素（引号专名优先，再按标点/虚词切短语），
在最终文本里找**原样出现**，算命中率。空提示词 = 不适用，绝不误判。

> **只做原样匹配，不做语义相似。** 语义相似要模型、不可复核；
> 「要素都被原样写上」是硬底线。命中率高 ≠ 写得好，只等于「没跑题」，
> 所以它只告警、不阻断。

### 4. `dfg consistency` — 这两张图是同一个人吗

> 这一条是唯一需要你自备素材的：一张锚图 + 若干张同一角色的其它视角。
> 下面用 `cast/hero/` 指代你自己的目录。

```bash
$ dfg consistency --anchor cast/hero/anchor.png --views cast/hero/views --backend hf
[一致性] backend=hf median=0.872 min=0.755（4 张）⚠ 漂移 · 低于 0.8：full.png
   full.png                 0.755
   side.png                 0.865
   three_quarter.png        0.883
   back.png                 0.905
```

**分数只在同 backend、同预处理下可比。** 同一个动漫角色，CLIP-L 给 0.86、
CLIP-H 给 0.92、ArcFace 直接不适用。所以每条结论都带 `backend` 与 `floor`：

| backend | 适合 | 不适合 | 默认强一致线 |
|---|---|---|---|
| `hf`（OpenAI CLIP-L） | 动漫 / 3D / 写实全身 | 精细五官差异 | 0.80 |
| `comfy`（CLIP-ViT-H-14 laion2B） | 与 ComfyUI 出图同源，口径最贴 | 需本地权重 | 0.70 |
| `arcface`（InsightFace） | 真人脸 | 动漫、背影、全身 | 0.45 |

#### 测全身/背影请加 `--floor auto`

用统一的 0.70 线去量全身视角，会把**四分之一的卡**误判成漂移。这不是模型不行，
是物理事实：全身和背影的构图占比变化最大，全局 CLIP 特征被背景和姿态稀释了。

实测 419 张真实角色卡（comfy 口径）：

| 视角 | median | p5 | 统一 0.70 的误报率 | 分级线 |
|---|---|---|---|---|
| three_quarter | 0.872 | 0.760 | 0.5% | 0.70 |
| side | 0.865 | 0.776 | 1.2% | 0.70 |
| full | 0.755 | 0.547 | **24.8%** | 0.48 |
| back | 0.812 | 0.593 | **16.5%** | 0.50 |

```bash
$ dfg consistency --anchor a.png --views v/ --backend comfy --floor auto
[一致性] backend=comfy median=0.833 min=0.683（4 张）✅ 一致
    full.png           0.683  (线 0.48)
    side.png           0.832  (线 0.7)
    back.png           0.834  (线 0.5)
    three_quarter.png  0.847  (线 0.7)
```

换成分级线后，419 张里只有 16 张真报警（3.8%），而这 16 张确实该重绘。
**一个总在报警的量具，等于没有量具** —— 人会对它免疫。

也可以自己给：`--floor '{"full":0.45}'`（Python 里直接传 dict）。
不传 `--floor` 时行为与旧版完全一致。

<details>
<summary>为什么 arcface 不适合全身/背影</summary>

ArcFace 是**人脸识别**模型：先检人脸框，再编码脸。背影和全身远景检不到脸，
它不是"分数低"，而是**没有分数**。本包在这种情况下会明确报错
（`这张图里没检出人脸`），而不是返回一个看起来正常的 0.2。
</details>

#### 跑批量：显存与速度

量具是**旁路工具**，不该有资格影响产线。所以它做了三件在你批量测几百张图时
才会体现价值的事：

```bash
# 显卡正被 ComfyUI / 本地模型占着（16G 卡常见），别去抢 —— 强制走 CPU
$ dfg consistency --anchor a.png --views v/ --backend comfy \
    --clip ~/ComfyUI/models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors \
    --device cpu
```

1. **`--device cpu` 真生效**：ComfyUI 用全局 `cpu_state` 表达这个意思，本包会去改它。
   不说这句，`--device cpu` 就只是一句吉祥话。
2. **权重整进程只加载一次**：CLIP-ViT-H-14 是 3.9G。每次 `compare()` 都重新
   `load()` 的话，你测 400 张卡就是在反复读 12 次盘顺序的字节——实测慢 10 倍。
3. **逐张回收**：不带 `inference_mode`、也不 `soft_empty_cache` 时，逐张累积
   到第 4 张就会 CUDA OOM（真的，51GB allocated 的日志见过）。

<details>
<summary>为什么不在 CI 里跑一致性真值</summary>

它需要 3.9G 权重 + 一个能跑 torch 的环境。本包的 CI 只测**不需要模型**的部分
（数学、判活、命令对账），一致性后端的用例在缺 torch 时会显式打印 `[SKIP]`
并计入"跳过"而不是"通过" —— 假装测过了比没测更危险。
</details>

## 在 Python 里用

```python
from dfg import key_terms, coverage
from dfg.llm_health import statuses, pick_alive
from dfg.preflight import check_cmd
from dfg.consistency import similarity, compare

key_terms('深夜便利店，女主叫「林小满」')      # ['林小满', '深夜便利店']
coverage('雨天 油纸伞', '雨天她撑着一把油纸伞')  # {'ratio': 1.0, 'ok': True, ...}

st = statuses('output/llm_call_log.jsonl')
pick_alive(['moonshot', 'qwen'], st)          # ['qwen']

check_cmd(['python', 'x.py', '--force']).ok   # True

similarity('a.png', 'b.png')                  # 0.8721
compare('anchor.png', ['v1.png', 'v2.png'])['verdict']   # 'consistent'
```

## 三个刻意不做的选择

1. **不自动修复。** 判死不等于替你把通道换掉；遵从度低不等于替你重跑。
   一次重生成可能是几分钟 + 真金白银，该由人决定。
2. **不静默降级。** 缺依赖时 `BackendMissing` 明确报错并给安装命令，
   绝不返回 0 分 —— 假分数比没有分数危险得多。
3. **不假装通用。** 一致性分数带 backend、遵从度只做原样匹配。
   口径写进报告里，别人才能复核；藏起来就只是"感觉不错"。

## 出处

这四把量具从 DreamForge（一个本地 AI 剧组的生产系统，未开源）里抽出来：
它们是在真实事故中长出来的，不是设计出来的。

| 量具 | 对应的事故 |
|---|---|
| `preflight` | 命令构造成 `--force`，脚本没注册 → `unrecognized arguments` 炸整集 |
| `llm_health` | 兜底写死 `modelscope_ds`，那家模型已下线 → 每次多烧一轮往返 |
| `adherence` | 演示样稿完全无视提示词，照出"罐头剧情"，界面无任何提示 |
| `consistency` | 跨视角漂移 0.507 → 0.905，肉眼在单张上看不出来，连起来看才像换了个人 |

抽出来的目的不是"开源一个库"，而是：**这些坑不该每个做 AI 视频的人都再踩一遍。**

## 边界

- 不含任何模型、卡池、提示词资产或业务规则；改一行业务不碰这个包。
- 不负责生成、拼接、渲染、发布。
- `consistency` 的 `comfy` 后端需要 ComfyUI 的运行环境；不在 CI 覆盖范围内。

## 许可

MIT。见 [LICENSE](LICENSE)。
