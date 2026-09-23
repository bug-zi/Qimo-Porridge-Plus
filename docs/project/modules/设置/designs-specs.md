# 设置（settings）域规格 specs

> 状态：🌱 AI 从代码生成，随代码同步 ｜ 生成日期 2026-08-29

## 导读（写给人）

**本域管什么**：设置页的每一个表单背后是什么。配模型、测连通性、换头像、
改学习画像、配 embedding，全在这里。

**一条典型调用链**（保存主模型并测试）：

```
SettingsView 表单提交
  → PUT /api/runtime-model                      routers/settings.py:176
  → update_runtime_model → model_profiles 封装 → 写 backend/.env
（另一按钮）测试连通性
  → POST /api/model-profiles/test               routers/settings.py:88
  → probe_model_chat(base_url, api_key, model)  model_client.py:342
     （真实发一条 chat 请求，走与生成相同的容错路径）
  → 前端显示成功/失败与错误详情
```

**常见困惑**（学习中问到就补）：
- 为什么"测试"不测保存后的配置？——test 端点用表单当前值直测，允许"先测后存"。
- 备用模型在哪配？——同页 backup-model 区（GET/PUT /api/backup-model），存 BACKUP_* 键。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| `backend/app/routers/settings.py` | 230 | 本域全部路由 |
| `backend/app/model_profiles.py` | 311 | .env 读写、模型画像、用户画像、消息构造器注入 |
| `backend/app/model_client.py` 部分 | — | probe_model_chat / fetch_available_model_ids / backup 读写 |
| `backend/app/knowledge_service.py` 部分 | — | embedding 配置读写与测试 |
| `backend/app/auth_service.py` 部分 | — | 账户资料与头像 |
| `web/src/components/SettingsView.tsx` | 1514 | 设置页界面 |

## 入口与调用链

**路由全景**（routers/settings.py）：
- 模型：GET/PUT runtime-model；GET/PUT model-profiles/{id}；GET/PUT backup-model；
  POST model-profiles/test；（模型列表发现经 model_profiles → fetch_available_model_ids）
- 账户：GET/PUT account-profile；POST/DELETE account-profile/avatar
- 画像：GET/PUT user-profile（学习画像 prompt，注入生成）
- embedding：GET/PUT knowledge/embedding；POST knowledge/embedding/test

**跨域依赖**：读写依赖 model-client（配置消费方）、knowledge-rag（embedding）、
auth-account（账户资料）；本域自身无状态存储（全部落在 .env / model_profiles.json / auth 表）。

## 数据契约

- `backend/.env`：RUNTIME_MODEL_BASE_URL/API_KEY/MODEL + BACKUP_* 组（丢失全失效）
- `backend/data/model_profiles.json`：多模型画像档案（现状保留，不扩张）
- 账户资料：auth 侧表；头像为上传文件（POST avatar / DELETE 恢复默认）
- API 响应中密钥字段一律脱敏（已保存显示 `···`，2026-08-28 优化）

## 测试锚点

- 后端 settings 相关 pytest 用例（密钥脱敏行为有回归覆盖，见看板 2026-08-28 条目）
- 验证基线：后端全量 187 passed（2026-08-29）

## 设计异议

（无）
