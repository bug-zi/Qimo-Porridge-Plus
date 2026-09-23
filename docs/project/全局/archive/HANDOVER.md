# 期末粥++ 开发交接文档（个人本地版优先）

> 更新日期：2026-08-28
> 仓库：`D:\Code\自创项目\网站类\期末粥++`
> 当前分支：`dev`
> 当前决策：**暂停服务器部署与企业级扩建，先完成个人版本地学习闭环。**

## 一、接手时先读

1. `docs/期末粥加速器_V1方案.md`：当前产品范围、优先级和验收标准。
2. 本文：实际实现、当前风险、启动与验证方式。
3. `git log --oneline -12`：最近开发演进。
4. `git status --short`：工作区存在用户未提交改动，接手时不得覆盖。

根目录 `README.md` 仍保留较多“校园版/云部署”描述。现阶段执行优先级以本交接文档和新版 V1 方案为准：已实现的认证与隔离保留，但不要继续开发课程广场、管理后台和云部署。

## 二、产品与架构现状

### 1. 当前支持形态

- Windows 本机运行。
- 前后端分离，但都部署在同一台个人电脑。
- 浏览器访问本地 Vite 页面，调用本地 FastAPI API。
- SQLite + 本地文件目录持久化。
- 当前以一个本地用户长期使用为主要场景；账号功能无需删除。
- 模型通过用户配置的 OpenAI 兼容 API 调用，可配置主模型与备用模型。

### 2. 技术栈

- 后端：FastAPI、SQLite WAL、后台 `AgentJobWorker`、SSE Agent 对话。
- 前端：React 19、TypeScript、Vite 8、React Flow、ELK、KaTeX。
- 资料解析：MarkItDown；可选 Docling/LibreOffice；RapidOCR + PyMuPDF 处理扫描资料。
- 记忆与检索：SQLite/本地文件、numpy 向量相似度、滚动摘要。

### 3. 关键本地数据

| 路径 | 内容 |
|---|---|
| `backend/data/exam_booster.db` | 主 SQLite 数据库 |
| `backend/data/courses/{course_id}/` | 课程 workspace、资料、策略、反馈、导图等 |
| `backend/data/material_cache/` | 资料解析缓存 |
| `backend/data/embedding_cache.db` | 向量缓存 |
| `backend/data/model_profiles.json` | 模型配置资料 |
| `backend/.env` | API Key、JWT secret 等本机敏感配置 |

停止后端后再整体备份 `backend/data/` 和 `backend/.env`。运行时数据库可能存在 `-wal`/`-shm` 文件，不要只热复制主 db 后就假定备份完整。

## 三、已经完成的主要能力

### 1. 基础与认证

- FastAPI 路由已按域拆到 `backend/app/routers/`。
- 注册、登录、刷新、登出、`/me` 已实现。
- access token + refresh token 轮换与重放检测已实现。
- 课程、归档和用户画像按 owner 隔离。
- SQLite 已启用 WAL 和 timeout。

这些原本为校园多用户版准备，但在个人版中继续作为本地数据保护和未来兼容基础，不是近期扩建方向。

### 2. 课程资料与解析

- 多课程、归档恢复、课程工作区持久化。
- 支持常见课件、文档、表格、Markdown、PDF、图片资料。
- MarkItDown 主链，Docling/LibreOffice 可选增强。
- 扫描 PDF/图片使用 RapidOCR，本地识别不足时可升级视觉模型。
- 解析缓存、资料状态、知识点同步与来源引用已具备基础实现。

### 3. 策略、课程与质量工作流

- 课程画像、复习总计划、课程 Prompt 生成与修订。
- 课程策略文档有版本历史，支持增量和全量课程生成。
- 标准版、对话版、故事版三种风格。
- 故事版加入结构契约、故事上下文和专门 Prompt。
- 有公式规则、可读性审查、检查点契约、内容校验与修复。
- 模拟题生成失败时倾向显式报错，不再用明显低质量内容假装成功。
- 支持课程全局反馈、小节反馈、重写提案与版本冲突检查。

