from rest_framework.response import Response
from rest_framework import status

def error_response(
    code: str,
    message: str,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    details: dict | None = None
) -> Response:
    payload = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    return Response(payload, status=status_code)

class B2BUnavailableError(Exception):
    pass

class BlockedProductError(Exception):
    pass

class ModerationNotFoundError(Exception):
    pass

class ModerationNotAssignedError(Exception):
    pass

class ModerationInvalidStatusError(Exception):
    pass

class ProductHasNoSkusError(Exception):
    pass

class B2BEventError(Exception):
    pass