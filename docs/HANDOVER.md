# 期末粥++（校园版）开发交接文档

> 写于 2026-08-21。交接给下一个模型/开发者继续推进。
> 阅读本文 + `git log` 即可接手，无需翻旧会话。

## 一、项目背景

- **仓库**：`D:\Code\自创项目\网站类\期末粥++`（git，分支 `main`）
- **定位**：「期末粥加速器」校园多用户版，由冻结的个人版 Qimo-Porridge v1.0.0-personal 演化（commit `c13b535` 初始化）
- **总目标**（README）：账号体系、课程广场（模板分享/审核/安装）、管理后台、云服务器部署
- **技术栈**：FastAPI + SQLite（WAL，timeout=30）后端；React 19 + TS + Vite 前端（`web/`）
- **运行方式**：后端 `cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000`（**必须用 backend/.venv**，系统 Python 缺 jwt/passlib）；前端 `cd web; npx vite`（默认 5173）。数据落在 `backend/data/exam_booster.db` + `backend/data/courses/{course_id}/`。

## 二、已完成工作（按提交顺序）

| 提交 | 内容 |
|---|---|
| `cc02402` | stage0：main.py 路由按域拆分到 `routers/`（URL 零变化） |
| `d6e65d8` | stage0：依赖补全 + API base 环境变量化 + SQLite WAL/timeout |
| `6dfa662` | **阶段1 认证体系**：注册/登录/刷新/登出/me；JWT access 30min + refresh 30天轮换（服务端只存 SHA-256 哈希）；盗窃检测（重放已轮换 token → 吊销该用户全部 token）；AuthMiddleware 白名单式守卫（`/api/*` 默认拒绝，白名单仅 health + auth 端点）；前端 LoginPage/auth.ts/authFetch（单飞 401 刷新重放） |
| `ca3ff09` | **阶段2-1 多租户骨架**：courses/archived_items 两表加 `owner_id`（新表建表带列 + 老库 ALTER）；启动时存量无主数据归属首个注册用户（`claim_legacy_courses`）；`tenancy.py` 承担启动期迁移 |
| `89f7d77` | **阶段2-2 路由层归属校验**：40 个课程级路由注入 `Depends(require_course_ownership)`；`list_courses` 按 owner 过滤、`create_course` 写 owner_id；归档写入/列出/恢复全带 owner；**顺带恢复 `fa730d1` 误删的 `GET /api/archive` 与 `POST /api/archive/{id}/restore`**（前端一直在调，此前 404）；agent-runs/agent-jobs 按 courseId 反查归属。双用户冒烟 18 项断言 ×2 全过 |
| `f24950c` | **阶段2-3 service 层核查 + 画像隔离**：确认所有 courses/archived_items SQL 点已被归属校验覆盖、文件目录经 `_validate_course_id` 正则防穿越；**用户自画像从全局单键改为按 owner 分键**（原来 A 的画像会注入 B 的 AI prompt，真实跨用户泄露），已实测隔离 |

### 多租户架构核心决策（必读）

1. **只有 `courses` 和 `archived_items` 两表带 `owner_id`**。其余表（plan_tasks/agent_jobs/artifacts/glossary/knowledge/chat_* 等）全部以 `course_id` 为索引——路由层校验课程归属后传递隔离，无需逐表加列。
2. **运行时归属校验统一入口在 `backend/app/routers/deps.py`**：
   - `current_owner_id(request)`：从 AuthMiddleware 注入的 `request.state.user_id` 取当前用户（防御性 401 兜底）
   - `course_is_owned(connection, course_id, owner_id)`：查课程归属
   - `require_course_ownership(course_id, owner)`：**FastAPI 依赖**，校验失败统一 404（不泄露存在性），通过则返回 owner_id
   - 注意：`course_is_owned` 原在 tenancy.py，后迁到 deps.py（避免循环导入）；tenancy.py 现在只有启动期迁移函数
3. **课程级文件目录** `backend/data/courses/{course_id}/`（workspace.json、mind_map.json、materials/、strategy/）——隔离靠路由层校验 + ID 正则 `[A-Za-z0-9][A-Za-z0-9_-]{0,119}` 防路径穿越，不需要按用户分目录（course_id 本身含时间戳全局唯一）。
4. **保持全局的端点**（实例级配置，校园部署由管理员配，暂不做多用户语义）：`settings.py` 的 runtime-model / knowledge/embedding、`mcp.py` 全部端点（MCP 服务器、B 站凭据）。**例外**：`/api/user-profile`（用户自画像）已改为按 owner 分键（`app_metadata` 表 key = `user_profile_prompt:{owner_id}`，空 owner 兼容旧全局键）。
5. **启动期迁移链**（main.py lifespan）：`initialize_database()` → `initialize_auth_database()` → `ensure_owner_columns()` → `claim_legacy_courses()` → knowledge/agent 初始化。种子课程（data-structure）无主，首个注册用户出现时被认领。

## 三、当前状态

- 阶段2-4 收尾已推进：新增 `backend/tests/test_multi_tenant_isolation.py` 覆盖课程列表/课程级路由/归档/自画像 owner 隔离；README 已补多用户部署注意事项
- 后端测试：`backend/.venv/Scripts/python.exe -m pytest tests -q` → 44 passed, 3 skipped
- 前端类型检查：`npx tsc -b` → 通过；`vite build` 仍在 2239 modules transformed 后原生退出 exit 1（无 JS/TS 报错，符合此前 rolldown 原生崩溃类问题；已重试 2 次）
- 后端语法全过（ast 28 文件）、启动实测通过、双用户隔离冒烟全过
- **注意**：`backend/app/routers/__init__.py` 文件头有个 UTF-8 BOM（历史遗留，Python 能正常 import，验证语法时需跳过或用 `utf-8-sig` 读）
- **测试数据**：`backend/data/exam_booster.db` 里有多个测试注册用户（test@example.com、alice*/bob*/prof-a*/prof-b*@example.com 等），生产部署前应清库或换库

