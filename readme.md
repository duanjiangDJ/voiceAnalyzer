# 语音仿读质量评估系统

对仿读音频进行**语音特征**（OpenSMILE）和**文字准确性**（Whisper + LLM 思考模式）双重评估，
输出多维度评分、结构化差异报告和错题可视化。提供 **Web UI**（浏览器）和 **CLI**（命令行）两种运行模式。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
choco install ffmpeg              # Windows 需安装 ffmpeg
copy .env.example .env             # 编辑 .env 填入 LLM_API_KEY
python run_ui.py                   # 浏览器打开 http://127.0.0.1:8000
```

## 运行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| **Web UI**（推荐） | `python run_ui.py` | 浏览器操作，班级/单元管理，实时进度监控 |
| CLI | `python run.py` | 命令行，直接处理 resource/ 下文件 |

## 项目结构

```
opensmile_test/
├── run_ui.py                   # Web UI 启动入口
├── run.py                      # CLI 启动入口
├── build_exe.py                # PyInstaller 打包脚本
├── .env / requirements.txt     # 密钥 + Python 依赖
├── stopwords.txt               # 词云停用词
│
├── src/                        # 核心引擎（8阶段流水线）
│   ├── launcher.py             # 主调度器（三线程池，断点续传）
│   ├── voice_compare.py        # OpenSMILE 语音分析（8维评分）
│   ├── text_llm.py             # Whisper 转写 + LLM 比对（含重试）
│   ├── audio_output.py         # Excel 汇总
│   ├── error_visualizer.py     # 错题词云 + 历史曲线
│   ├── config.py / constants.py / utils.py
│   └── filter_name.py          # 完整性预检查
│
├── server/                     # FastAPI 后端
│   ├── main.py                 # 应用工厂 + 托管 ui/dist/
│   ├── api/v1/                 # REST 端点（classes/files/tasks/results/...）
│   └── events/sse.py           # SSE 实时事件推送
│
├── services/                   # 业务逻辑层
│   ├── pipeline_service.py     # 后台任务 + 进度聚合
│   ├── class_service.py        # 班级/单元 CRUD
│   ├── file_service.py         # 文件管理（上传/校验）
│   ├── result_service.py       # 结果查询
│   ├── config_service.py       # 配置读写
│   └── log_service.py          # 结构化日志 (JSONL)
│
├── ui/                         # Vue 3 前端
│   └── src/App.vue             # SPA 主组件（8 页面视图）
│
├── resource/                   # 数据文件
│   ├── config.yaml             # 全局配置
│   ├── units/{单元}/            # 共享教材（标准音频+文本）
│   └── classes/{班级}/         # 班级数据（学生+仿读音频+结果）
│
├── models/                     # Whisper 模型文件
├── doc/                        # 技术架构 / 发版流程
├── agent_docs/                 # AI 开发辅助文档
└── tools/                      # benchmark_llm 等独立工具
```

## 配置

| 文件 | 用途 |
|------|------|
| `.env` | 仅 API 密钥，不纳管版本控制 |
| `resource/config.yaml` | 模型、模块开关、词云参数等 |

`.env` 中的同名变量优先级高于 YAML。

## API 接口

前缀 `/api/v1/`，响应格式 `{ success, data, error }`。
SSE 实时推送：`/events/tasks/{task_id}`。

## 环境要求

- Python >= 3.10
- ffmpeg（Whisper 音频处理）
- Node.js（仅前端开发时）
- PyTorch + Whisper + OpenSMILE（参见 requirements.txt）

## 打包分发

```bash
python build_exe.py          # 生产模式
python build_exe.py --dev    # 开发模式（无模型文件）
```

详见 `doc/发版流程.md` 和 `doc/技术架构说明书.md`。

## 开发

```bash
cd ui && npm install && npm run dev   # 前端热重载
python run_ui.py                       # 后端
```

详见 `AGENTS.md` 和 `agent_docs/`。
