# CLAUDE.md — 语音仿读质量评估系统

## WHAT：技术栈与代码库地图

### 技术栈

| 层 | 技术 |
|----|------|
| **核心引擎** | Python 3.13.5，虚拟环境 `.venv/` |
| **语音分析** | OpenSMILE (ComParE 2016 LLD) |
| **语音转写** | OpenAI Whisper (small.en / medium.en) |
| **LLM 比对** | DeepSeek API (v4-pro，思考模式) |
| **可视化** | matplotlib (Agg 后端) + wordcloud |
| **数据处理** | pandas |
| **Web 后端** | FastAPI + uvicorn + python-multipart |
| **Web 前端** | Vue 3 + TypeScript + Vite + ECharts + markdown-it |
| **配置** | PyYAML (config.yaml) + python-dotenv (.env) |

### 代码库地图

| 位置 | 说明 |
|------|------|
| **核心模块（src/）** | |
| `src/launcher.py` | 主调度器，8 阶段流水线，三线程池，断点续传，UI 回调支持 |
| `src/voice_compare.py` | OpenSMILE 语音分析：8 维评分 + 3×3 对比图 |
| `src/text_llm.py` | Whisper 转写 + LLM 比对 + 知识点查询 + 错误数据导出 |
| `src/audio_output.py` | 后处理：将分析结果汇总到 Excel |
| `src/filter_name.py` | 预检查：对比音频文件列表与已有记录 |
| `src/error_visualizer.py` | 错题可视化：三分类词云 + 历史进步曲线 |
| `src/config.py` | 统一配置（dataclass + YAML + .env 加载），零项目依赖 |
| `src/constants.py` | 共享常量、正则、列名（零项目依赖） |
| `src/utils.py` | 通用工具：文件查找、格式化、报告读写、JSON I/O |
| **Web 层（server/）** | |
| `server/main.py` | FastAPI 应用工厂：注册路由、中间件、静态文件托管 |
| `server/api/v1/health.py` | 健康检查 + 依赖可用性检测 |
| `server/api/v1/classes.py` | 班级/单元/学生 CRUD（13 个端点） |
| `server/api/v1/config.py` | 配置读写与验证（YAML + .env） |
| `server/api/v1/files.py` | 素材管理：音频上传、文本编辑、知识库预览 |
| `server/api/v1/tasks.py` | 任务控制：启动/取消/状态/日志 |
| `server/api/v1/results.py` | 结果查询：总览、统计、学生详情、错误聚合 |
| `server/api/v1/exports.py` | 数据导出：文件发现与下载 |
| `server/api/v1/logs.py` | 日志通道读取 |
| `server/events/sse.py` | SSE 任务事件推送（asyncio.Queue 驱动） |
| **服务层（services/）** | |
| `services/app_context.py` | UI 运行时上下文（路径解析、目录创建） |
| `services/class_service.py` | 班级/单元/学生 CRUD + 遗留数据自动迁移 |
| `services/config_service.py` | 配置读写（YAML + .env 原子写入）+ 验证 |
| `services/file_service.py` | 文件上传/校验/管理（含 zip 解压、命名校验） |
| `services/log_service.py` | 结构化日志（JSONL），线程安全，单例模式 |
| `services/pipeline_service.py` | 流水线封装：后台线程调用 launcher，asyncio.Queue 事件推送 |
| `services/result_service.py` | 结果查询：summary/statistics/student detail/error aggregate |
| **前端（ui/）** | |
| `ui/src/App.vue` | Vue 3 SPA 主组件（7 页面视图 + 1 Modal） |
| `ui/src/api.ts` | HTTP 客户端：fetch 封装 + toast 通知 + 错误处理 |
| `ui/src/types/index.ts` | TypeScript 类型定义（16 个接口） |
| `ui/src/styles.css` | 全局样式：CSS 变量 + Grid 布局 + 动画 + 响应式 |
| **入口与配置** | |
| `run_ui.py` | Web UI 一键启动（uvicorn + 自动打开浏览器） |
| `run.py` | CLI 模式一键启动（等价于 `python src/launcher.py`） |
| `resource/` | 所有数据文件：音频/文本/知识库/结果/班级/日志 |
| `doc/` | 项目文档：需求书、指标说明 |
| `agent_docs/` | 渐进式披露，按需读取的任务指令 |
| `tools/` | 独立工具（benchmark_llm 等），不参与流水线 |

