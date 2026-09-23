# 课程意见反馈（course-feedback）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/course_feedback_service.py | 1333 | 提交/分析/改写提案/应用/规则库/小节级提案/6 级替换链 |
| backend/app/course_feedback_store.py | 123 | 每课程 JSONL+JSON 存储、per-course RLock |
| backend/app/routers/course_feedback.py | 247 | 14 个端点，Pydantic 校验 |
| web/src/components/SelectionToNoteToolbar.tsx | 215 | 划词浮层 + 反馈对话框（划词基础域承载 UI） |
| web/src/components/courseFeedbackState.ts | 47 | feedbackDialogReducer（idle/submitting/partial-success/preview/refining/applying/success/error/abandoned），有 .test.ts |
| web/src/components/CourseFeedbackPreview.tsx | 26 | 修改前后对比 + 记住偏好勾选 |
| web/src/components/CoursePreferencesPanel.tsx | 51 | 规则启用/停用/删除/合并面板（设置域挂载） |
| web/src/api.ts | — | L362-440 共 12 个端点封装 |

## 调用链

划词 → POST /course-feedback → `submit_course_feedback_with_rewrite` → 分析+规则候选 → `generate_rewrite_proposal`；失败 persist_error（可重试）。refine → POST /{fid}/rewrite/refine；apply → `apply_course_feedback_rewrite` → 6 级替换链 → expected_revision 保存。小节整体修改：POST /course-feedback/global + global/refine + global/apply（AI伴学域入口）。

## 数据契约

- data/courses/{cid}/feedback/feedback.jsonl + optimization_rules.json
- 条目 id=`cfb_YYYYMMDDHHMMSS_8hex`；rewriteSession{attempts[](≤8)，latestProposal，acceptedRewrite}
- 端点全集：POST /course-feedback、/{fid}/rewrite/{refine,apply}、/{fid}/proposal/retry、/{fid}/abandon、GET open/列表/rules、PATCH/DELETE /rules/{rid}、POST /rules/merge、POST /course-feedback/global、/{fid}/global/{refine,apply}

## 测试锚点

test_course_feedback_lifecycle.py（8 测试：存储原子性/删除不调模型/rewrite 错误可重试/abandon 压缩/规则重建/RLock 串行/merge）、test_course_feedback_router.py（认证隔离/形状/422/404/409）、test_course_feedback_replacement.py（事务替换/回滚/编号标题恢复）、test_global_course_feedback.py（只改当前小节/refine 保留会话）、courseFeedbackState.test.ts（前端）

## 上游调用方 / 下游消费方

- 依赖：存储与工作区（load/save/_build_study_guide_sections）、模型调用（_model_json 注入）、划词基础、AI伴学（global 端点复用）
- 下游：课程生成流水线（append_course_feedback_rules 注入 course_prompt，study_service:1013-1015）

## 导读

读序：store（存储与锁）→ service 的 generate_rewrite_proposal/apply（核心两函数）→ 6 级替换链 → test_course_feedback_replacement（替换语义最可靠的文档）。
