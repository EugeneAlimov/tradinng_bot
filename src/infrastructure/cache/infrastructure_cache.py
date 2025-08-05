import time
import asyncio
import pickle
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Union, TypeVar, Generic, Callable, List
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock

from ..core.interfaces import ICacheService
from ..core.exceptions import CacheError
from ..core.constants import Timing

T = TypeVar('T')


@dataclass
class CacheEntry(Generic[T]):
    """📦 Запись в кэше"""
    value: T
    created_at: datetime
    expires_at: Optional[datetime] = None
    access_count: int = 0
    last_accessed: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_expired(self) -> bool:
        """Проверка истечения срока действия"""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at
    
    @property
    def age_seconds(self) -> float:
        """Возраст записи в секундах"""
        return (datetime.now() - self.created_at).total_seconds()
    
    def access(self) -> None:
        """Обновление статистики доступа"""
        self.access_count += 1
        self.last_accessed = datetime.now()


@dataclass
class CacheStats:
    """📊 Статистика кэша"""
    total_entries: int = 0
    memory_usage_bytes: int = 0
    hit_count: int = 0
    miss_count: int = 0
    eviction_count: int = 0
    expired_count: int = 0
    
    @property
    def hit_rate(self) -> float:
        """Процент попаданий в кэш"""
        total = self.hit_count + self.miss_count
        return (self.hit_count / total * 100) if total > 0 else 0.0
    
    @property
    def miss_rate(self) -> float:
        """Процент промахов кэша"""
        return 100.0 - self.hit_rate


class EvictionPolicy(ABC):
    """🗑️ Политика вытеснения записей из кэша"""
    
    @abstractmethod
    def should_evict(self, entry: CacheEntry, cache_size: int, max_size: int) -> bool:
        """Нужно ли вытеснять запись"""
        pass
    
    @abstractmethod
    def select_victims(self, entries: Dict[str, CacheEntry], count: int) -> List[str]:
        """Выбор записей для вытеснения"""
        pass


class LRUEvictionPolicy(EvictionPolicy):
    """🔄 Политика вытеснения LRU (Least Recently Used)"""
    
    def should_evict(self, entry: CacheEntry, cache_size: int, max_size: int) -> bool:
        """Вытесняем если кэш переполнен"""
        return cache_size >= max_size
    
    def select_victims(self, entries: Dict[str, CacheEntry], count: int) -> List[str]:
        """Выбираем наименее недавно использованные записи"""
        sorted_entries = sorted(
            entries.items(),
            key=lambda x: x[1].last_accessed
        )
        return [key for key, _ in sorted_entries[:count]]


class TTLEvictionPolicy(EvictionPolicy):
    """⏰ Политика вытеснения по TTL"""
    
    def should_evict(self, entry: CacheEntry, cache_size: int, max_size: int) -> bool:
        """Вытесняем истекшие записи"""
        return entry.is_expired
    
    def select_victims(self, entries: Dict[str, CacheEntry], count: int) -> List[str]:
        """Выбираем истекшие записи"""
        expired_keys = [
            key for key, entry in entries.items()
            if entry.is_expired
        ]
        return expired_keys[:count]


