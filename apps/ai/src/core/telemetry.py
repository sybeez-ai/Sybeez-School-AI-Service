import logging

logger = logging.getLogger("sybeez.ai.telemetry")


def track(name: str, **properties) -> None:
    logger.info("event=%s props=%s", name, properties)
