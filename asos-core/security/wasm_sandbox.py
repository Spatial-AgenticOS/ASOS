"""
THEORA WASM Sandbox — Secure execution of untrusted skill code
================================================================
Uses wasmtime-py to run WASM modules with:
  - Memory limits (default 64MB)
  - CPU limits via execution fuel / timeout
  - No network/filesystem by default
  - THEORA API exposed through host functions only

Skills compiled from Rust/Go/C/AssemblyScript → .wasm
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from security.wasm_host import WASMHostFunctions

logger = logging.getLogger("theora.wasm_sandbox")


class WASMSandbox:
    """
    Execute WASM modules in a sandboxed environment.
    Each execution gets fresh memory and limited fuel.
    """

    def __init__(self, policy: dict = None):
        self._policy = policy or {}
        self._memory_limit_mb = self._policy.get("memory_limit_mb", 64)
        self._timeout_seconds = self._policy.get("timeout_seconds", 5)
        self._fuel_limit = self._policy.get("fuel_limit", 1_000_000)
        self._wasmtime_available = False
        self._host = WASMHostFunctions(policy=self._policy)

        try:
            import wasmtime
            self._wasmtime_available = True
            logger.info(f"WASM sandbox ready (wasmtime) — memory={self._memory_limit_mb}MB, timeout={self._timeout_seconds}s")
        except ImportError:
            logger.info("wasmtime-py not installed — WASM sandbox disabled. Install with: pip install wasmtime")

    @property
    def available(self) -> bool:
        return self._wasmtime_available

    async def execute(
        self,
        wasm_path: str,
        params: dict = None,
        entry_point: str = "execute",
    ) -> dict:
        """
        Execute a WASM module and return the result.

        Args:
            wasm_path: Path to the .wasm file
            params: Tool call arguments to pass via host functions
            entry_point: Name of the exported function to call

        Returns:
            {"success": bool, "data": any, "logs": [...], "execution_ms": float}
        """
        if not self._wasmtime_available:
            return {"success": False, "error": "wasmtime not available", "data": None, "logs": []}

        params = params or {}
        self._host.reset()
        self._host.set_params(params)

        start = time.time()

        try:
            await asyncio.wait_for(
                self._run_wasm(wasm_path, entry_point),
                timeout=self._timeout_seconds,
            )
            elapsed_ms = (time.time() - start) * 1000

            raw_result = self._host.get_result()
            logs = self._host.get_logs()

            try:
                data = json.loads(raw_result) if raw_result else None
            except json.JSONDecodeError:
                data = raw_result

            return {
                "success": True,
                "data": data,
                "logs": logs,
                "execution_ms": elapsed_ms,
            }

        except asyncio.TimeoutError:
            elapsed_ms = (time.time() - start) * 1000
            logger.warning(f"WASM execution timed out after {elapsed_ms:.0f}ms: {wasm_path}")
            return {
                "success": False,
                "error": f"Execution timed out after {self._timeout_seconds}s",
                "data": None,
                "logs": self._host.get_logs(),
                "execution_ms": elapsed_ms,
            }
        except Exception as e:
            elapsed_ms = (time.time() - start) * 1000
            logger.error(f"WASM execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "data": None,
                "logs": self._host.get_logs(),
                "execution_ms": elapsed_ms,
            }

    async def _run_wasm(self, wasm_path: str, entry_point: str):
        """Run the WASM module in a thread to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run_wasm_sync, wasm_path, entry_point)

    def _run_wasm_sync(self, wasm_path: str, entry_point: str):
        """Synchronous WASM execution via wasmtime."""
        import wasmtime

        config = wasmtime.Config()
        config.consume_fuel = True

        engine = wasmtime.Engine(config)

        # Memory limits
        store = wasmtime.Store(engine)
        store.set_fuel(self._fuel_limit)

        # Load module
        wasm_file = Path(wasm_path)
        if not wasm_file.exists():
            raise FileNotFoundError(f"WASM file not found: {wasm_path}")

        module = wasmtime.Module.from_file(engine, str(wasm_file))

        # Create linker with host functions
        linker = wasmtime.Linker(engine)
        self._register_host_functions(linker, store)

        # Instantiate
        instance = linker.instantiate(store, module)

        # Get the entry point
        func = instance.exports(store).get(entry_point)
        if func is None:
            # Try _start or main as fallbacks
            for alt in ["_start", "main", "run"]:
                func = instance.exports(store).get(alt)
                if func:
                    break

        if func is None:
            raise RuntimeError(f"Entry point '{entry_point}' not found in WASM module")

        # Execute
        result = func(store)
        return result

    def _register_host_functions(self, linker, store):
        """Register THEORA host functions in the WASM linker."""
        import wasmtime

        # Get memory from the WASM instance (will be set after instantiation)
        # For now, create a shared memory
        memory_type = wasmtime.MemoryType(
            wasmtime.Limits(min=1, max=self._memory_limit_mb * 16),  # 16 pages per MB
        )

        host_memory = wasmtime.Memory(store, memory_type)
        host = self._host

        def log_fn(caller, msg_ptr: int, msg_len: int):
            mem = host_memory.data_ptr(caller)
            mem_bytes = bytearray((wasmtime.ffi.c_ubyte * host_memory.data_len(caller)).from_address(mem))
            host.theora_log(mem_bytes, msg_ptr, msg_len)

        def get_param_fn(caller, name_ptr: int, name_len: int) -> int:
            mem = host_memory.data_ptr(caller)
            mem_bytes = bytearray((wasmtime.ffi.c_ubyte * host_memory.data_len(caller)).from_address(mem))
            ptr, length = host.theora_get_param(mem_bytes, name_ptr, name_len)
            return ptr

        def set_result_fn(caller, data_ptr: int, data_len: int):
            mem = host_memory.data_ptr(caller)
            mem_bytes = bytearray((wasmtime.ffi.c_ubyte * host_memory.data_len(caller)).from_address(mem))
            host.theora_set_result(mem_bytes, data_ptr, data_len)

        try:
            # Register host functions under "theora" namespace
            log_type = wasmtime.FuncType([wasmtime.ValType.i32(), wasmtime.ValType.i32()], [])
            linker.define(store, "theora", "log", wasmtime.Func(store, log_type, log_fn))

            get_param_type = wasmtime.FuncType(
                [wasmtime.ValType.i32(), wasmtime.ValType.i32()],
                [wasmtime.ValType.i32()],
            )
            linker.define(store, "theora", "get_param", wasmtime.Func(store, get_param_type, get_param_fn))

            set_result_type = wasmtime.FuncType([wasmtime.ValType.i32(), wasmtime.ValType.i32()], [])
            linker.define(store, "theora", "set_result", wasmtime.Func(store, set_result_type, set_result_fn))

            linker.define(store, "theora", "memory", host_memory)

        except Exception as e:
            logger.warning(f"Failed to register some host functions: {e}")

    @property
    def stats(self) -> dict:
        return {
            "available": self._wasmtime_available,
            "memory_limit_mb": self._memory_limit_mb,
            "timeout_seconds": self._timeout_seconds,
            "fuel_limit": self._fuel_limit,
        }
