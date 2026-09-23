# 资料库（materials）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

课程资料的管家的编排层：上传/扫描/主辅角色/资料记忆 digest/知识库同步编排（解析本体在资料解析域，检索在 RAG检索域）。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 主辅角色存 workspace.materialRoles（文件系统只存文件），扫描后 `_apply_material_roles` 回填 | 用户选择与文件解耦，重扫不丢 |
| digest 失效：sha256(path\|size\|aiStatus\|analysisVersion\|role\|priorityOrder)[:16] 比对 materialMemory → contentRefreshRecommended + 改写 diagnostic.message | 资料变化显式提示重审主线/模拟卷，不静默 |
| 惰性刷新：load_workspace(refresh_materials=True) 仅当 analysisVersion≠5 或缺 memory 才重扫；内部调用普遍显式 False | 性能；避免每次读 workspace 都全量解析 |
| 资料变更统一下游：mark_strategy_maintenance_pending（仅 approved 且有 reviewPlan 时）→ 入队 glossary_refresh + maintain_review_plan | 变更语义收敛一处 |
| sync 失败不阻断 | knowledgeBase={status:'unavailable'} 如实标记 |

## 不变量

- role ∈ {primary, supplementary}，默认 supplementary
- 上传限制 MAX_SINGLE_MATERIAL_MB=512 / MAX_BATCH=1024（env 可覆盖）；upload-batch 自定义二进制协议（manifest 长度行 + JSON + 字节流）
- 递归扫描跳过 AGENTS.md
- study_service:195-270 是纯门面，打桩 patch materials/material_parser 本体

## 禁区

- 不在编排层做解析实现（属于资料解析域）

## 设计异议

（无）
