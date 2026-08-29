# project/ 开发文档库总文档

> 本文档是开发库的导航中枢：**全局架构参考 + 域地图**。各域细节在 `modules/` 与 `core/`
> 的 design.md / designs-specs.md 中；文档库规则见 `../docs.md`。
> 锚定 2026-08-30 代码快照（v2.1.0 开发中，学习/冻结期）。行号会随开发漂移，以函数名为准。
> 2026-08-30 由《项目架构解析》（2026-08-29）与原 project.md 合并而成，原件已删（git 可溯源）。

---

## 1. 一句话定位

个人本地版考试复习加速器：单用户 Windows 本机运行，**FastAPI + React + SQLite**，
通过用户自配的 OpenAI 兼容 API 把复习资料生成为结构化课程（讲义/例题/自测/模拟卷），
并提供练习、错题、复习计划、AI 伴学等学习闭环。不做平台化、多租户、云部署（见 CLAUDE.md 禁区）。

- 后端：Python / FastAPI，约 20,000 行 / 60 个 .py 文件，入口 `backend/app/main.py`，端口 8000
- 前端：React + TypeScript + Vite，入口 `web/src/main.tsx`，端口 5173
- 数据：SQLite（WAL 模式）+ JSON 工作区文件，全部在 `backend/data/`
- 模型：OpenAI 兼容 API（用户在设置页配置），主备双模型 failover

## 2. 分层总览

```
浏览器 (React @5173)
   │  fetch / SSE
   ▼
FastAPI 中间件栈 (main.py:277-291)
   ├─ CORSMiddleware (放行 5173/3500)
   └─ AuthMiddleware  ← 白名单式 JWT 认证：/api/* 默认拒绝
   ▼
routers/  ── HTTP 层：参数校验、归属校验（owner）、调服务层        （12 个 router + deps，~100 路由）
   ▼
领域服务层 ── 业务逻辑：workspace / practice / review_plan /
   │          agent_chat / strategy / materials / course_feedback …（阶段2 拆分的 8 个域模块）
   ▼
agents/   ── AI 工作流：课程生成流水线、prompt、校验、patch        （19 个业务文件）
   ▼
model_client.py ── 唯一的模型调用出口：流式 + 首 token 超时 + 重试 + 主备 failover
   ▼
外部 OpenAI 兼容 API

旁路系统：
  agent_runtime.py ── 持久后台队列（AgentJobWorker 单进程单线程 + lease fencing）
  knowledge_service.py ── RAG 知识库（本地 Ollama/embedding 检索）
  study_scheduler.py ── 纯函数复习调度器（知识点 DAG 拓扑排序）
```

**关键认知**：所有 AI 调用只有 `model_client.py` 一个出口；所有长任务（课程生成等）
不占 HTTP 请求，而是进 SQLite 持久队列由后台线程消费，前端轮询进度（1.8s）。

## 3. 后端模块地图

### 3.1 入口与横切层

| 文件 | 行数 | 职责 |
|---|---|---|
| `main.py` | 277 | FastAPI 实例、lifespan 启动序列（建库/WAL/认领遗留课程/知识库同步/队列启动）、注册 6 种后台 job、挂载 12 个 router |
| `routers/deps.py` | — | `get_connection`（SQLite timeout=30）、`current_owner_id`、`require_course_ownership`（归属不过统一 404） |
| `auth_middleware.py` / `auth_service.py` / `tenancy.py` | 46+371+41 | JWT 签发校验、注册登录、owner_id 列迁移与遗留数据认领 |
| `paths.py` | 24 | 路径常量唯一定义点（DATA_DIRECTORY 等），零依赖，测试 patch 的锚点 |

### 3.2 领域服务层（阶段2 拆分产物，study_service.py 的门面仍 re-export 它们）

