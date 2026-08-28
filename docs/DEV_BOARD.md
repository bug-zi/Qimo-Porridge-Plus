# 期末粥++ 开发看板（实时同步协作文档）

> **这是项目的实时状态真源。** 旧版固定文档 HANDOVER.md 已停止维护（历史存档见文末归档区）。
> 每个开发会话（人或 AI）结束时**必须**更新本看板对应区域，随代码一起提交。

## 看板维护规则

- 状态流转：`📋 计划中` → `🚧 开发中` → `🧪 待测试` → `✅ 已完成`（或 → `🐛 Bug`）
- 任务条目格式：`- [ ] 简述 ｜ 备注（负责人/日期/依赖）`，完成打勾并移入对应区
- Bug 条目格式：`- [ ] [严重度] 简述 ｜ 现象/复现/根因（已知时）｜ 状态`
- 已完成与提交记录**只保留最近 30 条**，更旧的剪贴到文末归档区
- 新发现的问题、风险、临时决定 → 随时记入对应区域，不要"回头再补"

---

## 📸 当前快照（每次会话结束刷新）

| 项 | 状态 |
|---|---|
| 日期 | 2026-08-28 |
| 分支 | dev |
| 后端测试 | ✅ 153 passed / 96s（2026-08-28，阶段2-4 拆分后，门面契约测试 ×10） |
| 前端 tsc / build | ✅ `npx tsc -b`；⚠️ build 转换 2265 modules 后 exit 1（既有 Windows 原生构建问题） |
| 工作区 | 阶段2-1~2-4 已提交；用户未提交改动仍在工作区（答案一致性 + 小节多轮对话代码，其看板条目已随 docs 提交入库） |
| 当前主线 | 阶段0止血 ✅ → 阶段1 AI工作流稳定性 ✅ → 队列双重执行修复 ✅ → 阶段2 拆分 study_service（2-1~2-4 ✅，后续拆分待排期） |
| 架构债提醒 | uvicorn --reload 在中文路径下失效（改代码不重启），修复需手动重启后端 |

---

## 🚧 开发中

- [ ] 前端"生成用量基线"：`App.tsx` 已记录基线、`ModuleView.tsx` 已加 `generationUsageBaseline` 属性定义，但**属性未从 App 传给 ModuleView、未参与增量用量展示**，链路没串完（6c622dd 已提交一半改动，注意 types.ts 已有字段）
- [ ] P1 验收：阶段1 流式改造需用真实上游验证（真实课程生成一轮，观察首 token 超时与 failover 是否按预期工作）

## 📋 计划中

**P1（真实课程端到端验收，人工执行为主）**

- [ ] 文字型 PDF/PPT 完整走一遍：导入 → 策略 → 增量第一课 → 继续生成 → 学习 → 练习 → 错题/笔记
- [ ] 含公式理工科资料验证公式、题目、讲解
- [ ] 扫描 PDF/图片验证 RapidOCR 与视觉兜底
- [ ] 抽查标准版、对话版、故事版三种风格（不只验证故事版）
- [ ] 手工验证模型超时、两次重试、主备切换、错误提示（阶段1完成后）
- [ ] 确认后台队列在上游挂起时能及时释放并继续处理后续任务

**P2（个人本地版可维护性）**

- [ ] 停服后的备份/恢复脚本或明确步骤文档
- [ ] 区分测试数据与个人正式数据的机制，避免误清库
- [ ] 改善失败/部分成功/继续生成/取消/恢复的前端状态展示
- [ ] 补本地首次安装、依赖检查、启动说明

**阶段2（后端结构，2-1~2-4 已完成）**

- [x] 2-1 抽取 model_profiles.py（模型配置/用户画像）+ paths.py（路径常量收敛）+ 门面契约测试（167357e）
- [x] 2-2 抽取 material_parser.py（资料解析域：MarkItDown/Docling/RapidOCR/视觉级联、转 PDF、XLSX、缓存）（c090366）
- [x] 2-3 抽取 materials.py（资料管理域：扫描/上传/删除、主辅角色、资料记忆、知识库同步）（7024558）
- [x] 2-4 抽取 workspace.py（工作空间域：load/save/锁、路径助手、内容质量迁移、空工作区、mind_map）（da02ca3）
- [ ] 继续拆分 `study_service.py`（现 ~3460 行）：练习/错题域、复习计划域、agent 对话域等，旧文件 re-export 门面模式不变

**阶段3（前端结构）**

- [ ] 给关键纯逻辑补 vitest 测试（当前前端 0 测试）
- [ ] 拆分 `ModuleView.tsx`（先拆用量展示、反馈面板等独立块）

## 🧪 待测试

- [ ] 队列 fencing 修复需重启后端后真实生成一轮验证（--reload 失效，当前 8000 端口服务仍是旧代码）：观察 job attempts 是否不再出现 2、同课程 job 不再并行 running
- [ ] `npm run build`：2026-08-28 复现 Vite/Rolldown 在 2265 modules 后 Windows 原生退出 `0xC0000409`；tsc 独立通过，待定位原生构建崩溃

## 🐛 Bug 跟踪

