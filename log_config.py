import sys
from pathlib import Path
from loguru import logger

Path("logs").mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stderr, level="DEBUG", colorize=True)
logger.add(
    "logs/app_{time:YYYY-MM-DD}.log",
    rotation="10 MB",
    retention="30 days",
    encoding="utf8",
    level="DEBUG",
)

logger.add(
    "logs/structured_{time:YYYY-MM-DD}.jsonl",
    rotation="10 MB",
    retention="30 days",
    encoding="utf8",
    level="DEBUG",
    serialize=True,
    filter=lambda r: "payload" in r["extra"],
)
