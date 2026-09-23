# 设置（settings）域设计

> 状态：🌱 AI 逆向起草，待用户审定 ｜ 起草日期 2026-08-29（学习/冻结期）

## 定位

用户对"系统本身"的配置面：主/备模型配置与连通性测试、模型画像、账户资料与头像、
用户学习画像、embedding 配置。是 model-client / knowledge-rag 等核心域的配置入口。

## 关键决策

1. **密钥只存本机**：模型 base_url/api_key 存 `backend/.env`（RUNTIME_* / BACKUP_*），
   不进数据库不进 workspace。*理由*：单用户本地版的数据边界；丢失=密钥+JWT 全失效（CLAUDE.md）。
2. **已保存密钥隐藏显示**（2026-08-28）：设置页已保存密钥显示 `···`，留空提交=继续沿用
   旧值，避免回显泄露与误清空。
3. **连通性测试走真实链路**：test 按钮调 `probe_model_chat`（model_client 内），测的是
   与生成时完全相同的请求路径——不用假的 ping 冒充测试。
4. **模型可发现**：`fetch_available_model_ids` 拉取上游模型列表供下拉选择。
5. **账户与画像分层**：account-profile（昵称/头像，auth 侧）与 user-profile（学习画像
   prompt，参与生成）是两回事，端点分离。
6. **embedding 配置独立**：RAG 的 embedding 服务地址/模型单独配置并带 test（服务于
   knowledge-rag 域，本地 Ollama 或远程均可）。

## 不变量

- .env 写入只经 model_profiles / model_client 的封装函数，密钥永不出现在 API 响应体。
- 模型配置变更后，现有生成任务不受影响（新配置下次调用生效）。

## 禁区

- 不做多套密钥档案管理（个人本地版，一组主备足够；model_profiles.json 的多 profile
  能力保留现状不扩张）。

## 设计异议

（无）