### 4. 学习功能

- 复习主线、每日任务和确定性调度器。
- 知识思维导图与前置依赖。
- 刷题、模拟卷、评分、错题本、笔记。
- 术语表、划词摘录、课程计时器、规划日历。
- AI 伴学流式对话、工具执行、长期记忆与计划调整提案。
- 浅色/深色主题和显示设置。

### 5. 最近一次提交

`8c27763`：

- 增加备用 AI 模型配置和故障切换基础。
- 修复部分 AI 课程生成失败问题。
- 优化故事版课程的故事感。
- 增加生成期间 Token/模型调用量展示相关能力。

此前 `7a773b4` 是一次较大的课程生成与学习体验整合提交，涉及 Agent 模块化、课程风格、质量校验、反馈、OCR、前端学习页面和大量测试。

## 四、当前工作区状态（重要）

接手时 `git status --short` 显示：

- `M backend/app/study_service.py`
- `M web/src/App.tsx`
- `M web/src/components/ModuleView.tsx`
- `?? docs/故事版课程生成_数学女孩教学叙事借鉴.md`

另有本次更新的两份文档。

未提交代码的意图：

- `study_service.py`：模型单请求超时从 1800 秒缩短为 300 秒；普通与瞬时重试都缩短为 2 次；供应商总预算缩短为请求超时 + 30 秒。目的是避免坏上游长时间占住单线程生成队列。
- `App.tsx`：提交策略生成后台任务后记录模型用量基线。
- `ModuleView.tsx`：增加 `generationUsageBaseline` 属性定义。

注意：这组前端改动看起来还没有完全串完。继续开发前先检查属性是否已从 App 传给 ModuleView、是否实际参与增量用量展示，再决定补完或回退；不要直接覆盖用户改动。

## 五、当前验证结果

2026-08-28 使用：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q
```

结果：

- `125 passed`
- `2 failed`
- 总耗时约 16 秒

失败测试：

1. `test_background_generation_waits_for_shared_content_lock`
2. `test_background_generation_forwards_incremental_batch`

均位于 `backend/tests/test_mainline_generation_repair.py`。测试中的 `fake_approve` 只记录参数并隐式返回 `None`，而现在 `backend/app/main.py::_approve_strategy_documents_job` 会读取返回值的 `workspace.get("tasks", [])` 以汇报完成度，因此触发 `AttributeError`。

处理建议：

- 优先判断新的 handler 返回契约是否必须要求 workspace。
- 若必须，更新测试替身返回最小 workspace，并补断言完成度字段。
- 若需要兼容旧 handler/替身，则在 `_approve_strategy_documents_job` 对非 dict 返回值做防御处理。
- 修复后重新跑全量测试，不能只跑这两个用例。

旧 HANDOVER 中的 `44 passed, 3 skipped` 已过时，不再作为当前基线。

## 六、本地启动与检查

### 后端

必须优先使用仓库内 `backend/.venv`：

```powershell
cd D:\Code\自创项目\网站类\期末粥++\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

### 前端

```powershell
cd D:\Code\自创项目\网站类\期末粥++\web
npm install
npm run dev
```

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

### 常用验证

```powershell
# 后端全量测试
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q

# 前端类型检查
cd ..\web
npx tsc -b

# 前端生产构建
npm run build
```

历史上 Vite/Rolldown 在 2000 多 modules transformed 后出现过 Windows 原生退出；若再次发生，应保存完整输出并核对当前 Vite/Rolldown 版本，不要把无 TS 错误等同于构建通过。

## 七、下一步任务（按优先级）

### P0：先把当前分支恢复为可靠基线

1. 修复 2 个失败测试，跑到后端全绿。
2. 补完或整理“生成用量基线”前端改动，执行 `npx tsc -b`。
3. 执行 `npm run build`，记录是否仍有原生构建退出。
4. 手工验证模型超时、两次重试、主备切换和错误提示。
5. 确认后台队列在上游挂起时能及时释放并继续处理后续任务。

### P1：真实课程端到端验收

