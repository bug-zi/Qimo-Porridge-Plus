# 外部MCP（external-mcp）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/mcp_gateway.py | 772 | MCP HTTP/stdio 双客户端、注册与预设、URL→工具参数映射、B 站凭据 |
| backend/app/external_source_service.py | 153 | 导入编排：提交→队列→AI 整理→批准落库 |
| backend/app/routers/mcp.py | 92 | 服务管理 + B 站凭据端点 |
| backend/app/routers/external_sources.py | ~85 | 导入生命周期端点 |
| backend/app/agent_runtime.py | — | mcp_servers/external_sources 表定义与 agent_jobs 队列 |

## 调用链

POST external-sources → `submit_external_source`(:26) → `validate_public_source_url`(mcp_gateway:136) → `create_external_source` + `enqueue_agent_job("external_source_import")` → `process_external_source_job`(:51)：`build_source_tool_arguments`(:616) → `call_mcp_tool`(:523，allowedTools 白名单) → `extract_mcp_text`(:672) → `_model_json` 整理（80k 截断）→ pending_review + save_artifact；批准 `approve_external_source`(:129) → 包装 md 经 `upload_course_material` 落为课程资料。

## 数据契约

- mcp_servers 表（endpoint/transport/command/args_json/tools_json/enabled/allowed_tools_json）；external_sources 表（status 状态机）
- 凭据在 backend/.env：BILIBILI_SESSDATA/BILI_JCT/DEDEUSERID、FIRECRAWL_API_KEY、XHS_COOKIE（MCP_ENV_INJECTIONS 白名单注入，不落库不回显）
- 端点：GET/PUT /api/mcp/servers、POST /api/mcp/servers/{id}/discover、GET/PUT/DELETE /api/mcp/bilibili/credentials(+verify)、POST/GET /api/courses/{id}/external-sources(+approve/dismiss)

## 测试锚点

**无**（backend/tests 中零匹配——已知缺口，见 design.md 异议节）。

## 上游调用方 / 下游消费方

- 依赖：后台队列（job）、规划域的 `_model_json`；落库后进入资料解析→RAG检索链
- agents/tools.py:733-744 fetch_web_page 工具直接用 McpStdioClient("npx",["-y","fetch-mcp"])；归档域覆盖 external_sources 清理

## 导读

读序：external_source_service.py（生命周期短小先读）→ mcp_gateway.py 的 call_mcp_tool 与 URL 映射。调凭据问题查 .env 与 /verify 端点。
