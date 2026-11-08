"""Logging setup. Rule: never log ID numbers, passwords, tokens or query strings."""
import logging

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Uvicorn's access log prints full URLs (incl. ?token=...). We log requests ourselves
    # in app.main (path only), so silence it.
    logging.getLogger("uvicorn.access").disabled = True
    _configured = True
