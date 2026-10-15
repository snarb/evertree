"""Console logging for the key LLM and system actions; level via EVERTREE_LOG_LEVEL."""

import logging
import os
import sys


def configure_logging():
    logging.basicConfig(
        level=os.environ.get("EVERTREE_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
