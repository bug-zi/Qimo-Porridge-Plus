# AGENTS.md

本项目所有 AI 编码助手（Codex、Cursor、Copilot、Windsurf、Claude Code 等）的共同约束文件。

**请阅读并遵守 [`CLAUDE.md`](./CLAUDE.md)**——它是本项目唯一的约束真源，包含：

- 项目定位与禁区（暂停项清单）
- 验证三件套（pytest / tsc / build，改完必跑）
- 大文件修改守则（study_service.py / ModuleView.tsx）
- Git 提交纪律
- 实时开发看板 `docs/project/DEV_BOARD.md` 的维护义务（**每个会话结束必须更新**）
- 文档体系 `docs/`（机制正本 `docs/project/README.md`）：涉及某域改动前先读该域 design.md / designs-specs.md（已有时）；
  有实质工作的会话结束时写当日开发日志 `docs/log/`

不要另行创建重复的约束文件；约束变更直接改 `CLAUDE.md`。
