"""OpenTelemetry 可选埋点：默认关闭，无 Collector 不阻塞启动。"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger("app.otel")


def setup_otel(app: FastAPI) -> None:
    """
    OTEL_ENABLED=true 时为 FastAPI / SQLAlchemy / Redis 自动埋点。
    导出失败只打 warning，不抛异常。
    """
    if not settings.OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError as exc:
        logger.warning("OpenTelemetry 依赖未安装，跳过埋点: %s", exc)
        return

    resource = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
    provider = TracerProvider(resource=resource)

    endpoint = (settings.OTEL_EXPORTER_OTLP_ENDPOINT or "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTel OTLP exporter endpoint=%s", endpoint)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OTel OTLP 初始化失败，回退 ConsoleExporter: %s", exc)
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        # 无 Collector：开发可见，不阻塞
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        logger.info("OTel 未配置 OTLP endpoint，使用 ConsoleSpanExporter")

    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="metrics,health")
    except Exception as exc:  # noqa: BLE001
        logger.warning("FastAPI OTel 埋点失败: %s", exc)

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from app.db.session import engine

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SQLAlchemy OTel 埋点失败: %s", exc)

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis OTel 埋点失败: %s", exc)

    logger.info("OpenTelemetry 已启用 service=%s", settings.OTEL_SERVICE_NAME)
