# 期末粥++ 项目约束（所有 AI 助手必读）

> 本文件是项目的最高协作契约。每次会话开始时先读完本文件，再动手。
> 配套的实时状态看板在 `docs/project/DEV_BOARD.md`——**每次会话结束时必须更新它**。
> 文档库机制正本见 `docs/project/README.md`（权责表 / spec-plan / 归档机制）：开发文档在 `docs/project/`，
> 学习文档在 `docs/study/`；涉及某域改动前先读该域的 design.md / designs-specs.md（已有时）。

## 项目定位（一句话）

个人本地版考试复习加速器：单用户 Windows 本机运行，FastAPI + React + SQLite，通过用户自配的 OpenAI 兼容 API 生成课程。**不做平台化、多租户运营、云部署。**

## 禁区（不要开发这些）

以下为已明确的暂停项，即使代码里有残留骨架也不要继续扩建：

- 课程广场、管理后台、管理员角色
- 云服务器、公网域名、HTTPS、反向代理
- PostgreSQL、Redis、Celery、对象存储、容器编排
- 企业组织、多租户运营、支付、额度售卖

已有认证/owner 隔离保留不删，但只作为本地数据保护，不向外扩张。

## 文档体系与维护权责

`docs/` 是开发者与 AI 共同维护的文档库（机制正本：`docs/project/README.md`），权责如下：

| 内容 | 维护方 | AI 的角色 |
|---|---|---|
| modules/、core/ 各域 `design.md` | 开发者主导 | 可提建议；经审核通过才可修改，不得擅自改写 |
| modules/、core/ 各域 `designs-specs.md` | **AI 生成并维护** | 基于 design.md 严格生成，是开发的直接依据；开发者仅简单审核 |
| `docs/project/project.md` | 开发者主导 | 可建议；协助完善需审核通过 |
| `docs/project/README.md` | **AI** | 机制正本：spec/plan 存放与归档机制、权责表、语言规范 |
| `docs/log/<YYMMDD>.md` | AI | 每天一个开发日志；小节下首行 `> 创建于 YYYY-MM-DD HH:MM`（date 实取） |
| `docs/project/DEV_BOARD.md` | AI 职责 | 实时状态真源，每会话结束更新 |
| `docs/project/全局/archive/`（错误档案） | AI 职责 | 遇错自动建档（`YYYY-MM-DD-<slug>.md`），只进不改；索引见 archive.md |
| `docs/project/新功能开发区.md` / `优化建议区.md` | 开发者记录 | AI 据此立项/实施；完成后按轮归档 |
| `docs/project/问题疑惑区.md` | 开发者记录 | **AI 不主动查阅**，指名时才读并答疑 |
| `docs/project/idea/` 与 `临时草稿（待写入）.md` | 开发者 | AI 不读取不修改（例外：AI 产出的 spec/plan 可存 idea/，只动自己产出的文件） |
| `docs/project/全局/` | 权责同模块文档 | 系统级/跨模块方案（spec/plan）与 archive/ |
| `docs/study/` | 见 `docs/study/study.md` | 学习文档库 |
| Git 操作 | 开发者 | **禁止 AI 自主执行任何 git 操作** |

工作流程：开发者写 design.md → AI 据此生成 designs-specs.md → AI 按 specs 开发；spec/plan 命名与归档四步见 `docs/project/README.md`。

## 验证三件套（任何代码改动后必跑）

```powershell
# 1. 后端全量测试（改了 backend/ 必跑）
cd backend
.\.venv\Scripts\python.exe -m pytest tests -q

# 2. 前端类型检查（改了 web/ 必跑）
cd web
npx tsc -b

# 3. 前端构建（改了 web/ 必跑，tsc 通过 ≠ 构建通过，历史上出现过原生退出）
npm run build
```

- 改动必须三项全绿才算完成；失败时修到绿或明确回退，**不许带着红灯提交**。
- 全量测试约 105 秒（187 项，2026-09-01 实测），不要为省时间只跑单文件。
- 测试失败时优先怀疑自己的改动，而不是改测试迁就代码；只有确认契约本身变了才改测试（如本文件末尾的案例）。

## 大文件修改守则

以下文件仍过大（5000+ 行），AI 单次会话无法完整理解，修改时必须：

| 文件 | 规模 | 守则 |
|---|---|---|
| `web/src/components/ModuleView.tsx` | ~5900 行 / 103 useState | 新功能放新组件文件；禁止在此文件新增顶层组件；改动前先 grep 确认所有调用方 |

