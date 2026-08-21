from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..mcp_gateway import (
    clear_bilibili_credentials,
    discover_mcp_tools,
    get_bilibili_credential_status,
    list_mcp_servers,
    save_bilibili_credentials,
    save_mcp_server,
    verify_bilibili_credentials,
)

router = APIRouter()


class McpServerUpdateRequest(BaseModel):
    id: str = Field(default="", max_length=120)
    name: str = Field(min_length=1, max_length=120)
    transport: Literal["http", "stdio"] = "http"
    endpoint: str = Field(default="", max_length=1000)
    command: str = Field(default="", max_length=300)
    args: list[str] = Field(default_factory=list, max_length=20)
    allowed_tools: list[str] = Field(min_length=1, max_length=40)


class BilibiliCredentialsRequest(BaseModel):
    sessdata: str = Field(min_length=1, max_length=512)
    bili_jct: str = Field(min_length=1, max_length=64)
    dedeuserid: str = Field(min_length=1, max_length=32)


@router.get("/api/mcp/servers")
def mcp_servers() -> list[dict[str, Any]]:
    return list_mcp_servers()


@router.put("/api/mcp/servers")
def update_mcp_server(payload: McpServerUpdateRequest) -> dict[str, Any]:
    try:
        return save_mcp_server(
            payload.name,
            payload.endpoint,
            payload.allowed_tools,
            payload.id,
            transport=payload.transport,
            command=payload.command,
            args=payload.args,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/api/mcp/servers/{server_id}/discover")
def discover_mcp_server_tools(server_id: str) -> dict[str, Any]:
    try:
        return discover_mcp_tools(server_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (RuntimeError, OSError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.get("/api/mcp/bilibili/credentials")
def bilibili_credentials_status() -> dict[str, Any]:
    return get_bilibili_credential_status()


@router.get("/api/mcp/bilibili/credentials/verify")
def bilibili_credentials_verify() -> dict[str, Any]:
    try:
        return verify_bilibili_credentials()
    except (RuntimeError, OSError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@router.put("/api/mcp/bilibili/credentials")
def save_bilibili_credentials_endpoint(payload: BilibiliCredentialsRequest) -> dict[str, Any]:
    try:
        return save_bilibili_credentials(payload.sessdata, payload.bili_jct, payload.dedeuserid)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/api/mcp/bilibili/credentials")
def clear_bilibili_credentials_endpoint() -> dict[str, Any]:
    return clear_bilibili_credentials()