- [x] 2026-08-28 关闭：[中] 侧边 AI 伴学“整体修改当前小节”生成一次预览后只能重填或应用，无法围绕候选版本继续多轮对话 ｜ 新增同一 feedback session 的 refine API、历史意见/上一版候选传递、对话式前端交互与回归测试
- [x] 2026-08-28 关闭：[高] 自测答案配置与解析冲突仍按错误 answerIndex 判分；自测4应为20ms却判50ms ｜ 新增保守的解析结论一致性校验，覆盖摸底/练习/错题重做/模拟卷；已修复现有作答、错题记录、掌握度和学习事件
- [ ] [中] Vite/Rolldown 生产构建在 Windows 转换 2265 modules 后原生退出 `0xC0000409`，无 JS 堆栈；tsc 正常 ｜ 已复现，待独立定位
- [ ] [中] uvicorn `--reload` 在中文路径下不生效（改代码不重启进程），开发期修改后端代码可能跑的是旧代码 ｜ 2026-08-28 实测发现（03:07 改 agent_runtime.py 服务未重启）｜ 待定位：考虑 watchfiles 路径兼容或改用显式重启脚本
- [ ] [低] `routers/__init__.py` 有 UTF-8 BOM，脚本读取需 `utf-8-sig` ｜ 待顺手清理
- [x] 2026-08-28 关闭（132e3e1 修复）：[高] agent 队列双重执行——心跳线程偶发猝死（SQLite 锁竞争无保护）→ lease 过期 → job 被二次 claim → 同一课程双份生成并发。修复三件套：心跳 try/except 保护、lease_token 代际 fencing（旧代完成/失败/续租写全被拒）、同课程 running 互斥（NOT EXISTS 子查询）+ has_agent_job_ownership 协作取消点接入 content_workflow
- [x] 2026-08-28 关闭（已由阶段1 解决）：[高] AI 生成队列偶发卡死（非流式长超时+上游静默挂起）——流式+30s 首 token 超时+job 级 2h 硬超时三重防线
- [x] 2026-08-28 关闭（已由阶段1 解决）：[中] 请求超时/挂起误判（300s 误杀思考型慢请求）——首 token 超时只判死真挂起，读流阶段不再误杀

## ✅ 已完成（最近）

- [x] 2026-08-28 阶段2-4 完成：workspace.py 抽取（load/save/锁、路径助手、内容质量迁移、空工作区、mind_map），study_service 4135→3465 行；load/save 的历史打桩面（monkeypatch study_service 命名空间）经函数级延迟 import 保持不变；门面契约测试 +2（da02ca3）
- [x] 2026-08-28 阶段2-1~2-3 完成：study_service.py 5482→4132 行，拆出 model_profiles / material_parser / materials + paths.py 路径常量收敛；re-export 门面 + 门面契约测试 ×8 锁定；三个独立提交（167357e / c090366 / 7024558）
- [x] 2026-08-28 完善“整体修改当前小节”多轮对话：可连续补充意见、保留历史要求并迭代候选预览，最终确认应用最新版本；切换小节自动重置会话
- [x] 2026-08-28 修复自测答案配置冲突：解析明确“应选20毫秒”时自动纠正 answerIndex 后再判分；现有自测4数据已回正；新增 4 个回归测试
- [x] 2026-08-28 修复 agent 队列双重执行（132e3e1）：现场实锤心跳猝死→lease 过期→二次 claim→同课程双份生成；fencing token + 心跳保护 + 同课程互斥三件套，138 passed
- [x] 2026-08-28 阶段1 真实上游验证通过：课程 course-1787678599479 增量生成第 7 课 task-d7-03-file-operations（13060 字 guide），job completed，流式+首 token 超时在真实模型下工作正常
- [x] 2026-08-28 阶段1 AI工作流稳定性改造完成（4 个提交）：model_client.py 抽取（b3c19e6）→ 流式+30s 首 token 超时（5fe4a13）→ job 级 2h 硬超时（c6c79cb）→ fake-provider 单测 ×7（317f71b）；全量 134 passed
- [x] 2026-08-28 真实课程 `course-1787678599479` 经持久队列增量生成严格一课：workspace `studyGuide` 5→6；任务 `task-d1-04-runtime-modes-interrupts`、8 道练习可用；job `job-ecceb24a35c244c68ea4268e1e1bf5eb` completed
- [x] 2026-08-28 阶段0止血完成：2 个失败测试修复（全量 127 passed）、CLAUDE.md/AGENTS.md 约束文件、本看板建立；工作区改动经用户以 6c622dd 提交
- [x] 2026-08-28 修复 2 个失败测试（test_mainline_generation_repair.py）：handler 契约要求返回 workspace，更新测试替身并补完成度断言，全量 127 passed
- [x] 8c27763 备用模型 + 故障切换、故事版优化、Token 用量展示

## 📊 验证记录（倒序，保留最近 15 条）

