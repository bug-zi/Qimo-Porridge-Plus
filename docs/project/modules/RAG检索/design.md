# RAG检索（knowledge-rag）｜design.md

> 状态：🌱 AI 起草稿（2026-09-24 从代码逆向起草，**待开发者审定**）
> 契约层；实现事实见同目录 `designs-specs.md`。

## 定位

课程知识库：资料分块入索引（FTS5 + 可选语义向量）、混合检索供给生成与对话链路、对话记忆与学习者弱点记忆、embedding 配置与本地 Ollama 自启动。

## 关键决策与理由

| 决策 | 理由 |
|---|---|
| 语义失败静默降级词法 + 30s 熔断 | embedding 服务不可用不阻塞主流程；`_EMBEDDING_UNAVAILABLE_UNTIL` 避免每次请求都撞死服务 |
| chunk_id 确定性（sha256(course\|path\|index\|hash)[:32]） | 重建索引幂等，重复同步不产生脏数据 |
| 双库分离（主库 + embedding_cache.db） | 向量数据与业务库解耦；跨库禁 JOIN，记忆向量分两步查 |
| RRF 混合排序（词法 FTS5 + 纯 Python 词法 + 语义） | 单一检索源不可靠；primary 角色资料加权（rank×1.35+0.01） |
| 本地 Ollama 自启动（默认 D:\AI\Ollama） | 单机本地方案，detached 进程 + 日志；/api/embed 404 降级 /api/embeddings 逐条 |

## 不变量

- 分块：900 字切分 / 1000 上限 / 120 重叠；删 chunk 同步清向量与缓存
- 向量矩阵进程内 TTL 300s 缓存；numpy 缺失回退逐条余弦
- 配置存 app_metadata key=`embedding_config`（默认 ollama/bge-m3）

## 禁区

- 主库与向量库之间不得建 JOIN（跨文件 DB）
- 不在检索链路里做同步 embedding 重试风暴（走熔断）

## 设计异议

- 占位文档记 1402 行，实际已 1541 行——行数漂移，以文件为准