1. 用文字型 PDF/PPT 走一次完整生成。
2. 用含公式的理工科资料验证公式、题目和讲解。
3. 用扫描 PDF/图片验证 RapidOCR 和视觉兜底。
4. 每类都按“导入 → 策略 → 增量第一课 → 继续生成 → 学习 → 练习 → 错题/笔记”验收。
5. 分别抽查标准版、对话版、故事版，不只验证故事版。

### P2：个人本地版可维护性

1. 提供停止服务后的备份/恢复脚本或明确步骤。
2. 区分测试数据和个人正式数据，避免误清库。
3. 改善失败、部分成功、继续生成、取消和恢复状态。
4. 补本地首次安装、依赖检查和启动说明。

### 暂停项

以下内容暂时不要开工：

- 课程广场。
- 管理后台与管理员角色。
- 云服务器、公网域名、HTTPS 和反向代理。
- PostgreSQL、Redis、Celery、对象存储、容器编排。
- 企业组织、多租户运营、支付和额度售卖。

## 八、关键文件索引

| 文件 | 职责 |
|---|---|
| `backend/app/main.py` | FastAPI 组装、lifespan、后台任务 handler |
| `backend/app/study_service.py` | 课程工作区、模型调用、主备切换、解析与核心业务；文件很大，修改需小心 |
| `backend/app/agent_runtime.py` | Agent 运行、消息/提案与持久后台任务 |
| `backend/app/agents/strategy_workflow.py` | 课程策略生成 |
| `backend/app/agents/content_workflow.py` | 课程正文生成主流程 |
| `backend/app/agents/lesson_generation.py` | 单课生成 |
| `backend/app/agents/content_prompts.py` | 课程内容 Prompt |
| `backend/app/agents/content_validation.py` | 生成内容质量校验 |
| `backend/app/course_style_templates.py` | 标准/对话/故事风格模板 |
| `backend/app/ocr_service.py` | 本地 OCR 与扫描资料处理 |
| `backend/app/study_scheduler.py` | 确定性复习调度 |
| `backend/app/routers/settings.py` | 主模型/备用模型等设置接口 |
| `web/src/App.tsx` | 前端主状态与页面编排 |
| `web/src/components/ModuleView.tsx` | 课程生成与主要学习模块；体积较大 |
| `web/src/components/SettingsView.tsx` | 模型及应用设置 |
| `web/src/components/AiCompanion.tsx` | AI 伴学界面 |
| `web/src/api.ts` / `apiClient.ts` | API 调用与认证请求 |
| `backend/tests/` | 当前 22 个测试文件，作为回归基线 |

## 九、已知风险与注意事项

1. `study_service.py` 和 `ModuleView.tsx` 都很大，继续堆功能会增加回归风险；近期优先小步修改并补测试，不做大重构。
2. `AgentJobWorker` 当前按单 FastAPI 进程设计；个人版不要开多个 uvicorn worker。
3. `backend/.env` 丢失会丢模型密钥，并使已有 JWT 失效；它必须纳入用户自己的安全备份，但不能提交到 Git。
4. 本地数据库已有测试用户和课程数据；清理前必须备份，不能默认当成可删除数据。
5. demo 模式会绕过真实认证和后端流程，不可用它代替个人版端到端验收。
6. 外部 MCP 是可选增强，默认关闭时核心学习流程仍应可用。
7. 课程生成可能耗时且消耗 Token，默认优先增量生成一课，再由用户决定是否继续。
8. 失败必须明确展示，不能为了“流程完成”回退成不可用的低质量课程正文。
9. `backend/app/routers/__init__.py` 历史上有 UTF-8 BOM，脚本读取时必要时使用 `utf-8-sig`。

## 十、交接完成定义

下一位开发者在开始新增功能前，应做到：

- 理解当前只做个人本地版。
- 保留现有认证/隔离，但不向平台化继续扩张。
- 保护当前未提交改动和本地数据。
- 先修复现有 2 个测试失败。
- 用真实课程验证，而不是只看单元测试或静态页面。
- 每次变更后至少记录后端测试、前端类型检查和构建结果。