### 依赖方向（单向，三层架构）

```
ui/ ──── HTTP/SSE ────▶ server/ ────▶ services/ ────▶ src/
                              │              │              │
                              └──────────────┴──────────────┘
                                   均不反向依赖上层
```

src/ 内部依赖（保持原有单向性）：
```
src/config.py  ←  src/constants.py  ←  src/utils.py
       │                  │                   │
       └──────────────────┼───────────────────┤
                          ↓                   ↓
                   src/launcher.py ──→ src/voice_compare.py
                          │          ──→ src/text_llm.py
                          │          ──→ src/audio_output.py
                          │          ──→ src/filter_name.py
                          │          ──→ src/error_visualizer.py
```

**零侵入原则**：server/、services/、ui/ 是新增层，通过薄封装调用 src/ 现有 API，不修改 src/ 内部逻辑。launcher.py 的 `main()` 新增了可选参数（`progress_cb`、`cancel_event`、`pause_event`、`paths_override`），但在 CLI 模式下完全向后兼容。

---

## WHY：项目目的

评估学生英语仿读质量，从两个维度量化：
1. **语音相似度**（OpenSMILE 8 个声学维度）：基频、能量、Jitter、Shimmer、HNR、谱质心、语速
2. **文字准确度**（Whisper 转写 + LLM 逐句比对）：标注替换/多读/漏读错误并关联知识点

### 各组件作用
- **launcher.py**：将所有模块串联为完整流水线，管理并发调度和断点续传；通过可选回调向 UI 推送进度
- **voice_compare.py**：对比学生与标准音频在 8 个声学维度上的相似度，生成 3×3 可视化报告
- **text_llm.py**：Whisper 语音转文字后由 LLM 逐句比对，标注差异并匹配学习资料
- **audio_output.py**：将分散的 .md 报告和 .png 图表聚合到 Excel 汇总表
- **filter_name.py**：运行前校验数据完整性，确保音频文件与记录一致
- **error_visualizer.py**：聚合所有学生的错误数据，生成词云图和历史进步曲线
- **三线程池设计原因**：voice（C++ 库非线程安全 → 1 worker）、whisper（PyTorch 模型大 → 单例 + 1 worker）、LLM（纯 I/O → 400 workers）
- **Web UI 层（server/ + services/ + ui/）**：将上述 CLI 功能包装为浏览器可访问的图形界面，支持班级/单元管理、文件拖拽上传、实时进度监控、交互式结果浏览（详见 `agent_docs/ui-architecture.md`）

### 班级/单元数据模型（共享单元架构）
单元为**共享教材**，所有班级可见同一套单元；班级数据按班级隔离：
```
resource/units/{unit_name}/           # 共享教材
├── standard_audio/                   # 标准音频
└── standard_text/                    # 标准文本
resource/classes/{class_name}/        # 班级私有
├── students.csv                      # 学生名单
└── {unit_name}/                      # 本班在此单元的数据
    ├── imitation_audio/              # 学生仿读音频
    └── result/                       # 评估结果
```
首次启动 `run_ui.py` 自动创建默认班级和默认单元。

---

## HOW：工作方式

### 运行命令
```bash
python run_ui.py                   # Web UI 一键启动（推荐）
python run.py                      # CLI 模式全流程
python build_exe.py                # PyInstaller 打包（分发用）
python build_exe.py --dev          # 打包（开发模式，不含模型）
cd ui && npm run dev               # 前端开发模式（热重载，需先启动后端）
cd ui && npm run build             # 前端生产构建（输出到 ui/dist/）
```

