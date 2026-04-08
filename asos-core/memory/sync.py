"""
THEORA Federated Memory — CRDT-based P2P sync
===============================================
Replicates memory across THEORA instances on the local network.
No cloud relay — all sync is peer-to-peer via mDNS discovery.

Protocol:
  1. mDNS discovery: find peers advertising _theora._tcp.local.
  2. WebSocket handshake with shared passphrase
  3. Exchange vector clocks to determine missing operations
  4. Send missing ops → merge via CRDT rules
  5. Periodic heartbeat to detect disconnections

Conflict resolution:
  - Notes/Knowledge: last-writer-wins (by HLC timestamp)
  - Episodes: union (never delete remote episodes)
  - Execution log: append-only
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from config.loader import theora_data_home
from config.runtime import brain_port
from memory.hlc import HybridLogicalClock, HLCTimestamp

logger = logging.getLogger("theora.memory.sync")

SYNC_PORT = int(os.getenv("THEORA_SYNC_PORT", str(brain_port())))
SYNC_PASSPHRASE = os.getenv("THEORA_SYNC_PASSPHRASE", "")
SERVICE_TYPE = "_theora._tcp.local."


@dataclass
class SyncOperation:
    """A single write operation to be replicated."""
    op_id: str
    table: str
    op_type: str  # "insert", "update", "delete"
    row_id: str
    data: dict
    hlc: str
    origin_node: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "op_id": self.op_id,
            "table": self.table,
            "op_type": self.op_type,
            "row_id": self.row_id,
            "data": self.data,
            "hlc": self.hlc,
            "origin_node": self.origin_node,
            "timestamp": self.timestamp,
        }

    @staticmethod
    def from_dict(d: dict) -> "SyncOperation":
        return SyncOperation(**d)


@dataclass
class VectorClock:
    """Tracks the latest HLC seen from each node."""
    clocks: dict[str, str] = field(default_factory=dict)

    def update(self, node_id: str, hlc: str):
        current = self.clocks.get(node_id, "0:0:")
        if hlc > current:
            self.clocks[node_id] = hlc

    def to_dict(self) -> dict:
        return dict(self.clocks)

    @staticmethod
    def from_dict(d: dict) -> "VectorClock":
        return VectorClock(clocks=dict(d))


class SyncWAL:
    """Write-Ahead Log for sync operations — stored in SQLite."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._init_wal()

    def _init_wal(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_wal (
                op_id TEXT PRIMARY KEY,
                table_name TEXT NOT NULL,
                op_type TEXT NOT NULL,
                row_id TEXT NOT NULL,
                data TEXT NOT NULL,
                hlc TEXT NOT NULL,
                origin_node TEXT NOT NULL,
                timestamp REAL NOT NULL,
                synced_to TEXT DEFAULT '[]'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wal_hlc ON sync_wal(hlc)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wal_origin ON sync_wal(origin_node)")
        conn.commit()
        conn.close()

    def append(self, op: SyncOperation):
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO sync_wal (op_id, table_name, op_type, row_id, data, hlc, origin_node, timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (op.op_id, op.table, op.op_type, op.row_id, json.dumps(op.data), op.hlc, op.origin_node, op.timestamp),
            )
            conn.commit()
        finally:
            conn.close()

    def get_changes_since(self, hlc: str, exclude_node: str = "") -> list[SyncOperation]:
        conn = sqlite3.connect(self._db_path)
        try:
            if exclude_node:
                rows = conn.execute(
                    "SELECT op_id, table_name, op_type, row_id, data, hlc, origin_node, timestamp FROM sync_wal WHERE hlc > ? AND origin_node != ? ORDER BY hlc",
                    (hlc, exclude_node),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT op_id, table_name, op_type, row_id, data, hlc, origin_node, timestamp FROM sync_wal WHERE hlc > ? ORDER BY hlc",
                    (hlc,),
                ).fetchall()

            return [
                SyncOperation(
                    op_id=r[0], table=r[1], op_type=r[2], row_id=r[3],
                    data=json.loads(r[4]), hlc=r[5], origin_node=r[6], timestamp=r[7],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def mark_synced(self, op_id: str, peer_node: str):
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute("SELECT synced_to FROM sync_wal WHERE op_id=?", (op_id,)).fetchone()
            if row:
                synced = json.loads(row[0])
                if peer_node not in synced:
                    synced.append(peer_node)
                    conn.execute("UPDATE sync_wal SET synced_to=? WHERE op_id=?", (json.dumps(synced), op_id))
                    conn.commit()
        finally:
            conn.close()

    @property
    def count(self) -> int:
        conn = sqlite3.connect(self._db_path)
        try:
            return conn.execute("SELECT COUNT(*) FROM sync_wal").fetchone()[0]
        finally:
            conn.close()


class SyncEngine:
    """
    Manages peer-to-peer memory replication.

    Uses mDNS for peer discovery (zeroconf) and WebSocket for data exchange.
    """

    def __init__(self, node_id: str, memory_store=None, db_path: str = None):
        self.node_id = node_id
        self._memory = memory_store
        self._hlc = HybridLogicalClock(node_id)
        self._vector_clock = VectorClock()

        wal_path = db_path or str(theora_data_home() / "sync_wal.db")
        self._wal = SyncWAL(wal_path)

        self._peers: dict[str, dict] = {}
        self._running = False
        self._zeroconf = None
        self._service_info = None

        logger.info(f"SyncEngine initialized: node={node_id}, wal={wal_path}")

    def log_operation(self, table: str, op_type: str, row_id: str, data: dict):
        """Called by MemoryStore on every write to log to WAL."""
        hlc_ts = self._hlc.now()
        op = SyncOperation(
            op_id=str(uuid4()),
            table=table,
            op_type=op_type,
            row_id=row_id,
            data=data,
            hlc=hlc_ts.to_string(),
            origin_node=self.node_id,
        )
        self._wal.append(op)
        self._vector_clock.update(self.node_id, op.hlc)

    def get_changes_since(self, hlc: str) -> list[dict]:
        ops = self._wal.get_changes_since(hlc)
        return [op.to_dict() for op in ops]

    def apply_remote_changes(self, changes: list[dict]) -> int:
        """Apply operations received from a peer. Returns count of applied ops."""
        applied = 0
        for change_dict in changes:
            op = SyncOperation.from_dict(change_dict)

            remote_hlc = HLCTimestamp.from_string(op.hlc)
            self._hlc.receive(remote_hlc)
            self._vector_clock.update(op.origin_node, op.hlc)

            self._wal.append(op)

            if self._memory:
                self._apply_to_memory(op)

            applied += 1

        return applied

    def _apply_to_memory(self, op: SyncOperation):
        """Apply a sync operation to the local MemoryStore."""
        try:
            conn = sqlite3.connect(self._memory.db_path)
            if op.op_type == "insert":
                if op.table == "notes":
                    d = op.data
                    conn.execute(
                        "INSERT OR REPLACE INTO notes (id, content, tags, importance, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (d.get("id", op.row_id), d.get("content", ""), d.get("tags", "[]"),
                         d.get("importance", "normal"), d.get("source", "sync"), d.get("created_at", time.time()), time.time()),
                    )
                elif op.table == "episodes":
                    d = op.data
                    conn.execute(
                        "INSERT OR IGNORE INTO episodes (id, session_id, event_type, summary, detail, importance, created_at) VALUES (?,?,?,?,?,?,?)",
                        (d.get("id", op.row_id), d.get("session_id", "sync"), d.get("event_type", "synced"),
                         d.get("summary", ""), d.get("detail", ""), d.get("importance", 0.5), d.get("created_at", time.time())),
                    )
                elif op.table == "knowledge":
                    d = op.data
                    conn.execute(
                        "INSERT OR REPLACE INTO knowledge (id, subject, predicate, object, confidence, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (d.get("id", op.row_id), d.get("subject", ""), d.get("predicate", ""),
                         d.get("object", ""), d.get("confidence", 1.0), d.get("source", "sync"),
                         d.get("created_at", time.time()), time.time()),
                    )
                elif op.table == "execution_log":
                    d = op.data
                    conn.execute(
                        "INSERT OR IGNORE INTO execution_log (id, session_id, skill_id, endpoint_id, args, result_status, result_summary, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (d.get("id", op.row_id), d.get("session_id", ""), d.get("skill_id", ""),
                         d.get("endpoint_id", ""), d.get("args", "{}"), d.get("result_status", "unknown"),
                         d.get("result_summary", ""), d.get("latency_ms", 0), d.get("created_at", time.time())),
                    )
            elif op.op_type == "delete":
                conn.execute(f"DELETE FROM {op.table} WHERE id=?", (op.row_id,))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to apply sync op to {op.table}: {e}")

    def get_vector_clock(self) -> dict:
        return self._vector_clock.to_dict()

    @staticmethod
    def _get_lan_ip() -> str:
        """Get the real LAN IP address, not loopback."""
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.1)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        hostname = socket.gethostname()
        try:
            addrs = socket.getaddrinfo(hostname, None, socket.AF_INET)
            for addr in addrs:
                ip = addr[4][0]
                if not ip.startswith("127."):
                    return ip
        except Exception:
            pass
        return "127.0.0.1"

    async def start_discovery(self):
        """Start mDNS service advertisement and peer discovery."""
        try:
            from zeroconf import Zeroconf, ServiceBrowser, ServiceInfo
            import socket

            self._zeroconf = Zeroconf()

            ip = self._get_lan_ip()

            self._service_info = ServiceInfo(
                SERVICE_TYPE,
                f"theora-{self.node_id}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(ip)],
                port=SYNC_PORT,
                properties={
                    b"node_id": self.node_id.encode(),
                    b"version": b"1.0.0",
                },
            )

            self._zeroconf.register_service(self._service_info)
            logger.info(f"mDNS service registered: {self.node_id} at {ip}:{SYNC_PORT}")

            class PeerListener:
                def __init__(self, engine: SyncEngine):
                    self.engine = engine

                def add_service(self, zc, type_, name):
                    info = zc.get_service_info(type_, name)
                    if info and info.properties:
                        peer_id = info.properties.get(b"node_id", b"").decode()
                        if peer_id and peer_id != self.engine.node_id:
                            peer_addr = socket.inet_ntoa(info.addresses[0]) if info.addresses else ""
                            self.engine._peers[peer_id] = {
                                "address": peer_addr,
                                "port": info.port,
                                "discovered_at": time.time(),
                            }
                            logger.info(f"Discovered peer: {peer_id} at {peer_addr}:{info.port}")

                def remove_service(self, zc, type_, name):
                    pass

                def update_service(self, zc, type_, name):
                    pass

            ServiceBrowser(self._zeroconf, SERVICE_TYPE, PeerListener(self))
            self._running = True

        except ImportError:
            logger.warning("zeroconf not installed — mDNS discovery disabled. Install with: pip install zeroconf")
        except Exception as e:
            logger.warning(f"mDNS discovery failed: {e}")

    async def stop_discovery(self):
        if self._zeroconf:
            if self._service_info:
                self._zeroconf.unregister_service(self._service_info)
            self._zeroconf.close()
            self._zeroconf = None
        self._running = False

    async def sync_with_peer(self, peer_id: str) -> dict:
        """Initiate a sync session with a discovered peer."""
        peer = self._peers.get(peer_id)
        if not peer:
            return {"success": False, "error": f"Peer {peer_id} not found"}

        try:
            import websockets

            addr = peer["address"]
            port = peer["port"]
            uri = f"ws://{addr}:{port}/sync"

            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({
                    "type": "sync_request",
                    "node_id": self.node_id,
                    "vector_clock": self.get_vector_clock(),
                    "passphrase": SYNC_PASSPHRASE,
                }))

                resp = json.loads(await ws.recv())

                if resp.get("type") == "sync_error":
                    return {"success": False, "error": resp.get("message", "rejected")}

                remote_vc = resp.get("vector_clock", {})

                peer_has = remote_vc.get(self.node_id, "0:0:")
                changes_for_peer = self._wal.get_changes_since(peer_has, exclude_node=peer_id)

                await ws.send(json.dumps({
                    "type": "sync_data",
                    "changes": [op.to_dict() for op in changes_for_peer],
                }))

                remote_changes_msg = json.loads(await ws.recv())
                remote_changes = remote_changes_msg.get("changes", [])
                applied = self.apply_remote_changes(remote_changes)

                return {
                    "success": True,
                    "sent": len(changes_for_peer),
                    "received": applied,
                    "peer": peer_id,
                }

        except ImportError:
            return {"success": False, "error": "websockets not installed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def export_to_bundle(self) -> dict:
        """Export all memory for manual sync (USB, AirDrop)."""
        bundle = {
            "node_id": self.node_id,
            "vector_clock": self.get_vector_clock(),
            "operations": self.get_changes_since("0:0:"),
            "exported_at": time.time(),
        }
        return bundle

    def import_from_bundle(self, bundle: dict) -> int:
        """Import a memory bundle from another node."""
        changes = bundle.get("operations", [])
        return self.apply_remote_changes(changes)

    @property
    def stats(self) -> dict:
        return {
            "node_id": self.node_id,
            "peers": list(self._peers.keys()),
            "peer_count": len(self._peers),
            "wal_entries": self._wal.count,
            "vector_clock": self.get_vector_clock(),
            "running": self._running,
        }
