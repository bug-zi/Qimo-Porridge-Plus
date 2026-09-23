# 认证与隔离（auth-isolation）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/auth_middleware.py | 63 | 白名单式 BaseHTTPMiddleware，默认拒绝 /api/*，验签后写 `request.state.user_id` |
| backend/app/tenancy.py | 51 | 启动期迁移：`ensure_owner_columns()` 补 owner_id 列、`claim_legacy_courses()` 存量认领 |
| backend/app/routers/deps.py | 282 | `current_owner_id` / `course_is_owned` / `require_course_ownership` + 归档辅助与课程彻底删除（归档域共享） |
| backend/app/main.py | 307 | 中间件注册（CORS→AuthMiddleware）、lifespan 初始化顺序、建表（courses/plan_tasks/archived_items） |

## 调用链

请求 → CORS（白名单 127.0.0.1:3500/5173 等，allow_credentials=False）→ `AuthMiddleware.dispatch`：OPTIONS/非 /api/路径/白名单路径放行 → 否则验 `Authorization: Bearer` → `decode_access_token`（auth_service）→ 失败 401（带 WWW-Authenticate，中文 detail）→ 成功写 `request.state.user_id` → 路由内 `Depends(current_owner_id)` 兜底 → 课程级路由 `Depends(require_course_ownership)` → `course_is_owned` SQL 校验，不通过统一 404。

## 数据契约

- courses 表：`owner_id TEXT NOT NULL DEFAULT ''` + 索引（新库建表即带，老库 ALTER 补列）；archived_items 同
- 其余业务表不加 owner 列，靠 course_id 间接隔离
- `request.state.user_id`（str，JWT `sub`）为中间件→deps 契约

## 测试锚点

test_multi_tenant_isolation.py（owner 列表/访问/归档/用户画像隔离 ×3）、test_feedback_cors.py（OPTIONS 豁免 + POST 仍 401）。白名单本身无独立单测（间接覆盖）。

## 上游调用方 / 下游消费方

- deps.py 被 8 个 router 复用（require_course_ownership 共 80+ 处）；settings.py 只用 current_owner_id
- 依赖账户与登录域（decode_access_token、users 表先行初始化）

## 导读

读序：auth_middleware.py（63 行，先读）→ tenancy.py → deps.py 的三个依赖函数。注意 deps.py 从 `.routers.deps` 反向 import `get_connection` 是为避免循环导入的既有安排。
