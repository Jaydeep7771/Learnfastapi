"""RFC 9457 Problem Details: one machine-readable error shape for the whole API."""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

CONTENT_TYPE = "application/problem+json"


class AppError(Exception):
    """Domain error raised by services; routers never build HTTP responses by hand."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        type_: str = "about:blank",
        title: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.type = type_
        self.title = title or detail


def problem(
    request: Request,
    *,
    status_code: int,
    title: str,
    detail: str,
    type_: str = "about:blank",
    **extra: object,
) -> JSONResponse:
    body = {
        "type": type_,
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": str(request.url.path),
        "correlation_id": request.scope.get("state", {}).get("correlation_id"),
        **extra,
    }
    return JSONResponse(body, status_code=status_code, media_type=CONTENT_TYPE)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem(
            request,
            status_code=exc.status_code,
            title=exc.title,
            detail=exc.detail,
            type_=exc.type,
        )

    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return problem(
            request,
            status_code=exc.status_code,
            title=str(exc.detail),
            detail=str(exc.detail),
            type_=f"https://httpstatuses.io/{exc.status_code}",
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return problem(
            request,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Request validation failed",
            detail="One or more fields are invalid.",
            type_="https://example.com/problems/validation-error",
            errors=[
                {"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ],
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak stack traces or SQL to clients.
        return problem(
            request,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            title="Internal Server Error",
            detail="An unexpected error occurred.",
        )