class InMemoryCache(ICacheService):
    """🧠 Кэш в памяти с расширенной функциональностью"""
    
    def __init__(
        self,
        max_size: int = 1000,
        default_ttl: int = 300,
        eviction_policy: Optional[EvictionPolicy] = None,
        enable_stats: bool = True
    ):
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.eviction_policy = eviction_policy or LRUEvictionPolicy()
        self.enable_stats = enable_stats
        
        # Хранилище данных
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = RLock()
        
        # Статистика
        self.stats = CacheStats()
        
        # Фоновая задача очистки
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
        
        self.logger = logging.getLogger(__name__)
    
    async def start(self) -> None:
        """🚀 Запуск кэша"""
        if not self._running:
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.logger.info("💾 Кэш запущен")
    
    async def stop(self) -> None:
        """🛑 Остановка кэша"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self.logger.info("💾 Кэш остановлен")
    
    async def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """🔍 Получение значения из кэша"""
        with self._lock:
            if key not in self._cache:
                if self.enable_stats:
                    self.stats.miss_count += 1
                return default
            
            entry = self._cache[key]
            
            # Проверяем истечение
            if entry.is_expired:
                del self._cache[key]
                if self.enable_stats:
                    self.stats.miss_count += 1
                    self.stats.expired_count += 1
                return default
            
            # Обновляем статистику доступа
            entry.access()
            if self.enable_stats:
                self.stats.hit_count += 1
            
            return entry.value
    
    async def set(
        self,
        key: str,
        value: T,
        ttl: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """💾 Сохранение значения в кэш"""
        with self._lock:
            # Определяем время истечения
            expires_at = None
            if ttl is not None:
                expires_at = datetime.now() + timedelta(seconds=ttl)
            elif self.default_ttl > 0:
                expires_at = datetime.now() + timedelta(seconds=self.default_ttl)
            
            # Создаем запись
            entry = CacheEntry(
                value=value,
                created_at=datetime.now(),
                expires_at=expires_at,
                metadata=metadata or {}
            )
            
            # Проверяем необходимость вытеснения
            if len(self._cache) >= self.max_size and key not in self._cache:
                await self._evict_entries(1)
            
            self._cache[key] = entry
            
            if self.enable_stats:
                self.stats.total_entries = len(self._cache)
                self.stats.memory_usage_bytes = self._calculate_memory_usage()
    
    async def delete(self, key: str) -> bool:
        """🗑️ Удаление ключа из кэша"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if self.enable_stats:
                    self.stats.total_entries = len(self._cache)
                return True
            return False
    
    async def exists(self, key: str) -> bool:
        """❓ Проверка существования ключа"""
        with self._lock:
            if key not in self._cache:
                return False
            
            entry = self._cache[key]
            if entry.is_expired:
                del self._cache[key]
                return False
            
            return True
    
    async def clear(self) -> None:
        """🧹 Очистка всего кэша"""
        with self._lock:
            self._cache.clear()
            if self.enable_stats:
                self.stats = CacheStats()
    
    async def get_or_set(
        self,
        key: str,
        factory: Callable[[], T],
        ttl: Optional[int] = None
    ) -> T:
        """🎯 Получение или создание значения"""
        value = await self.get(key)
        if value is not None:
            return value
        
        # Создаем значение
        new_value = factory() if not asyncio.iscoroutinefunction(factory) else await factory()
        await self.set(key, new_value, ttl)
        return new_value
    
    async def increment(self, key: str, delta: int = 1, initial: int = 0) -> int:
        """➕ Атомарное увеличение значения"""
        with self._lock:
            current = await self.get(key, initial)
            if not isinstance(current, (int, float)):
                current = initial
            
            new_value = int(current) + delta
            await self.set(key, new_value)
            return new_value
    
    async def get_stats(self) -> CacheStats:
        """📊 Получение статистики кэша"""
        if not self.enable_stats:
            return CacheStats()
        
        with self._lock:
            self.stats.total_entries = len(self._cache)
            self.stats.memory_usage_bytes = self._calculate_memory_usage()
            return self.stats
    
    async def get_keys(self, pattern: Optional[str] = None) -> List[str]:
        """🔑 Получение списка ключей"""
        with self._lock:
            keys = list(self._cache.keys())
            
            if pattern:
                import fnmatch
                keys = [key for key in keys if fnmatch.fnmatch(key, pattern)]
            
            return keys
    
    async def get_info(self) -> Dict[str, Any]:
        """ℹ️ Подробная информация о кэше"""
        stats = await self.get_stats()
        
        with self._lock:
            expired_count = sum(1 for entry in self._cache.values() if entry.is_expired)
            avg_age = sum(entry.age_seconds for entry in self._cache.values()) / len(self._cache) if self._cache else 0
            
            return {
                "type": "InMemoryCache",
                "config": {
                    "max_size": self.max_size,
                    "default_ttl": self.default_ttl,
                    "eviction_policy": type(self.eviction_policy).__name__,
                    "stats_enabled": self.enable_stats
                },
                "stats": {
                    "total_entries": stats.total_entries,
                    "memory_usage_mb": stats.memory_usage_bytes / 1024 / 1024,
                    "hit_rate": stats.hit_rate,
                    "miss_rate": stats.miss_rate,
                    "expired_entries": expired_count,
                    "average_age_seconds": avg_age
                },
                "running": self._running
            }
    
    async def _evict_entries(self, count: int) -> None:
        """🗑️ Вытеснение записей"""
        if not self._cache:
            return
        
        victims = self.eviction_policy.select_victims(self._cache, count)
        
        for key in victims:
            if key in self._cache:
                del self._cache[key]
                if self.enable_stats:
                    self.stats.eviction_count += 1
    
    async def _cleanup_loop(self) -> None:
        """🧹 Фоновая очистка истекших записей"""
        while self._running:
            try:
                await self._cleanup_expired()
                await asyncio.sleep(60)  # Проверяем каждую минуту
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Ошибка в cleanup_loop: {e}")
                await asyncio.sleep(60)
    
    async def _cleanup_expired(self) -> None:
        """🧹 Очистка истекших записей"""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired
            ]
            
            for key in expired_keys:
                del self._cache[key]
                if self.enable_stats:
                    self.stats.expired_count += 1
    
    def _calculate_memory_usage(self) -> int:
        """🧮 Приблизительный расчет использования памяти"""
        try:
            total_size = 0
            for key, entry in self._cache.items():
                # Размер ключа
                total_size += len(key.encode('utf-8'))
                
                # Размер значения (примерно)
                try:
                    if isinstance(entry.value, str):
                        total_size += len(entry.value.encode('utf-8'))
                    elif isinstance(entry.value, (int, float)):
                        total_size += 8  # Примерный размер числа
                    elif isinstance(entry.value, (list, dict)):
                        total_size += len(pickle.dumps(entry.value))
                    else:
                        total_size += 64  # Фиксированный размер для остальных типов
                except:
                    total_size += 64
                
                # Размер метаданных
                total_size += 64  # Примерный размер CacheEntry
            
            return total_size
        except:
            return 0