| 模块 | 行数 | 一句话职责 |
|---|---|---|
| `model_profiles.py` | 311 | 模型配置与用户画像（runtime/backup 模型、.env 读写） |
| `material_parser.py` | 717 | 资料解析级联：MarkItDown → Docling → RapidOCR → 视觉模型兜底，转 PDF/XLSX，缓存 |
| `materials.py` | 365 | 资料管理：上传/扫描/删除、主辅资料角色、资料记忆、知识库同步 |
| `workspace.py` | 403 | workspace.json 的 load/save/文件锁、内容质量迁移、空工作区、思维导图存取 |
| `practice.py` | 651 | 刷题/错题重做判分、AI 举一反三、掌握度联动、模拟卷修复与计分、计算题批改 |
| `review_plan.py` | 503 | 复习计划 AI 维护、每日进度、学习时长记录、顺延/减负/重排提案 |
| `agent_chat.py` | 716 | AI 伴学对话：SSE 流式、消息组装、滚动摘要、记忆联动 |
| `strategy.py` | 421 | 策略文档（复习总计划+课程 Prompt）的读写/版本化/初稿生成/审阅/对话式修订 |
| `course_feedback_service.py` | 1204 | 划词反馈全生命周期：意图识别→结构化提案→预览→确认应用→规则提炼 |
| `study_service.py` | 1553 | **门面 + 剩余域**：诊断/setup、主线生成入口 `approve_strategy_documents`、模块归并与思维导图、复习日程纯函数；9 个 re-export 块 |
| `study_scheduler.py` | 740 | **纯函数**：知识点前置依赖 DAG、三色 DFS 找环、拓扑排序、任务装包到复习日 |
| `knowledge_service.py` | 1402 | RAG：知识库建索引、embedding、资料上下文检索 `retrieve_material_context` |
| `mcp_gateway.py` | 697 | 外部 MCP 服务（B 站等）的网关与凭据 |
| `external_source_service.py` / `ocr_service.py` / `model_usage.py` / `course_style_templates.py` / `course_feedback_store.py` | — | 外源导入 job、OCR、token 用量遥测、课程风格契约（story/standard/dialogue）、反馈带锁存储 |

### 3.3 AI 工作流层 `agents/`（本项目的心脏，19 个业务文件）

| 文件 | 职责 |
|---|---|
| `content_workflow.py` | **总编排** `run_content_workflow`：规划（带签名缓存）→ 逐节生成 → 模拟卷 → 复习导引 → 排版审核 |
| `lesson_generation.py` | `LessonBuilder`：单节课的讲义+例题+自测生成与审查 |
| `question_generation.py` | 自测题生成（含考点覆盖增量补题） |
| `content_prompts.py` | 全部 prompt 模板（规划/讲义/自测/模拟卷） |
| `content_validation.py` / `contracts.py` | 确定性硬校验（结构/引用/覆盖）与 ReviewReport 契约 |
| `content_patches.py` | 定向 Patch：讲义/自测不合格时只修补丁而非整包重生成（path 归一化兼容 `/sections/0` 与点号） |
| `checkpoint_contracts.py` | **签名缓存契约**：输入不变则跳过昂贵的模型调用直接复用 checkpoint |
| `lesson_fallbacks.py` | 降级模板（仅极端兜底，历史决策：宁可显式失败也不低质成功） |
| `readability_review.py` / `orientation.py` / `answer_consistency.py` / `glossary.py` / `tutor.py` / `tools.py` | 排版审核、第 0 天复习导引、答案与解析一致性校验、术语表、伴学 agent、agent 工具箱 |
| `strategy_workflow.py` / `workflow_types.py` / `formula_rules.py` / `workflow.py` | 策略文档工作流、类型别名、公式规则、工作流公共基类 |

### 3.4 模型调用层 `model_client.py`（770 行，全项目唯一出网口）

调用链（自顶向下）：

```
_model_json / _model_agent_turn / _stream_model_turn   ← 三种业务入口（JSON / agent轮次 / 流式）
   → _model_completion    ← 拼装 payload、选择 provider、重试预算、主备 failover
      → _model_providers  ← 主模型 → 备用模型的有序列表（含熔断状态 _note_provider_result）
      → _provider_request ← 构造 requests.Request（stream=True）
      → _read_sse_response / _open_model_stream ← 流式读取，30s 首 token 超时判死
   → _extract_json        ← 从模型文本中鲁棒抽取 JSON
```

