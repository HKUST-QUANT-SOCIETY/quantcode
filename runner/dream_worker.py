"""Small background worker for Dream/Distill consumption."""
from __future__ import annotations

import logging
import threading

from runner.dream_consumer import consume_once

logger = logging.getLogger(__name__)


def serve(stop: threading.Event, *, interval: int = 300, min_occurrences: int = 3) -> None:
    """Consume completed runs until ``stop`` is set."""
    consumed: set[str] = set()
    while not stop.is_set():
        try:
            consume_once(min_occurrences=min_occurrences, consumed_run_ids=consumed)
        except Exception as exc:
            logger.error("dream consumer cycle failed (%s)", type(exc).__name__)
        stop.wait(interval)
