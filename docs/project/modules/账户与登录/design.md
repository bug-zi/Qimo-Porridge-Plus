# 账户与登录（auth-account）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

注册/登录/JWT 签发与刷新轮换、账户资料与头像。与认证与隔离域共用项目定位边界：本地数据保护，不扩张。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| refresh token 有状态轮换 + 重放检测 | 明文只返回一次，库存 SHA-256；重放已吊销 token 视为泄露，吊销该用户全部 refresh token |
| 密码 SHA-256 预哈希 + bcrypt(rounds=12) | 解 bcrypt 72 字节输入上限；用户不存在时跑 DUMMY_BCRYPT_HASH 抹平时序差 |
| JWT 密钥自举 | env 缺失时自动生成并追加写 backend/.env（避免重启全体掉线）；.env 不可写退回内存密钥 |
| 前端 401 单飞刷新 | `refreshInFlight` 单飞 Promise 去重；login/register/refresh 三请求刻意绕过 authFetch 防递归 |
| 登出只吊销 refresh | access 无状态自然过期（≤30 分钟残留） |
| demo 模式完全绕过认证 | `VITE_DEMO_MODE=true` 时LoginPage 不渲染、造假用户（注意：demo 不能用于验收，CLAUDE.md 历史教训） |

## 不变量

- access 30min / refresh 30 天，HS256，claims `{sub, type:"access", iat, exp, iss:"exam-booster"}`；JWT 不携带 role
- 前端会话仅 localStorage 三键（access/refresh/current-user），无 cookie
- `hasSession()` 以"存在 refresh token"判定登录；过期广播 AUTH_EXPIRED_EVENT 回登录页
- 头像 ≤2MB，魔数校验 JPEG/PNG/GIF/WebP

## 禁区

- 不引入角色权限体系；账户资料/头像端点在设置域路由（settings.py），不搬回 auth.py

## 设计异议

（无）
