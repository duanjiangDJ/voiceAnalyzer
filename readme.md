# 语音仿读质量评估系统

对仿读音频进行**语音特征**（OpenSMILE）和**文字准确性**（Whisper + LLM 思考模式）双重评估，
输出多维度评分、结构化差异报告和错题可视化，支持断点续传和模块化开关。

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 安装 ffmpeg（Whisper 依赖）
choco install ffmpeg        # Windows
# brew install ffmpeg        # macOS
# sudo apt install ffmpeg    # Linux

# 3. 编辑 .env，填入 API 密钥
# LLM_API_KEY=sk-xxx

# 4. 放置文件
#    resource/standard_audio/  ← 标准音频（恰好 1 个，mp3/wav/m4a 等）
#    resource/standard_text/   ← 标准文本（恰好 1 个 .txt，UTF-8）
#    resource/imitation_audio/ ← 学生仿读音频（可多个）

# 5. 运行
python run.py
```

## 目录结构

```
opensmile_test/
├── run.py                      # 总入口
├── .env                        # API 密钥
├── requirements.txt            # Python 依赖
│
├── src/                        # 核心模块
│   ├── launcher.py             # 主调度器（8 阶段流水线，三线程池，断点续传）
│   ├── voice_compare.py        # OpenSMILE 语音分析（8 维度评分 + 3×3 图表）
│   ├── text_llm.py             # Whisper 转写 + LLM 比对 + 知识点查询
│   ├── audio_output.py         # 后处理：结果汇总到 Excel
│   ├── filter_name.py          # 数据完整性预检查
│   ├── error_visualizer.py     # 错题词云 + 历史进步曲线
│   ├── config.py               # 统一配置管理
│   ├── constants.py            # 共享常量
│   └── utils.py                # 工具函数
│
├── tools/                      # 独立工具
│   ├── benchmark_llm.py        # LLM 模型/模式自动对比基准测试
│   └── verify_refactoring.py   # 重构验证测试
│
└── resource/                   # 所有数据文件
    ├── config.yaml             # 统一配置文件（模型/开关/词云参数）
    ├── standard_audio/         # 标准音频（恰好 1 个文件）
    ├── standard_text/          # 标准文本（恰好 1 个 .txt）
    ├── imitation_audio/        # 学生仿读音频（1~N 个）
    ├── result/                 # 自动生成的输出
    │   ├── progress.json
    │   ├── summary.csv
    │   ├── summary_with_details.xlsx
    │   ├── {学生名}-{学号}/    # 每位学生
    │   │   ├── voice_comparison_report.png
    │   │   ├── {学生名}-{学号}.md
    │   │   └── {学生名}-{学号}_errors.json
    │   ├── history/            # 历史运行归档
    │   │   ├── {时间戳}_summary.csv
    │   │   └── {时间戳}_meta.json
    │   └── error_analysis/     # 错题可视化
    │       ├── wordcloud_replace.png
    │       ├── wordcloud_insert.png
    │       ├── wordcloud_delete.png
    │       ├── wordcloud_all.png
    │       └── progress_curves/
    │           ├── {学生名}_progress.png
    │           └── ...
    └── knowledge/
        └── learning_source.csv
