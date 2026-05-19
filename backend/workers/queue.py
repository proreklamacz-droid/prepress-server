"""
RQ queue definitions.
Three priority queues: high (interactive), normal (standard jobs), low (batch).
"""
from rq import Queue
from redis import Redis
from config import settings

redis_conn = Redis.from_url(settings.REDIS_URL)

queue_high = Queue("prepress-high", connection=redis_conn)
queue_normal = Queue("prepress-normal", connection=redis_conn)
queue_low = Queue("prepress-low", connection=redis_conn)
