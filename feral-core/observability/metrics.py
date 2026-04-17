"""Lightweight OpenTelemetry-compatible metrics. Uses OTel if available; falls back to in-memory counters."""
import logging
import os
import time
from collections import defaultdict
from contextlib import contextmanager

logger = logging.getLogger("feral.observability")

_OTEL_ENABLED = False
_meter = None
_counters = {}
_histograms = {}
_inmem = {"counters": defaultdict(int), "histograms": defaultdict(list)}


def init_metrics(service_name: str = "feral"):
    """Initialize OpenTelemetry metrics if opentelemetry-sdk is installed."""
    global _OTEL_ENABLED, _meter
    try:
        from opentelemetry import metrics
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader, ConsoleMetricExporter
        from opentelemetry.sdk.resources import Resource

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        readers = []
        if endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
                readers.append(PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint)))
            except ImportError:
                pass
        if os.environ.get("FERAL_METRICS_CONSOLE") == "1":
            readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))

        if readers:
            provider = MeterProvider(resource=Resource.create({"service.name": service_name}), metric_readers=readers)
            metrics.set_meter_provider(provider)
            _meter = metrics.get_meter(service_name)
            _OTEL_ENABLED = True
            logger.info("OpenTelemetry metrics initialized (readers=%d)", len(readers))
    except ImportError:
        logger.debug("opentelemetry-sdk not installed; using in-memory metrics")


def increment(name: str, by: int = 1, attributes: dict = None):
    """Increment a counter. Falls back to in-memory if OTel not available."""
    if _OTEL_ENABLED and _meter:
        c = _counters.get(name)
        if not c:
            c = _meter.create_counter(name)
            _counters[name] = c
        c.add(by, attributes or {})
    else:
        _inmem["counters"][name] += by


def observe(name: str, value: float, attributes: dict = None):
    """Record a value to a histogram."""
    if _OTEL_ENABLED and _meter:
        h = _histograms.get(name)
        if not h:
            h = _meter.create_histogram(name)
            _histograms[name] = h
        h.record(value, attributes or {})
    else:
        _inmem["histograms"][name].append(value)


@contextmanager
def measure(name: str, attributes: dict = None):
    """Context manager: record elapsed ms into histogram {name}_ms."""
    t0 = time.time()
    try:
        yield
    finally:
        observe(f"{name}_ms", (time.time() - t0) * 1000, attributes)


def in_memory_snapshot():
    """For tests and debugging — snapshot the in-mem metrics."""
    return {
        "counters": dict(_inmem["counters"]),
        "histograms": {k: {"count": len(v), "mean": sum(v) / max(len(v), 1)} for k, v in _inmem["histograms"].items()},
    }


def _reset_inmem():
    """Reset in-memory stores — for test isolation only."""
    _inmem["counters"].clear()
    _inmem["histograms"].clear()
