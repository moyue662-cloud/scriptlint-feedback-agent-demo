# ScriptLint（短剧成片音频 + 字幕审片与反馈记忆 Agent）

> 上传短剧成片，提取音轨生成中文 ASR、抽取画面硬字幕，并与用户自己的剧本台词三方对齐；同时把编导纠正沉淀为可确认、可检索、可审计的项目规则，并在后续版本复用。

项目已经提供完全离线、人工构造数据驱动的纵向切片与 Streamlit 工作台：

```powershell
py -B scriptlint_phase1_demo.py
py -B scriptlint_phase2_demo.py
py -B -m pytest -q -p no:cacheprovider
py -m streamlit run app.py
```

当前 V3 增加“视频音频审片”首页：支持上传 `.mp4 / .mov / .mkv / .webm / .avi / .m4v`，由 PyAV 从视频容器提取 16kHz 单声道音轨，使用 faster-whisper CPU INT8 生成中文时间码转写，再报告疑似漏词、改词和基础音质问题。首次运行会从 Hugging Face 下载所选 Whisper 模型。

当前 V4 增加 RapidOCR 字幕证据：按自适应时间间隔抽取视频下半屏画面，读取硬字幕并与 ASR、剧本三方比对。字幕与剧本一致，且同时间段存在实际语音时，即使 ASR 严重错字也可标记为“字幕强证据通过”；如果没有任何语音证据，即使字幕存在也保留疑似漏录，避免掩盖真实收音问题。

当前 V5 将 ASR 和 OCR 证据统一转为简体中文，并增加带声调拼音匹配与受数字、否定词、方向/动作反义词保护的轻量语义归一。音频与剧本或画面字幕任一方在字面、读音或安全语义层面一致时，不再误报为改词；每条被消歧的结果都会展示具体判定依据。

未稳定对应到剧本行的 ASR 片段现在只进入“未匹配语音”折叠参考区，不再作为红色“疑似加词”错误，也不会用“剧本第—行”占位。纯破折号、空白，以及与已确认台词时间段重叠的重复残余会直接忽略。

当前 V6 将 `base` 设为默认模型，中文解码从单束搜索升级为多候选束搜索，并提供 `small` 精度优先选项和可选人名/专业词表。提示词只包含角色名与术语，不包含完整台词，避免把现场改词强行识别成剧本原句。界面显示明确构建版本，升级后自动清除旧会话报告。

当前 V7 修复长视频证据链：OCR 全时轴抽帧并叠加 ASR 锚点，不再因 ASR 漏听而同时漏掉字幕；Whisper 使用词级时间戳重切过长片段，并对连续 BGM 视频全时轴解码。字幕完整匹配剧本且同时间窗确有 ASR 声学片段时，即使 ASR 文字不可读，也会以“字幕 + 有声”双证据通过。

当前 V8 加入多模态画面基础层：对成片抽帧并输出镜头变化、持续黑帧、极端模糊与长静止镜头的时间码。这是后续角色跟踪、动作/表情、服化道一致性审计的可复用证据底座，当前不声称已具备这些语义能力。

音频对齐前会先执行“剧本结构预检”：识别 Markdown 的作品信息、人物设定与正文章节，将“类型、原作、时长、场景、核心主题”等元数据和背景说明排除，只把“角色：台词”送入 ASR 对齐。页面会分别展示纳入与排除的原文、行号和理由，用户可在正式审片前核对。

文本侧继续支持 `.txt / .md / .fountain`、项目版本、人物事实和反馈记忆。工作台包含“视频音频审片 / 剧本审计 / 项目规则 / 固定评测 / 用户验证 / 演进路线”六页。推荐现场路径：粘贴带“角色：台词”的剧本 → 上传已获授权的单集或片段 → 运行音轨审核 → 回看时间码证据 → 提交编导纠正并确认规则 → 后续版本复用。

当前版本仍不能可靠判断说话人身份，也不能根据画面判断动作、表情、服装和道具；OCR 只读取硬字幕，画面扫描只读取技术信号，都不等于理解视频语义。异常均为“待编导复核”，不得冒充最终质量结论。完整视觉演进见 `MULTIMODAL_ROADMAP.md`，真实媒体样本的指标定义和局限见 `docs/ACTUAL_MEDIA_EVALUATION.md`。

以下内容是可复用的 DecisionPatch 原型基线，后续会逐步替换为 ScriptLint 的页面和领域流程。

---

# 定了吗？ DecisionPatch（原型基线）

> 一个会从成员纠正中学习的"小组决策记忆 Agent"：把散落在群聊里的提议、决定、否决、分工和变更，变成可追溯、可纠正、可复用的团队记忆。

本仓库是参赛项目 **DecisionPatch** 的代码实现。规格与单一事实来源见
`DecisionPatch_项目方案与AI协作规格.md`（v0.2，参赛前可执行基线）。

