"""mDNS service advertisement + discovery for FERAL on the LAN."""
import logging
import socket
from typing import Optional

logger = logging.getLogger("feral.services.mdns")

_registration: Optional[tuple] = None

PHONE_BRIDGE_SERVICE_TYPE = "_feral-phone._tcp.local."


def advertise_brain(port: int = 9090, name: str = "FERAL Brain") -> bool:
    """Advertise the brain as a _feral._tcp service on the local network."""
    global _registration
    try:
        from zeroconf import Zeroconf, ServiceInfo

        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)

        info = ServiceInfo(
            "_feral._tcp.local.",
            f"{name}._feral._tcp.local.",
            addresses=[socket.inet_aton(ip)],
            port=port,
            properties={
                "version": "2026.4.11",
                "name": name,
                "hostname": hostname,
            },
        )

        zc = Zeroconf()
        zc.register_service(info)
        _registration = (zc, info)
        logger.info(f"mDNS: Advertising {name} on {ip}:{port}")
        return True
    except ImportError:
        logger.debug("zeroconf not installed — mDNS discovery disabled")
        return False
    except Exception as e:
        # Log exception type + repr (not bare str()) so tests/ops can see the
        # underlying failure cause (e.g. OSError: address already in use).
        logger.warning(
            "mDNS advertisement failed: %s: %r",
            type(e).__name__,
            e,
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )
        return False


def stop_advertisement():
    """Stop advertising and clean up zeroconf resources."""
    global _registration
    if _registration:
        zc, info = _registration
        zc.unregister_service(info)
        zc.close()
        _registration = None
        logger.info("mDNS: Advertisement stopped")


def discover_phone_bridge(timeout: float = 2.5) -> Optional[str]:
    """Discover a FERAL phone bridge on the LAN via mDNS.

    Browses ``_feral-phone._tcp.local.`` for ``timeout`` seconds and returns the
    first ``ws://host:port/path`` URL it finds, or ``None``. Used when the user
    selected "auto" during setup.
    """
    try:
        from zeroconf import Zeroconf, ServiceBrowser, ServiceListener
    except ImportError:
        logger.debug("zeroconf not installed — phone-bridge discovery disabled")
        return None

    found: list[str] = []

    class _Listener(ServiceListener):
        def add_service(self, zc, type_, name):
            try:
                info = zc.get_service_info(type_, name, timeout=1500)
                if not info:
                    return
                addrs = info.parsed_addresses() if hasattr(info, "parsed_addresses") else []
                host = addrs[0] if addrs else socket.inet_ntoa(info.addresses[0])
                port = info.port
                props = info.properties or {}
                path = props.get(b"path", b"/bridge").decode("utf-8", "ignore")
                if not path.startswith("/"):
                    path = "/" + path
                found.append(f"ws://{host}:{port}{path}")
            except Exception as e:
                logger.debug("phone bridge resolve failed: %s: %r", type(e).__name__, e)

        def update_service(self, *a, **kw):
            pass

        def remove_service(self, *a, **kw):
            pass

    zc = None
    try:
        zc = Zeroconf()
        ServiceBrowser(zc, PHONE_BRIDGE_SERVICE_TYPE, _Listener())
        import time
        end = time.monotonic() + max(0.1, timeout)
        while time.monotonic() < end:
            if found:
                break
            time.sleep(0.1)
    except Exception as e:
        logger.warning(
            "phone-bridge discovery failed: %s: %r",
            type(e).__name__,
            e,
        )
    finally:
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass

    return found[0] if found else None
