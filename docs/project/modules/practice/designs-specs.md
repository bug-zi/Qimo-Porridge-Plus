# 刷题（practice）域规格 specs

> 状态：🌱 AI 从代码生成，随代码同步 ｜ 生成日期 2026-08-29

## 导读（写给人）

**本域管什么**：点一道练习题选答案/提交 → 判分 → 记错题 → 更新掌握度 → 影响
复习计划，这一整条链。错题重做、模拟卷作答也在本域后端（前端分属 wrong-book /
mock-exam 域视图）。

**一条典型调用链**（提交一道练习答案）：

```
ModuleView 练习卡片提交
  → POST /api/courses/{id}/practice/answer        routers/practice.py:83
  → submit_practice_answer(...)                    practice.py:392
     ① _find_any_question 定位题目
     ② 答案一致性校验（answer_consistency）
     ③ 判分；错 → _record_wrong_answer(:315) 写 workspace.wrongAnswers
     ④ _update_mastery(:355) 更新知识点掌握度
     ⑤ _prioritize_tasks(:365) 调整任务优先级
  → save_workspace（带锁读-改-写）
  → 前端拿到判分结果与掌握度变化
```

**常见困惑**（学习中问到就补）：
- 练习题从哪来？——课程生成流水线（core/content-pipeline）产出 practiceQuestions 进
  workspace；AI 举一反三的变式题经 `_append_practice_questions` 动态并入同一池。
- 为什么 practice/mock/wrong-book 三个前端域共用一个 practice.py？——阶段2 按后端职责拆分
  （判分/错题/模拟卷天然共享题目定位与掌握度联动），前端域视图是另一维度。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| `backend/app/practice.py` | 651 | 本域主体（阶段2-5 从 study_service 抽取，7a2d38e） |
| `backend/app/routers/practice.py` | ~200 | 路由层 + 学习时长 time-log 端点 |
| `backend/app/agents/answer_consistency.py` | — | 答案与解析一致性校验（判分前置） |
| `web/src/components/ModuleView.tsx` 练习部分 | — | 练习作答界面（巨石组件内） |
| `web/src/types.ts` 相关类型 | — | 作答/错题/掌握度前端契约 |

## 入口与调用链

**后端公开入口**（全部挂在课程下）：
- `POST /practice/answer` → `submit_practice_answer`（练习判分全链）
- `POST /wrong-answers/{id}/retry` → `submit_wrong_answer_retry`(:452)（错题重做判分）
- `POST /mock/submit` → `submit_mock_answers`(:607)（模拟卷作答+计分，含 `_grade_mock_written_answer`
  主观题批改、`_estimate_score` 估分）
- `POST /mock/repair` → `repair_course_mock_questions`(:535)（AI 修复模拟题）
- `DELETE /practice/answers/{qid}` / `DELETE /mock/result`（清除作答）
- `POST|DELETE /time-log`（学习时长，服务复习计划域）

**关键内部函数**：题目定位 `_find_question`/`_find_any_question`；错题 `_record_wrong_answer`/
`_record_written_wrong_answer`；AI 举一反三 `_ai_review_wrong_answer`(:239)（走 model_client）；
掌握度 `_update_mastery`；优先级 `_prioritize_tasks`。

**上游数据来源**：workspace.practiceQuestions / mockQuestions（content-pipeline 产出）。
**下游消费方**：wrong-book 域（错题视图）、review-plan 域（掌握度与优先级输入调度）、
strategy_workflow（错题进入策略修订的证据）。

## 数据契约

- **workspace 键**：`practiceAnswers`（作答）、`wrongAnswers`（错题，含知识点归属）、
  `mockResult`（模拟卷结果）；全部随 workspace.save 持久化（revision + 文件锁）。
- **掌握度语义**：`_update_mastery` 按对错增减 knowledgePoint.mastery；知识点"已完成"
  判定见 study_scheduler.kp_completion_map（有任务→全 completed；无任务→mastery≥60）。
- 错题归档走 archived_items（owner 隔离 + 7 天清理，见 archive 域）。

## 测试锚点

- `backend/tests/` 中练习/错题/模拟卷相关用例（answer consistency 修复时 +4，
  见看板 2026-08-28）；门面契约测试锁住 study_service re-export。
- 验证基线：后端全量 187 passed（2026-08-29）。

## 设计异议

（无）
