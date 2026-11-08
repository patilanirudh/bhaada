"""Domain errors raised by services. The API layer maps them to HTTP responses
(see ``app.main``), so services never import FastAPI."""


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str, errors: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or {}


class BadRequest(AppError):
    status_code = 400


class Unauthorized(AppError):
    status_code = 401


class Forbidden(AppError):
    status_code = 403


class NotFound(AppError):
    status_code = 404


class Conflict(AppError):
    status_code = 409


class Gone(AppError):
    status_code = 410


class ValidationFailed(AppError):
    status_code = 422


class RateLimited(AppError):
    status_code = 429


class ServerError(AppError):
    status_code = 500