### 模块开关（config.yaml + .env 双重控制）
配置优先级：`config.yaml` 的 `modules` 段为默认值，`.env` 中的同名变量可覆盖。UI 的配置中心页面可视化编辑这些开关。

```yaml
# resource/config.yaml 中的 modules 段：
modules:
  voice_analysis: true     # Phase 2: 语音分析
  whisper_transcribe: true # Phase 3: 转写
  llm_compare: true        # Phase 3: LLM 比对
  post_process: true       # Phase 5: 后处理
  filter_precheck: true    # Phase 7: 预检查
  error_visualize: true    # Phase 8: 词云+曲线
```
也可在 `.env` 中设置（如 `VOICE_ANALYSIS=0`），优先级高于 YAML。

### 渐进式披露
本文件（CLAUDE.md）为总入口。开始工作前先读完本文件。
然后根据任务类型，决定是否读取 agent_docs/ 中对应文件：

| 文件 | 何时读取 |
|------|---------|
| `agent_docs/coding-conventions.md` | 修改任何代码前（Python + Vue/TS/CSS） |
| `agent_docs/frontend-conventions.md` | 修改前端 Vue/TS/CSS 代码时 |
| `agent_docs/modal-conventions.md` | 添加弹窗/Modal 组件时 |
| `agent_docs/verification-guide.md` | 添加功能 / 修 bug 后 |
| `agent_docs/file-handling-rules.md` | 处理文件 I/O 时 |
| `agent_docs/resource-naming-conventions.md` | 添加资源文件时 |
| `agent_docs/module-architecture.md` | 跨模块修改时 |
| `agent_docs/workflow-phases.md` | 修改流水线逻辑时 |
| `agent_docs/ui-architecture.md` | 修改 UI 层时（注：此文档已淘汰，以 `doc/技术架构说明书.md` 为准） |
| `agent_docs/api-conventions.md` | 修改/新增 API 端点时 |
| `doc/技术架构说明书.md` | 了解完整项目架构 |
| `doc/发版流程.md` | 执行发版/打包操作时 |

所有 agent_docs 文件为**英文文件名 + 中文内容**，且**不含代码片段**（纯指令文档）。

### 关键约定

**Python 后端**
- 所有模块顶部有中文 docstring（功能、依赖）
- 私有函数 `_` 前缀；线程锁 `_xxx_lock` 后缀
- `text_llm.py` / `voice_compare.py` 各自可独立运行
- 错误处理：单学生失败标记 `failed`，不阻塞其他学生
- `matplotlib.use("Agg")` 必须在任何 matplotlib 导入前设置
- 所有资源路径统一经 `resource/` 目录
- `.env` 不提交到版本控制（已在 .gitignore 中）

**Web API**
- 统一响应格式：`{success: bool, data: T, error?: string}`
- REST 端点前缀：`/api/v1/{resource}`
- SSE 端点前缀：`/events/`
- 班级/单元通过 query string 传递（`?class_id=...&unit_id=...`）
- 异常不直接抛 HTTPException，返回 `{success: false, error: "..."}`

**Vue 前端**
- 使用 Composition API + `<script setup lang="ts">`
- 所有 API 数据类型定义在 `ui/src/types/index.ts`，禁止 `any`
- 每个数据获取必须有 loading/error/empty 三态处理
- API 调用使用 `api.ts` 封装，错误自动 toast 通知
- 前端构建产物 `ui/dist/` 不提交到版本控制

**零侵入集成**
- `server/` 和 `services/` 是新增代码，不修改 `src/` 现有文件
- `src/launcher.py` 新增的可选参数（`progress_cb`、`cancel_event`、`pause_event`、`paths_override`）均有 `None` 默认值，CLI 模式完全兼容
- `python run.py` 命令行模式持续可用，与 Web UI 并行不悖
