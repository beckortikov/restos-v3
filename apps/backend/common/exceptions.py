from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


class BusinessError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail: dict | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


def custom_exception_handler(exc, context):
    if isinstance(exc, BusinessError):
        return Response(
            {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}},
            status=exc.status_code,
        )

    # LicenseExpired (apps.licensing.permissions) — формат как BusinessError, 402
    try:
        from apps.licensing.permissions import LicenseExpired

        if isinstance(exc, LicenseExpired):
            return Response(
                {
                    "error": {
                        "code": exc.error_code,
                        "message": exc.error_message,
                        "detail": exc.detail_data,
                    }
                },
                status=exc.status_code,
            )
    except ImportError:
        pass

    if isinstance(exc, AuthenticationFailed):
        detail = exc.detail
        code = "AUTH_TOKEN_EXPIRED"
        message = "Требуется авторизация"
        if isinstance(detail, dict) and "code" in detail:
            code = str(detail["code"])
            message = str(detail.get("message", message))
        elif isinstance(detail, str):
            message = detail
        return Response(
            {"error": {"code": code, "message": message, "detail": {}}},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict) and "error" in data:
        return response

    code = "VALIDATION_ERROR"
    if response.status_code == status.HTTP_403_FORBIDDEN:
        code = "PERMISSION_DENIED"
    elif response.status_code == status.HTTP_404_NOT_FOUND:
        code = "NOT_FOUND"
    elif response.status_code == status.HTTP_401_UNAUTHORIZED:
        code = "AUTH_TOKEN_EXPIRED"

    response.data = {
        "error": {
            "code": code,
            "message": data.get("detail") if isinstance(data, dict) else "Ошибка запроса",
            "detail": data if not isinstance(data, str) else {},
        }
    }
    return response