---

## 快速开始（目标：15 分钟内可运行）

### 1. 环境要求
- Python **3.11+**（已在 3.13.15 上验证）
- pip
- git

### 2. 安装依赖

```bash
# 在仓库根目录
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
# 或可编辑安装（含开发依赖）
pip install -e ".[dev]"
```

### 3. 配置模型通道（可选）

默认使用 **离线 Mock**，无需任何 API Key 即可跑通核心闭环与演示。

如需接入七牛云 OpenAI 兼容接口，复制并填写环境变量（**不要把 Key 写进文件**）：

```bash
# Windows PowerShell
$env:DP_PROVIDER = "qiniu"
$env:DP_QINIU_BASE_URL = "https://your-qiniu-endpoint/v1"
$env:DP_QINIU_API_KEY = "your-key"
$env:DP_QINIU_MODEL = "your-model-name"

# macOS / Linux
export DP_PROVIDER=qiniu
export DP_QINIU_BASE_URL=https://your-qiniu-endpoint/v1
export DP_QINIU_API_KEY=your-key
export DP_QINIU_MODEL=your-model-name
```

未配置时，`config.py` 会自动回退到 Mock，保证网络异常时仍可演示（规格 §3.2 / §15）。

### 4. 运行

```bash
python -m streamlit run app.py
```

启动后推荐按这条路径演示：左侧点击“载入第一次分析”并运行 → 展开一条
“已确认”凭证 → 改为“待确认”并提交纠正 → 在审核台确认候选记忆 → 点击
“载入第二次分析”并运行。第二次结果会显示记忆命中、应用理由和新的待确认凭证。
切换到“另一支小组 · 隔离演示”可以验证 team scope 隔离。

如当前目录没有写权限，可将 SQLite 路径指向可写目录：

```powershell
$env:DP_DB_PATH = "C:\path\to\decisionpatch_demo.db"
py -m streamlit run app.py
```

### 5. 运行测试

```bash
pytest
```

### 6. 运行评测

```bash
python eval/run_eval.py
```

评测是仓库内 30 条固定样例的离线 smoke benchmark，覆盖 10 条应应用、10 条
不应应用、5 条冲突和 5 条跨团队隔离；它验证评测管道和 scope guard，不应被
表述为线上模型准确率。

---

## 仓库结构（规格 §7.4）

```
decisionpatch/
  app.py                  # 完整 Streamlit demo：工作台 / 记忆库 / 评测
  config.py               # 环境变量与运行配置
  schemas/                # Pydantic 模型（冻结契约，解锁前端）
    message.py
    decision.py
    memory.py
    feedback.py
    metrics.py
  services/               # 业务编排
    agent_orchestrator.py
    memory_service.py
    feedback_service.py
    evaluation_service.py
  tools/                  # P0 工具（规格 §7.2）
    normalize_chat.py
    extract_decisions.py
    detect_conflicts.py
    build_receipt.py
    propose_memory.py
    record_metrics.py
  repositories/
    sqlite.py             # 持久层
  providers/              # 模型适配
    llm_base.py
    qiniu_openai.py
    mock_provider.py
    demo_provider.py      # 无网演示用的可解释结构化 Mock
  prompts/                # Prompt 合同（规格 §9）
    extract_decisions.md
    propose_memory.md
    judge_applicability.md
  eval/
    fixtures/
      labels.jsonl
    run_eval.py
  tests/
  README.md
```

## 核心闭环

群聊输入 → 识别五类对象（提议/已确认/已否决/任务/冲突）→ 用户纠正 → 提取候选记忆 → 用户确认 → 下次分析时选择性应用，并解释"为什么应用/为什么忽略"。

## 隐私与安全（规格 §8.3）

- 默认本地 SQLite；演示不上传真实姓名、手机号、学号和聊天图片。
- API Key 只从环境变量读取，不写入仓库、截图或日志。
- 提供"一键清空演示数据"；正式删除前必须二次确认。

## 对外定位

不要把项目表述成“首个 AI 团队记忆产品”；团队记忆和决策记忆已经有同类方向。
本项目的具体切口是本科小组协作中的“到底定没定”：五类决策凭证、原消息证据、
用户纠正生成候选规则、人工确认后才应用，以及 team/project scope 隔离。仓库里的
“演示小组（虚构）”和“人工构造 · Demo”均为演示占位，不代表真实用户或比赛项目。

## 多模型协作（规格 §16）

- **前端实现**：当前仓库已包含可录屏的 Streamlit 工作台、记忆库和评测页；
  后续视觉迭代仍只消费现有 schema / service 契约。
- **GLM**：确定性工程（schema / SQLite / 记忆服务 / Provider / 工具 / 评测 / 测试）
- **Opus**：复杂问题，随时插队