配套：`_transient_retry_delay`（抖动退避）、`get_backup_model_profile`/`save_backup_model_profile`、
`probe_model_chat`（设置页连通性测试）、`model_usage.py` 遥测（record_call_start/result）。

### 3.5 后台队列 `agent_runtime.py`（1104 行）

- `AgentJobWorker`（`main.py:105` 实例化）：单进程单线程消费循环，注册 6 种 job：
  `approve_strategy_documents`（课程生成主线）、`maintain_review_plan`、`rebalance_daily_plan`、
  `glossary_refresh`、`orientation_refresh`、`external_source_import`
- 可靠性三件套（132e3e1 修复，历史教训）：**lease_token 代际 fencing**（旧代完成/失败/续租全被拒）+
  **心跳线程 try/except 保护** + **同课程 running 互斥**（NOT EXISTS 子查询）
- 还承载：agent_runs / artifacts 表（`save_artifact` / `get_latest_artifact`，checkpoint 落盘）、
  job 进度 `update_agent_job_progress`（前端刷新不断线的关键）、术语表与外源存储、调整提案

## 4. 四条关键链路解剖

### 4.1 课程生成全链路（产品主干，读代码优先读这条）

```
前端 PlanningView → POST /api/courses/{id}/strategy-documents/approve-job
  → routers/strategy.py 入队
    → agent_runtime 持久队列（job: approve_strategy_documents）
      → study_service.approve_strategy_documents（study_service.py 剩余域的主入口）
        → agents/content_workflow.run_content_workflow
            ① 内容规划：签名命中 checkpoint 则跳过模型调用；否则 planner 生成+校验修复循环
            ② 逐节生成：LessonBuilder.build(task) → 讲义/自测各自"生成→硬校验→不合格走定向 patch"
            ③ 每节完成立即 on_progress 回调 → workspace.json 逐节落盘（前端 1.8s 轮询可见）
            ④ 全部完成后：模拟卷（同样签名缓存+修复循环）→ 第0天复习导引 → 排版审核
            ⑤ save_artifact(content_bundle) + 部分失败如实标记 partial
  前端 useStrategyGenerationJob / features/courseGeneration/generationStatus.ts 轮询展示
```

### 4.2 模型调用链路（一次出网）

任何 AI 功能 → `model_json(task_prompt, user_content, course_prompt)` → `_model_completion`
→ 重试预算内尝试主模型（流式，30s 无首 token 判死）→ 不行切备用 → 全挂则抛
"主模型与备用模型均不可用" → content_workflow 捕获后**立即中止本轮**避免逐节空转（content_workflow.py:350-356）。

### 4.3 一次读请求的一生（最简链路，学习起点）

`App.tsx` → `api.ts` → `apiClient.ts`（fetch 封装）→ `GET /api/courses`
→ AuthMiddleware 校验 JWT 注入 `request.state.user_id` → `routers/courses.py`
→ `Depends(require_course_ownership)` → `deps.get_connection()` → SQLite → JSON 返回。

### 4.4 划词反馈闭环（个性化主线）

`ModuleView` 划词 → `POST /course-feedback` → `course_feedback_service` 意图识别 →
结构化提案（删除预览/改写候选）→ 用户确认 → `apply` 写 workspace（带 revision 幂等）→
确认后的规则经 `merge` 沉淀为生成规则 → 注入后续课程生成（MUST- 前缀指令，content_workflow.py:63-66）。

## 5. 数据布局（`backend/data/`）

```
backend/data/
├─ exam_booster.db          SQLite（WAL）：courses / plan_tasks / archived_items /
│                           app_metadata / agent_jobs / agent_runs / artifacts /
│                           glossary / external_sources / adjustment_proposals …
├─ courses/<course_id>/
│   ├─ workspace.json       ★ 该课程的一切生成内容与进度（modules/knowledgePoints/
│   │                       tasks[].studyGuide/practiceQuestions/mockQuestions/revision…）
│   └─ （资料文件等）
├─ material_cache/          资料解析缓存
└─ model_profiles.json      模型配置

backend/.env                模型密钥 + JWT 密钥（丢失=全失效，永不提交）
```

