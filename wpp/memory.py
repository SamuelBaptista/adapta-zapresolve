"""
Redis Client Configuration.

Create a redis client from configuration.
"""

import json
import logging
from datetime import datetime
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class RedisManager:
    """
    Manager for Redis-based memory storage and retrieval.

    This class provides methods to store, retrieve, and manage data in Redis.
    """

    def __init__(self, redis: Any, memory_id: str) -> None:
        """
        Initialize the Redis manager.

        Args:
            redis: Redis client instance
            memory_id: Unique identifier for this memory in Redis
        """
        self.redis = redis
        self.id = memory_id
        self.memory_dict = self.redis.hgetall(name=self.id)

    def get_memory_dict(self) -> dict:
        """
        Get the memory dictionary from Redis.

        Returns:
            dict: The memory dictionary with decoded values
        """
        new_memory_dict = {}

        for k, v in self.memory_dict.items():
            try:
                key = k.decode("utf-8") if isinstance(k, bytes) else k
                value = v.decode("utf-8") if isinstance(v, bytes) else v

                new_memory_dict[key] = json.loads(value)
            except json.JSONDecodeError:
                try:
                    new_memory_dict[key] = int(value)
                except ValueError:
                    new_memory_dict[key] = value
            except Exception as e:
                logger.warning(
                    f"Erro para coletar a memória: {e}\n\n Não conseguimos acessar a chave {key}: {value}"
                )
        return new_memory_dict

    def set_memory_dict(
        self, memory_dict: dict, expire_time: int | None = None
    ) -> None:
        """
        Set memory dictionary with optional expiration.

        Args:
            memory_dict: Dictionary to store
            expire_time: Optional expiration time in seconds. If None, data persists indefinitely
        """
        try:
            new_memory_dict = {}

            for k, v in memory_dict.items():
                if isinstance(v, (list | dict)):
                    new_memory_dict[k] = json.dumps(v, default=self.convert_types)
                else:
                    new_memory_dict[k] = str(v)

            # Add timestamp for tracking
            new_memory_dict["_last_updated"] = datetime.now().isoformat()

            self.redis.hset(name=self.id, mapping=new_memory_dict)

            # Only set expiration if specified
            if expire_time is not None:
                self.redis.expire(name=self.id, time=expire_time)

            self.memory_dict = new_memory_dict

        except Exception as e:
            logger.warning(f"Erro para atualizar a memória: {e}")


    def reset_memory_dict(self) -> None:
        """Clear the memory dictionary."""
        self.redis.delete(self.id)

    @staticmethod
    def convert_types(number: Any) -> Any:
        """
        Convert NumPy numeric types to Python native types.

        Args:
            number: The number to convert

        Returns:
            The converted number or the original value if no conversion needed
        """
        if isinstance(number, (np.int64 | np.float64)):
            return number.item()
