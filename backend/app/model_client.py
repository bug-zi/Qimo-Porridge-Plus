"""模型调用层：OpenAI 兼容 HTTP 客户端、重试/熔断/主备 failover、用量统计。

从 study_service.py 抽取（阶段1-1）。设计约束：
- 本模块不 import study_service（避免循环依赖）；构造带用户画像/课程 Prompt
  的 messages 由调用方完成，_model_completion 只负责 HTTP 与重试语义。
- study_service 通过模块级 re-export 保持外部符号（含测试的
  patch.object(study_service, "_stream_model_turn")）不变。
- build_model_messages 留在 study_service（读用户画像），通过
  set_message_builder 注入到 _model_json。
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .model_usage import record_call_result, record_call_start

RUNTIME_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

MODEL_CONNECT_TIMEOUT_SECONDS = 20
# 首 token 超时：流式请求发出后等第一个字节的最长时间。思考型模型（glm-5.2 等）
# 出结果前有 5-8 分钟静默期，但那是“非流式整包等待”下的表现；改流式后上游会在
# 思考阶段就推送首个 chunk（或至少 keep-alive 字节），30s 无任何字节说明上游已
# 挂起/死机，立即判死重试或 failover，不再耗满整包超时。这是“区分思考与挂起”的关键。
MODEL_FIRST_TOKEN_TIMEOUT_SECONDS = 30
# 单次模型请求的整包上限（流式下=首字节之后的总读流时长上限）。
# 阶段1-2 流式改造后：首 30s 由 MODEL_FIRST_TOKEN_TIMEOUT_SECONDS 把关，
# 之后只要流持续有数据，读到这里为止。最慢正常请求（思考型模型完整一节课
# 讲义 JSON）实测约 8 分钟，取 1800s 为其约 4 倍裕量；真实挂起已被首 token
# 超时拦截，不会吃满这个值。
MODEL_REQUEST_TIMEOUT_SECONDS = 1800
MODEL_MAX_ATTEMPTS = 3
MODEL_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS = (20, 45)
# 连接级瞬时错误（SSL EOF、连接重置、读超时）的专用重试预算。
# 上游模型网关（如 token.aiedulab.cn）偶发掐断连接，单次重试往往即可恢复；
# 策略生成等 Agent 工作流需串行多次模型调用，更薄的预算会让整条链在坏窗口里全挂。
# 因此对这类“廉价的、可安全重试”的连接错误给更多次、带抖动的指数退避；
# HTTP 错误仍按 MODEL_MAX_ATTEMPTS 退避，行为不变。
MODEL_TRANSIENT_MAX_ATTEMPTS = 6
MODEL_TRANSIENT_BACKOFF_BASE_SECONDS = 2.0
MODEL_TRANSIENT_BACKOFF_CAP_SECONDS = 16.0

# ------------------------------------------------------------------
# 多模型档案与主备 failover
# ------------------------------------------------------------------
# 主模型与备用模型各自独立配置。主模型按“档案”保存（openai/deepseek/glm/custom…），
# 切换档案只是切换激活哪一份，不会覆盖其他档案已保存的 Base URL / API Key / 模型名。
# 备用模型单独一组变量；主模型整体失败（重试预算耗尽）后自动改投备用模型。
BACKUP_MODEL_ENV_KEYS = {
    "base_url": "EXAM_BOOSTER_BACKUP_MODEL_BASE_URL",
    "api_key": "EXAM_BOOSTER_BACKUP_MODEL_API_KEY",
    "model": "EXAM_BOOSTER_BACKUP_MODEL_NAME",
}
# 熔断：主模型连续 N 次调用（每次调用含其内部重试预算）失败后，冷却期内直接走备用，
# 避免每次调用都先耗尽主模型数分钟的退避重试；冷却到期自动先试回主模型。
PROVIDER_BREAKER_THRESHOLD = 3
PROVIDER_BREAKER_COOLDOWN_SECONDS = 1800
# 单个 provider 在一次调用内的总时间预算：一次完整请求超时（300s）加余量。
# 防止“静默挂起”的上游把 6 次内部重试 × 300s 全部吃满（约 30 分钟）才放弃，
# 让 failover 形同虚设。预算烧完立即切下一个 provider。正常慢请求（gpt-5.x
# 大 JSON 约 160s）不受影响。
MODEL_PROVIDER_BUDGET_SECONDS = MODEL_REQUEST_TIMEOUT_SECONDS + 60
_PROVIDER_BREAKER = {"consecutive_failures": 0, "open_until": 0.0}


# ------------------------------------------------------------------
# 模型调用用量统计（进程级累计，供前端生成进度展示）
# ------------------------------------------------------------------
from collections import deque as _deque

_MODEL_USAGE_LOCK = threading.Lock()
_MODEL_USAGE: dict[str, Any] = {
    "promptTokens": 0,
    "completionTokens": 0,
    "totalTokens": 0,
    "calls": 0,
    "failures": 0,
    "startedAt": "",
    "updatedAt": "",
    "currentCall": {"model": "", "startedAt": ""},
}
_MODEL_USAGE_RECENT: _deque = _deque(maxlen=30)


def _record_model_call_start(model_name: str) -> None:
    """记录一次模型调用的开始：思考型模型出结果前有数分钟静默期，
    前端靠这个字段展示“调用进行中已等待 Ns”，而不是毫无反馈。"""
    with _MODEL_USAGE_LOCK:
        _MODEL_USAGE["currentCall"] = {
            "model": model_name,
            "startedAt": datetime.now().isoformat(timespec="seconds"),
        }


def _record_model_usage(data: dict[str, Any], model_name: str, *, failed: bool = False) -> None:
    """从响应的 usage 字段累计 token 用量；失败调用只计数不累计 token。"""
    now = datetime.now().isoformat(timespec="seconds")
    with _MODEL_USAGE_LOCK:
        if not _MODEL_USAGE["startedAt"]:
            _MODEL_USAGE["startedAt"] = now
        _MODEL_USAGE["updatedAt"] = now
        _MODEL_USAGE["currentCall"] = {"model": "", "startedAt": ""}
        if failed:
            _MODEL_USAGE["failures"] += 1
            return
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        _MODEL_USAGE["promptTokens"] += prompt_tokens
        _MODEL_USAGE["completionTokens"] += completion_tokens
        _MODEL_USAGE["totalTokens"] += prompt_tokens + completion_tokens
        _MODEL_USAGE["calls"] += 1
        _MODEL_USAGE_RECENT.append(
            {
                "at": now,
                "model": model_name,
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
                "totalTokens": prompt_tokens + completion_tokens,
            }
        )


def get_model_usage() -> dict[str, Any]:
    """返回当前用量快照与最近若干次调用明细。"""
    with _MODEL_USAGE_LOCK:
        return {
            **{key: value for key, value in _MODEL_USAGE.items()},
            "recent": list(_MODEL_USAGE_RECENT),
        }


def _transient_retry_delay(attempt: int) -> float:
    """连接级瞬时错误的指数退避（含抖动），避免多请求同步重试压垮上游网关。"""
    delay = min(MODEL_TRANSIENT_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), MODEL_TRANSIENT_BACKOFF_CAP_SECONDS)
    return delay + random.uniform(0, delay * 0.25)


def _read_runtime_env() -> dict[str, str]:
    values = {
        "EXAM_BOOSTER_MODEL_BASE_URL": os.getenv("EXAM_BOOSTER_MODEL_BASE_URL", ""),
        "EXAM_BOOSTER_MODEL_API_KEY": os.getenv("EXAM_BOOSTER_MODEL_API_KEY", ""),
        "EXAM_BOOSTER_MODEL_NAME": os.getenv("EXAM_BOOSTER_MODEL_NAME", ""),
    }
    if not RUNTIME_ENV_PATH.exists():
        return values

    for line in RUNTIME_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in values and not values[key]:
            values[key] = value.strip().strip('"').strip("'")
    return values


# ------------------------------------------------------------------
# 备用模型配置（独立于主模型档案）
# ------------------------------------------------------------------


def _read_backup_model_env() -> dict[str, str]:
    values = {key: os.getenv(env_name, "") for key, env_name in BACKUP_MODEL_ENV_KEYS.items()}
    if not RUNTIME_ENV_PATH.exists():
        return values
    for line in RUNTIME_ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        for field, env_name in BACKUP_MODEL_ENV_KEYS.items():
            if key == env_name and not values[field]:
                values[field] = value.strip().strip('"').strip("'")
    return values


def get_backup_model_profile() -> dict[str, Any]:
    backup = _read_backup_model_env()
    return {
        "baseUrl": backup["base_url"].rstrip("/"),
        "model": backup["model"],
        "apiKey": backup["api_key"],
        "hasApiKey": bool(backup["api_key"].strip()),
        "connected": bool(backup["base_url"].strip() and backup["api_key"].strip() and backup["model"].strip()),
    }


def save_backup_model_profile(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    current = _read_backup_model_env()
    next_key = api_key.strip() or current["api_key"]
    _rewrite_env_lines(
        {
            BACKUP_MODEL_ENV_KEYS["base_url"]: base_url.strip().rstrip("/"),
            BACKUP_MODEL_ENV_KEYS["api_key"]: next_key,
            BACKUP_MODEL_ENV_KEYS["model"]: model.strip(),
        }
    )
    return get_backup_model_profile()


# ------------------------------------------------------------------
# 主备 failover：provider 列表 + 熔断
# ------------------------------------------------------------------


def _note_provider_result(role: str, succeeded: bool) -> None:
    if role != "primary":
        return
    if succeeded:
        _PROVIDER_BREAKER["consecutive_failures"] = 0
        _PROVIDER_BREAKER["open_until"] = 0.0
        return
    _PROVIDER_BREAKER["consecutive_failures"] += 1
    if _PROVIDER_BREAKER["consecutive_failures"] >= PROVIDER_BREAKER_THRESHOLD:
        _PROVIDER_BREAKER["open_until"] = time.monotonic() + PROVIDER_BREAKER_COOLDOWN_SECONDS


def _model_providers() -> list[dict[str, str]]:
    """返回按尝试顺序排列的 provider 列表；主模型熔断期间备用先行。"""
    primary = _read_runtime_env()
    backup = _read_backup_model_env()
    providers: list[dict[str, str]] = []
    if primary["EXAM_BOOSTER_MODEL_BASE_URL"] and primary["EXAM_BOOSTER_MODEL_API_KEY"] and primary["EXAM_BOOSTER_MODEL_NAME"]:
        providers.append(
            {
                "role": "primary",
                "base_url": primary["EXAM_BOOSTER_MODEL_BASE_URL"].rstrip("/"),
                "api_key": primary["EXAM_BOOSTER_MODEL_API_KEY"],
                "model": primary["EXAM_BOOSTER_MODEL_NAME"],
            }
        )
    if backup["base_url"] and backup["api_key"] and backup["model"]:
        same_as_primary = any(
            provider["base_url"] == backup["base_url"].rstrip("/")
            and provider["api_key"] == backup["api_key"]
            and provider["model"] == backup["model"]
            for provider in providers
        )
        # 主备配置完全相同时跳过备用：failover 到同一个端点只会把失败时间翻倍。
        if not same_as_primary:
            providers.append(
                {
                    "role": "backup",
                    "base_url": backup["base_url"].rstrip("/"),
                    "api_key": backup["api_key"],
                    "model": backup["model"],
                }
            )
    if (
        len(providers) == 2
        and providers[0]["role"] == "primary"
        and time.monotonic() < _PROVIDER_BREAKER["open_until"]
    ):
        providers.reverse()
    return providers


def _provider_request(provider: dict[str, str], payload: dict[str, Any], *, stream: bool = False) -> Request:
    body = {"model": provider["model"], **payload}
    if stream:
        body["stream"] = True
    return Request(
        f"{provider['base_url']}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "exam-booster-local-api/0.2.0",
        },
        method="POST",
    )


def parse_available_model_ids(payload: bytes) -> list[str]:
    data = json.loads(payload.decode("utf-8"))
    model_items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(model_items, list):
        return []

    seen: set[str] = set()
    model_ids: list[str] = []
    for item in model_items:
        if isinstance(item, dict):
            model_id = item.get("id")
        elif isinstance(item, str):
            model_id = item
        else:
            model_id = None
        if isinstance(model_id, str) and model_id and model_id not in seen:
            seen.add(model_id)
            model_ids.append(model_id)
    return model_ids


def fetch_available_model_ids(base_url: str, api_key: str) -> list[str]:
    request = Request(
        f"{base_url.strip().rstrip('/')}/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": "exam-booster-local-api/0.2.0",
        },
        method="GET",
    )
    with urlopen(request, timeout=MODEL_CONNECT_TIMEOUT_SECONDS) as response:
        return parse_available_model_ids(response.read())


def _non_retryable_http_reason(error: HTTPError) -> str:
    """读取 HTTP 错误体，识别不可通过等待恢复的错误（如账户无额度/套餐耗尽）。

    bigmodel 的配额类错误以 429 返回但 body 中带 code=1113（“当前无可用套餐资源，请充值”）。
    这类错误重试毫无意义——按限流退避只会让每个调用空转一分钟以上。
    返回非空字符串表示不可重试的原因；空字符串表示可按正常策略重试。
    """
    try:
        body = error.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    for marker in ("1113", "套餐资源", "请充值", "insufficient", "balance", "arrearage"):
        if marker.lower() in body.lower():
            return f"账户配额不足（{body[:160]}）"
    return ""


def probe_model_chat(base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """测试连接的真实探测：向 /chat/completions 发一条极小请求。

    仅凭 GET /models 列模型会误报“连接成功”——列表接口不消耗额度，
    账户无套餐/余额时照样 200。真实可用性必须发一次对话请求验证。
    """
    if not (base_url and api_key and model):
        return {"success": False, "message": "请先填写 Base URL、API Key 和模型名"}
    request = Request(
        f"{base_url.strip().rstrip('/')}/chat/completions",
        data=json.dumps(
            {
                "model": model.strip(),
                "messages": [{"role": "user", "content": "只回复两个字符：ok"}],
                "max_tokens": 32,
                "temperature": 0.1,
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "exam-booster-local-api/0.2.0",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        body = ""
        try:
            body = error.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        quota_reason = _non_retryable_http_reason(error)
        if quota_reason:
            return {"success": False, "message": f"模型不可用（HTTP {error.code}）：{quota_reason}。注意：智谱 Coding Plan 套餐请使用 https://open.bigmodel.cn/api/coding/paas/v4 端点"}
        return {"success": False, "message": f"模型不可用（HTTP {error.code}）：{body or '服务返回错误'}"}
    except (URLError, TimeoutError, OSError) as error:
        return {"success": False, "message": f"无法连接模型服务：{error}"}
    except ValueError:
        return {"success": False, "message": "模型服务返回内容无法解析，请确认接口兼容 OpenAI 格式"}
    choices = data.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content = str(message.get("content", "")).strip()
    # 推理模型的短探测可能把 token 花在思考上，content 为空也视为可用
    # （HTTP 200 已证明鉴权与额度通过）。
    return {"success": True, "message": f"模型 {model.strip()} 实测可用", "content": content[:40]}

def _read_sse_response(response, operation: str) -> dict[str, Any]:
    """读取流式 SSE 响应并重组为非流式结构（阶段1-2）。

    socket timeout 全程为 MODEL_FIRST_TOKEN_TIMEOUT_SECONDS（30s）：首字节前
    判死静默挂起；读流中它退化为"相邻 chunk 间隔上限"，一旦流持续到达即不断续命。
    tool_calls 按 index 组装回非流式契约（arguments 为完整 JSON 字符串），
    _model_agent_turn 等消费方无感知。流式响应通常不带 usage，缺失时按 0 计。
    """
    content_parts: list[str] = []
    tool_call_buffers: dict[int, dict[str, Any]] = {}
    usage: dict[str, Any] | None = None
    role = "assistant"
    for raw_line in response:
        if not raw_line:
            continue
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if not data_str:
            continue
        if data_str == "[DONE]":
            break
        try:
            chunk = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        if not isinstance(chunk, dict):
            continue
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        if isinstance(delta.get("role"), str):
            role = delta["role"]
        piece = delta.get("content")
        if isinstance(piece, str) and piece:
            content_parts.append(piece)
        for fragment in delta.get("tool_calls") or []:
            if not isinstance(fragment, dict):
                continue
            try:
                index_key = int(fragment.get("index", 0))
            except (TypeError, ValueError):
                index_key = len(tool_call_buffers)
            bucket = tool_call_buffers.setdefault(index_key, {"id": "", "name": "", "arguments": ""})
            fragment_id = fragment.get("id")
            if isinstance(fragment_id, str) and fragment_id:
                bucket["id"] = fragment_id
            function = fragment.get("function") or {}
            fname = function.get("name")
            if isinstance(fname, str) and fname:
                bucket["name"] = fname
            fargs = function.get("arguments")
            if isinstance(fargs, str):
                bucket["arguments"] += fargs
    content = "".join(content_parts)
    message: dict[str, Any] = {"role": role, "content": content}
    if tool_call_buffers:
        message["tool_calls"] = [
            {
                "id": tool_call_buffers[index]["id"],
                "type": "function",
                "function": {
                    "name": tool_call_buffers[index]["name"],
                    "arguments": tool_call_buffers[index]["arguments"] or "{}",
                },
            }
            for index in sorted(tool_call_buffers)
        ]
    if not content_parts and not tool_call_buffers:
        raise RuntimeError(f"{operation}流式响应无内容")
    result: dict[str, Any] = {
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "object": "chat.completion",
    }
    if usage is not None:
        result["usage"] = usage
    return result


def _request_model_json(request: Request, operation: str, *, deadline: float | None = None) -> dict[str, Any]:
    """发流式请求并重组为非流式结果（阶段1-2 改造）。

    对外契约与旧非流式版本完全一致（返回 OpenAI chat completion dict），
    内部改为 stream=True + SSE 重组，以获得首 token 超时能力：
    连接建立 timeout=MODEL_FIRST_TOKEN_TIMEOUT_SECONDS，30s 无首字节判死。
    注意：request 必须由 _provider_request(..., stream=True) 构建。
    """
    last_error: Exception | None = None
    http_attempts = 0
    for attempt in range(1, MODEL_TRANSIENT_MAX_ATTEMPTS + 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError(f"{operation}超出单 provider 时间预算，立即改投备用模型")
        retry_delay = 0.0
        try:
            try:
                body_model = str(json.loads(request.data.decode("utf-8")).get("model", ""))
            except Exception:
                body_model = ""
            _record_model_call_start(body_model)
            record_call_start(body_model)
            with urlopen(request, timeout=MODEL_FIRST_TOKEN_TIMEOUT_SECONDS) as response:
                data = _read_sse_response(response, operation)
            if not isinstance(data, dict):
                raise RuntimeError(f"{operation}返回格式无效")
            _record_model_usage(data if isinstance(data.get("usage"), dict) else {}, body_model)
            record_call_result(data, body_model)
            return data
        except HTTPError as error:
            last_error = error
            quota_reason = _non_retryable_http_reason(error)
            if quota_reason:
                raise RuntimeError(f"{operation}返回 HTTP {error.code}：{quota_reason}，请到模型服务商控制台充值或更换模型") from error
            http_attempts += 1
            if error.code not in MODEL_RETRYABLE_HTTP_CODES or http_attempts >= MODEL_MAX_ATTEMPTS:
                raise RuntimeError(f"{operation}连续 {http_attempts} 次返回 HTTP {error.code}") from error
            retry_delay = 2 ** (http_attempts - 1)
            if error.code == 429:
                retry_after = error.headers.get("Retry-After")
                retry_delay = (
                    int(retry_after)
                    if retry_after and retry_after.isdigit()
                    else MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS[min(http_attempts - 1, len(MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS) - 1)]
                )
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            # 首 token 超时（socket.timeout 是 OSError 子类）：上游静默挂起，
            # 不值得按瞬时错误退避 6 次——快速重试一次后让 provider 预算接管。
            if isinstance(error, TimeoutError) or "timed out" in str(error):
                if attempt >= 2:
                    raise RuntimeError(f"{operation}首字节超时（上游无响应）") from error
                retry_delay = _transient_retry_delay(attempt)
                time.sleep(retry_delay)
                continue
            # 连接级瞬时错误（SSL EOF/重置/超时）单独给更激进的重试预算，熬过网关坏窗口。
            if attempt >= MODEL_TRANSIENT_MAX_ATTEMPTS:
                raise RuntimeError(f"{operation}连接失败或响应超时") from error
            if deadline is not None and time.monotonic() >= deadline:
                raise RuntimeError(f"{operation}超出单 provider 时间预算，立即改投备用模型") from error
            retry_delay = _transient_retry_delay(attempt)
        except ValueError as error:
            raise RuntimeError(f"{operation}返回内容无法解析") from error
        time.sleep(retry_delay)
    raise RuntimeError(f"{operation}失败") from last_error


def _model_completion(
    messages: list[dict[str, Any]],
    *,
    json_mode: bool = False,
) -> str:
    providers = _model_providers()
    if not providers:
        raise RuntimeError("本机模型尚未配置")

    payload: dict[str, Any] = {
        "messages": messages,
        "temperature": 0.25,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    errors: list[str] = []
    for provider in providers:
        # 阶段1-2：内部改流式以获得首 token 超时；_read_sse_response 重组回非流式结构。
        request = _provider_request(provider, payload, stream=True)
        try:
            data = _request_model_json(
                request,
                f"模型服务({provider['role']})",
                deadline=time.monotonic() + MODEL_PROVIDER_BUDGET_SECONDS,
            )
        except RuntimeError as error:
            # 主模型（含其内部重试预算）整体失败 → 记录熔断计数并改投下一个 provider。
            _note_provider_result(provider["role"], False)
            _record_model_usage({}, provider["model"], failed=True)
            record_call_result({}, provider["model"], failed=True)
            errors.append(f"{provider['role']}({provider['model']}): {error}")
            continue
        _note_provider_result(provider["role"], True)
        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("模型服务没有返回可用内容")
        content = choices[0].get("message", {}).get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("模型服务返回内容为空")
        return content.strip()
    raise RuntimeError("主模型与备用模型均不可用：" + "；".join(errors))


_MESSAGE_BUILDER: Callable[..., list[dict[str, str]]] | None = None


def set_message_builder(builder: Callable[..., list[dict[str, str]]]) -> None:
    """study_service 启动时注入 build_model_messages（读用户画像，留在原地）。"""
    global _MESSAGE_BUILDER
    _MESSAGE_BUILDER = builder


def _model_json(task_prompt: str, user_content: str, course_prompt: str = "") -> dict[str, Any]:
    if _MESSAGE_BUILDER is None:
        raise RuntimeError("message builder 未注入：请先调用 set_message_builder")
    return _extract_json(
        _model_completion(
            _MESSAGE_BUILDER(task_prompt, user_content, course_prompt=course_prompt),
            json_mode=True,
        )
    )


def _model_agent_turn(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    providers = _model_providers()
    if not providers:
        raise RuntimeError("本机模型尚未配置")
    payload: dict[str, Any] = {
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    data: dict[str, Any] = {}
    errors: list[str] = []
    for provider in providers:
        # 阶段1-2：同 _model_completion，内部流式 + SSE 重组。
        request = _provider_request(provider, payload, stream=True)
        try:
            data = _request_model_json(
                request,
                f"模型工具调用({provider['role']})",
                deadline=time.monotonic() + MODEL_PROVIDER_BUDGET_SECONDS,
            )
        except RuntimeError as error:
            _note_provider_result(provider["role"], False)
            _record_model_usage({}, provider["model"], failed=True)
            record_call_result({}, provider["model"], failed=True)
            errors.append(f"{provider['role']}({provider['model']}): {error}")
            continue
        _note_provider_result(provider["role"], True)
        break
    if not data:
        raise RuntimeError("主模型与备用模型均不可用：" + "；".join(errors))
    choices = data.get("choices", [])
    if not choices or not isinstance(choices[0].get("message"), dict):
        raise RuntimeError("模型没有返回可用工具调用结果")
    message = choices[0]["message"]
    parsed_calls = []
    for call in message.get("tool_calls", []) or []:
        function = call.get("function", {}) if isinstance(call, dict) else {}
        raw_arguments = function.get("arguments", "{}")
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except json.JSONDecodeError:
            arguments = {}
        parsed_calls.append(
            {
                "id": str(call.get("id", "")),
                "name": str(function.get("name", "")),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    return {
        "content": str(message.get("content") or ""),
        "toolCalls": parsed_calls,
        "assistantMessage": message,
    }


def _open_model_stream(request: Request, operation: str, *, deadline: float | None = None):
    """建立到模型服务的流式连接。

    仅在“连接建立”阶段重试；连接级瞬时错误按 MODEL_TRANSIENT_MAX_ATTEMPTS 退避
    （更多次、带抖动），HTTP 错误仍按 MODEL_MAX_ATTEMPTS 退避。
    一旦 urlopen 成功返回 response，即进入“读流”阶段，不再重试——
    流中途断开交由调用方按 error 事件处理。
    """
    last_error: Exception | None = None
    http_attempts = 0
    for attempt in range(1, MODEL_TRANSIENT_MAX_ATTEMPTS + 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise RuntimeError(f"{operation}超出单 provider 时间预算，立即改投备用模型")
        retry_delay = 0.0
        try:
            # 首 token 超时：连接建立阶段 30s 无首字节判死（阶段1-2）。
            # 读流阶段的 timeout 由 _stream_model_turn 的迭代循环天然接管。
            return urlopen(request, timeout=MODEL_FIRST_TOKEN_TIMEOUT_SECONDS)
        except HTTPError as error:
            last_error = error
            http_attempts += 1
            quota_reason = _non_retryable_http_reason(error)
            if quota_reason:
                raise RuntimeError(f"{operation}返回 HTTP {error.code}：{quota_reason}，请到模型服务商控制台充值或更换模型") from error
            if error.code not in MODEL_RETRYABLE_HTTP_CODES or http_attempts >= MODEL_MAX_ATTEMPTS:
                raise RuntimeError(f"{operation}连续 {http_attempts} 次返回 HTTP {error.code}") from error
            retry_delay = 2 ** (http_attempts - 1)
            if error.code == 429:
                retry_after = error.headers.get("Retry-After")
                retry_delay = (
                    int(retry_after)
                    if retry_after and retry_after.isdigit()
                    else MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS[min(http_attempts - 1, len(MODEL_RATE_LIMIT_RETRY_DELAYS_SECONDS) - 1)]
                )
        except (URLError, TimeoutError, OSError) as error:
            last_error = error
            if attempt >= MODEL_TRANSIENT_MAX_ATTEMPTS:
                raise RuntimeError(f"{operation}连接失败或响应超时") from error
            retry_delay = _transient_retry_delay(attempt)
        time.sleep(retry_delay)
    raise RuntimeError(f"{operation}失败") from last_error


def _stream_model_turn(messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
    """流式调用模型工具回合。

    逐行解析 OpenAI 兼容 SSE：收到 delta.content 即 yield ("token", text)，
    同时按 index 累积 delta.tool_calls（name 只在首片出现，arguments 为增量字符串）。
    流结束后 yield ("turn", {content, toolCalls, assistantMessage})——结构同 _model_agent_turn。
    """
    providers = _model_providers()
    if not providers:
        raise RuntimeError("本机模型尚未配置")

    payload: dict[str, Any] = {
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.2,
    }
    response = None
    errors: list[str] = []
    for provider in providers:
        # failover 只发生在“连接建立”阶段；读流中途断开仍按原有语义交给调用方。
        request = _provider_request(provider, payload, stream=True)
        try:
            response = _open_model_stream(
                request,
                f"模型流式工具调用({provider['role']})",
                deadline=time.monotonic() + MODEL_PROVIDER_BUDGET_SECONDS,
            )
        except RuntimeError as error:
            _note_provider_result(provider["role"], False)
            errors.append(f"{provider['role']}({provider['model']}): {error}")
            continue
        _note_provider_result(provider["role"], True)
        break
    if response is None:
        raise RuntimeError("主模型与备用模型均不可用：" + "；".join(errors))
    content_parts: list[str] = []
    tool_call_buffers: dict[int, dict[str, Any]] = {}
    try:
        for raw_line in response:
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str or data_str == "[DONE]":
                if data_str == "[DONE]":
                    break
                continue
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if isinstance(piece, str) and piece:
                content_parts.append(piece)
                yield ("token", piece)
            for fragment in delta.get("tool_calls") or []:
                if not isinstance(fragment, dict):
                    continue
                index = fragment.get("index", 0)
                try:
                    index_key = int(index)
                except (TypeError, ValueError):
                    index_key = len(tool_call_buffers)
                bucket = tool_call_buffers.setdefault(
                    index_key, {"id": "", "name": "", "arguments": ""}
                )
                fragment_id = fragment.get("id")
                if isinstance(fragment_id, str) and fragment_id:
                    bucket["id"] = fragment_id
                function = fragment.get("function") or {}
                fname = function.get("name")
                if isinstance(fname, str) and fname:
                    bucket["name"] = fname
                fargs = function.get("arguments")
                if isinstance(fargs, str):
                    bucket["arguments"] += fargs
    finally:
        try:
            response.close()
        except Exception:
            pass

    content = "".join(content_parts).strip()
    parsed_calls: list[dict[str, Any]] = []
    for index in sorted(tool_call_buffers):
        bucket = tool_call_buffers[index]
        raw_arguments = bucket.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except json.JSONDecodeError:
            arguments = {}
        parsed_calls.append(
            {
                "id": str(bucket.get("id", "")),
                "name": str(bucket.get("name", "")),
                "arguments": arguments if isinstance(arguments, dict) else {},
            }
        )
    assistant_message: dict[str, Any] = {"role": "assistant", "content": content}
    if parsed_calls:
        assistant_message["tool_calls"] = [
            {
                "id": call["id"],
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                },
            }
            for call in parsed_calls
        ]
    yield (
        "turn",
        {
            "content": content,
            "toolCalls": parsed_calls,
            "assistantMessage": assistant_message,
        },
    )


def _extract_json(content: str) -> dict[str, Any]:
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL | re.IGNORECASE)
    raw = fenced.group(1) if fenced else content
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回 JSON 对象")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("模型 JSON 不是对象")
    return parsed