class PersistentCache(ICacheService):
    """💽 Персистентный кэш с сохранением на диск"""
    
    def __init__(
        self,
        storage_path: str,
        max_size: int = 10000,
        default_ttl: int = 3600,
        sync_interval: int = 300
    ):
        self.storage_path = Path(storage_path)
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.sync_interval = sync_interval
        
        # Создаем директорию если не существует
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        # In-memory слой для быстрого доступа
        self.memory_cache = InMemoryCache(max_size, default_ttl)
        
        # Метаданные для отслеживания файлов
        self._metadata_file = self.storage_path / "cache_metadata.json"
        self._metadata: Dict[str, Dict[str, Any]] = {}
        
        # Синхронизация
        self._sync_task: Optional[asyncio.Task] = None
        self._dirty_keys: set = set()
        self._lock = RLock()
        
        self.logger = logging.getLogger(__name__)
        
        # Загружаем метаданные при инициализации
        self._load_metadata()
    
    async def start(self) -> None:
        """🚀 Запуск персистентного кэша"""
        await self.memory_cache.start()
        self._sync_task = asyncio.create_task(self._sync_loop())
        self.logger.info("💽 Персистентный кэш запущен")
    
    async def stop(self) -> None:
        """🛑 Остановка кэша"""
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        
        await self._sync_to_disk()  # Финальная синхронизация
        await self.memory_cache.stop()
        self.logger.info("💽 Персистентный кэш остановлен")
    
    async def get(self, key: str, default: Optional[T] = None) -> Optional[T]:
        """🔍 Получение значения"""
        # Сначала проверяем память
        value = await self.memory_cache.get(key)
        if value is not None:
            return value
        
        # Загружаем с диска
        disk_value = await self._load_from_disk(key)
        if disk_value is not None:
            # Кэшируем в памяти
            await self.memory_cache.set(key, disk_value)
            return disk_value
        
        return default
    
    async def set(
        self,
        key: str,
        value: T,
        ttl: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """💾 Сохранение значения"""
        # Сохраняем в память
        await self.memory_cache.set(key, value, ttl, metadata)
        
        # Отмечаем как требующий синхронизации
        with self._lock:
            self._dirty_keys.add(key)
            
            # Обновляем метаданные
            self._metadata[key] = {
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(seconds=ttl or self.default_ttl)).isoformat(),
                "metadata": metadata or {}
            }
    
    async def delete(self, key: str) -> bool:
        """🗑️ Удаление ключа"""
        # Удаляем из памяти
        memory_deleted = await self.memory_cache.delete(key)
        
        # Удаляем с диска
        disk_deleted = await self._delete_from_disk(key)
        
        # Очищаем метаданные
        with self._lock:
            self._metadata.pop(key, None)
            self._dirty_keys.discard(key)
        
        return memory_deleted or disk_deleted
    
    async def exists(self, key: str) -> bool:
        """❓ Проверка существования"""
        # Проверяем память
        if await self.memory_cache.exists(key):
            return True
        
        # Проверяем диск
        return await self._exists_on_disk(key)
    
    async def clear(self) -> None:
        """🧹 Полная очистка"""
        await self.memory_cache.clear()
        
        # Очищаем диск
        for file in self.storage_path.glob("cache_*.pkl"):
            file.unlink(missing_ok=True)
        
        with self._lock:
            self._metadata.clear()
            self._dirty_keys.clear()
        
        await self._save_metadata()
    
    async def get_stats(self) -> Dict[str, Any]:
        """📊 Статистика кэша"""
        memory_stats = await self.memory_cache.get_stats()
        
        disk_files = list(self.storage_path.glob("cache_*.pkl"))
        disk_size = sum(f.stat().st_size for f in disk_files)
        
        return {
            "memory": {
                "entries": memory_stats.total_entries,
                "hit_rate": memory_stats.hit_rate,
                "memory_usage_mb": memory_stats.memory_usage_bytes / 1024 / 1024
            },
            "disk": {
                "files": len(disk_files),
                "size_mb": disk_size / 1024 / 1024,
                "dirty_keys": len(self._dirty_keys)
            },
            "total_keys": len(self._metadata)
        }
    
    async def _load_from_disk(self, key: str) -> Optional[T]:
        """💽 Загрузка с диска"""
        try:
            file_path = self._get_file_path(key)
            if not file_path.exists():
                return None
            
            # Проверяем метаданные на истечение
            if key in self._metadata:
                expires_str = self._metadata[key].get("expires_at")
                if expires_str:
                    expires_at = datetime.fromisoformat(expires_str)
                    if datetime.now() > expires_at:
                        # Удаляем истекший файл
                        await self._delete_from_disk(key)
                        return None
            
            with open(file_path, 'rb') as f:
                return pickle.load(f)
                
        except Exception as e:
            self.logger.error(f"Ошибка загрузки {key} с диска: {e}")
            return None
    
    async def _save_to_disk(self, key: str, value: T) -> None:
        """💾 Сохранение на диск"""
        try:
            file_path = self._get_file_path(key)
            
            # Сохраняем в временный файл, потом переименовываем (атомарно)
            temp_path = file_path.with_suffix('.tmp')
            
            with open(temp_path, 'wb') as f:
                pickle.dump(value, f)
            
            temp_path.replace(file_path)
            
        except Exception as e:
            self.logger.error(f"Ошибка сохранения {key} на диск: {e}")
    
    async def _delete_from_disk(self, key: str) -> bool:
        """🗑️ Удаление с диска"""
        try:
            file_path = self._get_file_path(key)
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            self.logger.error(f"Ошибка удаления {key} с диска: {e}")
            return False
    
    async def _exists_on_disk(self, key: str) -> bool:
        """❓ Проверка существования на диске"""
        file_path = self._get_file_path(key)
        return file_path.exists()
    
    def _get_file_path(self, key: str) -> Path:
        """📁 Получение пути к файлу для ключа"""
        # Безопасное имя файла
        safe_key = key.replace('/', '_').replace('\\', '_').replace(':', '_')
        return self.storage_path / f"cache_{safe_key}.pkl"
    
    async def _sync_loop(self) -> None:
        """🔄 Цикл синхронизации с диском"""
        while True:
            try:
                await asyncio.sleep(self.sync_interval)
                await self._sync_to_disk()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Ошибка в sync_loop: {e}")
    
    async def _sync_to_disk(self) -> None:
        """💾 Синхронизация измененных ключей на диск"""
        with self._lock:
            keys_to_sync = self._dirty_keys.copy()
            self._dirty_keys.clear()
        
        for key in keys_to_sync:
            value = await self.memory_cache.get(key)
            if value is not None:
                await self._save_to_disk(key, value)
        
        if keys_to_sync:
            await self._save_metadata()
            self.logger.debug(f"Синхронизировано {len(keys_to_sync)} ключей")
    
    def _load_metadata(self) -> None:
        """📋 Загрузка метаданных"""
        try:
            if self._metadata_file.exists():
                with open(self._metadata_file, 'r') as f:
                    self._metadata = json.load(f)
        except Exception as e:
            self.logger.error(f"Ошибка загрузки метаданных: {e}")
            self._metadata = {}
    
    async def _save_metadata(self) -> None:
        """💾 Сохранение метаданных"""
        try:
            with open(self._metadata_file, 'w') as f:
                json.dump(self._metadata, f, indent=2)
        except Exception as e:
            self.logger.error(f"Ошибка сохранения метаданных: {e}")


