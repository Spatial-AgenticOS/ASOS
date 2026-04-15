"""mDNS service advertisement for FERAL Brain discovery on LAN."""
import logging
import socket
from typing import Optional

logger = logging.getLogger("feral.services.mdns")

_registration: Optional[tuple] = None


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
                "version": "2026.4.16",
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
        logger.warning(f"mDNS advertisement failed: {e}")
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
