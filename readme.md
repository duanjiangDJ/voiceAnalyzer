# 语音仿读质量评估系统

对仿读音频进行**语音特征**（OpenSMILE）和**文字准确性**（Whisper + LLM 思考模式）双重评估，输出多维度评分和结构化差异报告，支持断点续传、模块化开关和错题可视化。

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 安装 ffmpeg（Whisper 依赖）
choco install ffmpeg        # Windows
# brew install ffmpeg        # macOS
# sudo apt install ffmpeg    # Linux

# 3. 编辑 .env，填入 DeepSeek API 密钥
# LLM_API_KEY=sk-xxx

# 4. 放置文件
#    resource/standard_audio/  ← 标准音频（恰好 1 个文件，mp3/wav/m4a 等）
#    resource/standard_text/   ← 标准文本（恰好 1 个 .txt，UTF-8 编码）
#    resource/imitation_audio/ ← 学生仿读音频（可多个）

# 5. 运行
python run.py
```

## 资源文件夹命名规范

### 目录约定
所有输入输出文件统一放在 `resource/` 目录下：

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
- 示例：`代祺月-2220241548.m4a`

### 结果输出命名（自动生成，勿手动创建）
- `progress.json` — 断点续传状态
- `summary.csv` — 最终评分汇总表
- `{姓名}-{学号}/voice_comparison_report.png` — 语音对比图
- `{姓名}-{学号}/{姓名}-{学号}.md` — 文字比对报告
- `{姓名}-{学号}/{姓名}-{学号}_errors.json` — 结构化错误数据

### 知识库 CSV 命名
- 使用中文描述性文件名
- UTF-8 with BOM 编码（兼容 Excel 直接打开）
- 示例：`learning_source.csv`、`指标作用.csv`

## 环境要求

- **Python** 3.13+
- **ffmpeg**（Whisper 音频处理必需）

## 环境变量（`.env`）

```bash
# LLM API 配置
LLM_API_KEY=sk-xxx              # API 密钥（必填）
LLM_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-pro       # 模型名
LLM_THINKING=1                  # 1=启用 DeepSeek 思考模式
LLM_MAX_CONCURRENCY=400         # LLM 最大并发请求数
LLM_TIMEOUT=120                 # API 超时秒数

# Whisper 模型配置
WHISPER_MODEL=small.en          # 默认模型
WHISPER_FULL_MODEL=medium.en    # 完整模型

# 模块开关（1=启用, 0=跳过）
FILTER_PRECHECK=1
VOICE_ANALYSIS=1
WHISPER_TRANSCRIBE=1
LLM_COMPARE=1
POST_PROCESS=1
ERROR_VISUALIZE=1
```

## 核心架构

三线程池分离调度，各司其职：

| 线程池 | 并发 | 职责 | 特征 |
|---|---|---|---|
| `voice_executor` | 1 | OpenSMILE 语音特征分析 | 低 CPU（C++ 库），标准音频预分析一次后复用 |
| `whisper_executor` | 1 | Whisper 语音转写 | 高 CPU（PyTorch），全局单例模型 |
| `llm_executor` | 400（可配） | LLM 文本比对 | 纯网络 I/O，支持 DeepSeek 思考模式 |

**关键设计决策：**
- **8 阶段流水线**：预检查 → 标准分析 → 语音 → 文字 → 等待 → 后处理 → 汇总 → 归档+可视化
- **模块开关独立控制**：6 个开关可自由组合，关闭某模块时自动跳过对应阶段并防止死锁
- **Whisper 不等 LLM**：转写完成后立即提交比对任务，whisper worker 继续处理下一个学生
- **标准音频预分析**：OpenSMILE 特征仅提取一次并缓存，所有学生共享
- **断点续传**：`progress.json` 记录每一步状态，中断后重启自动跳过已完成步骤

## 评估维度

### 语音（8 维度 → 综合分）

通过 OpenSMILE ComParE 2016 特征集提取低层声学描述符，计算以下维度的模仿相似度（0~100 分）：

| 维度 | 指标 | 说明 |
|---|---|---|
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

Whisper 转写后由 LLM（DeepSeek 思考模式）逐句比对标准文本，标注：
- **替换错误**：识别词与标准词含义不同
- **多读部分**：转写中多出的词
- **漏读部分**：转写中遗漏的词

同时自动匹配 `learning_source.csv` 中的知识点，在差异词下方附上发音、释义、例句、视频链接。

### 总成绩

```
总成绩 = 单词准确率 × 50 + 语音综合分 × 0.5
```

### 错题可视化

每次运行后自动生成：
- **三分类词云图**：替换/多读/漏读错误的高频词可视化
- **历史进步曲线**：每位学生历次运行的准确率+语音分+总成绩变化趋势

## 断点续传

中断后重新运行 `python run.py` 即可从上次中断处继续。状态机：

```
voice:  pending → running → done / failed
text:   pending → running → transcribed（Whisper 完成，LLM 排队中）
                            → done / failed
```

## 独立运行各模块

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

## 基准测试

```bash
python tools/benchmark_llm.py
```

## 常见问题

**Q: 运行时提示找不到音频/文本文件**
A: 确保 `resource/standard_audio/` 和 `resource/standard_text/` 中各只有一个文件，`resource/imitation_audio/` 中至少有一个音频文件。

**Q: 语音对比图中文无法显示**
A: 确保系统安装了中文字体（SimHei），或修改 `src/voice_compare.py` 中的 `plt.rcParams['font.sans-serif']`。

**Q: 中途中断后重跑会重复处理吗**
A: 不会。`progress.json` 记录了每步状态，重启后自动跳过已完成步骤。

**Q: 如何只跑文字分析不跑语音**
A: 在 `.env` 中设置 `VOICE_ANALYSIS=0`，其他开关保持 1。所有模块开关均可独立控制。
