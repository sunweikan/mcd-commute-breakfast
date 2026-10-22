"""极简 MCP (Model Context Protocol) Streamable HTTP 客户端。

仅使用 Python 标准库，实现与麦当劳 MCP Server (https://mcp.mcd.cn)
的 initialize 握手、tools/list 与 tools/call 调用。

协议要点：
- 所有请求都是 POST JSON-RPC 2.0
- Accept 头必须同时包含 application/json 与 text/event-stream
- 服务端可能返回纯 JSON，也可能返回 SSE（text/event-stream）
- initialize 响应头里会带 mcp-session-id，后续请求必须回传
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional


class MCPError(RuntimeError):
    """MCP 调用失败。"""


class MCPClient:
    """与远程 MCP Server 通信（Streamable HTTP 传输）。"""

    def __init__(self, url: str, token: str, timeout: int = 30) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._session_id: Optional[str] = None
        self._next_id = 0
        self._initialized = False

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------
    def connect(self) -> None:
        """完成 initialize 握手并发送 initialized 通知。"""
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcd-commute-breakfast", "version": "1.0.0"},
            },
        )
        if result is None:
            raise MCPError("initialize 未返回结果")
        self._initialized = True
        # initialized 通知（无 id，无响应体）
        self._rpc("notifications/initialized", None, is_notification=True)

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出服务端支持的全部工具。"""
        self._ensure_initialized()
        result = self._rpc("tools/list", {})
        return (result or {}).get("tools", [])

    def call_tool(self, name: str, arguments: Optional[dict] = None) -> Any:
        """调用一个 MCP 工具，返回结构化结果或文本内容。"""
        self._ensure_initialized()
        result = self._rpc(
            "tools/call", {"name": name, "arguments": arguments or {}}
        )
        if result is None:
            return None
        if result.get("isError"):
            texts = _extract_texts(result)
            raise MCPError(f"工具 {name} 返回错误: {texts or result}")
        # 优先返回 structuredContent，其次解析文本中的 JSON
        if "structuredContent" in result:
            return result["structuredContent"]
        texts = _extract_texts(result)
        for text in texts:
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                continue
        return texts[0] if texts else None

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _ensure_initialized(self) -> None:
        if not self._initialized:
            self.connect()

    def _rpc(
        self,
        method: str,
        params: Optional[dict],
        is_notification: bool = False,
    ) -> Optional[dict]:
        self._next_id += 1
        request_id = self._next_id
        payload: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not is_notification:
            payload["id"] = request_id

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self._session_id:
            headers["mcp-session-id"] = self._session_id

        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                session = resp.headers.get("mcp-session-id")
                if session:
                    self._session_id = session
                if is_notification or resp.status == 202:
                    return None
                content_type = resp.headers.get("Content-Type", "")
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise MCPError(
                    "MCP Token 无效或已过期 (401)，请到 https://open.mcd.cn/mcp 重新获取"
                ) from exc
            if exc.code == 429:
                raise MCPError("触发限流 (429，每分钟最多 600 次)，请稍后再试") from exc
            raise MCPError(f"HTTP {exc.code}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise MCPError(f"无法连接 MCP Server: {exc.reason}") from exc

        message = self._parse_body(content_type, body, request_id)
        if message is None:
            return None
        if "error" in message:
            err = message["error"]
            raise MCPError(f"JSON-RPC 错误 {err.get('code')}: {err.get('message')}")
        return message.get("result")

    @staticmethod
    def _parse_body(content_type: str, body: str, request_id: int) -> Optional[dict]:
        """兼容纯 JSON 与 SSE 两种响应格式。"""
        if "text/event-stream" in content_type:
            for line in body.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    message = json.loads(data)
                except ValueError:
                    continue
                if message.get("id") == request_id:
                    return message
            return None
        if not body.strip():
            return None
        try:
            return json.loads(body)
        except ValueError as exc:
            raise MCPError(f"无法解析响应: {body[:200]}") from exc


def _extract_texts(result: Dict[str, Any]) -> List[str]:
    """从 tools/call 结果中提取全部 text 内容块。"""
    texts: List[str] = []
    for block in result.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
    return texts
