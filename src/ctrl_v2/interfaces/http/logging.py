from __future__ import annotations

import logging
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger("ctrl_v2.http")


async def safe_access_log(request: Request, call_next: object):
    """Log routing metadata without headers, query values, bodies, or exception values."""
    request_id = str(uuid4())
    route_template = request.scope.get("route")
    route_path = getattr(route_template, "path", "unmatched")
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            "request_failed method=%s route=%s request_id=%s error_type=%s",
            request.method,
            route_path,
            request_id,
            type(exc).__name__,
        )
        raise
    logger.info(
        "request_completed method=%s route=%s status=%s request_id=%s",
        request.method,
        route_path,
        response.status_code,
        request_id,
    )
    response.headers["X-Request-ID"] = request_id
    return response
