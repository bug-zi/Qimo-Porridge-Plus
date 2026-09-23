# 知识地图（mind-map）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| web/src/components/CourseMindMapView.tsx | 1715 | ReactFlow+elkjs 无限画布（lazy 加载；loadMap/generate/ensureLayouted/scheduleSave 650ms 防抖/regenerate/regroup） |
| web/src/components/ModuleView.tsx | — | 挂载点（:108 lazy import；:5861-5883 Suspense 渲染） |
| backend/app/routers/courses.py | 787 | 4 个端点（:240-292），均挂 require_course_ownership |
| backend/app/workspace.py | 466 | _mind_map_path(:50)/load_mind_map(:430)/save_mind_map(:444) |
| backend/app/study_service.py | 1687 | _knowledge_point_pid(:1182)/_slugify_module_id(:1188)/_cluster_points_by_name(:1194)/resolve_course_modules(:1239)/_llm_regroup_modules(:1304)/regroup_course_modules(:1362)/generate_mind_map(:1388) |
| web/src/api.ts | 1314 | getCourseMindMap/generateCourseMindMap/regroupCourseMindMapModules/saveCourseMindMap |

## 调用链

GET course_mind_map → load_mind_map；PUT → save_mind_map；POST generate → generate_mind_map；POST regroup → regroup_course_modules → _llm_regroup_modules（异常回退 resolve_course_modules）→ 回写 workspace.modules/knowledgePoints[].moduleId → save_workspace → generate_mind_map。前端：ModuleView lazy → loadMap（空则自动 generate）→ ensureLayouted → MindMapCanvas → scheduleSave。

## 数据契约

- data/courses/<id>/mind_map.json：{version:1, courseId, generatedAt, sourceRevision, layout:'tree-right', layouted, layoutVersion, viewport{x,y,zoom}, nodes[], edges[]}；node.type ∈ course/chapter/knowledge/task/material/question/wrongAnswer，kind?'module'\|'bucket'，collapsed；edge label ∈ 章节/模块/知识点/任务/题目/错题/前置
- workspace：modules[{id,title,order}]、knowledgePoints[].moduleId
- TS：MindMapNodeType/MindMapNode/MindMapEdge/CourseMindMap（types.ts:736-792）

## 测试锚点

test_facade_exports.py:187-199（门面 re-export 同一性）；无行为测试（design.md 异议节已记）。

## 上游调用方 / 下游消费方

- 读 workspace 全量（knowledgePoints/tasks/三类 questions/wrongAnswers/assessmentProfile/diagnostic）；依赖模型调用（_llm_regroup_modules）、复习调度器（PREREQUISITE_EDGE_LABEL）
- regroup 回写影响规划与复习主线

## 导读

读序：study_service 的 generate_mind_map（内容→图）→ 布局继承逻辑（:1419-1427）→ CourseMindMapView 的 ensureLayouted（ELK 与版本控制）→ regroup 链。
