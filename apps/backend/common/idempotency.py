import json
import re
from datetime import timedelta
from functools import lru_cache

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _missing_key_response() -> JsonResponse:
    return JsonResponse(
        {
            "error": {
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "Header Idempotency-Key обязателен для write-эндпоинтов",
                "detail": {},
            }
        },
        status=400,
    )


@lru_cache(maxsize=1)
def _compiled_patterns() -> tuple[re.Pattern, ...]:
    raw = tuple(getattr(settings, "IDEMPOTENT_PATH_PATTERNS", ()))
    return tuple(re.compile(p) for p in raw)


def _path_requires_idempotency(path: str) -> bool:
    return any(p.match(path) for p in _compiled_patterns())


class IdempotencyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in WRITE_METHODS or not _path_requires_idempotency(request.path):
            return self.get_response(request)

        key = request.headers.get("Idempotency-Key")
        if not key:
            return _missing_key_response()

        from common.models import IdempotencyRecord

        ttl = timedelta(hours=getattr(settings, "IDEMPOTENCY_TTL_HOURS", 24))
        cutoff = timezone.now() - ttl

        existing = (
            IdempotencyRecord.objects.filter(key=key, created_at__gte=cutoff)
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return JsonResponse(existing.response_body, status=existing.response_status, safe=False)

        response = self.get_response(request)

        if 200 <= response.status_code < 500:
            try:
                body = json.loads(response.content.decode("utf-8") or "null")
            except (UnicodeDecodeError, json.JSONDecodeError):
                return response
            user_id = getattr(getattr(request, "user", None), "id", None)
            try:
                with transaction.atomic():
                    IdempotencyRecord.objects.create(
                        key=key,
                        method=request.method,
                        path=request.path,
                        user_id=user_id,
                        response_status=response.status_code,
                        response_body=body,
                    )
            except IntegrityError:
                pass

        return response