# Декоратор для кэширования результатов функций
def cached(
    cache: ICacheService,
    ttl: Optional[int] = None,
    key_func: Optional[Callable] = None
):
    """🎯 Декоратор для кэширования результатов функций"""
    def decorator(func):
        async def async_wrapper(*args, **kwargs):
            # Генерируем ключ
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = f"{func.__name__}:{hash(str(args) + str(sorted(kwargs.items())))}"
            
            # Пытаемся получить из кэша
            result = await cache.get(cache_key)
            if result is not None:
                return result
            
            # Вычисляем результат
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            # Сохраняем в кэш
            await cache.set(cache_key, result, ttl)
            return result
        
        def sync_wrapper(*args, **kwargs):
            return asyncio.run(async_wrapper(*args, **kwargs))
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


# Фабрика кэшей
class CacheFactory:
    """🏭 Фабрика для создания кэшей"""
    
    @staticmethod
    def create_memory_cache(
        max_size: int = 1000,
        default_ttl: int = 300,
        eviction_policy: str = "lru"
    ) -> InMemoryCache:
        """Создание кэша в памяти"""
        policy_map = {
            "lru": LRUEvictionPolicy(),
            "ttl": TTLEvictionPolicy()
        }
        
        policy = policy_map.get(eviction_policy, LRUEvictionPolicy())
        return InMemoryCache(max_size, default_ttl, policy)
    
    @staticmethod
    def create_persistent_cache(
        storage_path: str,
        max_memory_size: int = 1000,
        default_ttl: int = 3600,
        sync_interval: int = 300
    ) -> PersistentCache:
        """Создание персистентного кэша"""
        return PersistentCache(storage_path, max_memory_size, default_ttl, sync_interval)
    
    @staticmethod
    def create_from_settings(cache_type: str, **kwargs) -> ICacheService:
        """Создание кэша по типу"""
        if cache_type == "memory":
            return CacheFactory.create_memory_cache(**kwargs)
        elif cache_type == "persistent":
            return CacheFactory.create_persistent_cache(**kwargs)
        else:
            raise ValueError(f"Неподдерживаемый тип кэша: {cache_type}")
