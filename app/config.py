"""Runtime configuration.

Everything is read from the environment so the same image runs locally, in the
demo deployment, and inside a restricted network with no code changes.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from app.extraction.base import VisionExtractor
from app.extraction.mock_extractor import MockExtractor

logger = logging.getLogger("ttb.config")

ENV_FILE = Path(__file__).parent.parent / ".env"


def _load_env_file(path: Path = ENV_FILE) -> None:
    """Read a .env file into the environment.

    Parsed here rather than via python-dotenv so that configuration never
    depends on an optional package being installed. An earlier version wrapped
    the dotenv import in a bare try/except, which meant a missing dependency
    silently disabled all configuration and the application started in offline
    mode with no explanation. Configuration that fails should say so.

    Real environment variables always win, which is what deployment platforms
    set.
    """
    if not path.exists():
        logger.info("No .env file at %s; using environment variables only.", path)
        return

    loaded = []
    # utf-8-sig strips the byte order mark Notepad writes on Windows.
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)

    if loaded:
        logger.info("Loaded from .env: %s", ", ".join(loaded))
    else:
        logger.warning("Found %s but read no settings from it.", path)


_load_env_file()

# Claude Haiku 4.5 is the default: the transcription task is well within its
# vision capability, and its latency is what makes the five second budget
# comfortable rather than tight. Override with EXTRACTION_MODEL to trade cost
# for accuracy on difficult artwork.
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", 50))

# Deliberately conservative. New API accounts sit in a low rate limit tier, and
# firing eight concurrent extractions at one produces 429s that the SDK absorbs
# by retrying with backoff. The retries are invisible from here but show up as
# a single request that appears to take ten seconds. Four keeps a batch well
# inside typical entry-tier limits; raise it once the account's limits are
# known.
MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", 4))

ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


@lru_cache(maxsize=1)
def get_extractor() -> VisionExtractor:
    """Build the configured extractor once and reuse it.

    Falls back to the offline extractor when no key is present so that a fresh
    clone runs immediately with no setup.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return MockExtractor()

    from app.extraction.anthropic_extractor import AnthropicExtractor

    return AnthropicExtractor(
        api_key=api_key,
        model=os.getenv("EXTRACTION_MODEL", DEFAULT_MODEL),
        timeout=float(os.getenv("EXTRACTION_TIMEOUT_S", 20.0)),
    )


def using_live_model() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY", "").strip())