- `backend/app/study_service.py` 已拆分至 ~1700 行（阶段 2-1~2-8 完成，model_client / model_profiles / agent_runtime / workspace 等已抽出），不再属于大文件，但继续遵守"先抽到新模块再改"的方向，旧文件保留 re-export 门面，外部 import 零改动。
- 改 ModuleView.tsx 前后都要跑验证三件套。

## AI 工作流/模型调用约束

- 模型调用链路已抽到独立模块 `model_client.py`（`_provider_request` / `_model_providers` / 超时常量都在此），`study_service.py` 通过 re-export 门面保持外部符号不变。当前策略：**流式 SSE + 首 token 超时 30s**（`MODEL_FIRST_TOKEN_TIMEOUT_SECONDS`，无首字节判死）+ 整流读超时上限 + 重试预算 + 主备 failover + 熔断。
- 流式 + 首 token 超时改造（阶段1-2）已完成；剩余待办是 P1 真实上游端到端验收（见看板）。历史教训仍然有效：不要单纯调小 `MODEL_REQUEST_TIMEOUT_SECONDS`——它现在只约束"首字节之后的总读流时长"，首 token 超时由独立参数把关。
- `AgentJobWorker` 在 `agent_runtime.py`，按单进程单线程设计，**不要开多个 uvicorn worker**。
- 生成失败必须显式报错，禁止用低质量内容假装成功（历史决策，不许回退）。

## 重大更新先研究、规划、确认

- 当用户提出较大的项目更新或修改想法时，AI Agent **不得直接开始实现**。
- 必须先详细研究当前项目代码、既有架构、调用链、数据契约、测试与相关文档，再结合用户需求和项目实际情况制定可执行方案。
- 必须先将完整方案编写为独立 Markdown 文档并保存到 `docs/`（系统级方案放 `docs/project/全局/`，单域功能走该域 spec/plan，机制见 `docs/project/README.md`），内容至少包括：现状分析、需求理解、影响范围、实施步骤、风险与兼容性、测试及验收方式。
- 方案文档交由用户审阅；只有在用户明确确认方案无误后，才能按照方案执行代码修改。若用户要求调整方案，应先更新文档并再次等待确认。

## Git 提交纪律

- **禁止 AI Agent 代替用户执行任何 Git 提交操作；所有 Git 提交均由用户本人完成。**
- **一类改动一个 commit**，禁止大杂烩。消息格式：`类型(范围): 概要`，类型用 feat/fix/refactor/test/docs/chore。
- 提交前 `git status --short` 确认没有把无关文件带进去。
- 工作区可能存在用户未提交的改动，**先确认归属再动手，不得覆盖**。
- `backend/.env`、`backend/data/` 永远不提交。

## 数据安全

- `backend/data/exam_booster.db` 是用户的真实学习数据，任何测试/脚本**不得清库**；需要测试数据时新建独立课程，用完归档。
- 停后端后才能整体备份 `backend/data/`；运行时有 `-wal`/`-shm` 文件。
- `backend/.env` 丢失 = 模型密钥 + JWT 全失效。

## 会话流程（每个 AI 会话的标准动作）

1. **开始时**：读 `docs/project/DEV_BOARD.md` 了解当前状态 → `git status --short` 看工作区。
2. **动手前**：确认任务在看板"📋 计划中"或用户明确指示；有冲突先问。
3. **问题疑惑区**：`docs/project/问题疑惑区.md` AI 不主动查阅；用户指名时才读并答疑，解答后按轮归档（机制见 `docs/project/README.md`）。
4. **过程中**：改动超出单个职责时拆分任务记录到看板。
5. **结束时**：
   - 跑验证三件套（有代码改动时）
   - **更新 `docs/project/DEV_BOARD.md`**：任务状态流转、Bug 区新增/解决、提交记录、验证记录
   - **写当日开发日志 `docs/log/<YYMMDD>.md`**（append-only，同日多会话追加；有实质工作时必写）
   - 看板与日志随代码一起提交

## 历史教训（避免重蹈覆辙）

- `7a773b4`、`8c27763` 两个大杂烩提交导致回归无法 bisect——所以有上面的提交纪律。
- 课程质量降级处理被移除（`c66dea6`），改为显式失败——所以不许加回"失败时返回凑合内容"的逻辑。
- 测试 `test_background_generation_*` 曾因 handler 契约变更（返回 workspace）而替身未跟上——契约变了要同步更新测试替身并补断言，而不是删测试。
- demo 模式绕过真实后端流程，不能用它做验收。
