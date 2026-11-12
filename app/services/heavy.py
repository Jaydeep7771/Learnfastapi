"""CPU-bound work, kept off the event loop.

Module-level functions only: ProcessPoolExecutor pickles the callable by qualified
name, so a closure or a lambda would raise PicklingError.
"""

import hashlib
import time


def pbkdf2_digest(payload: bytes, rounds: int = 400_000) -> str:
    """Deliberately expensive, pure-Python-visible CPU work (holds the GIL)."""
    return hashlib.pbkdf2_hmac("sha256", payload, b"workbook-salt", rounds).hex()


def blocking_sleep(seconds: float) -> float:
    """Simulates a blocking *I/O* call (a sync DB driver, `requests`, etc.)."""
    started = time.perf_counter()
    time.sleep(seconds)
    return time.perf_counter() - started


def parse_document(text: str) -> dict[str, int]:
    """Stand-in for PDF parsing: CPU-bound, releases nothing."""
    words = text.split()
    return {"chars": len(text), "words": len(words), "unique": len(set(words))}
