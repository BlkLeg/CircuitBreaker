"""OpenTelemetry bootstrap — no-op when CB_OTEL_ENDPOINT is unset."""

from __future__ import annotations

import logging
import os
from typing import Any

_logger = logging.getLogger(__name__)
_tracer: Any = None

CB_OTEL_ENDPOINT = os.getenv("CB_OTEL_ENDPOINT", "").strip()


def init_otel(app: Any) -> None:
    """Instrument the FastAPI app with OpenTelemetry if CB_OTEL_ENDPOINT is set."""
    if not CB_OTEL_ENDPOINT:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from app.db.session import engine

        global _tracer
        provider = TracerProvider()
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=CB_OTEL_ENDPOINT)))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("circuitbreaker")
        FastAPIInstrumentor.instrument_app(app)
        SQLAlchemyInstrumentor().instrument(engine=engine)
        _logger.info("OpenTelemetry initialized → %s", CB_OTEL_ENDPOINT)
    except ImportError:
        _logger.warning("CB_OTEL_ENDPOINT set but opentelemetry packages not installed")


class _NoOpSpan:
    """Minimal no-op span context manager used when OTEL is disabled/unavailable."""

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def set_attribute(self, *_: Any) -> None:
        pass

    def record_exception(self, *_: Any) -> None:
        pass

    def set_status(self, *_: Any) -> None:
        pass


class _NoOpTracer:
    def start_as_current_span(self, *_: Any, **__: Any) -> _NoOpSpan:
        return _NoOpSpan()


def get_tracer() -> Any:
    """Return the active tracer, or a no-op tracer if OTEL is not configured."""
    if _tracer:
        return _tracer
    try:
        from opentelemetry import trace

        return trace.get_tracer("circuitbreaker")
    except ImportError:
        return _NoOpTracer()