```

## 资源文件命名规范

### 目录约定

| 目录 | 文件数 | 说明 |
|------|--------|------|
| `resource/standard_audio/` | 恰好 1 个 | 标准朗读音频，任意常见格式 |
| `resource/standard_text/` | 恰好 1 个 | 标准文本，UTF-8 编码 .txt |
| `resource/imitation_audio/` | 1~N 个 | 学生仿读音频 |
| `resource/result/` | 自动生成 | 评分结果（勿手动编辑） |
| `resource/knowledge/` | 若干 CSV | 知识点等参考资料 |

### 仿读音频命名规则

格式：`{姓名}-{10位学号}.{扩展名}`
- 姓名与学号之间用连字符 `-` 分隔
- 学号必须为 10 位数字
- 扩展名小写，支持 mp3 / wav / m4a / flac / ogg / mp4
- 示例：`一二三-2220241234.m4a`

### 结果输出命名（自动生成）

| 文件 | 说明 |
|------|------|
| `progress.json` | 断点续传状态 |
| `summary.csv` | 最终评分汇总表 |
| `summary_with_details.xlsx` | 含转写文本和比对结果的增强版汇总 |
| `voice_comparison_report.png` | 语音 3×3 对比图 |
| `{姓名}-{学号}.md` | 文字比对 Markdown 报告 |
| `{姓名}-{学号}_errors.json` | 结构化错误数据 |
| `{时间戳}_summary.csv` | 历史运行归档（如 `2026-07-04_125337_summary.csv`） |
| `{时间戳}_meta.json` | 运行元数据（学生列表、人数） |
| `wordcloud_{replace\|insert\|delete\|all}.png` | 错题词云图（3 分类 + 1 合计） |
| `{学生名}_progress.png` | 每位学生的历史进步曲线 |

## 环境要求

- **Python** 3.13+
- **ffmpeg**（Whisper 音频处理必需）

## 配置说明

项目使用两层配置：

- **`.env`** — 仅存放 API 密钥，不纳入版本控制
- **`resource/config.yaml`** — 所有其他配置（模型、开关、词云参数等）

### .env（仅 API 密钥）

```bash
LLM_API_KEY=sk-xxx
```

### resource/config.yaml

```yaml
llm:
  api_base: "https://api.deepseek.com/v1"
  model: "deepseek-v4-pro"
  thinking: true          # 思考模式
  max_concurrency: 400    # LLM 最大并发数
  timeout: 120            # API 超时（秒）

whisper:
  model_name: "small.en"
  full_model_name: "medium.en"

modules:                  # 模块开关（true=启用）
  voice_analysis: true
  whisper_transcribe: true
  llm_compare: true
  post_process: true
  filter_precheck: true
  error_visualize: true

wordcloud:                # 词云参数
  width: 800
  height: 600
  max_words: 100
  prefer_horizontal: 1.0  # 1.0=全部横向
  stopwords:              # 停用词（不显示在词云中）
    - "the"
    - "of"
    - "and"
    # ... 
```

修改 YAML 后重新运行 `python run.py` 即可生效。

### 模块开关对照

| 开关 | 控制阶段 | 说明 |
|------|---------|------|
| `voice_analysis` | Phase 2 | OpenSMILE 语音特征分析 |
| `whisper_transcribe` | Phase 3 | Whisper 语音转写 |
| `llm_compare` | Phase 3 | LLM 文本比对 |
| `post_process` | Phase 5 | 结果汇总到 Excel |
| `filter_precheck` | Phase 7 | 数据完整性预检查 |
| `error_visualize` | Phase 8 | 错题词云 + 历史曲线 |

## 核心架构

### 8 阶段流水线

| 阶段 | 说明 | 开关控制 |
|------|------|---------|
| Phase 1 | 标准文件发现 + 特征预计算 | — |
| Phase 2 | 语音分析（OpenSMILE 8 维度评分） | `VOICE_ANALYSIS` |
| Phase 3 | Whisper 转写 + LLM 逐句比对 | `WHISPER_TRANSCRIBE` + `LLM_COMPARE` |
| Phase 4 | 阻塞等待所有任务完成 | — |
| Phase 5 | 后处理（汇总 Excel） | `POST_PROCESS` |
| Phase 6 | 最终汇总 + 耗时统计 | — |
| Phase 7 | 数据完整性预检查 | `FILTER_PRECHECK` |
| Phase 8 | 归档 + 错题可视化（词云 + 曲线） | `ERROR_VISUALIZE` |

### 三线程池设计

| 线程池 | 并发数 | 职责 | 设计原因 |
|--------|--------|------|---------|
| `voice_executor` | 1 | OpenSMILE 语音特征分析 | C++ 库非线程安全 |
| `whisper_executor` | 1 | Whisper 语音转写 | PyTorch 模型大，全局单例避免重复加载 |
| `llm_executor` | 400（可配） | LLM 文本比对 | 纯 HTTP 网络 I/O，高并发充分利用带宽 |

### 关键设计决策

- **标准音频预分析**：OpenSMILE 特征仅在启动时提取一次并缓存，所有学生共享
- **Whisper 不等 LLM**：转写完成后立即提交 LLM 任务并处理下一个学生，不等待结果
- **断点续传**：`progress.json` 记录每步状态，中断后重启自动跳过已完成步骤
- **模块开关独立控制**：6 个开关可自由组合，关闭时自动标记对应阶段完成并防止死锁

## 评估维度

### 语音

通过 OpenSMILE ComParE 2016 特征集提取低层声学描述符，计算相似度（0~100 分）：

| 维度 | 指标 | 说明 |
|------|------|------|
| 基频均值 | F0 Mean | 音高整体水平 |
| 基频标准差 | F0 Std | 语调起伏变化 |
| 能量均值 | RMS Energy | 重音与力度 |
| Jitter 均值 | Jitter Local | 音高稳定性（频率微扰） |
| Shimmer 均值 | Shimmer Local | 音量稳定性（振幅微扰） |
| log HNR 均值 | log HNR | 清晰度 vs 气息（谐噪比） |
| 谱质心均值 | Spectral Centroid | 音色明亮度 |
| 语速 | Syllable Rate | 每秒音节数估算 |

综合分 = 8 维度算术平均。

### 文字（逐句差异分析）

Whisper 转写后由 LLM（DeepSeek 思考模式）逐句比对标准文本，标注三类错误：
- **替换错误**：识别词与标准词含义不同
- **多读部分**：转写中多出的词
- **漏读部分**：转写中遗漏的词

同时自动匹配 `learning_source.csv` 中的知识点，在差异词下方附上发音、释义、例句。

### 总成绩

```
总成绩 = 单词准确率 × 50 + 语音综合分 × 0.5
```

### 错题可视化

每次运行后自动生成：

- **4 张词云图**：
  - `wordcloud_replace.png` — 替换错误高频词
  - `wordcloud_insert.png` — 多读错误高频词
  - `wordcloud_delete.png` — 漏读错误高频词
  - `wordcloud_all.png` — 三类错误合计
  - 自动过滤停用词（the/of/and 等英语功能词），全部横向排列
- **历史进步曲线**：每位学生一张独立 PNG（`progress_curves/{学生名}_progress.png`），含历次运行的准确率+语音分+总成绩三条折线
- **运行归档**：每次运行结果自动存入 `history/`，附带 `meta.json` 元数据
- **汇总 Excel**：将转写文本、标准文本、比对结果、对比图片路径汇总到 Excel

## 断点续传

中断后重新运行 `python run.py` 即可从上次中断处继续。状态机：

```
voice:  pending → running → done / failed
text:   pending → running → transcribed（Whisper 完成，LLM 排队中）
                            → done / failed
