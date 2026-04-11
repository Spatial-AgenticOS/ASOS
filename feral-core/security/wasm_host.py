"""
FERAL WASM Host Functions — The ABI bridge between sandbox and FERAL
========================================================================
These are the ONLY functions WASM skills can call.  All access is audited.
The host functions translate between WASM linear memory and Python objects.
"""

from __future__ import annotations
import json
import logging
from typing import Optional

logger = logging.getLogger("feral.wasm_host")


class WASMHostFunctions:
    """
    Defines the host function ABI available to WASM skills.
    Functions read/write to WASM linear memory via pointer+length pairs.
    """

    def __init__(self, policy: dict = None, http_client=None):
        self._policy = policy or {}
        self._http_client = http_client
        self._params: dict[str, str] = {}
        self._result: str = ""
        self._logs: list[str] = []
        self._allowed_domains = self._policy.get("allowed_domains", [])
        self._allowed_functions = set(self._policy.get("allowed_host_functions", []))

    def set_params(self, params: dict):
        """Set the tool call arguments before execution."""
        self._params = {k: json.dumps(v) if not isinstance(v, str) else v for k, v in params.items()}

    def get_result(self) -> str:
        return self._result

    def get_logs(self) -> list[str]:
        return list(self._logs)

    def reset(self):
        self._result = ""
        self._logs.clear()
        self._params.clear()

    def _check_allowed(self, func_name: str) -> bool:
        if not self._allowed_functions:
            return True
        return func_name in self._allowed_functions

    def _check_domain(self, url: str) -> bool:
        if not self._allowed_domains:
            return True
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return any(
            hostname == d or hostname.endswith(f".{d}") or d.startswith("*.")
            and hostname.endswith(d[1:])
            for d in self._allowed_domains
        )

    # --- Host Functions ---

    def feral_log(self, memory: bytearray, msg_ptr: int, msg_len: int):
        """Log a message from the WASM skill."""
        if not self._check_allowed("feral_log"):
            return
        msg = memory[msg_ptr:msg_ptr + msg_len].decode("utf-8", errors="replace")
        self._logs.append(msg)
        logger.info(f"[WASM] {msg[:200]}")

    def feral_get_param(self, memory: bytearray, name_ptr: int, name_len: int) -> tuple[int, int]:
        """Read a tool call parameter. Returns (ptr, len) in WASM memory."""
        if not self._check_allowed("feral_get_param"):
            return (0, 0)
        name = memory[name_ptr:name_ptr + name_len].decode("utf-8", errors="replace")
        value = self._params.get(name, "")
        value_bytes = value.encode("utf-8")
        # Write to a known offset in WASM memory (simple allocator)
        offset = 65536  # Use a high offset to avoid collision
        memory[offset:offset + len(value_bytes)] = value_bytes
        return (offset, len(value_bytes))

    def feral_set_result(self, memory: bytearray, data_ptr: int, data_len: int):
        """Set the return value of the WASM skill execution."""
        if not self._check_allowed("feral_set_result"):
            return
        self._result = memory[data_ptr:data_ptr + data_len].decode("utf-8", errors="replace")

    def feral_http_get(self, memory: bytearray, url_ptr: int, url_len: int) -> tuple[int, int]:
        """Make an HTTP GET request (gated by policy network rules)."""
        if not self._check_allowed("feral_http_get"):
            return (0, 0)
        url = memory[url_ptr:url_ptr + url_len].decode("utf-8", errors="replace")
        if not self._check_domain(url):
            logger.warning(f"[WASM] HTTP GET blocked by domain policy: {url}")
            error = json.dumps({"error": "Domain not allowed"}).encode("utf-8")
            offset = 65536
            memory[offset:offset + len(error)] = error
            return (offset, len(error))

        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read(8192)
                offset = 65536
                memory[offset:offset + len(body)] = body
                return (offset, len(body))
        except Exception as e:
            error = json.dumps({"error": str(e)}).encode("utf-8")
            offset = 65536
            memory[offset:offset + len(error)] = error
            return (offset, len(error))

    def feral_http_post(
        self, memory: bytearray,
        url_ptr: int, url_len: int,
        body_ptr: int, body_len: int,
    ) -> tuple[int, int]:
        """Make an HTTP POST request (gated by policy network rules)."""
        if not self._check_allowed("feral_http_post"):
            return (0, 0)
        url = memory[url_ptr:url_ptr + url_len].decode("utf-8", errors="replace")
        body = memory[body_ptr:body_ptr + body_len]

        if not self._check_domain(url):
            logger.warning(f"[WASM] HTTP POST blocked by domain policy: {url}")
            error = json.dumps({"error": "Domain not allowed"}).encode("utf-8")
            offset = 65536
            memory[offset:offset + len(error)] = error
            return (offset, len(error))

        try:
            import urllib.request
            req = urllib.request.Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp_body = resp.read(8192)
                offset = 65536
                memory[offset:offset + len(resp_body)] = resp_body
                return (offset, len(resp_body))
        except Exception as e:
            error = json.dumps({"error": str(e)}).encode("utf-8")
            offset = 65536
            memory[offset:offset + len(error)] = error
            return (offset, len(error))
