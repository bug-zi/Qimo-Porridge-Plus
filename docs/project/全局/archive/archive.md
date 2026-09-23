# 已落地提案归档

实施完成且耐久结论已合并回对应域 design.md 的提案存放于此，只进不改。

## 错误档案（原 bugs/，2026-09-24 并入）

AI 遇错自动建档义务不变：新错误直接在本目录建档（`YYYY-MM-DD-<英文slug>.md`，
规则与模板见 [bugs.md](./bugs.md)），看板 🐛 区只留活跃/待验证条目。

索引（按发现时间倒序）：

| 档案 | 标题 | 严重度 | 状态 | 域 |
|---|---|---|---|---|
| [2026-08-29-missing-question-draft-patch](./2026-08-29-missing-question-draft-patch.md) | 无自测检查点时空初稿走 patch，考点覆盖校验循环失败 | 高 | 🟡 已修待真实验证 | content-pipeline |
| [2026-08-29-patch-path-format](./2026-08-29-patch-path-format.md) | patch path 斜杠格式被拒 + partial 被掩盖为"完成" | 高 | 🟡 已修待真实验证 | content-pipeline / mainline |
| [2026-08-28-vite-rolldown-native-exit](./2026-08-28-vite-rolldown-native-exit.md) | Vite/Rolldown Windows 生产构建原生退出 0xC0000409 | 中 | 🔴 待定位 | settings 无关（构建链） |
| [2026-08-28-uvicorn-reload-chinese-path](./2026-08-28-uvicorn-reload-chinese-path.md) | uvicorn --reload 在中文路径下失效 | 中 | 🔴 待定位 | 跨域（开发环境） |
| [2026-08-28-routers-init-bom](./2026-08-28-routers-init-bom.md) | routers/__init__.py UTF-8 BOM | 低 | 🔴 待顺手清理 | storage 无关（代码卫生） |
| [2026-08-28-selection-delete-feedback-preview](./2026-08-28-selection-delete-feedback-preview.md) | 划词删除反馈无删除预览/确认 | 高 | ✅ 已关闭 | course-feedback |
| [2026-08-28-feedback-rules-premature-pollution](./2026-08-28-feedback-rules-premature-pollution.md) | 未确认/放弃的反馈提前污染生成规则 | 高 | ✅ 已关闭 | course-feedback |
| [2026-08-28-ai-companion-refine-multiround](./2026-08-28-ai-companion-refine-multiround.md) | 小节整体修改只能单轮，无法多轮对话逼近 | 中 | ✅ 已关闭 | ai-companion |
| [2026-08-28-answer-consistency-grading](./2026-08-28-answer-consistency-grading.md) | 答案配置与解析冲突时按错误 answerIndex 判分 | 高 | ✅ 已关闭 | practice |
| [2026-08-28-agent-queue-double-execution](./2026-08-28-agent-queue-double-execution.md) | agent 队列双重执行（心跳猝死→lease 过期→二次 claim） | 高 | ✅ 已关闭（132e3e1） | job-queue |
| [2026-08-28-agent-queue-hang](./2026-08-28-agent-queue-hang.md) | AI 生成队列偶发卡死（非流式长超时+上游静默） | 高 | ✅ 已关闭（阶段1） | job-queue / model-client |
| [2026-08-28-request-timeout-misjudge](./2026-08-28-request-timeout-misjudge.md) | 300s 总超时误杀思考型慢请求 | 中 | ✅ 已关闭（阶段1） | model-client |

> 首批 12 个档案自看板 🐛 区迁移建档（2026-08-29），此后看板只保留活跃/待验证条目。
> 档案内"所属域"的 `core/` 前缀为建档当时结构，core/ 已并入 modules/。

## course-style-lab/（原 draft/，2026-09-24 并入）

课程风格共创实验稿：标准/对话/故事版课程样例与 80 分课程生成 Prompt 各版本。
三种风格已落地进正式生成 Prompt（content_prompts），此目录作历史参考，
[README](./course-style-lab/进程与线程基础/README.md) 与 STYLE-DECISIONS 保留原样。

## 其他

- [core.md](./core.md)：原 core/ 引擎域总文档（9 域已于 2026-09-24 并入 modules/，说明合并进 modules/modules.md）。
- 原 proposals/ 时期归档的 8 份方案，与重构时补归档的《学习文档编排与规则优化方案》（2026-08-30 已实施）。
