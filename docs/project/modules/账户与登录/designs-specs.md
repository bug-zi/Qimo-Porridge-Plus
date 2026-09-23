# 账户与登录（auth-account）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/auth_service.py | 430 | users/refresh_tokens 表、bcrypt、JWT 签发/验签、refresh 轮换、资料与头像 CRUD |
| backend/app/routers/auth.py | 85 | register/login/refresh/logout/me 五端点 |
| web/src/auth.ts | 220 | 前端会话层：localStorage 存储、authFetch（Bearer 注入 + 401 刷新重放）、并发刷新去重 |
| web/src/components/LoginPage.tsx | 115 | 登录/注册双模式整页表单，onAuthed 回调拉起工作台 |
| backend/.env | — | EXAM_BOOSTER_JWT_SECRET（缺失自动生成追加；永不提交） |
| web/vite.config.ts | 17 | dev 代理 /api → 127.0.0.1:8000（同源无 CORS） |

## 调用链

登录：LoginPage.handleSubmit → `loginWithPassword`（auth.ts:126）→ POST /api/auth/login → `authenticate_user`（auth_service:197）→ `issue_token_pair`（:416）→ `saveSession` 写 localStorage → onAuthed。
刷新：任意 API 401 → `authFetch`（:198）→ `refreshTokensQueued`（单飞）→ POST /api/auth/refresh → `rotate_refresh_token`（:240，轮换+重放检测）→ 新 token 对 → 重放原请求一次；再 401 → `clearSession()` + AUTH_EXPIRED_EVENT → 回登录页。

## 数据契约

- users 表：id（`user-`+16hex）、email UNIQUE、password_hash、role（遗留，不使用）、后补列 avatar_url/avatar_data/avatar_mime_type/gender/age/signature
- refresh_tokens 表：token_hash UNIQUE（SHA-256）、expires_at、revoked_at、replaced_by_token_hash；启动物理删除过期行
- localStorage 三键：`final-congee-access-token` / `final-congee-refresh-token` / `final-congee-current-user`
- 账户资料：GET/PUT /api/account-profile、POST/DELETE /api/account-profile/avatar（在设置域路由）

## 测试锚点

test_account_avatar.py（头像上传/改名/删除/422/413）、test_multi_tenant_isolation.py（register helper）、test_feedback_cors.py。无前端测试（tsc+build 兜底）；refresh 轮换重放吊销逻辑无直接单测（已知缺口）。

## 上游调用方 / 下游消费方

- 认证与隔离域依赖本域（decode_access_token）；api.ts 全部 API 走 authFetch；users 表被设置域（user_profile_prompt 按用户分键）与课程意见反馈域引用

## 导读

读序：auth_service.py（表结构+token 机制）→ auth.ts（前端会话与刷新）→ LoginPage.tsx。调试登录问题先看 localStorage 三键与 .env 的 JWT secret 是否一致。
