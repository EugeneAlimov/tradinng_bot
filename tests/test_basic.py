import pytest
import asyncio


class TestBasicFunctionality:
    """Базовая функциональность"""
    
    def test_python_version(self):
        """Тест версии Python"""
        import sys
        assert sys.version_info >= (3, 8), "Требуется Python 3.8+"
    
    def test_imports(self):
        """Тест базовых импортов"""
        import json
        import asyncio
        import logging
        import pathlib
        assert True
    
    def test_async_support(self):
        """Тест поддержки async/await"""
        async def async_func():
            await asyncio.sleep(0.01)
            return "success"
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(async_func())
            assert result == "success"
        finally:
            loop.close()
    
    def test_json_operations(self):
        """Тест JSON операций"""
        import json
        
        test_data = {"test": "value", "number": 123}
        json_str = json.dumps(test_data)
        parsed_data = json.loads(json_str)
        
        assert parsed_data == test_data
    
    def test_file_operations(self, tmp_path):
        """Тест файловых операций"""
        import json
        
        test_file = tmp_path / "test.json"
        test_data = {"bot": "DOGE Trading Bot"}
        
        # Запись
        with open(test_file, 'w') as f:
            json.dump(test_data, f)
        
        # Чтение
        with open(test_file, 'r') as f:
            loaded_data = json.load(f)
        
        assert loaded_data == test_data


class TestConfiguration:
    """Тесты конфигурации"""
    
    def test_sample_config(self, sample_config):
        """Тест тестовой конфигурации"""
        assert sample_config["pair"] == "DOGE_EUR"
        assert sample_config["test_mode"] is True
    
    def test_sample_market_data(self, sample_market_data):
        """Тест тестовых данных"""
        assert sample_market_data["current_price"] > 0
        assert sample_market_data["balance"] > 0


@pytest.mark.asyncio
async def test_async_with_pytest():
    """Тест async функций с pytest-asyncio"""
    async def async_operation():
        await asyncio.sleep(0.01)
        return "async_result"
    
    result = await async_operation()
    assert result == "async_result"
