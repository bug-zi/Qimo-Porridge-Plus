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
| 日期 | 2026-09-24 |
| 分支 | feature |
| 后端测试 | ✅ 187 passed / 105s（2026-09-01 本会话实测，无代码改动仅核验） |
| 前端 tsc / test / build | ✅ `npx tsc -b`；✅ Vitest 5 passed；⚠️ build 转换 2249 modules 后原生 exit 1（既有 Windows Vite/Rolldown 问题） |
| 反馈后端路由验收 | ✅ 8000 OpenAPI 已确认 open/retry/abandon/rules merge/update/delete/global refine/apply 全部注册 |
| 项目阶段切换 | 🧊 **进入学习/冻结期**（2026-08-29 用户决策）：暂不增不改功能；两件事——①通读理解现有代码 ②建立新的 AI 协作文档框架 |
| AI 协作框架 | ✅ `docs/` 机制正本 v2.1（2026-09-24）：v2.0 结构清理——core/ 9 引擎域并入 modules/（29 域）、bugs/ 错误档案与 draft/ 风格实验稿并入 `全局/archive/`，docs-creator 标准结构达成；机制正本 `project/README.md`（权责表 / spec-plan / 归档四步 / 三区按轮归档 / 语言规范），log 迁 `docs/log/` 改 YYMMDD，旧库整体冻结 `doc/` 只读。v2.0 当日重构与 v1.x 宪法历史见 `全局/archive/文档库混合升级方案.md`、`doc/docs.md`。详见 `log/260924.md` 会话 1/5/6 |
| 看板新位置 | 本文件位于 `docs/project/DEV_BOARD.md`；Bug 细节持久档案在 `docs/project/全局/archive/`（索引 archive.md），看板 🐛 区只留活跃/待验证条目 |
| 后续计划 | ✅ 已完成当前项目考核；新计划见 [1m`docs/project/全局/archive/后续项目考核与任务实施计划.md`[0m；旧反馈方案已归档删除 |
| 工作区 | 阶段2-6~2-8 已提交；用户未提交改动仍在工作区（答案一致性 + 小节多轮对话代码，其看板条目已随 docs 提交入库） |
| 当前主线 | 阶段0止血 ✅ → 阶段1 AI工作流稳定性 ✅ → 队列双重执行修复 ✅ → 阶段2 拆分 study_service（2-1~2-8 ✅，study_service 5482→1687 行；剩余域待排期） |
| CLAUDE.md 校准 | ✅ 2026-09-01 全文审计并更新 4 处过时信息：study_service 5400→~1700 行已非大文件、模型链路已抽至 model_client.py、流式+首token超时已完成（"已知架构债"改写为已完成+P1待验收）、测试时长 17s→105s；ModuleView.tsx 仍是大文件（5910 行/103 useState） |
| 学习进度 | 2026-09-01：已将学习方式升级为“项目老开发者带新人”带教模式；一轮一个问题，先为什么后怎么做，含轻量检查点并交还选择权。方案见 `docs/project/全局/新人带教式项目学习模式优化方案.md`，待用户审阅；A→B→C→D→E→F 主线保留 |
| 域双文档 | 🌱 2026-09-24 全 29 域两件套齐备：26 域 design.md/designs-specs.md 从代码逆向补全（**AI 起草稿待开发者审定**），刷题/设置/模型调用 3 样板域保留；域目录已改中文名（英文标识保留对照）；调研中发现 agent_chat 缺 import 缺陷已建档 |
| 架构债提醒 | uvicorn --reload 在中文路径下失效（改代码不重启），修复需手动重启后端 |
| 本地启动 | ✅ 根目录 `启动项目.bat`（纯 ASCII 双击入口）+ `start.ps1`（UTF-8 BOM 实际逻辑，可读可编辑）：一键拉起 uvicorn 8000 + Vite 5173，端口占用自动跳过，实测通过（详见 log/260924.md 会话 3） |

---

## 🚧 开发中

- [x] 2026-08-28 设置页 API Key 显示优化：已保存密钥隐藏状态改为 `···`，移除“已保存到本机，留空继续使用”提示（主模型/备用模型）
- [ ] 前端"生成用量基线"：`App.tsx` 已记录基线、`ModuleView.tsx` 已加 `generationUsageBaseline` 属性定义，但**属性未从 App 传给 ModuleView、未参与增量用量展示**，链路没串完（6c622dd 已提交一半改动，注意 types.ts 已有字段）
- [x] 学习文档编排规则优化 ｜ 已确认并实施：docs.md §8、study.md、guide.md、patterns.md 已同步；新增学习路线记录与后台 job/双存储两篇 pattern；未改功能代码
- [x] 学习地图补强 ｜ 已读 docs 总纲、项目学习指南、后台任务与持久队列、读改写与双存储；核对 agent_runtime / workspace 实现、真实 workspace.json 和 DB 表结构；未改功能代码
- [ ] P1 验收：阶段1 流式改造需用真实上游验证（真实课程生成一轮，观察首 token 超时与 failover 是否按预期工作）
- [ ] 修复多节生成取消后的已完成内容交付：后端已有逐节预览落盘，但需补强取消/终态结果与前端恢复展示，避免用户误以为已完成课程被吞掉（本轮已定位，待方案确认）

## 📋 计划中

- [x] 课程排版保留审核、移除评分 ｜ 已完成：审核仍保留，移除单课/汇总 score 计算、返回与界面展示；复习主线审核状态卡片和审核按钮均已移除，后台审核接口保留；tsc 通过；build 仍复现既有 Windows 原生 exit 1
- [ ] 课程初稿定向微调修复 ｜ 用户已批准；已接入讲义/自测 patch Prompt、定向合并器与失败 artifact；新增 `backend/tests/test_content_patches.py`；后端 pytest 183 passed；仍需补强 patch 字段契约与真实上游验收

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
- [ ] 课程生成效率优化（方案待用户确认）｜ 详见 `docs/project/全局/课程生成效率优化方案.md`
  - 基线：用户最近单节约 9 分钟、7.5 分钟；审计结论为主要耗时来自讲义+自测两次串行大模型调用，返工/重试会放大
  - 第一轮建议：阶段耗时基线 + 自测缺失考点增量补题；不降低硬校验、不启用低质兜底、不直接缩短总超时/并行 worker
  - 后续再基于 5~10 次真实数据评估上下文精简、轻量自测模型或合并调用实验
- [x] 2026-08-28 修复课程生成完成后无法继续生成下一节：完成态 Job 摘要继续保留时，计划页仍根据待生成课程显示“生成下一课/下 3 课/剩余全部”按钮；仅 queued/running 隐藏重复入队入口

**阶段2（后端结构，2-1~2-8 已完成）**

- [x] 2-1 抽取 model_profiles.py（模型配置/用户画像）+ paths.py（路径常量收敛）+ 门面契约测试（167357e）
- [x] 2-2 抽取 material_parser.py（资料解析域：MarkItDown/Docling/RapidOCR/视觉级联、转 PDF、XLSX、缓存）（c090366）
- [x] 2-3 抽取 materials.py（资料管理域：扫描/上传/删除、主辅角色、资料记忆、知识库同步）（7024558）
- [x] 2-4 抽取 workspace.py（工作空间域：load/save/锁、路径助手、内容质量迁移、空工作区、mind_map）（da02ca3）
- [x] 2-5 抽取 practice.py（练习/错题/模拟卷域：刷题/错题重做判分、AI 举一反三、掌握度联动、模拟卷修复与计分、计算题批改）（7a2d38e）
- [x] 2-6 抽取 review_plan.py（复习计划域：总计划 AI 维护、每日进度、时长记录、顺延/减负/重排提案、工作台手动更新）（34896c3）
- [x] 2-7 抽取 agent_chat.py（Agent 对话域：agent_chat/agent_chat_stream、SSE、消息组装、滚动摘要、knowledge_service 记忆联动）（2719755）
- [x] 2-8 抽取 strategy.py（策略文档域：文档读写/版本化、初稿生成、审阅保存、维护标记、草稿对话修订 revise_strategy_draft）（8b9e3ec）
- [ ] study_service.py 剩余 ~1660 行（原 5482）：复习日程纯函数（_review_session_days/_remap）、诊断与 setup（save_course_setup/submit_course_diagnostic）、主线生成（approve_strategy_documents/_sanitize_custom_workspace 等）、模块归并与思维导图（resolve_course_modules/generate_mind_map）、9 个 re-export 门面块——后续按需拆分，门面模式不变

**阶段3（前端结构）**

- [ ] 给关键纯逻辑补 vitest 测试（当前前端 0 测试）
- [ ] 拆分 `ModuleView.tsx`（先拆用量展示、反馈面板等独立块）
- [x] 修复深色模式生成课程模块背景：状态卡片改用主题 surface 变量，指标与图标背景同步暗色主题

## 🧪 待测试

- [ ] 队列 fencing 修复需重启后端后真实生成一轮验证（--reload 失效，当前 8000 端口服务仍是旧代码）：观察 job attempts 是否不再出现 2、同课程 job 不再并行 running
- [ ] `npm run build`：2026-08-28 复现 Vite/Rolldown 在 2265 modules 后 Windows 原生退出 `0xC0000409`；tsc 独立通过，待定位原生构建崩溃

## 🐛 Bug 跟踪

- [ ] 2026-09-24 新增：[高] agent_chat.py 缺 `run_tutor_agent(_stream)` import，NameError 被宽 except 吞掉，Agent 工具循环在流式/非流式两路径均不可达（AI伴学恒走降级 RAG 问答） ｜ 2026-09-24 文档逆向调研静态发现（L484/L686 调用但模块 import 区无此名，grep 复核确认无 setattr 注入）｜ 根因：2719755 抽取 agent_chat.py 时漏带 tutor import ｜ 已建档 `全局/archive/2026-09-24-agent-chat-tutor-unreachable.md` ｜ 待开发者决策修复（冻结期只记不修）
- [ ] 2026-08-29 新增：[高] 无自测检查点时直接拿空初稿走 patch，补题不带 examPointIds 导致考点覆盖校验循环失败 ｜ 现象：task-d3-03"调度概念"课讲义成功但自测环节失败，前端永远"内容生成中"，面板只显示 2 次模型调用 ｜ 根因：定向微调重构把 `generate_questions()` 首次调用删丢，patch 的 add_question 不带 examPointIds 而覆盖校验只认该字段 ｜ 修复：补回初稿生成调用（方案阶段三步骤1）、恢复初稿一次通过时的 checkpoint 落盘、patch artifact 输入/剩余问题分离、patch Prompt 明确要求 add_question 携带 examPointIds；+2 回归测试（test_lesson_question_draft.py）｜ 已修，待用户重启后端后真实重生成验证

- [x] 2026-08-29 关闭：[高] 生成下一课 10 分钟后显示"生成完成"，但目标课仍"内容生成中" ｜ 现象：job completed 但 task-d3-03 无 studyGuide；根因三层：①模型按 JSON Pointer 习惯返回 patch path `/sections/0/questions`，`content_patches._segments` 只认点号格式直接拒绝；②PATCH prompt 未约定 path 格式；③`generationHeadline` 只看 `job.status==='completed'`，掩盖 `result.partial=true` 的部分失败。修复：路径归一化兼容斜杠+纯数字段转下标；两个 PATCH prompt 明确格式与示例；headline 读取 `job.result.partial` 如实提示；+2 回归测试 ｜ 待用户重启后端后真实重生成验证
- [x] 2026-08-28 关闭：[高] 课程划词删除反馈只显示提交成功，无删除预览/确认 ｜ 删除意图补“删去”；rewriteError 改为部分成功并支持原 feedbackId 重试；删除显示结构化预览与确认
- [x] 2026-08-28 关闭：[高] 未确认/放弃的小节反馈提前污染生成规则且历史无减法 ｜ proposed→确认激活；legacy 仅 accepted 恢复；带锁存储、8轮上限、结束压缩、放弃/恢复及课程偏好启停/删除已实现
- [x] 2026-08-28 关闭：[中] 侧边 AI 伴学“整体修改当前小节”生成一次预览后只能重填或应用，无法围绕候选版本继续多轮对话 ｜ 新增同一 feedback session 的 refine API、历史意见/上一版候选传递、对话式前端交互与回归测试
- [x] 2026-08-28 关闭：[高] 自测答案配置与解析冲突仍按错误 answerIndex 判分；自测4应为20ms却判50ms ｜ 新增保守的解析结论一致性校验，覆盖摸底/练习/错题重做/模拟卷；已修复现有作答、错题记录、掌握度和学习事件
- [ ] [中] Vite/Rolldown 生产构建在 Windows 转换 2265 modules 后原生退出 `0xC0000409`，无 JS 堆栈；tsc 正常 ｜ 已复现，待独立定位
- [ ] [中] uvicorn `--reload` 在中文路径下不生效（改代码不重启进程），开发期修改后端代码可能跑的是旧代码 ｜ 2026-08-28 实测发现（03:07 改 agent_runtime.py 服务未重启）｜ 待定位：考虑 watchfiles 路径兼容或改用显式重启脚本
- [ ] [低] `routers/__init__.py` 有 UTF-8 BOM，脚本读取需 `utf-8-sig` ｜ 待顺手清理
- [x] 2026-08-28 关闭（132e3e1 修复）：[高] agent 队列双重执行——心跳线程偶发猝死（SQLite 锁竞争无保护）→ lease 过期 → job 被二次 claim → 同一课程双份生成并发。修复三件套：心跳 try/except 保护、lease_token 代际 fencing（旧代完成/失败/续租写全被拒）、同课程 running 互斥（NOT EXISTS 子查询）+ has_agent_job_ownership 协作取消点接入 content_workflow
- [x] 2026-08-28 关闭（已由阶段1 解决）：[高] AI 生成队列偶发卡死（非流式长超时+上游静默挂起）——流式+30s 首 token 超时+job 级 2h 硬超时三重防线
- [x] 2026-08-28 关闭（已由阶段1 解决）：[中] 请求超时/挂起误判（300s 误杀思考型慢请求）——首 token 超时只判死真挂起，读流阶段不再误杀

## ✅ 已完成（最近）

- [x] 2026-09-24 域目录中文化 + 全域双文档补全（机制正本 v2.2）：29 个域目录改中文名（英文标识保留于 modules.md / project.md §8 对照）；26 域 design.md/designs-specs.md 经 10 个并行只读调研从代码逆向补全（标注 AI 起草稿待开发者审定），刷题/设置/模型调用 3 样板域原样保留；核验修正 mind_map 为独立文件非 workspace 内嵌；**发现并建档 agent_chat 缺 import 缺陷（Agent 工具循环不可达，冻结期只记不修）**；纯文档变更，验证三件套不适用
- [x] 2026-09-24 网页标签栏图标切回 `app-icon.png`：文件已就位，`web/index.html` 的 `<link rel="icon">` 由 favicon.svg 改回 `/app-icon.png`（type image/png），撤回会话 4 的临时改指；grep 确认无其他引用残留；tsc 通过，build 复现既有 Rolldown 原生退出（无关）；dev server 下用户浏览器实测确认显示正常
- [x] 2026-09-24 文档库结构清理（机制正本 v2.1）：core/ 9 引擎域并入 modules/（共 29 域，core.md 说明并入 modules.md）；bugs/ 11 份错误档案并入 全局/archive/（索引并入 archive.md，建档义务同步改指）；draft/course-style-lab/ 并入 全局/archive/。core.md/bugs.md 原件入 archive/ 保存；全库引用修正（project.md/README.md/全局.md/idea.md/practice specs/CLAUDE.md/看板），grep 核验活动文档旧路径零残留
- [x] 2026-09-24 文档库按 docs-creator 体系整体重构（机制正本 v2.0）：docs/ 整体改名 doc/ 冻结只读；新 docs/ 按 skill 结构重建——project/README.md 机制正本（权责表/spec-plan/归档四步/语言规范）、log 迁 docs/log/ 改 YYMMDD、ideas 灵感池并入新功能开发区+优化建议区、questions.md→问题疑惑区.md、proposals→全局/；modules/core/study/bugs/draft/DEV_BOARD 原样迁入；学习文档编排方案补归档；CLAUDE/AGENTS 接线 + conftest.py 注释路径修正（纯注释，随改跑全量 pytest）
- [x] 2026-09-24 修复网页标签栏图标不显示：`web/index.html` 引用的 `/app-icon.png`（png 类型）在 public/ 中不存在，dev 下被 SPA fallback 以 HTML 应答导致图标渲染失败；改指已存在的 `public/favicon.svg`（type 改 image/svg+xml）。实测 dev server 下 `/favicon.svg` 返回 200 且浏览器成功拉取；tsc 通过；build 复现既有原生 exit（无关）
- [x] 2026-09-24 文档库混合升级（宪法 v1.3）：并入 docs-creator skill 机制——新增 questions.md 问题疑惑区（AI 不主动查阅/按轮归档）、§2.4 域内 spec/plan、§4.6 域内归档（固定四步/永不删除）、log 创建时间行；权限表 +3 行；方案文档按四步归档 proposals/archive/。仅文档变更，无代码改动，三件套不适用
- [x] 2026-09-24 新增本地一键启动脚本：根目录 `启动项目.bat`（纯 ASCII 三行入口）+ `start.ps1`（UTF-8 BOM，实际逻辑）——检查 .venv/.env/node_modules、端口占用自动跳过（可重复执行）、分窗口拉起后端 uvicorn 8000 与前端 Vite 5173 并打开浏览器；实测真实拉起双服务、health 200 后清理。乱码修复：bat 含中文必须 GBK（UTF-8+chcp 或 LF 行尾会解析错乱），GBK 在编辑器又必乱码——故 bat 只留 ASCII 入口，中文逻辑全部放 PowerShell（5.1 读 UTF-8 必须带 BOM）
- [x] 2026-09-01 CLAUDE.md 过时信息审计与更新：逐一核实代码现状后修正 4 处——①大文件守则：study_service.py 已拆至 1687 行/24 顶层函数移出表格，ModuleView.tsx 仍 5910 行/103 useState 保留；②模型调用链路已抽至 model_client.py（re-export 门面），AgentJobWorker 在 agent_runtime.py；③"已知架构债：非流式整包等待"改写为"流式+30s 首 token 超时已完成（5fe4a13），剩 P1 真实上游验收"；④全量测试时长 17s→105s（187 项实测）。仅文档变更，无功能代码改动
- [x] 2026-08-30 文档整理：《项目架构解析》并入 project.md（以架构解析详细骨架为主干 + 保留域地图为 §8，章节号保持 §3.4/§4.1 不变以保住学习指南锚点）；核实并修正漂移数字（agents/ 16→19 文件、ModuleView useState 108→104、auth 三文件 371→458、modules 域 18→20）；学习指南 7 处引用同步改指 project.md；删除库根原件。docs.md 宪法新增 §6「AI 生成语言规范」（用户执笔专区，AI 只读遵守），框架 v1.1→v1.2
- [x] 2026-08-29 移除01课前准备问题生成链路（用户决策）：根因是生成合同"2至5个问题"（content_prompts 结构模板 + story 模板 preparation_rules）与强反馈硬校验"最多1个"长期互相矛盾，每次生成必撞线。修复：删"最多1个"强反馈校验与"最多5个"结构校验；prompt 两处不再要求生成问题；新硬校验"01不应包含问题列表"；story 模板 version 5→6 使旧 checkpoint 缓存自动失效；降级模板与 4 处测试同步。前端 questions 渲染保留（旧课数据兼容，新课自然为空）
- [x] 2026-08-28 完成课程生成可观察性与状态可信化：Job progress 持久化+lease fencing，刷新恢复最新活动/终态任务，单飞退避轮询，通信/预览/真实失败分离；课程规划、讲义/修复、自测/修复、模拟卷、保存阶段可见；真实 1/1 Job 尝试、心跳、模型统计和持久终态摘要；独立 hook/状态卡/纯逻辑模块
- [x] 2026-08-28 完成课程划词反馈效果链与生命周期治理：删除预览/部分成功/重试/放弃/刷新恢复；服务端权威 proposal、workspace revision 与幂等 apply；规则确认制、会话压缩、课程偏好面板；新增带锁存储模块与 10 个后端/5 个前端回归测试
- [x] 2026-08-28 完成课程划词反馈效果链与数据生命周期只读审计：定位本次“删去”未出删除预览的直接根因、确认反馈文件存储/规则提炼/后续生成注入链路，并形成待确认方案文档（仅 docs 变更，未实施代码、未运行代码验证）
- [x] 2026-08-28 更新重大变更工作流约束：较大更新须先研究现有代码，在 `docs/` 编写完整方案并经用户确认后方可实施（仅文档变更，无需运行代码验证）
- [x] 2026-08-28 更新 AI 协作约束：禁止 AI Agent 代替用户执行 Git 提交，所有提交操作均由用户本人完成（仅文档变更，无需运行代码验证）
- [x] 2026-08-28 阶段2-8 完成：strategy.py 抽取（策略文档读写/版本化、初稿生成、审阅保存、维护标记、草稿对话修订），study_service 2036→1660 行；revise_strategy_draft 的 _stream_model_turn/_sse 经缝合点延迟 import 保住 test_strategy_revision 打桩面；门面契约测试 +2
- [x] 2026-08-28 阶段2-7 完成：agent_chat.py 抽取（agent_chat/agent_chat_stream、SSE、消息组装、滚动摘要、knowledge_service 记忆联动），study_service 2681→2036 行；6 处缝合点；门面契约测试 +2
- [x] 2026-08-28 阶段2-6 完成：review_plan.py 抽取（复习计划 AI 维护、每日进度、时长记录、顺延/减负/重排提案、工作台手动更新），study_service 3142→2681 行；record_time 的 build_daily_progress 打桩面经别名延迟 import 保持；门面契约测试 +2
- [x] 2026-08-28 阶段2-5 完成：practice.py 抽取（刷题/错题重做判分、AI 举一反三、掌握度联动、模拟卷修复与计分、计算题 AI 批改），study_service 3465→3142 行；repair_mock_questions 测试打桩点经延迟 import study_service 保持；门面契约测试 +2
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
| 2026-09-24 | 域目录中文化 + 26 域双文档补全：29 域目录两件套存在性脚本核验（29/29 齐备）；grep 确认活动文档无旧英文目录路径引用 | ✅ 29 域齐备（纯文档变更，验证三件套不适用） |
| 2026-09-24 | 图标切回 app-icon.png：tsc / build / dev server 5174 用户浏览器实测 | ✅ tsc / ⚠️ Vite 2249 modules 后既有原生 exit（与本轮无关）/ ✅ 图标显示用户确认 |
| 2026-09-24 | 文档库结构清理 v2.1：mv 迁移 core 9 域 / bugs 11 档案 / course-style-lab，活动文档引用全量修正后 grep 核验 | ✅ core/、bugs/、draft/ 目录消除；活动文档旧路径零残留（纯文档变更，验证三件套不适用） |
| 2026-09-24 | favicon 修复：Vite dev 5173 实测 `/favicon.svg` 200（image/svg+xml）、Chrome 打开页面后网络面板确认浏览器成功拉取图标；`npx tsc -b` / `npm run build` | ✅ 图标加载正常 / ✅ tsc / ⚠️ Vite 2249 modules 后既有原生 exit 1（与本轮无关） |
| 2026-09-24 | 启动项目.bat 实测：真实拉起 uvicorn 8000 + Vite 5173，/api/health 与前端均 200，验证后清理测试进程 | ✅ 通过（无 backend/web 代码改动，未跑验证三件套） |
| 2026-09-24 | 文档库混合升级（无代码改动）：全库引用一致性核验 | ✅ questions.md 互引 5 处正确；旧路径仅日志迁移记录（→archive/ 标注，合规） |
| 2026-09-01 | CLAUDE.md 审计核验（无代码改动）：全量 pytest / tsc / build | ✅ 187 passed / 105s；✅ tsc；⚠️ Vite 2249 modules 后既有原生 exit 1（与本轮无关） |
| 2026-08-29 | 自测初稿生成调用补回 + patch artifact 字段分离：全量 pytest | ✅ 187 passed（+2）/ 97s |
| 2026-08-29 | 移除01课前准备问题生成链路：全量 pytest / tsc / build | ✅ 185 passed / ✅ tsc / ⚠️ Vite 既有原生 exit 1（无关） |
| 2026-08-29 | patch 路径斜杠兼容 + partial 如实展示：全量 pytest / tsc / build | ✅ 185 passed（+2）/ ✅ tsc / ⚠️ Vite 2249 modules 后既有原生 exit 1（与本轮无关） |
| 2026-08-28 | 课程反馈生命周期：全量 pytest / Vitest / tsc / build | ✅ 173 passed / ✅ 5 passed / ✅ tsc / ⚠️ Vite 2249 modules 后既有原生 exit 1 |
| 2026-08-28 | 阶段2-8 后全量 pytest（strategy 抽取后，含新增门面 ×2） | ✅ 161 passed / 97s |
| 2026-08-28 | 阶段2-7 后全量 pytest（agent_chat 抽取后，含新增门面 ×2） | ✅ 159 passed / 101s |
| 2026-08-28 | 阶段2-6 后全量 pytest（review_plan 抽取后，含新增门面 ×2） | ✅ 157 passed / 98s |
| 2026-08-28 | 阶段2-5 后全量 pytest（practice 抽取后，含新增门面 ×2） | ✅ 155 passed / 100s |
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
| 2026-08-28 | 8b9e3ec | refactor(strategy): 抽取策略文档域到 strategy.py（阶段2-8） |
| 2026-08-28 | 2719755 | refactor(agent_chat): 抽取 Agent 对话域到 agent_chat.py（阶段2-7） |
| 2026-08-28 | 34896c3 | refactor(review_plan): 抽取复习计划域到 review_plan.py（阶段2-6） |
| 2026-08-28 | ab4e7c7 | docs: 看板更新——阶段2-5 完成，study_service 3465→3142 行、155 passed |
| 2026-08-28 | 7a2d38e | refactor(practice): 抽取练习/错题/模拟卷域到 practice.py（阶段2-5） |
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