```

恢复逻辑：
- `voice=done, text=done` → 完全跳过
- `voice=done, text=transcribed` → 仅重跑 LLM 比对
- 其他状态 → 从对应步骤重跑

## 模块独立运行

```bash
python src/voice_compare.py            # 语音分析
python src/text_llm.py                 # 文字分析（独立批量模式）
python src/audio_output.py \           # 后处理
    --excel resource/result/summary.csv \
    --result-dir resource/result
python src/filter_name.py \            # 预检查
    --audio-dir resource/imitation_audio \
    --summary resource/result/summary.csv
python src/error_visualizer.py \       # 可视化
    --result-dir resource/result
```

## TODO LIST

- [ ] 持续优化token消耗
- [ ] 本地纠错识别算法
- [ ] GUI
- [ ] 师生双端
- [ ] 校师生三方平台
- [ ] ...



## 基准测试

```bash
python tools/benchmark_llm.py
```

自动运行 4 轮完整流水线（flash/pro × 思考开/关），对比耗时和准确率，
生成 `benchmark_report.md`，结果保存在 `resource/result/benchmark/`。

## 常见问题

**Q: 运行时提示找不到音频/文本文件**
A: 确保 `resource/standard_audio/` 和 `resource/standard_text/` 中各只有一个文件，
`resource/imitation_audio/` 中至少有一个音频文件。

**Q: 语音对比图或词云图的中文无法正常显示**
A: 确保系统安装了中文字体（SimHei 或 Microsoft YaHei），或修改 `src/voice_compare.py` 中的
`plt.rcParams['font.sans-serif']`，对于词云图，`error_visualizer.py` 会自动检测系统中的中文字体并使用。

**Q: LLM 比对结果不理想**
A: 尝试在 `resource/config.yaml` 中启用思考模式（`thinking: true`）或更换模型（`model: "deepseek-v4-pro"`）。
运行 `benchmark_llm.py` 可自动对比不同配置。

**Q: 中途中断后重跑会重复处理吗**
A: 不会。`progress.json` 记录了每步状态，重启后自动跳过已完成步骤。

**Q: 如何只跑文字分析不跑语音**
A: 在 `resource/config.yaml` 中将 `voice_analysis` 设为 `false`，其他开关保持 `true`。

