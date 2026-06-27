from pydantic import BaseModel


class ErrorBody(BaseModel):
    type: str
    message: str
    code: str | None = None
    details: str | list[dict] | None = None
    hint: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