| 日期 | 内容 | 结果 |
|---|---|---|
| 2026-08-28 | 阶段2-4 后全量 pytest（workspace 抽取后，含新增门面 ×2） | ✅ 153 passed / 96s |
| 2026-08-28 | 阶段2-3 后全量 pytest（materials 抽取后） | ✅ 151 passed / 96s |
| 2026-08-28 | 阶段2-2 后全量 pytest（material_parser 抽取后） | ✅ 149 passed / 96s |
| 2026-08-28 | 阶段2-1 后全量 pytest（model_profiles + paths 抽取后） | ✅ 147 passed / 96s |
| 2026-08-28 | 小节整体修改多轮对话：后端全量 pytest / 前端 tsc / build | ✅ 143 passed / ✅ tsc / ⚠️ Vite 2265 modules 后既有原生 exit 1 |
| 2026-08-28 | 后端全量 pytest（答案一致性修复，新增 ×4） | ✅ 142 passed / 100.19s |
| 2026-08-28 | 前端 `npx tsc -b` / `npm run build`（本轮无前端改动） | ⚠️ 并行中的 `AiCompanion.tsx` 未使用变量 ×2；build 转换 2265 modules 后 exit 1 |
| 2026-08-28 | 后端全量 pytest（队列 fencing 修复后，含新增 ×4） | ✅ 138 passed / 96s |
| 2026-08-28 | 真实上游增量生成监控（job-0d929645，approve attempt 1→2 双执行现场） | ✅ completed；第 7 课产出 13060 字；bug 现场已捕获并修复 |
| 2026-08-28 | 后端全量 pytest（阶段1完成后，含新增 test_model_client ×7） | ✅ 134 passed / 95.63s |
| 2026-08-28 | 阶段1 各步完成后全量 pytest（×3） | ✅ 127 passed（每步） |
| 2026-08-28 | 真实课程下一课生成验收 | ✅ studyGuide 5→6；目标任务 + 8 道练习；持久 job completed |
| 2026-08-28 | 前端 `pnpm exec tsc -b` / `pnpm run build` | ✅ tsc；❌ Vite 2265 modules 后原生退出 0xC0000409 |
| 2026-08-28 | 后端全量 pytest（生成验收后） | ✅ 127 passed / 15.60s |
| 2026-08-28 | 后端全量 pytest（修复测试后） | ✅ 127 passed / 17s |
| 2026-08-28 | 后端全量 pytest（修复前） | ❌ 2 failed（test_mainline_generation_repair） |

## 📝 提交记录（倒序，保留最近 15 条）

| 日期 | commit | 说明 |
|---|---|---|
| 2026-08-28 | da02ca3 | refactor(workspace): 抽取工作空间域到 workspace.py（阶段2-4） |
| 2026-08-28 | 7024558 | refactor(materials): 抽取资料管理域到 materials.py（阶段2-3） |
| 2026-08-28 | c090366 | refactor(materials): 抽取资料解析域到 material_parser.py（阶段2-2） |
| 2026-08-28 | 167357e | refactor(model): 抽取模型配置/用户画像到 model_profiles.py + paths.py（阶段2-1） |
| 2026-08-28 | 132e3e1 | fix(queue): lease 代际 fencing + 心跳保护 + 同课程互斥，杜绝双重生成 |
| 2026-08-28 | d3fdc3c | docs: 看板更新——阶段1 完成、134 passed、卡死/误杀两条 Bug 关闭 |
| 2026-08-28 | 317f71b | test: fake-provider 单测锁定流式/超时/重试/failover（阶段1-4，7 个新测试） |
| 2026-08-28 | c6c79cb | feat(queue): AgentJobWorker job 级 2h 硬超时（阶段1-3） |
| 2026-08-28 | 5fe4a13 | feat(model): 流式 + 30s 首 token 超时（阶段1-2，解决思考/挂起无法区分的死结） |
| 2026-08-28 | b3c19e6 | refactor(model): 抽取模型调用层到 model_client.py（阶段1-1，study_service 5905→5170 行） |
| 2026-08-28 | 86fc678 | docs: 建立 AI 协作约束与实时开发看板 |
| 2026-08-28 | 8c27763 | 备用模型故障切换、故事版优化、Token 用量展示（大杂烩提交，教训见 CLAUDE.md） |
| 2026-08-27 | 7a773b4 | 复习总计划 prompt、课程故事风格、Agent 模块化等大整合（大杂烩提交） |

---

## 📦 归档

<details>
<summary>旧 HANDOVER.md 关键决策存档（点击展开，不再更新）</summary>

- 项目从校园多用户版转向个人本地版（2026-08 决策）：保留认证/隔离，暂停课程广场、管理后台、云部署、PostgreSQL/Redis/Celery、多租户运营。
- 课程生成失败显式报错，不做低质量降级（c66dea6）。
- `AgentJobWorker` 单进程单线程设计，不开多 uvicorn worker。
- demo 模式绕过真实后端，不可用于验收。
- 外部 MCP 为可选增强，默认关闭不影响核心流程。
- 本地启动：后端 `backend/.venv` + uvicorn 8000；前端 Vite 5173。

</details>

<details>
<summary>更早的已完成条目（点击展开）</summary>

（暂无，完成条目满 30 条后剪贴至此）

</details>