## 四、冒烟测试方法（已验证可复用）

服务器跑起来后用 PowerShell（注意中文输出会显示 `???`，是控制台编码问题，数据本身正确）：

```powershell
# 注册 → 拿 token
$a = Invoke-RestMethod "http://127.0.0.1:8000/api/auth/register" -Method Post -ContentType "application/json" -Body (@{email="x@example.com";display_name="X";password="Xx12345!x"}|ConvertTo-Json)
$ha = @{Authorization="Bearer $($a.access_token)"}
# 建课 → 换个用户 token 访问同一 course_id 应 404
```

历史冒烟脚本：`C:\Users\Administrator\AppData\Local\Temp\claude\smoke_2_2.ps1`（18 项断言：未登录 401 / B 看不到 A 的课程、归档 / 越权 GET·PUT·POST·DELETE 全 404 / A 自访问正常 / A 恢复自己归档成功）。**坑**：PowerShell 5.1 写脚本文件时中文注释可能吞换行导致解析错，脚本内注释尽量用英文或写后用 PSParser 校验。

## 五、下一步工作（按优先级）

### 1. 阶段2-4：多用户隔离终验 + 收尾（任务列表 #4，进行中）
- 已完成：README 部署说明补齐；`backend/tests/test_multi_tenant_isolation.py` 新增 3 个多租户隔离 pytest（课程、归档、自画像）
- 已完成：后端全量 pytest 回归 44 passed, 3 skipped；前端 `npx tsc -b` 通过
- 待人工/浏览器终验：两个浏览器身份（或隐身窗口）分别登录，验证课程列表互不可见
- 待处理/确认：`npx vite build` 在 rolldown/Vite 原生构建阶段 exit 1，无 TypeScript 错误；若继续失败，可考虑临时锁 Vite/Rolldown 版本或切换构建后端

### 2. 已知遗留问题
- `web/src/demo/demoApi.ts`（demo 模式）没有 auth 概念，`VITE_DEMO_MODE=true` 时完全绕过登录——多用户部署环境**不要开** demo 模式，或后续给 demo 加独立入口
- CORS 硬编码 `127.0.0.1:5173`/`localhost:5173`（main.py），部署时需按域名放开
- `backend/.env` 里自动生成的 `EXAM_BOOSTER_JWT_SECRET` 若丢失所有用户会被登出（secret 变了 token 全失效），部署时务必持久化

### 3. 总路线图后续阶段（README 目标）
- **阶段3 课程广场**：模板分享/审核/安装——需要新表（templates：id/owner_id/审核状态/载荷）、广场列表页（公开只读）、安装 = 复制模板生成自己的课程
- **阶段4 管理后台**：用户管理（封禁/重置）、课程广场审核台、实例监控——需要 admin 角色（users 表加 role 列 + 管理端点鉴权）
- **阶段5 云服务器部署**：HTTPS 反代（CORS/白名单调整）、数据备份策略、多 worker 下 AgentJobWorker 的并发安全（当前单进程假设——uvicorn 多 worker 会跑多份 job worker，需上锁或拆进程）

## 六、关键文件索引

| 文件 | 职责 |
|---|---|
| `backend/app/main.py` | app 组装、CORS、中间件、路由挂载、lifespan 迁移链 |
| `backend/app/auth_service.py` | users/refresh_tokens 表、bcrypt+JWT、token 轮换与盗窃检测 |
| `backend/app/auth_middleware.py` | 白名单式 `/api/*` 认证守卫，写 `request.state.user_id` |
| `backend/app/routers/deps.py` | **归属校验统一入口**（current_owner_id / require_course_ownership / course_is_owned）+ SQLite 连接 + 归档 helpers |
| `backend/app/tenancy.py` | 启动期迁移（补 owner_id 列 + 存量认领） |
| `backend/app/routers/courses.py` | 课程 CRUD + workspace + **archive 恢复端点**（含归档三分支恢复逻辑） |
| `backend/app/study_service.py` | 业务核心（6200+ 行）：workspace 读写、AI 对话、计划维护；`get/save_user_profile_prompt(owner_id)` 在 ~236 行 |
| `web/src/auth.ts` / `LoginPage.tsx` | 前端认证（token 存储刷新、登录门） |
| `web/src/api.ts` | API 客户端（authFetch 带 401 自动刷新） |

## 七、踩坑记录（下一个模型请避开）

1. **venv**：后端必须用 `backend/.venv`，系统 Python 缺依赖（报 `No module named 'jwt'`）
2. **vite build 偶发原生崩溃**（exit 9 / 0xC0000409）：rolldown 问题，重试就好
3. **email-validator 拒绝保留域**：测试邮箱用 `@example.com`，别用 `.local`
4. **PowerShell 中文**：控制台输出 `???` 只是显示问题；写 .ps1 文件时中文注释可能引发解析错误（换行被吞）
5. **归档 payload 里存的 course dict 是 snake_case（库行）或 camelCase（workspace）**，恢复时两种都要处理——courses.py `restore_archive_item` 已处理，改动归档逻辑时注意
6. `git show fa730d1^:backend/app/main.py` 有拆分前的完整老代码可参考
