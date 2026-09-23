de

# 期末粥++ (Exam Porridge Booster · Campus)

> **多用户校园版**。基于个人版 [Qimo-Porridge](https://github.com/bug-zi/Qimo-Porridge)（冻结于 `v1.0.0-personal`）演进而来。
> 本仓库目标：账号体系、课程广场（模板分享/审核/安装）、管理后台、云服务器部署。个人单机版请使用上游仓库。

面向大学生期末周冲刺的 AI 学习工作台。围绕单门课程导入资料、完成快速摸底、生成复习主线，并在刷题、模拟卷、笔记和错题回顾中持续调整学习策略。校园版新增：

- **账号体系**：邮箱注册登录，数据按用户隔离
- **课程广场**：用户将生成的速成课程提交审核，审核通过后公开，其他用户可预览并一键添加
- **管理后台**：用户/课程审核/反馈/使用统计/运维日志
- **LLM 额度**：平台赠送小额免费额度，重度使用可配置个人 API Key

## 核心特性

### 课程学习闭环

- **课程空间**：多课程切换、考试倒计时、目标分数和每日可用时间管理。
- **资料库**：本地导入 PPT/PPTX、PDF、Word、Excel、Markdown 等格式；MarkItDown + 可选 Docling/LibreOffice 解析，解析结果本地缓存，资料引用可追溯，区分「AI 可读」与「浏览器可预览」状态。
- **复习主线**：按知识点优先级组织的每日学习任务，任务状态实时同步。
- **刷题练习**：题目作答、即时讲评、掌握度更新，可重置单题作答记录。
- **模拟卷**：限时组卷、蓝图校验、评分与错题沉淀，支持重新生成与备份回滚。
- **笔记 & 错题本**：关联知识点的轻量笔记；错误归因、复练和回顾，删除内容进归档区（默认 7 天可恢复）。

### 课程思维导图

- 基于 React Flow + ELK 自动布局的课程知识图谱，支持课程 / 章节 / 知识点三级下钻。
- 知识点节点展示掌握度、难度与前置依赖边（「前置」标注），薄弱知识点高亮。
- 节点详情侧栏聚合该知识点的任务、练习题、真题考点与错题，支持手动编辑并保存。

### 确定性复习调度器

- LLM 只负责抽取知识点之间的前置依赖（prerequisites）与难度，复习任务的**顺序完全由确定性图算法计算**（拓扑排序 + 按日装包 + DAG 约束内动态重排），保证「循序渐进、从简单到难」，不依赖模型当次的排序自觉。
- 自动清洗依赖数据：环检测 + 断边、剔除自指/未知引用、难度钳制。
- 「共复习 K 次」均匀落到「距考试 D 天」的日程上，前后端口径一致（`reviewSchedule.ts` ↔ `_review_session_days`）。

### AI 伴学 Agent

- **流式对话**（SSE）：工具调用轨迹在对话历史中持久可见，随时回看 Agent 做了什么。
- **直接落地工具**：Agent 可直接更新任务状态、创建笔记、调整计划参数，执行结果落库。
- **主动提案**：理解自然语言调整需求（如「删除不考内容」「增加复习时间」），生成待确认的计划调整提案，用户确认后才应用。
- **长期记忆**：向量检索（numpy 余弦相似度）+ 滚动摘要 + 相关历史召回，跨会话记住学习偏好与薄弱点。
- **外部检索工具**（需自行配置对应 MCP 服务）：fetch-mcp 读取网页、Tavily 联网搜索、arXiv 论文搜索与全文阅读。

### 学习体验

- **多课程规划日历**：跨课程的计划时间线视图，按月展示每天的课程任务、预计时长与实际投入，超预算提醒。
- **课程计时器**：顶栏常驻，任意页面可开始/暂停/记入/放弃，时间日志落库可删除。
- **划词摘录**：选中任意文本即可一键追加到当前课程的复习笔记。
- **弧形滚轮选择器**：课程切换的 OptionWheel 交互组件，支持拖拽、键盘与循环滚动。
- 浅色 / 深色主题、自定义字体与字号、背景融合的视觉方案。

## 技术架构

```text
React 19 + TypeScript + Vite
        |
        |  本地 HTTP API + SSE 流式对话
        v
FastAPI + SQLite + 本地文件库
        |
        +-- 确定性复习调度器（纯函数图算法）
        +-- 向量记忆（numpy 余弦相似度）
        +-- MCP 网关（fetch / Tavily / arXiv / GitMCP）
        v
OpenAI 兼容模型适配层（GPT / DeepSeek / GLM / 自定义）
```

- 前端负责课程工作台、思维导图渲染、学习交互与本地展示状态。
- 后端负责本地 API、资料解析、学习记忆、复习调度与 Agent 编排。
- SQLite 保存课程、资料、知识点、任务、作答、错题、笔记、消息与调整提案。
- 课程资料与解析产物保存在 `backend/data/courses/{course_id}/` 下。

## 本地运行

后端（Windows，本仓库已约定使用 `backend/.venv`）：

```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

co前端：

```bash
cd web
npm install
npm run dev
```

后端默认监听 `http://127.0.0.1:8000`；前端开发服务器默认监听 `http://127.0.0.1:5173`。如前端部署地址不同，需要同步调整后端 CORS 白名单。

### 多用户与部署注意事项

- `/api/*` 默认需要登录；仅健康检查与注册/登录/刷新端点在白名单中。课程、归档、自画像等数据均按当前用户隔离。
- 首次启动会在 `backend/.env` 中生成 `EXAM_BOOSTER_JWT_SECRET`；部署时务必持久化该文件或显式配置同名环境变量，否则重启/迁移后已有 token 会全部失效。
- SQLite 数据库位于 `backend/data/exam_booster.db`，课程文件位于 `backend/data/courses/{course_id}/`。生产/演示环境切换前建议备份或清理测试库。
- 默认 CORS 仅面向本地开发地址（`127.0.0.1:5173`/`localhost:5173`）；公网部署需改成实际 HTTPS 域名，并通过反向代理终止 TLS。
- 多进程部署需谨慎：当前 `AgentJobWorker` 按单 FastAPI 进程设计，`uvicorn --workers N` 会启动多份 worker，后续应加分布式锁或拆独立任务进程。
- 多用户部署不要启用 `VITE_DEMO_MODE=true`；demo 模式会绕过认证，仅用于静态演示。

运行测试：

```bash
cd backend
.\.venv\Scripts\Activate.ps1
pip install pytest
pytest tests/
```

## 隐私与边界

- 校园版已包含邮箱账号体系与按用户隔离的数据访问控制，但仍默认由部署者自管 SQLite 数据库和本地文件库。
- 网址资料仅保存链接、备注和用户摘录，不自动抓取网页正文。
- 外部联网检索默认关闭，仅在用户配置对应 MCP 服务后可用。
- 模型调用通过用户配置的 GPT、DeepSeek、GLM 或 OpenAI 兼容接口完成；API Key 仅保存在本机 `.env`，不会上传。

## 项目结构

```text
backend/
  app/
    main.py               # FastAPI 路由（/api/courses/{course_id}/...）
    agent_runtime.py      # Agent 运行时（工具循环、流式输出）
    agents/
      tutor.py            # AI 伴学系统提示词
      tools.py            # 内置 + MCP 工具定义与执行
      workflow.py         # 画像/计划/组题/讲评等工作流
    study_scheduler.py    # 确定性复习调度器（纯函数）
    study_service.py      # 学习空间服务（计划重排、时间日志等）
    knowledge_service.py  # 知识点/资料/向量记忆
    mcp_gateway.py        # MCP 服务网关
  tests/                  # pytest 测试
web/
  src/
    components/           # 思维导图、规划日历、计时器、划词摘录等
    hooks/                # 课程计时、划词选区、镜面按钮
    utils/                # 复习日分布、课程时间线
```

详细产品方案见 [期末粥加速器_V1方案.md](./期末粥加速器_V1方案.md)，实现进度见 [开发文档.md](./开发文档.md)。
