# 认证与隔离（auth-isolation）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

白名单式认证中间件 + owner 数据隔离 + 遗留数据认领。**项目定位边界（CLAUDE.md 禁区）：认证仅作本地数据保护，不做多租户扩张，无管理后台/管理员角色。**

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 默认拒绝 + 精确白名单 | 所有 /api/* 需 Bearer，仅 /api/health、/api/auth/register、/api/auth/login、/api/auth/refresh 四条精确放行（frozenset 等值匹配，无前缀通配） |
| OPTIONS 预检豁免 | 避免 bare 401 无 CORS 头导致前端 "Failed to fetch" 误报 |
| 归属不通过返回 404 而非 403 | 不泄露课程存在性 |
| owner 过滤只落两张表 | 仅 courses 与 archived_items 直接带 owner_id 过滤；其余业务表靠 course_id 传递隔离（单用户本机，克制不扩张） |

## 不变量

- 中间件与 deps 的契约：验签成功写 `request.state.user_id`（JWT `sub`），路由内 `Depends(current_owner_id)` 防御性兜底
- 启动顺序：`initialize_auth_database`（users 表）→ `ensure_owner_columns`（老库 ALTER 补列）→ `claim_legacy_courses`（存量认领）
- `/api/auth/me`、`/api/auth/logout` 故意不在白名单（需要 user_id）

## 禁区

- 不做多租户运营、管理员角色、角色权限体系（users 表的 role 字段为遗留，JWT 不携带 role，代码无 role 检查——不得开始使用它）
- 白名单不得改为前缀/通配匹配

## 设计异议

（无）
