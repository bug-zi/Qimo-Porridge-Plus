# 刷题（practice）域设计

> 状态：🌱 AI 逆向起草，待用户审定 ｜ 起草日期 2026-08-29（学习/冻结期）

## 定位

学习者与题目的一切交互：课程练习作答与判分、错题记录与重做、AI 举一反三、
掌握度反馈。是"学→练→纠"闭环中"练"的一环，向上承接复习主线产出的题目，
向下驱动错题本（wrong-book 域共享本域后端）与复习计划调整。

## 关键决策

1. **判分与掌握度联动**：每次作答（练习/错题重做）都经 `_update_mastery` 更新
   知识点掌握度、经 `_prioritize_tasks` 调整任务优先级——练习结果直接改变复习主线的调度输入。
2. **答案一致性校验优先于 answerIndex**（2026-08-28 修复）：题目配置的 answerIndex 与
   解析文字结论冲突时，以解析结论保守纠正后再判分（agents/answer_consistency）。
   *背景事故*：自测题"应选 20ms"却被按 50ms 判错。判分宁可保守，不可错怪学习者。
3. **错题是数据不是视图**：错题记在 workspace 的 `wrongAnswers` 列表（practice.py:139/324
   setdefault），归档/恢复走 archived_items 表；错题本界面只是这份同一数据的另一个视图
   （wrong-book 域与本域共享 practice.py 后端）。
4. **AI 举一反三走 model_client**：`_ai_review_wrong_answer` 把错题+解析交给模型出变式，
   产物并入练习题池（`_append_practice_questions` / `_normalize_generated_practice_questions`）。
5. **作答可清除**：练习答案与模拟卷结果都提供 DELETE 端点（clear_practice_answer /
   clear_mock_result），支持重做场景。
6. **模拟卷 AI 修复**：`repair_course_mock_questions` 对质量不合格的模拟题走模型修复而非整卷重生成。

## 不变量

- 判分前必须过答案一致性校验（摸底/练习/错题重做/模拟卷四场景全覆盖）。
- 掌握度与任务优先级的更新只能发生在判分确定之后。
- 错题写入必须同时携带知识点归属（供掌握度与调度使用）。

## 禁区

- 不做判分宽松化兜底（错就是错，解析冲突时纠正配置而不是放过作答）。

## 设计异议

（无）
