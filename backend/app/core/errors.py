from fastapi import HTTPException

from app.schemas import ErrorCode


def api_error(
    status_code: int,
    code: ErrorCode | str,
    message: str,
) -> HTTPException:
    """Build an HTTPException with a stable machine-readable error code."""
    return HTTPException(
        status_code=status_code,
        detail={"code": str(code), "message": message},
    )
