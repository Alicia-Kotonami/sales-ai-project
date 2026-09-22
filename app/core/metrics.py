"""Prometheus /metrics：挂 prometheus-fastapi-instrumentator，并兼容新版 FastAPI 路由。"""
from __future__ import annotations

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_fastapi_instrumentator import routing as pfi_routing


def _patch_route_name_for_included_router() -> None:
    """
    FastAPI 0.138+ / Starlette 0.52 的 include_router 会产生 `_IncludedRouter`，
    无 `.path`，会导致 instrumentator 7.1 抛 AttributeError。
    解析失败时退回 None，由中间件用 request.url.path。
    """
    original = pfi_routing.get_route_name

    def safe_get_route_name(request):  # type: ignore[no-untyped-def]
        try:
            return original(request)
        except AttributeError:
            return None

    pfi_routing.get_route_name = safe_get_route_name  # type: ignore[assignment]


def setup_metrics(app: FastAPI) -> None:
    _patch_route_name_for_included_router()
    Instrumentator(
        should_group_status_codes=True,
        should_group_untemplated=True,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)
