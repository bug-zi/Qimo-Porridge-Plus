"""模型调用层流式/超时/重试/failover 行为锁定（阶段1-4）。

用本地 HTTP 服务器模拟四种上游故障：
静默挂起（无首字节）、慢首字节、掐连接、429 限流。
运行：cd backend 然后 python -m pytest tests/test_model_client.py -q
"""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import model_client


class _FakeUpstream(BaseHTTPRequestHandler):
    """按 request body 里的 prompt 内容决定故障剧本。"""

    def log_message(self, *args):  # 静默
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        script = body["messages"][-1]["content"]

        if script == "hang":  # 静默挂起：收请求后永远不发任何字节
            time.sleep(60)
            return
        if script == "slow-first-token":  # 慢首字节：首字节超过 30s 阈值
            time.sleep(35)
            self._send_sse(["hello"])
            return
        if script == "normal-think":  # 正常思考型：静默数秒后开始流式输出
            time.sleep(2)
            self._send_sse(["思", "考", "完", "成"])
            return
        if script == "cut":  # 掐连接：发一半断开
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"par"}}]}\n\n')
            self.wfile.flush()
            self.wfile.close()
            self.connection.close()
            return
        if script == "flaky-then-ok":  # 第一次 429，第二次成功
            if not getattr(self.server, "served_429", False):
                self.server.served_429 = True
                self.send_response(429)
                self.send_header("Retry-After", "0")
                self.end_headers()
                self.wfile.write(b"{}")
                return
            self._send_sse(["recovered"])
            return
        # 默认：正常 SSE 流
        self._send_sse(["ok-", "stream"])

    def _send_sse(self, pieces: list[str]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for piece in pieces:
            chunk = {"choices": [{"delta": {"content": piece}}]}
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def _start_upstream() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeUpstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _configure(monkeypatch, base_url: str, *, with_backup: bool = False) -> None:
    monkeypatch.setattr(model_client, "_read_runtime_env", lambda: {
        "EXAM_BOOSTER_MODEL_BASE_URL": base_url,
        "EXAM_BOOSTER_MODEL_API_KEY": "test-key",
        "EXAM_BOOSTER_MODEL_NAME": "fake-model",
    })
    monkeypatch.setattr(model_client, "_read_backup_model_env", lambda: {
        "base_url": base_url + "/backup" if with_backup else "",
        "api_key": "backup-key" if with_backup else "",
        "model": "backup-model" if with_backup else "",
    })
    # 压缩重试等待，测试才跑得快
    monkeypatch.setattr(model_client, "MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS", (0, 0))
    monkeypatch.setattr(model_client, "_transient_retry_delay", lambda attempt: 0.01)
    model_client._PROVIDER_BREAKER.update({"consecutive_failures": 0, "open_until": 0.0})


def test_sse_reassembly_returns_nonstream_contract():
    """正常流式响应被重组回非流式结构：content 拼接、choices[0].message 完整。"""
    server = _start_upstream()
    try:
        request = model_client._provider_request(
            {"role": "primary", "base_url": f"http://127.0.0.1:{server.server_port}",
             "api_key": "k", "model": "m"},
            {"messages": [{"role": "user", "content": "normal"}], "temperature": 0.25},
            stream=True,
        )
        data = model_client._request_model_json(request, "测试")
        content = data["choices"][0]["message"]["content"]
        assert content == "ok-stream"
        assert data["object"] == "chat.completion"
    finally:
        server.shutdown()


def test_thinking_model_slow_start_still_succeeds():
    """正常思考型模型：静默 2s（<30s 阈值）后流式输出 → 成功，不被误杀。"""
    server = _start_upstream()
    try:
        request = model_client._provider_request(
            {"role": "primary", "base_url": f"http://127.0.0.1:{server.server_port}",
             "api_key": "k", "model": "m"},
            {"messages": [{"role": "user", "content": "normal-think"}], "temperature": 0.25},
            stream=True,
        )
        data = model_client._request_model_json(request, "测试")
        assert data["choices"][0]["message"]["content"] == "思考完成"
    finally:
        server.shutdown()


def test_silent_hang_fails_fast_within_first_token_budget():
    """静默挂起：30s 无首字节判死，不重试 6 次——总耗时 ≈2×30s 内抛 RuntimeError。"""
    server = _start_upstream()
    try:
        request = model_client._provider_request(
            {"role": "primary", "base_url": f"http://127.0.0.1:{server.server_port}",
             "api_key": "k", "model": "m"},
            {"messages": [{"role": "user", "content": "hang"}], "temperature": 0.25},
            stream=True,
        )
        start = time.monotonic()
        try:
            model_client._request_model_json(request, "测试")
            raise AssertionError("静默挂起应当失败")
        except RuntimeError as error:
            assert "首字节超时" in str(error) or "响应超时" in str(error), str(error)
        elapsed = time.monotonic() - start
        assert elapsed < 70, f"静默挂起应在首token超时预算内失败，实际 {elapsed:.0f}s"
    finally:
        server.shutdown()


def test_rate_limit_429_recovers_on_retry():
    """429 后按 Retry-After 退避重试成功。"""
    server = _start_upstream()
    try:
        request = model_client._provider_request(
            {"role": "primary", "base_url": f"http://127.0.0.1:{server.server_port}",
             "api_key": "k", "model": "m"},
            {"messages": [{"role": "user", "content": "flaky-then-ok"}], "temperature": 0.25},
            stream=True,
        )
        data = model_client._request_model_json(request, "测试")
        assert data["choices"][0]["message"]["content"] == "recovered"
    finally:
        server.shutdown()


def test_primary_failure_fails_over_to_backup(monkeypatch):
    """主模型整体失败 → 记熔断计数 → 改投备用成功。"""
    server = _start_upstream()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        # 主模型指向不存在的端口（连接立即失败），备用指向 fake 上游。
        monkeypatch.setattr(model_client, "_read_runtime_env", lambda: {
            "EXAM_BOOSTER_MODEL_BASE_URL": "http://127.0.0.1:1",
            "EXAM_BOOSTER_MODEL_API_KEY": "test-key",
            "EXAM_BOOSTER_MODEL_NAME": "dead-model",
        })
        monkeypatch.setattr(model_client, "_read_backup_model_env", lambda: {
            "base_url": base, "api_key": "backup-key", "model": "backup-model",
        })
        monkeypatch.setattr(model_client, "MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS", (0, 0))
        monkeypatch.setattr(model_client, "_transient_retry_delay", lambda attempt: 0.01)
        model_client._PROVIDER_BREAKER.update({"consecutive_failures": 0, "open_until": 0.0})

        content = model_client._model_completion(
            [{"role": "user", "content": "normal"}]
        )
        assert content == "ok-stream"
        assert model_client._PROVIDER_BREAKER["consecutive_failures"] == 1
    finally:
        server.shutdown()
        model_client._PROVIDER_BREAKER.update({"consecutive_failures": 0, "open_until": 0.0})


def test_breaker_opens_after_threshold_and_prefers_backup(monkeypatch):
    """主模型连续失败达阈值 → 熔断打开 → provider 列表备用先行。"""
    monkeypatch.setattr(model_client, "_read_runtime_env", lambda: {
        "EXAM_BOOSTER_MODEL_BASE_URL": "http://primary",
        "EXAM_BOOSTER_MODEL_API_KEY": "k",
        "EXAM_BOOSTER_MODEL_NAME": "m",
    })
    monkeypatch.setattr(model_client, "_read_backup_model_env", lambda: {
        "base_url": "http://backup", "api_key": "k", "model": "m2",
    })
    model_client._PROVIDER_BREAKER.update({"consecutive_failures": 0, "open_until": 0.0})
    try:
        for _ in range(model_client.PROVIDER_BREAKER_THRESHOLD):
            model_client._note_provider_result("primary", False)
        providers = model_client._model_providers()
        assert providers[0]["role"] == "backup"
        # 备用成功不重置主模型熔断；主模型成功才重置
        model_client._note_provider_result("backup", True)
        assert model_client._model_providers()[0]["role"] == "backup"
    finally:
        model_client._PROVIDER_BREAKER.update({"consecutive_failures": 0, "open_until": 0.0})


def test_cut_connection_midstream_raises(monkeypatch):
    """流中途被掐：content 不完整也按已收内容返回（不抛错），由上层校验质量。"""
    server = _start_upstream()
    try:
        _configure(monkeypatch, f"http://127.0.0.1:{server.server_port}")
        request = model_client._provider_request(
            {"role": "primary", "base_url": f"http://127.0.0.1:{server.server_port}",
             "api_key": "k", "model": "m"},
            {"messages": [{"role": "user", "content": "cut"}], "temperature": 0.25},
            stream=True,
        )
        # 掐连接发生在读到首个 chunk 后：SSE 循环自然结束（readline 抛错或 EOF），
        # _read_sse_response 已收到 "par" → 返回部分内容；这是既有语义（不丢已生成内容）。
        try:
            data = model_client._request_model_json(request, "测试")
            assert data["choices"][0]["message"]["content"] == "par"
        except (RuntimeError, OSError):
            pass  # 若以连接错误形式抛出也符合预期（掐断时机不同）
    finally:
        server.shutdown()
