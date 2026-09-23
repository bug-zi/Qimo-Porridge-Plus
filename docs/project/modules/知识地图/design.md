# 知识地图（mind-map）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

课程思维导图：从 workspace 全量内容生成 ReactFlow 无限画布，支持手动拖拽/折叠/重排与 LLM 模块重组。**布局与内容分离**：图内容可再生成，用户布局持久保留。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| mind_map.json 独立文件（非 workspace 内嵌；占位文档此表述已纠正） | 布局数据高频小写，与 workspace 大 JSON 解耦；load 前仍校验课程存在 |
| 重建按 node id 继承旧 position/collapsed，新节点网格兜底 | 再生成不丢用户手动布局 |
| layoutVersion===3 才跳过前端 ELK 重排 | 版本升级自动重排旧图，防布局算法漂移产生脏图 |
| 前置依赖边不进 ELK layered 布局（跨模块成环），布局后叠加绘制 | 图算法可行性与语义完整性兼得 |
| 模块层级仅两来源：moduleId 声明命中 / 知识点名 2-gram 并查集聚类兜底（slug+sha1[:8] 稳定 id） | 聚类稳定可继承拖拽坐标；绝不再从资料文件名抽章号 |
| regroup LLM 聚 4-8 个学科标准章节，异常确定性回退 resolve_course_modules | 端点永远可用 |

## 不变量

- schema：{version:1, courseId, generatedAt, sourceRevision(=workspace.revision), layout:'tree-right', layouted, layoutVersion, viewport, nodes[], edges[]}；edge id 固定 `edge-{source}-{target}`
- `_knowledge_point_pid`（point.id || kp-{index}）两处必须同逻辑
- 题目预览每知识点限 5

## 禁区

- regroup 回写 workspace.modules / knowledgePoints[].moduleId——这是课程结构变更，必须经 save_workspace 且保持 revision 一致性

## 设计异议

- 无行为测试（仅门面 re-export 同一性测试）——1715 行前端组件 + 生成逻辑均零覆盖，待开发者裁决
