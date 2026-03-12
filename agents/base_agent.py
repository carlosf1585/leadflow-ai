import asyncio
import json
import signal
import time
import uuid
from abc import ABC, abstractmethod
from typing import Optional

import redis.asyncio as aioredis
import structlog

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import AgentLog

log = structlog.get_logger()


class BaseAgent(ABC):
    name: str = "base_agent"
    queue: str = "base_queue"

    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        self._running = True
        signal.signal(signal.SIGTERM, self._handle_sigterm)

    def _handle_sigterm(self, signum, frame):
        log.info("SIGTERM received, shutting down", agent=self.name)
        self._running = False

    async def connect_redis(self):
        self.redis = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    async def publish(self, queue: str, payload: dict):
        await self.redis.rpush(queue, json.dumps(payload))

    async def log_to_db(self, action: str, status: str, details: dict, duration_ms: int):
        try:
            async with AsyncSessionLocal() as db:
                entry = AgentLog(
                    id=str(uuid.uuid4()),
                    agent_name=self.name,
                    action=action,
                    status=status,
                    details=details,
                    duration_ms=duration_ms,
                )
                db.add(entry)
                await db.commit()
        except Exception as e:
            log.error("Failed to log to DB", agent=self.name, error=str(e))

    @abstractmethod
    async def process(self, payload: dict):
        pass

    async def run(self):
        await self.connect_redis()
        log.info("Agent started", agent=self.name, queue=self.queue)
        while self._running:
            try:
                result = await self.redis.blpop(self.queue, timeout=5)
                if result:
                    _, raw = result
                    payload = json.loads(raw)
                    start = time.time()
                    try:
                        await self.process(payload)
                        duration = int((time.time() - start) * 1000)
                        await self.log_to_db(payload.get("action", "process"), "success", payload, duration)
                    except Exception as e:
                        duration = int((time.time() - start) * 1000)
                        log.error("Agent processing error", agent=self.name, error=str(e))
                        await self.log_to_db(payload.get("action", "process"), "error", {"error": str(e)}, duration)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error("Agent loop error", agent=self.name, error=str(e))
                await asyncio.sleep(5)
        await self.redis.close()
        log.info("Agent stopped", agent=self.name)
