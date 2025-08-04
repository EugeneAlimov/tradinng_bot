#!/usr/bin/env python3
"""📊 Инвентаризация компонентов торговой системы - Этап 1.1"""

import os
import ast
import inspect
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class ComponentInfo:
    """📦 Информация о компоненте"""
    name: str
    file_path: str
    type: str  # class, function, module
    dependencies: Set[str] = field(default_factory=set)
    methods: List[str] = field(default_factory=list)
    attributes: List[str] = field(default_factory=list)
    imports: Set[str] = field(default_factory=set)
    size_lines: int = 0
    complexity_score: int = 0
    is_legacy: bool = True
    is_critical: bool = False


@dataclass
class DependencyGraph:
    """🔗 Граф зависимостей"""
    nodes: Dict[str, ComponentInfo] = field(default_factory=dict)
    edges: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    reverse_edges: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))


class ComponentInventory:
    """📊 Инвентаризатор компонентов"""
    
    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path)
        self.components: Dict[str, ComponentInfo] = {}
        self.dependency_graph = DependencyGraph()
        
        # Критические компоненты (ядро системы)
        self.critical_components = {
            'TradingBot', 'HybridTradingBot', 'ImprovedTradingBot',
            'TradeOrchestrator', 'StrategyManager', 'APIService',
            'PositionManager', 'RiskManager', 'ExmoAPIClient'
        }
        
        # Паттерны для определения legacy кода
        self.legacy_patterns = {
            'improved_bot.py', 'hybrid_bot.py', 'bot.py',
            'trade_orchestrator.py', 'strategies.py'
        }
    
    def analyze_project(self) -> Dict[str, Any]:
        """🔍 Полный анализ проекта"""
        print("📊 Начинаем инвентаризацию компонентов...")
        
        # 1. Сканируем файлы
        self._scan_python_files()
        
        # 2. Анализируем зависимости
        self._analyze_dependencies()
        
        # 3. Строим граф
        self._build_dependency_graph()
        
        # 4. Рассчитываем метрики
        metrics = self._calculate_metrics()
        
        # 5. Выявляем проблемы
        issues = self._identify_issues()
        
        # 6. Генерируем отчет
        report = self._generate_report(metrics, issues)
        
        print("✅ Инвентаризация завершена")
        return report
    
    def _scan_python_files(self) -> None:
        """📂 Сканирование Python файлов"""
        python_files = list(self.root_path.rglob("*.py"))
        excluded_patterns = {'__pycache__', '.git', 'venv', 'env'}
        
        for file_path in python_files:
            # Пропускаем служебные директории
            if any(pattern in str(file_path) for pattern in excluded_patterns):
                continue
                
            try:
                self._analyze_file(file_path)
            except Exception as e:
                print(f"⚠️ Ошибка анализа {file_path}: {e}")
    
    def _analyze_file(self, file_path: Path) -> None:
        """📄 Анализ отдельного файла"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            tree = ast.parse(content)
            
            # Анализируем классы
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    self._analyze_class(node, file_path, content)
                elif isinstance(node, ast.FunctionDef):
                    if not self._is_method(node, tree):
                        self._analyze_function(node, file_path)
                        
        except SyntaxError as e:
            print(f"⚠️ Синтаксическая ошибка в {file_path}: {e}")
        except Exception as e:
            print(f"⚠️ Ошибка чтения {file_path}: {e}")
    
    def _analyze_class(self, node: ast.ClassDef, file_path: Path, content: str) -> None:
        """🏗️ Анализ класса"""
        component_info = ComponentInfo(
            name=node.name,
            file_path=str(file_path),
            type="class",
            size_lines=len(content.split('\n')),
            is_legacy=file_path.name in self.legacy_patterns,
            is_critical=node.name in self.critical_components
        )
        
        # Методы
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                component_info.methods.append(item.name)
        
        # Атрибуты (приблизительно)
        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        component_info.attributes.append(target.id)
        
        # Базовые классы (зависимости)
        for base in node.bases:
            if isinstance(base, ast.Name):
                component_info.dependencies.add(base.id)
        
        # Импорты из файла
        component_info.imports = self._extract_imports(file_path)
        
        # Сложность (примерная)
        component_info.complexity_score = self._calculate_complexity(node)
        
        self.components[f"{file_path.stem}.{node.name}"] = component_info
    
    def _analyze_function(self, node: ast.FunctionDef, file_path: Path) -> None:
        """⚙️ Анализ функции"""
        component_info = ComponentInfo(
            name=node.name,
            file_path=str(file_path),
            type="function",
            is_legacy=file_path.name in self.legacy_patterns,
            complexity_score=len(node.body)
        )
        
        self.components[f"{file_path.stem}.{node.name}"] = component_info
    
    def _extract_imports(self, file_path: Path) -> Set[str]:
        """📥 Извлечение импортов"""
        imports = set()
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.add(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.add(node.module)
                        
        except Exception:
            pass
            
        return imports
    
    def _is_method(self, node: ast.FunctionDef, tree: ast.Module) -> bool:
        """🔍 Проверка является ли функция методом класса"""
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef):
                if node in parent.body:
                    return True
        return False
    
    def _calculate_complexity(self, node: ast.AST) -> int:
        """📊 Расчет сложности (McCabe)"""
        complexity = 1  # Базовая сложность
        
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.With)):
                complexity += 1
            elif isinstance(child, ast.Try):
                complexity += len(child.handlers)
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
                
        return complexity
    
    def _analyze_dependencies(self) -> None:
        """🔗 Анализ зависимостей между компонентами"""
        for comp_name, component in self.components.items():
            # Анализируем импорты как зависимости
            for import_name in component.imports:
                # Ищем соответствующие компоненты
                for other_name, other_comp in self.components.items():
                    if (import_name in other_comp.file_path or 
                        import_name == other_comp.name):
                        component.dependencies.add(other_name)
    
    def _build_dependency_graph(self) -> None:
        """🕸️ Построение графа зависимостей"""
        self.dependency_graph.nodes = self.components.copy()
        
        for comp_name, component in self.components.items():
            for dep in component.dependencies:
                if dep in self.components:
                    self.dependency_graph.edges[comp_name].add(dep)
                    self.dependency_graph.reverse_edges[dep].add(comp_name)
    
    def _calculate_metrics(self) -> Dict[str, Any]:
        """📈 Расчет метрик"""
        total_components = len(self.components)
        legacy_components = sum(1 for c in self.components.values() if c.is_legacy)
        critical_components = sum(1 for c in self.components.values() if c.is_critical)
        
        # Сложность
        total_complexity = sum(c.complexity_score for c in self.components.values())
        avg_complexity = total_complexity / max(total_components, 1)
        
        # Размеры
        total_lines = sum(c.size_lines for c in self.components.values())
        avg_size = total_lines / max(total_components, 1)
        
        # Связанность
        total_dependencies = sum(len(c.dependencies) for c in self.components.values())
        avg_dependencies = total_dependencies / max(total_components, 1)
        
        return {
            'total_components': total_components,
            'legacy_components': legacy_components,
            'critical_components': critical_components,
            'legacy_percentage': (legacy_components / max(total_components, 1)) * 100,
            'total_complexity': total_complexity,
            'avg_complexity': round(avg_complexity, 2),
            'total_lines': total_lines,
            'avg_component_size': round(avg_size, 2),
            'total_dependencies': total_dependencies,
            'avg_dependencies': round(avg_dependencies, 2),
            'coupling_ratio': round(avg_dependencies / max(total_components, 1), 3)
        }
    
    def _identify_issues(self) -> Dict[str, List[str]]:
        """🚨 Выявление проблем"""
        issues = {
            'high_complexity': [],
            'large_components': [],
            'high_coupling': [],
            'circular_dependencies': [],
            'missing_dependencies': [],
            'legacy_critical': []
        }
        
        for name, component in self.components.items():
            # Высокая сложность
            if component.complexity_score > 20:
                issues['high_complexity'].append(f"{name} (сложность: {component.complexity_score})")
            
            # Большие компоненты
            if component.size_lines > 500:
                issues['large_components'].append(f"{name} ({component.size_lines} строк)")
            
            # Высокая связанность
            if len(component.dependencies) > 10:
                issues['high_coupling'].append(f"{name} ({len(component.dependencies)} зависимостей)")
            
            # Критический legacy код
            if component.is_critical and component.is_legacy:
                issues['legacy_critical'].append(name)
        
        # Поиск циклических зависимостей (упрощенный)
        issues['circular_dependencies'] = self._find_circular_dependencies()
        
        return issues
    
    def _find_circular_dependencies(self) -> List[str]:
        """🔄 Поиск циклических зависимостей"""
        cycles = []
        visited = set()
        path = []
        
        def dfs(node: str) -> None:
            if node in path:
                cycle_start = path.index(node)
                cycle = " -> ".join(path[cycle_start:] + [node])
                cycles.append(cycle)
                return
            
            if node in visited:
                return
                
            visited.add(node)
            path.append(node)
            
            for neighbor in self.dependency_graph.edges.get(node, []):
                dfs(neighbor)
            
            path.pop()
        
        for node in self.components:
            if node not in visited:
                dfs(node)
        
        return cycles[:5]  # Первые 5 циклов
    
    def _generate_report(self, metrics: Dict[str, Any], issues: Dict[str, List[str]]) -> Dict[str, Any]:
        """📋 Генерация отчета"""
        
        # Топ компонентов по различным критериям
        top_complex = sorted(
            self.components.items(),
            key=lambda x: x[1].complexity_score,
            reverse=True
        )[:5]
        
        top_large = sorted(
            self.components.items(),
            key=lambda x: x[1].size_lines,
            reverse=True
        )[:5]
        
        top_coupled = sorted(
            self.components.items(),
            key=lambda x: len(x[1].dependencies),
            reverse=True
        )[:5]
        
        return {
            'timestamp': str(Path.cwd()),
            'metrics': metrics,
            'issues': issues,
            'top_rankings': {
                'most_complex': [(name, comp.complexity_score) for name, comp in top_complex],
                'largest': [(name, comp.size_lines) for name, comp in top_large],
                'most_coupled': [(name, len(comp.dependencies)) for name, comp in top_coupled]
            },
            'components_by_type': {
                'classes': [name for name, comp in self.components.items() if comp.type == 'class'],
                'functions': [name for name, comp in self.components.items() if comp.type == 'function']
            },
            'critical_path': self._identify_critical_path(),
            'migration_recommendations': self._generate_migration_recommendations()
        }
    
    def _identify_critical_path(self) -> List[str]:
        """🎯 Определение критического пути"""
        critical_components = [
            name for name, comp in self.components.items() 
            if comp.is_critical
        ]
        
        # Сортируем по количеству зависимостей (важность)
        critical_path = sorted(
            critical_components,
            key=lambda x: len(self.dependency_graph.reverse_edges.get(x, set())),
            reverse=True
        )
        
        return critical_path[:10]
    
    def _generate_migration_recommendations(self) -> List[str]:
        """💡 Рекомендации по миграции"""
        recommendations = []
        
        # На основе анализа
        if len([c for c in self.components.values() if c.is_legacy]) > 10:
            recommendations.append("Создать адаптеры для legacy компонентов")
        
        if any(len(c.dependencies) > 15 for c in self.components.values()):
            recommendations.append("Разбить высокосвязанные компоненты")
        
        if any(c.size_lines > 1000 for c in self.components.values()):
            recommendations.append("Разбить большие классы на модули")
        
        recommendations.extend([
            "Реализовать слой абстракций (interfaces)",
            "Создать dependency injection контейнер", 
            "Добавить unit тесты для критических компонентов",
            "Внедрить логирование и мониторинг"
        ])
        
        return recommendations
    
    def save_report(self, report: Dict[str, Any], output_file: str = "component_inventory_report.json") -> None:
        """💾 Сохранение отчета"""
        import json
        
        # Конвертируем sets в lists для JSON сериализации
        def convert_sets(obj):
            if isinstance(obj, set):
                return list(obj)
            elif isinstance(obj, dict):
                return {k: convert_sets(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_sets(item) for item in obj]
            return obj
        
        json_report = convert_sets(report)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(json_report, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Отчет сохранен в {output_file}")


def main():
    """🚀 Главная функция"""
    inventory = ComponentInventory()
    report = inventory.analyze_project()
    
    # Печатаем краткий отчет
    print("\n" + "="*60)
    print("📊 КРАТКИЙ ОТЧЕТ ПО КОМПОНЕНТАМ")
    print("="*60)
    
    metrics = report['metrics']
    print(f"📦 Всего компонентов: {metrics['total_components']}")
    print(f"📜 Legacy компонентов: {metrics['legacy_components']} ({metrics['legacy_percentage']:.1f}%)")
    print(f"🎯 Критических: {metrics['critical_components']}")
    print(f"📏 Средний размер: {metrics['avg_component_size']:.0f} строк")
    print(f"🔗 Средняя связанность: {metrics['avg_dependencies']:.2f}")
    print(f"⚙️ Общая сложность: {metrics['total_complexity']}")
    
    # Проблемы
    issues = report['issues']
    print(f"\n🚨 ВЫЯВЛЕННЫЕ ПРОБЛЕМЫ:")
    for issue_type, items in issues.items():
        if items:
            print(f"  {issue_type}: {len(items)}")
    
    # Критический путь
    print(f"\n🎯 КРИТИЧЕСКИЙ ПУТЬ:")
    for i, comp in enumerate(report['critical_path'][:5], 1):
        print(f"  {i}. {comp}")
    
    # Рекомендации
    print(f"\n💡 РЕКОМЕНДАЦИИ:")
    for i, rec in enumerate(report['migration_recommendations'][:5], 1):
        print(f"  {i}. {rec}")
    
    # Сохраняем полный отчет
    inventory.save_report(report)
    
    return report


if __name__ == "__main__":
    main()