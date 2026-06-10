"""
Custom exceptions and DRF exception handler for Inventra.
All API errors return a consistent JSON envelope:
{
    "success": false,
    "error": {
        "code": "INSUFFICIENT_STOCK",
        "message": "Human-readable message",
        "detail": { ... } // optional extra context
    }
}
"""
import logging
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

logger = logging.getLogger("inventra.exceptions")


def custom_exception_handler(exc, context):
    """Global DRF exception handler — wraps all errors in a consistent envelope."""
    response = exception_handler(exc, context)

    if response is not None:
        error_payload = {
            "success": False,
            "error": {
                "code": _get_error_code(exc),
                "message": _get_error_message(response.data),
                "detail": response.data if not isinstance(response.data, str) else {},
            },
        }
        response.data = error_payload
    else:
        # Unhandled exception — log and return 500
        logger.exception(f"Unhandled exception in view: {exc}", exc_info=exc)
        response = Response(
            {
                "success": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred. Please try again.",
                    "detail": {},
                },
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response


def _get_error_code(exc) -> str:
    if hasattr(exc, "error_code"):
        return exc.error_code
    return type(exc).__name__.upper().replace("EXCEPTION", "ERROR")


def _get_error_message(data) -> str:
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        if "detail" in data:
            return str(data["detail"])
        # Return first validation message
        for key, value in data.items():
            if isinstance(value, list) and value:
                return f"{key}: {value[0]}"
            return str(value)
    if isinstance(data, list) and data:
        return str(data[0])
    return "An error occurred."


# ── Custom Exception Classes ─────────────────────────────────────────────────

class InventraException(Exception):
    """Base exception for all Inventra domain errors."""
    error_code = "INVENTRA_ERROR"
    default_message = "An application error occurred."
    http_status = status.HTTP_400_BAD_REQUEST

    def __init__(self, message=None, detail=None):
        self.message = message or self.default_message
        self.detail = detail or {}
        super().__init__(self.message)


class TenantNotFoundException(InventraException):
    error_code = "TENANT_NOT_FOUND"
    default_message = "Tenant not found or inactive."
    http_status = status.HTTP_404_NOT_FOUND


class TenantAccessDeniedException(InventraException):
    error_code = "TENANT_ACCESS_DENIED"
    default_message = "You do not have access to this tenant."
    http_status = status.HTTP_403_FORBIDDEN


class InsufficientStockException(InventraException):
    error_code = "INSUFFICIENT_STOCK"
    default_message = "Insufficient stock to complete this operation."
    http_status = status.HTTP_400_BAD_REQUEST


class DuplicateSKUException(InventraException):
    error_code = "DUPLICATE_SKU"
    default_message = "A product with this SKU already exists."
    http_status = status.HTTP_409_CONFLICT


class PlanLimitExceededException(InventraException):
    error_code = "PLAN_LIMIT_EXCEEDED"
    default_message = "Your plan limit has been reached. Please upgrade."
    http_status = status.HTTP_402_PAYMENT_REQUIRED


class OrderAlreadyProcessedException(InventraException):
    error_code = "ORDER_ALREADY_PROCESSED"
    default_message = "This order has already been processed and cannot be modified."
    http_status = status.HTTP_409_CONFLICT


class InvalidStockOperationException(InventraException):
    error_code = "INVALID_STOCK_OPERATION"
    default_message = "This stock operation is not valid."
    http_status = status.HTTP_400_BAD_REQUEST