**双存储分工**：SQLite 管"结构化小数据 + 队列/运行史"，workspace.json 管"每课程大文档"。
workspace 有 revision 与文件锁（workspace.py），写入走"读-改-写"整包保存。

## 6. 前端结构（web/src/）

| 文件 | 行数 | 职责 |
|---|---|---|
| `App.tsx` | 2052 | 顶层状态与视图切换、课程数据加载、登录态 |
| `components/ModuleView.tsx` | 5598 | **巨石组件**：学习页（讲义渲染/划词/反馈/练习/自测，104 个 useState），拆分是阶段3计划 |
| `components/SettingsView.tsx` | 1514 | 设置页（模型配置/连通性测试） |
| `components/CourseMindMapView.tsx` | 1608 | 思维导图 |
| `components/AiCompanion.tsx` | 722 | 侧边 AI 伴学（SSE） |
| `components/PlanningView.tsx` | 396 | 策略文档审阅与生成入口 |
| `api.ts` + `apiClient.ts` | 1181+113 | 全部后端调用封装（与后端路由一一对应） |
| `types.ts` | 854 | 前后端共享类型契约 |
| `hooks/` | — | useCourseTimer（学习计时）/ useGlossary / useTextSelection / useStrategyGenerationJob |
| `features/courseGeneration/` | — | 生成状态归并逻辑（含 partial 如实展示） |
| `demo/` | — | demo 模式：绕过真实后端，**不可用于验收**（CLAUDE.md） |

## 7. 跨领域关注点（改动前必知）

| 关注点 | 机制 | 位置 |
|---|---|---|
| 认证与隔离 | 白名单 JWT 中间件 + 所有课程路由 owner 过滤（404 不泄露存在性） | auth_middleware / deps.py |
| 缓存 | checkpoint 签名缓存：输入签名不变 → 直接复用 artifact，跳过模型调用 | checkpoint_contracts.py + agent_runtime.save_artifact |
| 失败策略 | 显式失败优于低质成功；partial 如实标记；无可用模型立即中止整轮 | content_workflow / lesson_fallbacks |
| 风格系统 | story/standard/dialogue 三风格 prompt 契约，模板 version 变更使旧 checkpoint 失效 | course_style_templates.py |
| 并发 | SQLite WAL + timeout=30；workspace 文件锁；队列单线程 + 同课程互斥 | deps / workspace / agent_runtime |
| 验证 | 后端 187 测试（含门面契约测试锁 re-export）；前端 tsc + vitest + build | CLAUDE.md 验证三件套 |

## 8. 域地图（modules/ + core/ 与代码的对应）

### 8.1 modules/（可见功能域，前后端纵切）

| 域文件夹 | 中文 | 核心代码锚点 | 文档状态 |
|---|---|---|---|
| sidebar-shell | 侧边栏框架 | `web/src/components/Sidebar.tsx` | ⏳ 占位 |
| topbar | 顶部栏 | `TopbarCourseTimer.tsx` + `hooks/useCourseTimer.tsx` | ⏳ 占位 |
| right-panel | 右侧面板框架 | `NotesSidebarPanel.tsx` 等面板容器 | ⏳ 占位 |
| overview | 总览 | App.tsx 工作台区 + review_plan 数据 | ⏳ 占位 |
| planning | 规划 | `PlanningView.tsx` + `strategy.py` + `agents/strategy_workflow.py` | ⏳ 占位 |
| mainline | 复习主线 | `ModuleView.tsx` + `content_workflow.py` 落点 | ⏳ 占位 |
| practice | 刷题 | `practice.py` submit_practice_answer 一族 | 🌱 样板 |
| mock-exam | 模拟卷 | `practice.py` submit_mock_answers/repair | ⏳ 占位 |
| wrong-book | 错题本 | `practice.py` 错题部分 + routers/courses 归档 | ⏳ 占位 |
| materials | 资料库 | `materials.py` + `routers/materials.py` | ⏳ 占位 |
| mind-map | 知识地图 | `CourseMindMapView.tsx` + workspace mind_map | ⏳ 占位 |
| glossary | 专业名词 | `agents/glossary.py` + `useGlossary` + GlossaryTermSpan | ⏳ 占位 |
| review-plan | 复习计划 | `review_plan.py` + `study_scheduler.py` 调用方 | ⏳ 占位 |
| selection | 划词基础 | `useTextSelection.ts` + `SelectionToNoteToolbar.tsx` | ⏳ 占位 |
| notes | 笔记 | `utils/noteHighlights.ts` + `NoteHighlightDismiss.tsx` | ⏳ 占位 |
| course-feedback | 课程意见反馈 | `course_feedback_service.py`(1204行) + `course_feedback_store.py` + CourseFeedbackPreview | ⏳ 占位 |
| ai-companion | AI 伴学 | `AiCompanion.tsx` + `agent_chat.py`(SSE) | ⏳ 占位 |
| archive | 归档 | archived_items 表 + `deps.py` 归档辅助 | ⏳ 占位 |
| auth-account | 账户与登录 | `LoginPage.tsx` + `auth_service.py` | ⏳ 占位 |
| settings | 设置 | `routers/settings.py` + `SettingsView.tsx` + `model_profiles.py` | 🌱 样板 |

