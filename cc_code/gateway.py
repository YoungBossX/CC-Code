"""Minimal HTTP gateway for CC-Coder.

The gateway intentionally uses only the standard library so the Docker and
console entry points remain zero-dependency. It exposes a health endpoint and a
small headless execution endpoint for platform bridges to build on.
"""

from __future__ import annotations

import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# /run 请求体上限，防止超大 body 耗尽内存
MAX_BODY_BYTES = 1_048_576  # 1 MiB


def _json_bytes(payload: dict[str, Any], status: int = 200) -> tuple[int, bytes]:
    return status, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _expected_token() -> str:
    """读取网关共享密钥；未配置返回空串（表示禁用 /run）。"""
    return os.environ.get("CC_CODE_GATEWAY_TOKEN", "").strip()


class CcCoderGatewayHandler(BaseHTTPRequestHandler):
    server_version = "CC-CoderGateway/0.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        if os.environ.get("CC_CODE_GATEWAY_ACCESS_LOG") == "1":
            super().log_message(format, *args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        status_code, body = _json_bytes(payload, status)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        """校验 Authorization: Bearer <token> 是否匹配共享密钥。"""
        expected = _expected_token()
        if not expected:
            return False
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        presented = header[len(prefix):].strip()
        return hmac.compare_digest(presented, expected)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/health"}:
            self._send_json({"ok": True, "service": "cc-coder-gateway"})
            return
        self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/run":
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return

        if not _expected_token():
            self._send_json(
                {"ok": False, "error": "gateway auth not configured: set CC_CODE_GATEWAY_TOKEN"},
                status=503,
            )
            return

        if not self._authorized():
            self._send_json({"ok": False, "error": "unauthorized"}, status=401)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json({"ok": False, "error": "invalid Content-Length"}, status=400)
            return
        if length > MAX_BODY_BYTES:
            self._send_json(
                {"ok": False, "error": f"request body too large (>{MAX_BODY_BYTES} bytes)"},
                status=413,
            )
            return

        try:
            raw = self.rfile.read(length).decode("utf-8")
            data = json.loads(raw) if raw.strip() else {}
            prompt = str(data.get("prompt", "")).strip()
            if not prompt:
                self._send_json({"ok": False, "error": "prompt is required"}, status=400)
                return

            from cc_code.headless import run_headless

            self._send_json({"ok": True, "response": run_headless(prompt)})
        except (Exception, SystemExit) as exc:  # noqa: BLE001
            if isinstance(exc, SystemExit):
                message = str(exc) or f"headless exited with status {exc.code}"
                print(f"CC-Coder gateway headless exit: {message}", file=sys.stderr)
                self._send_json({"ok": False, "error": message}, status=500)
                return
            self._send_json({"ok": False, "error": str(exc)}, status=500)


def run_gateway() -> None:
    host = os.environ.get("CC_CODE_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("CC_CODE_GATEWAY_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), CcCoderGatewayHandler)
    print(f"CC-Coder gateway listening on http://{host}:{port}", flush=True)
    if not _expected_token():
        print(
            "WARNING: CC_CODE_GATEWAY_TOKEN not set — /run is disabled (returns 503). "
            "Set it to enable authenticated execution.",
            file=sys.stderr,
            flush=True,
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_gateway()
