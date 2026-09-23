# RAG检索（knowledge-rag）｜designs-specs.md

> AI 生成并维护（2026-09-24）；与代码冲突时以代码为准并更新本文件。

## 文件清单

| 文件 | 行数 | 职责 |
|---|---|---|
| backend/app/knowledge_service.py | 1541 | 分块/双库存储/混合检索/对话记忆/学习者记忆/embedding 配置与 Ollama 自启动 |

## 调用链

- 索引：`materials.sync_course_knowledge`(materials.py:195) → `sync_material_documents`(:548) → `_chunk_document`(:508) → material_chunks + FTS5；删除同步清 chunk_embeddings 并失效向量缓存
- 重建：routers/courses.py:633 → `rebuild_course_embeddings`(:706) → `_request_embeddings`(:377，/api/embed 404 降级 /api/embeddings) → 批量 16 写向量库
- 检索：`retrieve_material_context`(:987) = `_keyword_candidates`(FTS5 bm25) + `_lexical_candidates`(纯 Python) RRF 合并 → 语义 `_score_semantic_vectors`（numpy L2 归一矩阵点积，TTL 300s 缓存）top30 再 RRF → primary 角色加权
- 记忆：agent_chat 四处调用 `build_conversation_memory`(:1225，近 8 条+滚动摘要+相关史)；`record_learning_event`(:1297，答错自动写 weak_point 置信 0.85) → `learner_memory_context`(:1404)
- Ollama 自启动：`_start_local_ollama_service`(:308)

## 数据契约

- 主库 exam_booster.db：knowledge_materials、material_chunks(+FTS5)、chat_turns、learning_events、learner_memories、memory_evidence、chat_summaries、app_metadata
- 向量库 embedding_cache.db：chunk_embeddings / memory_embeddings（PK id+model）
- API：GET/PUT /api/knowledge/embedding、POST /api/knowledge/embedding/test（settings.py）；GET …/knowledge/status、POST …/knowledge/reindex、GET …/search（courses.py）

## 测试锚点

test_embedding_pdf_regressions.py（按课程隔离）、test_workflow_modularization / test_lesson_question_draft / test_mock_questions_repair / test_mainline_generation_repair / test_checkpoint_contracts（均 stub retrieve_material_context）、test_facade_exports

## 上游调用方 / 下游消费方

- 上游：资料解析（抽出文本后入库）、设置域（embedding 配置端点）
- 下游注入点：study_service:986-992（生成证据 limit=20）、lesson_generation:119、question_generation:353、模拟卷 limit=12、agents/tools.py:726-732（search_materials 工具）、strategy_workflow:116、glossary:303（15000 字均匀采样）、AI伴学（对话记忆）

## 导读

读序：retrieve_material_context（检索主口径）→ sync_material_documents（索引）→ build_conversation_memory/learner_memory_context（记忆）。调 embedding 问题先看 app_metadata 的 embedding_config 与 Ollama 进程/熔断状态。
