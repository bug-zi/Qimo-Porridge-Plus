# bugs/ 错误档案库

> 收录项目中遇到过的所有错误：什么时间、遇到什么错误、导致什么后果、
> 根因（已知时）、建议修复方式。**AI 在执行过程中遇到错误时自动记录到这里**（宪法 §4.4）。

## 规则

- **AI 遇错自动建档义务**：任何会话中遇到（或被告知）真实错误——运行失败、测试红灯、
  行为异常、构建崩溃——必须在本文件夹建档，一个错误一个文件，无论当时是否顺手修复。
- 文件命名：`YYYY-MM-DD-<英文slug>.md`（发现日期 + 短横线英文标识）。
- **与看板 🐛 区的分工**：本库是**全量持久档案**（不删除）；看板只保留
  **活跃/待验证**条目做状态跟踪。bug 完全关闭后，看板条目移除，档案永久保留。
- 状态流转：🔴 待修复 → 🟡 已修复待验证 → ✅ 已关闭（附 commit）；另有 ⚪ 暂不修（附理由）。
- 误报/根因纠正：在原档案中标注更正并保留原文，不删文件。

## 档案模板

```markdown
# <错误标题>
- 档案号：<文件名>
- 发现时间：YYYY-MM-DD HH:MM（大致即可）
- 严重度：高 / 中 / 低
- 所属域：<modules 或 core 域，可多个>
- 发现场景：<哪个任务/会话/操作中遇到>
- 错误现象：<看到了什么>
- 导致后果：<对功能/数据/开发的影响>
- 根因：<已知时写；未知写"待查">
- 建议修复方式：<哪怕已修复也记录"当时应该怎么做"或修复思路>
- 状态：🔴/🟡/✅/⚪ + 备注验证方式
- 关联：<commit、看板条目、proposals、域 design 的异议区>
```

## 索引（按发现时间倒序）

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
