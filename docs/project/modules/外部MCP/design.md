# 外部MCP（external-mcp）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

外部资料源网关：MCP HTTP/stdio 双客户端、B 站等凭据管理、URL 提交 → 队列 → AI 整理 → 批准落库为课程资料。Agent 对话的 fetch_web_page 工具也走此网关类。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 启动播种 5 个预设（arXiv/Firecrawl/GitMCP/Bilibili/小红书）默认启用 | 开箱即用；但 get/save 强制 enabled=1，**无禁用端点**（现状限制，见异议） |
| stdio 命令白名单 {npx,node,bunx,uvx}，参数 ≤20 个且每个 ≤500 字符 | 防任意命令执行 |
| SSRF 防护：DNS 解析后拒 private/loopback/link-local/multicast/reserved | 防 URL 提交打内网 |
| 凭据写 backend/.env（MCP_ENV_INJECTIONS 白名单注入子进程） | 不落库、不回显 |
| AI 整理提示词含 prompt-injection 防御；批准落库文档头部声明"不可信资料" | 外部内容不可信 |

## 不变量

- external_sources 状态机：fetching → pending_review → approved/dismissed/failed
- external_source_import job 优先级 1（仅次于课程生成）；80k 字符截断后 AI 整理
- bili_jct 32 位 hex 校验、arXiv ID regex、GitMCP 仅 github.com、小红书必须 xsec_token

## 禁区

- 不得扩大 stdio 命令白名单；不得放开 SSRF 私网限制

## 设计异议

- **该域无任何测试覆盖**（backend/tests 零匹配）——待开发者裁决是否补测试
- 预设无法下线（无禁用端点）——如需下线能力需加端点