### 8.2 core/（引擎与基础设施，用户不可见）

| 域文件夹 | 中文 | 核心代码锚点 | 文档状态 |
|---|---|---|---|
| model-client | 模型调用 | `model_client.py`(770行) + `model_usage.py` | 🌱 样板 |
| job-queue | 后台队列 | `agent_runtime.py`(1104行) AgentJobWorker + lease fencing | ⏳ 占位 |
| content-pipeline | 课程生成流水线 | `agents/content_workflow.py` + lesson/question/validation/patches | ⏳ 占位 |
| knowledge-rag | RAG 检索 | `knowledge_service.py`(1402行) retrieve_material_context | ⏳ 占位 |
| material-parser | 资料解析 | `material_parser.py`（MarkItDown→Docling→RapidOCR→视觉兜底） | ⏳ 占位 |
| scheduler | 复习调度器 | `study_scheduler.py`(740行，纯函数 DAG) | ⏳ 占位 |
| storage | 存储与工作区 | `workspace.py` + `paths.py` + SQLite 表 + 双存储分工 | ⏳ 占位 |
| auth-isolation | 认证与隔离 | `auth_middleware.py` + `tenancy.py` + deps.require_course_ownership | ⏳ 占位 |
| external-mcp | 外部 MCP | `mcp_gateway.py` + `external_source_service.py` | ⏳ 占位 |

> 文档状态：⏳ 占位（design.md 仅一句话定位）→ 🌱 样板/进行中 → ✅ 已审定。
> 生长节奏：随学习阶段（见 ../study/guide/）逐域补全，不批量 AI 起草。

## 9. 已知复杂度热点与债务（2026-08 看板口径）

- `ModuleView.tsx` 5598 行 / 104 useState —— 阶段3 待拆
- `study_service.py` 剩余 1553 行待继续拆（门面模式不变）
- `agent_runtime.py` 是"队列+存储+杂项"混合体，职责待分离
- Windows 下 Vite/Rolldown 生产构建原生 exit 1（tsc 正常）；uvicorn --reload 在中文路径失效
- 课程生成单节约 7~9 分钟，效率优化方案待确认（`proposals/课程生成效率优化方案.md`）

## 10. 文档索引与本库导航

- 根 `CLAUDE.md`：协作契约（禁区/验证三件套/提交纪律/数据安全）——最高优先级
- `../docs.md`：文档库宪法（结构/生命周期/权限/AI 生成语言规范）
- `DEV_BOARD.md`：实时看板（状态真源，会话结束时刷新）｜ 日志：`log/` ｜ 灵感：`ideas/` ｜ 提案：`proposals/`
- `../study/guide/项目学习指南.md`：学习路线（本文的"怎么读"版本）
- `draft/course-style-lab/`：课程风格实验场与决策记录
