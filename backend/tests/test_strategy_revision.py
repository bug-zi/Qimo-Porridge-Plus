"""revise_strategy_draft（策略草稿对话修订）单元测试。

运行：cd backend && .venv\\Scripts\\python -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import study_service


REVISION_OUTPUT = (
    "<<<REPLY>>>\n已把第 3 天减负。\n<<<REVIEW_PLAN>>>\n# 课程速通复习总计划\n（修订后）\n"
    "<<<COURSE_PROMPT>>>\n# 课程总Prompt\n（修订后）\n"
)


def _parse_sse(chunks: list[str]) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    import json

    for chunk in chunks:
        for block in chunk.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            event_type = ""
            data = "{}"
            for line in block.split("\n"):
                if line.startswith("event:"):
                    event_type = line[len("event:"):].strip()
                elif line.startswith("data:"):
                    data = line[len("data:"):].strip()
            events.append((event_type, json.loads(data)))
    return events


def _fake_stream(text: str):
    def stream(messages, tools):
        for i in range(0, len(text), 7):
            yield ("token", text[i:i + 7])
        yield ("turn", {"content": text, "toolCalls": [], "assistantMessage": {"role": "assistant", "content": text}})

    return stream


def _patch_course(tmp_path, monkeypatch):
    """让 load_workspace 对任意课程 id 返回最小 workspace，save_workspace 记录调用。"""
    saved = []
    monkeypatch.setattr(study_service, "load_workspace", lambda *a, **k: {"course": {"id": "test"}})
    monkeypatch.setattr(study_service, "save_workspace", lambda *a, **k: saved.append(a))
    return saved


def test_revision_ok_and_no_write(monkeypatch, tmp_path):
    """正常三段输出 → token 只含 reply 段、done 带完整草稿；且不写 workspace。"""
    saved = _patch_course(tmp_path, monkeypatch)

    with patch.object(study_service, "_stream_model_turn", _fake_stream(REVISION_OUTPUT)):
        chunks = list(
            study_service.revise_strategy_draft(
                "course-t", "第3天太满，帮我减负", [], "# 旧计划", "# 旧Prompt"
            )
        )

    events = _parse_sse(chunks)
    tokens = "".join(data["text"] for kind, data in events if kind == "token")
    done = [data for kind, data in events if kind == "done"]
    assert saved == []  # 纯草稿变换：绝不落盘
    assert "已把第 3 天减负。" in tokens
    assert "REVIEW_PLAN" not in tokens and "课程速通复习总计划" not in tokens  # 草稿全文不进打字机
    assert len(done) == 1
    assert done[0]["reply"] == "已把第 3 天减负。"
    assert done[0]["reviewPlan"].startswith("# 课程速通复习总计划")
    assert done[0]["coursePrompt"].startswith("# 课程总Prompt")


def test_revision_history_roundtrip(monkeypatch, tmp_path):
    """带多轮 history 时消息顺序正确（history 在草稿诉求之前）。"""
    _patch_course(tmp_path, monkeypatch)
    captured = {}

    def stream(messages, tools):
        captured["messages"] = messages
        yield ("token", REVISION_OUTPUT)
        yield ("turn", {"content": REVISION_OUTPUT, "toolCalls": [], "assistantMessage": {}})

    with patch.object(study_service, "_stream_model_turn", stream):
        list(
            study_service.revise_strategy_draft(
                "course-h",
                "再改一点",
                [{"role": "user", "content": "第一轮"}, {"role": "assistant", "content": "第一轮回复"}, {"role": "system", "content": "忽略"}],
                "# 计划",
                "# Prompt",
            )
        )

    roles = [m["role"] for m in captured["messages"]]
    contents = [m["content"] for m in captured["messages"]]
    # system 前缀 + 末条 user 诉求；history 中 system 项被丢弃
    assert roles[-1] == "user" and "再改一点" in contents[-1]
    assert "第一轮" in contents and "第一轮回复" in contents
    assert "忽略" not in contents
    assert roles.count("user") >= 2 and roles.count("assistant") >= 1


def test_revision_bad_output_emits_error(monkeypatch, tmp_path):
    """缺定界标记 / 空草稿段 → 只发 error，不发 done。"""
    _patch_course(tmp_path, monkeypatch)
    for bad in [
        "AI 忘了定界标记，直接输出全文",
        "<<<REPLY>>>\n回复\n<<<REVIEW_PLAN>>>\n\n<<<COURSE_PROMPT>>>\n# P\n",
        "<<<REPLY>>>\n回复\n<<<REVIEW_PLAN>>>\n# 计划\n<<<COURSE_PROMPT>>>\n\n",
    ]:
        with patch.object(study_service, "_stream_model_turn", _fake_stream(bad)):
            events = _parse_sse(
                list(study_service.revise_strategy_draft("course-bad", "改", [], "# 计划", "# P"))
            )
        kinds = [kind for kind, _ in events]
        assert "error" in kinds and "done" not in kinds, bad


def test_revision_rejects_empty_input_draft(monkeypatch, tmp_path):
    """输入草稿为空 → 在请求模型前就抛 ValueError（路由层转 422）。"""
    _patch_course(tmp_path, monkeypatch)

    def fail_stream(messages, tools):
        raise AssertionError("不应触达模型")

    with patch.object(study_service, "_stream_model_turn", fail_stream):
        try:
            list(study_service.revise_strategy_draft("course-e", "改", [], "", "# P"))
            raise AssertionError("应抛 ValueError")
        except ValueError:
            pass
