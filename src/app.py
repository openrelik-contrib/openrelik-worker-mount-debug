import os

import redis
from celery.app import Celery

from openrelik_worker_common.debug_utils import start_debugger

if os.getenv("OPENRELIK_PYDEBUG") == "1":
    start_debugger()

REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"
celery = Celery(
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["src.tasks"],
    worker_hijack_root_logger=False, # Disable Celery hijacking configured Python loggers.
    worker_log_format="%(message)s",
    worker_task_log_format="%(message)s",
)
redis_client = redis.Redis.from_url(REDIS_URL)
