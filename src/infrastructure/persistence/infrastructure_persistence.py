#!/usr/bin/env python3
"""🗄️ Инфраструктурный слой - Система персистентности данных"""

import json
import csv
import sqlite3
import asyncio
import aiosqlite
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Union, TypeVar, Generic, Type
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from decimal import Decimal
import pickle

from ..core.interfaces import IRepository, IUnitOfWork
from ..core.models import Position, TradeOrder, TradeResult, TradingPair
from ..core.exceptions import PersistenceError, ValidationError
from ..core.constants import Trading

T = TypeVar('T')


@dataclass
class RepositoryConfig:
    """⚙️ Конфигурация репозитория"""
    storage_type: str = "json"  # json, sqlite, csv
    storage_path: str = "data"
    backup_enabled: bool = True
    backup_interval: int = 3600  # секунд
    auto_migrate: bool = True
    compression: bool = False


class JSONSerializer:
    """📄 JSON сериализатор с поддержкой Decimal"""
    
    @staticmethod
    def serialize(obj: Any) -> str:
        """Сериализация объекта в JSON"""
        def decimal_handler(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif hasattr(obj, '__dict__'):
                return asdict(obj) if hasattr(obj, '__dataclass_fields__') else obj.__dict__
            raise TypeError(f"Объект типа {type(obj)} не сериализуем")
        
        return json.dumps(obj, default=decimal_handler, indent=2, ensure_ascii=False)
    
    @staticmethod
    def deserialize(data: str, target_type: Optional[Type] = None) -> Any:
        """Десериализация JSON в объект"""
        parsed = json.loads(data)
        
        if target_type and hasattr(target_type, '__dataclass_fields__'):
            # Конвертируем в dataclass
            return JSONSerializer._dict_to_dataclass(parsed, target_type)
        
        return parsed
    
    @staticmethod
    def _dict_to_dataclass(data: Dict, target_type: Type) -> Any:
        """Конвертация словаря в dataclass"""
        if not isinstance(data, dict):
            return data
        
        # Обрабатываем специальные типы
        converted_data = {}
        for key, value in data.items():
            if isinstance(value, str):
                # Пытаемся конвертировать строки в Decimal
                try:
                    if '.' in value and value.replace('.', '').replace('-', '').isdigit():
                        converted_data[key] = Decimal(value)
                    else:
                        converted_data[key] = value
                except:
                    converted_data[key] = value
            else:
                converted_data[key] = value
        
        try:
            return target_type(**converted_data)
        except TypeError:
            # Если не получается создать dataclass, возвращаем словарь
            return converted_data


class FileRepository(IRepository[T], Generic[T]):
    """📁 Файловый репозиторий"""
    
    def __init__(
        self,
        entity_type: Type[T],
        config: RepositoryConfig,
        filename: Optional[str] = None
    ):
        self.entity_type = entity_type
        self.config = config
        self.filename = filename or f"{entity_type.__name__.lower()}s.json"
        
        # Создаем директорию
        self.storage_path = Path(config.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.file_path = self.storage_path / self.filename
        self.backup_path = self.storage_path / "backups"
        
        if config.backup_enabled:
            self.backup_path.mkdir(exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        self._lock = asyncio.Lock()
    
    async def save(self, entity: T) -> T:
        """💾 Сохранение сущности"""
        async with self._lock:
            entities = await self._load_all()
            
            # Получаем ID сущности
            entity_id = self._get_entity_id(entity)
            
            if entity_id is None:
                # Новая сущность - генерируем ID
                entity_id = self._generate_id(entities)
                self._set_entity_id(entity, entity_id)
            
            # Обновляем или добавляем
            entities[entity_id] = entity
            
            await self._save_all(entities)
            
            self.logger.debug(f"Сохранена сущность {self.entity_type.__name__} с ID {entity_id}")
            return entity
    
    async def find_by_id(self, entity_id: str) -> Optional[T]:
        """🔍 Поиск по ID"""
        entities = await self._load_all()
        return entities.get(entity_id)
    
    async def find_all(self) -> List[T]:
        """📋 Получение всех сущностей"""
        entities = await self._load_all()
        return list(entities.values())
    
    async def find_by_criteria(self, criteria: Dict[str, Any]) -> List[T]:
        """🔎 Поиск по критериям"""
        entities = await self.find_all()
        
        result = []
        for entity in entities:
            if self._matches_criteria(entity, criteria):
                result.append(entity)
        
        return result
    
    async def delete(self, entity_id: str) -> bool:
        """🗑️ Удаление сущности"""
        async with self._lock:
            entities = await self._load_all()
            
            if entity_id in entities:
                del entities[entity_id]
                await self._save_all(entities)
                self.logger.debug(f"Удалена сущность {self.entity_type.__name__} с ID {entity_id}")
                return True
            
            return False
    
    async def count(self) -> int:
        """🔢 Подсчет количества сущностей"""
        entities = await self._load_all()
        return len(entities)
    
    async def exists(self, entity_id: str) -> bool:
        """❓ Проверка существования"""
        entities = await self._load_all()
        return entity_id in entities
    
    async def backup(self) -> str:
        """💾 Создание резервной копии"""
        if not self.config.backup_enabled:
            return ""
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{self.filename}.{timestamp}.bak"
        backup_file = self.backup_path / backup_filename
        
        if self.file_path.exists():
        if self.file_path.exists():
            async with self._lock:
                # Копируем файл
                import shutil
                shutil.copy2(self.file_path, backup_file)
                
                self.logger.info(f"Создана резервная копия: {backup_filename}")
                return str(backup_file)
        
        return ""
    
    async def restore(self, backup_path: str) -> bool:
        """🔄 Восстановление из резервной копии"""
        try:
            backup_file = Path(backup_path)
            if not backup_file.exists():
                return False
            
            async with self._lock:
                # Создаем резервную копию текущего файла
                await self.backup()
                
                # Восстанавливаем из резервной копии
                import shutil
                shutil.copy2(backup_file, self.file_path)
                
                self.logger.info(f"Восстановлено из резервной копии: {backup_path}")
                return True
                
        except Exception as e:
            self.logger.error(f"Ошибка восстановления из {backup_path}: {e}")
            return False
    
    async def _load_all(self) -> Dict[str, T]:
        """📥 Загрузка всех данных"""
        try:
            if not self.file_path.exists():
                return {}
            
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = f.read()
            
            if not data.strip():
                return {}
            
            # Десериализуем данные
            raw_data = json.loads(data)
            
            if not isinstance(raw_data, dict):
                return {}
            
            # Конвертируем в объекты
            entities = {}
            for entity_id, entity_data in raw_data.items():
                try:
                    if hasattr(self.entity_type, '__dataclass_fields__'):
                        entity = JSONSerializer._dict_to_dataclass(entity_data, self.entity_type)
                    else:
                        entity = self.entity_type(**entity_data)
                    
                    entities[entity_id] = entity
                except Exception as e:
                    self.logger.warning(f"Не удалось загрузить сущность {entity_id}: {e}")
            
            return entities
            
        except Exception as e:
            self.logger.error(f"Ошибка загрузки данных из {self.file_path}: {e}")
            return {}
    
    async def _save_all(self, entities: Dict[str, T]) -> None:
        """💾 Сохранение всех данных"""
        try:
            # Конвертируем в сериализуемый формат
            serializable_data = {}
            for entity_id, entity in entities.items():
                if hasattr(entity, '__dataclass_fields__'):
                    serializable_data[entity_id] = asdict(entity)
                elif hasattr(entity, '__dict__'):
                    serializable_data[entity_id] = entity.__dict__
                else:
                    serializable_data[entity_id] = entity
            
            # Сериализуем в JSON
            json_data = JSONSerializer.serialize(serializable_data)
            
            # Атомарная запись через временный файл
            temp_file = self.file_path.with_suffix('.tmp')
            
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(json_data)
            
            # Атомарное переименование
            temp_file.replace(self.file_path)
            
        except Exception as e:
            self.logger.error(f"Ошибка сохранения данных в {self.file_path}: {e}")
            raise PersistenceError(f"Не удалось сохранить данные: {e}")
    
    def _get_entity_id(self, entity: T) -> Optional[str]:
        """🆔 Получение ID сущности"""
        if hasattr(entity, 'id'):
            return getattr(entity, 'id')
        elif hasattr(entity, 'trade_id'):
            return getattr(entity, 'trade_id')
        elif hasattr(entity, 'position_id'):
            return getattr(entity, 'position_id')
        return None
    
    def _set_entity_id(self, entity: T, entity_id: str) -> None:
        """🆔 Установка ID сущности"""
        if hasattr(entity, 'id'):
            setattr(entity, 'id', entity_id)
        elif hasattr(entity, 'trade_id'):
            setattr(entity, 'trade_id', entity_id)
        elif hasattr(entity, 'position_id'):
            setattr(entity, 'position_id', entity_id)
    
    def _generate_id(self, existing_entities: Dict[str, T]) -> str:
        """🔢 Генерация нового ID"""
        import uuid
        
        # Пытаемся использовать числовые ID если возможно
        if existing_entities:
            try:
                max_id = max(int(entity_id) for entity_id in existing_entities.keys() if entity_id.isdigit())
                return str(max_id + 1)
            except ValueError:
                pass
        
        # Используем UUID как fallback
        return str(uuid.uuid4())
    
    def _matches_criteria(self, entity: T, criteria: Dict[str, Any]) -> bool:
        """✅ Проверка соответствия критериям"""
        for key, expected_value in criteria.items():
            if not hasattr(entity, key):
                return False
            
            actual_value = getattr(entity, key)
            
            # Поддержка различных типов сравнения
            if isinstance(expected_value, dict):
                # Операторы сравнения
                for op, value in expected_value.items():
                    if op == '$eq' and actual_value != value:
                        return False
                    elif op == '$ne' and actual_value == value:
                        return False
                    elif op == '$gt' and actual_value <= value:
                        return False
                    elif op == '$gte' and actual_value < value:
                        return False
                    elif op == '$lt' and actual_value >= value:
                        return False
                    elif op == '$lte' and actual_value > value:
                        return False
                    elif op == '$in' and actual_value not in value:
                        return False
                    elif op == '$nin' and actual_value in value:
                        return False
            else:
                # Простое сравнение
                if actual_value != expected_value:
                    return False
        
        return True


class SQLiteRepository(IRepository[T], Generic[T]):
    """🗃️ SQLite репозиторий"""
    
    def __init__(
        self,
        entity_type: Type[T],
        config: RepositoryConfig,
        table_name: Optional[str] = None
    ):
        self.entity_type = entity_type
        self.config = config
        self.table_name = table_name or f"{entity_type.__name__.lower()}s"
        
        # Путь к базе данных
        self.storage_path = Path(config.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_path / "trading_bot.db"
        
        self.logger = logging.getLogger(__name__)
        
        # Инициализируем таблицу
        asyncio.create_task(self._init_table())
    
    async def _init_table(self) -> None:
        """🏗️ Инициализация таблицы"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Создаем таблицу на основе полей entity_type
                schema = self._generate_table_schema()
                
                await db.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        {schema}
                    )
                """)
                
                await db.commit()
                
        except Exception as e:
            self.logger.error(f"Ошибка инициализации таблицы {self.table_name}: {e}")
    
    def _generate_table_schema(self) -> str:
        """📋 Генерация схемы таблицы"""
        # Базовые поля
        fields = [
            "id TEXT PRIMARY KEY",
            "created_at TEXT NOT NULL",
            "updated_at TEXT NOT NULL",
            "data TEXT NOT NULL"  # JSON данные
        ]
        
        return ", ".join(fields)
    
    async def save(self, entity: T) -> T:
        """💾 Сохранение сущности"""
        entity_id = self._get_entity_id(entity)
        
        if entity_id is None:
            entity_id = self._generate_id()
            self._set_entity_id(entity, entity_id)
        
        # Сериализуем данные
        data = JSONSerializer.serialize(asdict(entity) if hasattr(entity, '__dataclass_fields__') else entity.__dict__)
        
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Проверяем существование записи
                cursor = await db.execute(
                    f"SELECT id FROM {self.table_name} WHERE id = ?",
                    (entity_id,)
                )
                exists = await cursor.fetchone()
                
                if exists:
                    # Обновляем существующую запись
                    await db.execute(f"""
                        UPDATE {self.table_name}
                        SET data = ?, updated_at = ?
                        WHERE id = ?
                    """, (data, now, entity_id))
                else:
                    # Создаем новую запись
                    await db.execute(f"""
                        INSERT INTO {self.table_name} (id, created_at, updated_at, data)
                        VALUES (?, ?, ?, ?)
                    """, (entity_id, now, now, data))
                
                await db.commit()
                
                self.logger.debug(f"Сохранена сущность {self.entity_type.__name__} с ID {entity_id}")
                return entity
                
        except Exception as e:
            self.logger.error(f"Ошибка сохранения сущности {entity_id}: {e}")
            raise PersistenceError(f"Не удалось сохранить сущность: {e}")
    
    async def find_by_id(self, entity_id: str) -> Optional[T]:
        """🔍 Поиск по ID"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    f"SELECT data FROM {self.table_name} WHERE id = ?",
                    (entity_id,)
                )
                row = await cursor.fetchone()
                
                if row:
                    return JSONSerializer.deserialize(row[0], self.entity_type)
                
                return None
                
        except Exception as e:
            self.logger.error(f"Ошибка поиска сущности {entity_id}: {e}")
            return None
    
    async def find_all(self) -> List[T]:
        """📋 Получение всех сущностей"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(f"SELECT data FROM {self.table_name}")
                rows = await cursor.fetchall()
                
                entities = []
                for row in rows:
                    try:
                        entity = JSONSerializer.deserialize(row[0], self.entity_type)
                        entities.append(entity)
                    except Exception as e:
                        self.logger.warning(f"Не удалось десериализовать сущность: {e}")
                
                return entities
                
        except Exception as e:
            self.logger.error(f"Ошибка получения всех сущностей: {e}")
            return []
    
    async def find_by_criteria(self, criteria: Dict[str, Any]) -> List[T]:
        """🔎 Поиск по критериям (простая реализация через JSON)"""
        # Для SQLite можно было бы использовать JSON операторы,
        # но для простоты загружаем все и фильтруем в памяти
        all_entities = await self.find_all()
        
        result = []
        for entity in all_entities:
            if self._matches_criteria(entity, criteria):
                result.append(entity)
        
        return result
    
    async def delete(self, entity_id: str) -> bool:
        """🗑️ Удаление сущности"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    f"DELETE FROM {self.table_name} WHERE id = ?",
                    (entity_id,)
                )
                await db.commit()
                
                deleted = cursor.rowcount > 0
                
                if deleted:
                    self.logger.debug(f"Удалена сущность {self.entity_type.__name__} с ID {entity_id}")
                
                return deleted
                
        except Exception as e:
            self.logger.error(f"Ошибка удаления сущности {entity_id}: {e}")
            return False
    
    async def count(self) -> int:
        """🔢 Подсчет количества сущностей"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(f"SELECT COUNT(*) FROM {self.table_name}")
                row = await cursor.fetchone()
                return row[0] if row else 0
                
        except Exception as e:
            self.logger.error(f"Ошибка подсчета сущностей: {e}")
            return 0
    
    async def exists(self, entity_id: str) -> bool:
        """❓ Проверка существования"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    f"SELECT 1 FROM {self.table_name} WHERE id = ? LIMIT 1",
                    (entity_id,)
                )
                row = await cursor.fetchone()
                return row is not None
                
        except Exception as e:
            self.logger.error(f"Ошибка проверки существования {entity_id}: {e}")
            return False
    
    def _get_entity_id(self, entity: T) -> Optional[str]:
        """🆔 Получение ID сущности"""
        if hasattr(entity, 'id'):
            return getattr(entity, 'id')
        elif hasattr(entity, 'trade_id'):
            return getattr(entity, 'trade_id')
        elif hasattr(entity, 'position_id'):
            return getattr(entity, 'position_id')
        return None
    
    def _set_entity_id(self, entity: T, entity_id: str) -> None:
        """🆔 Установка ID сущности"""
        if hasattr(entity, 'id'):
            setattr(entity, 'id', entity_id)
        elif hasattr(entity, 'trade_id'):
            setattr(entity, 'trade_id', entity_id)
        elif hasattr(entity, 'position_id'):
            setattr(entity, 'position_id', entity_id)
    
    def _generate_id(self) -> str:
        """🔢 Генерация нового ID"""
        import uuid
        return str(uuid.uuid4())
    
    def _matches_criteria(self, entity: T, criteria: Dict[str, Any]) -> bool:
        """✅ Проверка соответствия критериям"""
        for key, expected_value in criteria.items():
            if not hasattr(entity, key):
                return False
            
            actual_value = getattr(entity, key)
            
            if isinstance(expected_value, dict):
                for op, value in expected_value.items():
                    if op == '$eq' and actual_value != value:
                        return False
                    elif op == '$ne' and actual_value == value:
                        return False
                    elif op == '$gt' and actual_value <= value:
                        return False
                    elif op == '$gte' and actual_value < value:
                        return False
                    elif op == '$lt' and actual_value >= value:
                        return False
                    elif op == '$lte' and actual_value > value:
                        return False
                    elif op == '$in' and actual_value not in value:
                        return False
                    elif op == '$nin' and actual_value in value:
                        return False
            else:
                if actual_value != expected_value:
                    return False
        
        return True


class UnitOfWork(IUnitOfWork):
    """🔄 Unit of Work pattern для координации транзакций"""
    
    def __init__(self, repositories: Dict[str, IRepository]):
        self.repositories = repositories
        self._is_committed = False
        self._rollback_data: Dict[str, Any] = {}
        self.logger = logging.getLogger(__name__)
    
    async def __aenter__(self):
        """🚀 Начало транзакции"""
        await self._create_checkpoint()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """🏁 Завершение транзакции"""
        if exc_type is not None:
            # Произошла ошибка - откатываемся
            await self.rollback()
        elif not self._is_committed:
            # Автоматический commit если не было явного
            await self.commit()
    
    async def commit(self) -> None:
        """✅ Фиксация изменений"""
        try:
            # Все изменения уже сохранены в репозиториях
            # В данной реализации commit'им сразу
            self._is_committed = True
            self.logger.debug("Транзакция зафиксирована")
            
        except Exception as e:
            self.logger.error(f"Ошибка фиксации транзакции: {e}")
            await self.rollback()
            raise
    
    async def rollback(self) -> None:
        """🔄 Откат изменений"""
        try:
            # В простой файловой реализации откат сложен
            # Можно было бы восстанавливать из checkpoint'ов
            self.logger.warning("Откат транзакции (базовая реализация)")
            
        except Exception as e:
            self.logger.error(f"Ошибка отката транзакции: {e}")
    
    async def _create_checkpoint(self) -> None:
        """📸 Создание checkpoint'а для отката"""
        # Базовая реализация - сохраняем состояние для простых случаев
        pass
    
    def get_repository(self, entity_type: Type[T]) -> IRepository[T]:
        """📂 Получение репозитория по типу сущности"""
        repo_name = entity_type.__name__.lower()
        
        if repo_name not in self.repositories:
            raise ValueError(f"Репозиторий для {entity_type.__name__} не найден")
        
        return self.repositories[repo_name]


# Специализированные репозитории
class PositionRepository(FileRepository[Position]):
    """📊 Репозиторий позиций"""
    
    def __init__(self, config: RepositoryConfig):
        super().__init__(Position, config, "positions.json")
    
    async def find_by_currency(self, currency: str) -> Optional[Position]:
        """🔍 Поиск позиции по валюте"""
        positions = await self.find_by_criteria({"currency": currency})
        return positions[0] if positions else None
    
    async def find_active_positions(self) -> List[Position]:
        """📈 Поиск активных позиций"""
        return await self.find_by_criteria({"quantity": {"$gt": 0}})


class TradeRepository(FileRepository[TradeResult]):
    """📈 Репозиторий сделок"""
    
    def __init__(self, config: RepositoryConfig):
        super().__init__(TradeResult, config, "trades.json")
    
    async def find_by_date_range(self, start_date: datetime, end_date: datetime) -> List[TradeResult]:
        """📅 Поиск сделок по диапазону дат"""
        all_trades = await self.find_all()
        
        result = []
        for trade in all_trades:
            if hasattr(trade, 'timestamp'):
                trade_date = trade.timestamp
                if isinstance(trade_date, str):
                    trade_date = datetime.fromisoformat(trade_date.replace('Z', '+00:00'))
                
                if start_date <= trade_date <= end_date:
                    result.append(trade)
        
        return result
    
    async def find_by_pair(self, pair: str) -> List[TradeResult]:
        """💱 Поиск сделок по торговой паре"""
        return await self.find_by_criteria({"pair": pair})
    
    async def find_successful_trades(self) -> List[TradeResult]:
        """✅ Поиск успешных сделок"""
        return await self.find_by_criteria({"success": True})


class CSVExporter:
    """📊 Экспорт данных в CSV"""
    
    @staticmethod
    async def export_trades(trades: List[TradeResult], file_path: str) -> None:
        """📈 Экспорт сделок в CSV"""
        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['trade_id', 'pair', 'action', 'quantity', 'price', 'timestamp', 'success', 'profit']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for trade in trades:
                    writer.writerow({
                        'trade_id': getattr(trade, 'trade_id', ''),
                        'pair': getattr(trade, 'pair', ''),
                        'action': getattr(trade, 'action', ''),
                        'quantity': getattr(trade, 'quantity', ''),
                        'price': getattr(trade, 'price', ''),
                        'timestamp': getattr(trade, 'timestamp', ''),
                        'success': getattr(trade, 'success', ''),
                        'profit': getattr(trade, 'profit', '')
                    })
                    
        except Exception as e:
            logging.getLogger(__name__).error(f"Ошибка экспорта в CSV: {e}")
            raise PersistenceError(f"Не удалось экспортировать в CSV: {e}")
    
    @staticmethod
    async def export_positions(positions: List[Position], file_path: str) -> None:
        """📊 Экспорт позиций в CSV"""
        try:
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['position_id', 'currency', 'quantity', 'avg_price', 'total_cost', 'created_at']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for position in positions:
                    writer.writerow({
                        'position_id': getattr(position, 'position_id', ''),
                        'currency': getattr(position, 'currency', ''),
                        'quantity': getattr(position, 'quantity', ''),
                        'avg_price': getattr(position, 'avg_price', ''),
                        'total_cost': getattr(position, 'total_cost', ''),
                        'created_at': getattr(position, 'created_at', '')
                    })
                    
        except Exception as e:
            logging.getLogger(__name__).error(f"Ошибка экспорта позиций в CSV: {e}")
            raise PersistenceError(f"Не удалось экспортировать позиции в CSV: {e}")


# Фабрика репозиториев
class RepositoryFactory:
    """🏭 Фабрика репозиториев"""
    
    @staticmethod
    def create_repository(
        entity_type: Type[T],
        config: RepositoryConfig,
        storage_type: Optional[str] = None
    ) -> IRepository[T]:
        """🔨 Создание репозитория"""
        storage = storage_type or config.storage_type
        
        if storage == "json":
            return FileRepository(entity_type, config)
        elif storage == "sqlite":
            return SQLiteRepository(entity_type, config)
        else:
            raise ValueError(f"Неподдерживаемый тип хранилища: {storage}")
    
    @staticmethod
    def create_position_repository(config: RepositoryConfig) -> PositionRepository:
        """📊 Создание репозитория позиций"""
        return PositionRepository(config)
    
    @staticmethod
    def create_trade_repository(config: RepositoryConfig) -> TradeRepository:
        """📈 Создание репозитория сделок"""
        return TradeRepository(config)
    
    @staticmethod
    def create_unit_of_work(
        config: RepositoryConfig,
        entity_types: List[Type] = None
    ) -> UnitOfWork:
        """🔄 Создание Unit of Work"""
        entity_types = entity_types or [Position, TradeResult]
        
        repositories = {}
        for entity_type in entity_types:
            repo_name = entity_type.__name__.lower()
            repositories[repo_name] = RepositoryFactory.create_repository(entity_type, config)
        
        return UnitOfWork(repositories)
