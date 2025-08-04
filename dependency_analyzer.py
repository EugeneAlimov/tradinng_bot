#!/usr/bin/env python3
"""🔗 Анализатор зависимостей и критического пути - Этап 1.3"""

import ast
import os
from pathlib import Path
from typing import Dict, List, Set, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
import json


@dataclass
class DependencyInfo:
    """🔗 Информация о зависимости"""
    source: str
    target: str
    dependency_type: str  # import, inheritance, composition, call
    location: str  # file:line
    strength: int = 1  # сила зависимости (1-3)
    is_critical: bool = False


@dataclass
class ComponentNode:
    """📦 Узел компонента в графе"""
    name: str
    file_path: str
    component_type: str  # class, function, module
    incoming: Set[str] = field(default_factory=set)
    outgoing: Set[str] = field(default_factory=set)
    depth: int = 0
    is_critical: bool = False
    cyclic_group: int = -1


class DependencyAnalyzer:
    """🔗 Анализатор зависимостей"""
    
    def __init__(self, root_path: str = "."):
        self.root_path = Path(root_path)
        self.components: Dict[str, ComponentNode] = {}
        self.dependencies: List[DependencyInfo] = []
        self.modules: Dict[str, Set[str]] = defaultdict(set)  # модуль -> классы/функции
        
        # Критические компоненты
        self.critical_components = {
            'TradingBot', 'HybridTradingBot', 'ImprovedTradingBot',
            'TradeOrchestrator', 'StrategyManager', 'ExmoAPIClient',
            'PositionManager', 'RiskManager', 'APIService'
        }
    
    def analyze_dependencies(self) -> Dict[str, Any]:
        """🔍 Полный анализ зависимостей"""
        print("🔗 Анализируем зависимости...")
        
        # 1. Сканируем файлы и строим граф
        self._scan_project_files()
        
        # 2. Анализируем импорты
        self._analyze_imports()
        
        # 3. Анализируем наследование
        self._analyze_inheritance()
        
        # 4. Анализируем композицию
        self._analyze_composition()
        
        # 5. Анализируем вызовы методов
        self._analyze_method_calls()
        
        # 6. Находим циклические зависимости
        cycles = self._find_cycles()
        
        # 7. Определяем критический путь
        critical_path = self._find_critical_path()
        
        # 8. Рассчитываем метрики
        metrics = self._calculate_metrics()
        
        # 9. Генерируем рекомендации
        recommendations = self._generate_recommendations(cycles, critical_path)
        
        return {
            'components': {name: self._node_to_dict(node) for name, node in self.components.items()},
            'dependencies': [self._dependency_to_dict(dep) for dep in self.dependencies],
            'cycles': cycles,
            'critical_path': critical_path,
            'metrics': metrics,
            'recommendations': recommendations,
            'migration_order': self._calculate_migration_order()
        }
    
    def _scan_project_files(self) -> None:
        """📂 Сканирование файлов проекта"""
        python_files = list(self.root_path.rglob("*.py"))
        excluded = {'__pycache__', '.git', 'venv', 'env', 'tests'}
        
        for file_path in python_files:
            if any(ex in str(file_path) for ex in excluded):
                continue
                
            try:
                self._process_file(file_path)
            except Exception as e:
                print(f"⚠️ Ошибка обработки {file_path}: {e}")
    
    def _process_file(self, file_path: Path) -> None:
        """📄 Обработка отдельного файла"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            module_name = file_path.stem
            
            # Анализируем классы и функции
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    component_name = f"{module_name}.{node.name}"
                    self.components[component_name] = ComponentNode(
                        name=node.name,
                        file_path=str(file_path),
                        component_type="class",
                        is_critical=node.name in self.critical_components
                    )
                    self.modules[module_name].add(node.name)
                    
                elif isinstance(node, ast.FunctionDef):
                    # Только функции верхнего уровня
                    if self._is_top_level_function(node, tree):
                        component_name = f"{module_name}.{node.name}"
                        self.components[component_name] = ComponentNode(
                            name=node.name,
                            file_path=str(file_path),
                            component_type="function"
                        )
                        self.modules[module_name].add(node.name)
            
        except Exception as e:
            print(f"⚠️ Ошибка парсинга {file_path}: {e}")
    
    def _is_top_level_function(self, func_node: ast.FunctionDef, tree: ast.Module) -> bool:
        """🔍 Проверка функции верхнего уровня"""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if func_node in node.body:
                    return False
        return True
    
    def _analyze_imports(self) -> None:
        """📥 Анализ импортов"""
        for file_path in self.root_path.rglob("*.py"):
            if any(ex in str(file_path) for ex in ['__pycache__', '.git', 'venv']):
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                module_name = file_path.stem
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            self._add_import_dependency(
                                module_name, alias.name, f"{file_path}:{node.lineno}"
                            )
                    
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            self._add_import_dependency(
                                module_name, node.module, f"{file_path}:{node.lineno}"
                            )
                        
                        # Импорт конкретных классов/функций
                        for alias in node.names:
                            if node.module and alias.name != '*':
                                target = f"{node.module}.{alias.name}"
                                self._add_import_dependency(
                                    module_name, target, f"{file_path}:{node.lineno}", 
                                    strength=2
                                )
                        
            except Exception as e:
                print(f"⚠️ Ошибка анализа импортов {file_path}: {e}")
    
    def _add_import_dependency(self, source_module: str, target: str, location: str, strength: int = 1) -> None:
        """➕ Добавление зависимости импорта"""
        # Ищем компоненты в source модуле
        source_components = self.modules.get(source_module, {source_module})
        
        for source_comp in source_components:
            source_key = f"{source_module}.{source_comp}" if source_comp != source_module else source_module
            
            # Определяем target компонент
            if '.' in target:
                target_module, target_comp = target.rsplit('.', 1)
                target_key = target
            else:
                target_key = target
                target_comp = target
            
            # Проверяем существование компонентов
            if source_key in self.components or target_key in self.components:
                dependency = DependencyInfo(
                    source=source_key,
                    target=target_key,
                    dependency_type="import",
                    location=location,
                    strength=strength,
                    is_critical=(source_comp in self.critical_components or 
                               target_comp in self.critical_components)
                )
                self.dependencies.append(dependency)
                
                # Обновляем граф
                if source_key in self.components:
                    self.components[source_key].outgoing.add(target_key)
                if target_key in self.components:
                    self.components[target_key].incoming.add(source_key)
    
    def _analyze_inheritance(self) -> None:
        """🧬 Анализ наследования"""
        for file_path in self.root_path.rglob("*.py"):
            if any(ex in str(file_path) for ex in ['__pycache__', '.git', 'venv']):
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                module_name = file_path.stem
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.bases:
                        class_name = f"{module_name}.{node.name}"
                        
                        for base in node.bases:
                            base_name = self._resolve_name(base, tree)
                            if base_name:
                                dependency = DependencyInfo(
                                    source=class_name,
                                    target=base_name,
                                    dependency_type="inheritance",
                                    location=f"{file_path}:{node.lineno}",
                                    strength=3,  # Наследование - сильная зависимость
                                    is_critical=True
                                )
                                self.dependencies.append(dependency)
                                
                                # Обновляем граф
                                if class_name in self.components:
                                    self.components[class_name].outgoing.add(base_name)
                                if base_name in self.components:
                                    self.components[base_name].incoming.add(class_name)
                        
            except Exception as e:
                print(f"⚠️ Ошибка анализа наследования {file_path}: {e}")
    
    def _analyze_composition(self) -> None:
        """🏗️ Анализ композиции"""
        for file_path in self.root_path.rglob("*.py"):
            if any(ex in str(file_path) for ex in ['__pycache__', '.git', 'venv']):
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                module_name = file_path.stem
                
                # Анализируем присваивания в __init__ методах
                for class_node in ast.walk(tree):
                    if isinstance(class_node, ast.ClassDef):
                        class_name = f"{module_name}.{class_node.name}"
                        
                        for method in class_node.body:
                            if (isinstance(method, ast.FunctionDef) and 
                                method.name == '__init__'):
                                
                                self._analyze_init_method(
                                    method, class_name, file_path, tree
                                )
                        
            except Exception as e:
                print(f"⚠️ Ошибка анализа композиции {file_path}: {e}")
    
    def _analyze_init_method(self, init_node: ast.FunctionDef, class_name: str, 
                           file_path: Path, tree: ast.Module) -> None:
        """🔧 Анализ __init__ метода"""
        for node in ast.walk(init_node):
            if isinstance(node, ast.Assign):
                # Ищем присваивания вида self.attr = SomeClass()
                for target in node.targets:
                    if (isinstance(target, ast.Attribute) and
                        isinstance(target.value, ast.Name) and
                        target.value.id == 'self'):
                        
                        # Анализируем правую часть присваивания
                        if isinstance(node.value, ast.Call):
                            func_name = self._resolve_name(node.value.func, tree)
                            if func_name and func_name != class_name:
                                dependency = DependencyInfo(
                                    source=class_name,
                                    target=func_name,
                                    dependency_type="composition",
                                    location=f"{file_path}:{node.lineno}",
                                    strength=2,
                                    is_critical=func_name.split('.')[-1] in self.critical_components
                                )
                                self.dependencies.append(dependency)
                                
                                # Обновляем граф
                                if class_name in self.components:
                                    self.components[class_name].outgoing.add(func_name)
                                if func_name in self.components:
                                    self.components[func_name].incoming.add(class_name)
    
    def _analyze_method_calls(self) -> None:
        """📞 Анализ вызовов методов"""
        for file_path in self.root_path.rglob("*.py"):
            if any(ex in str(file_path) for ex in ['__pycache__', '.git', 'venv']):
                continue
                
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                tree = ast.parse(content)
                module_name = file_path.stem
                
                # Анализируем только критические вызовы
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func_name = self._resolve_name(node.func, tree)
                        if func_name and any(crit in func_name for crit in self.critical_components):
                            # Определяем источник вызова
                            source = self._find_containing_component(node, tree, module_name)
                            if source and source != func_name:
                                dependency = DependencyInfo(
                                    source=source,
                                    target=func_name,
                                    dependency_type="call",
                                    location=f"{file_path}:{node.lineno}",
                                    strength=1,
                                    is_critical=True
                                )
                                self.dependencies.append(dependency)
                        
            except Exception as e:
                print(f"⚠️ Ошибка анализа вызовов {file_path}: {e}")
    
    def _resolve_name(self, node: ast.AST, tree: ast.Module) -> str:
        """🔍 Разрешение имени узла AST"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value = self._resolve_name(node.value, tree)
            return f"{value}.{node.attr}" if value else None
        return None
    
    def _find_containing_component(self, node: ast.AST, tree: ast.Module, module_name: str) -> str:
        """🔍 Поиск содержащего компонента"""
        # Простая эвристика - ищем класс или функцию, содержащую узел
        for class_node in ast.walk(tree):
            if isinstance(class_node, ast.ClassDef):
                for child in ast.walk(class_node):
                    if child is node:
                        return f"{module_name}.{class_node.name}"
        
        for func_node in ast.walk(tree):
            if isinstance(func_node, ast.FunctionDef):
                for child in ast.walk(func_node):
                    if child is node:
                        if self._is_top_level_function(func_node, tree):
                            return f"{module_name}.{func_node.name}"
                        else:
                            # Метод класса - ищем класс
                            for class_node in ast.walk(tree):
                                if isinstance(class_node, ast.ClassDef):
                                    if func_node in class_node.body:
                                        return f"{module_name}.{class_node.name}"
        
        return module_name
    
    def _find_cycles(self) -> List[Dict[str, Any]]:
        """🔄 Поиск циклических зависимостей"""
        cycles = []
        visited = set()
        path = []
        path_set = set()
        
        def dfs(node: str) -> None:
            if node in path_set:
                # Найден цикл
                cycle_start = path.index(node)
                cycle_nodes = path[cycle_start:] + [node]
                
                # Вычисляем силу цикла
                cycle_strength = 0
                cycle_types = set()
                for i in range(len(cycle_nodes) - 1):
                    source, target = cycle_nodes[i], cycle_nodes[i + 1]
                    for dep in self.dependencies:
                        if dep.source == source and dep.target == target:
                            cycle_strength += dep.strength
                            cycle_types.add(dep.dependency_type)
                
                cycles.append({
                    'nodes': cycle_nodes,
                    'length': len(cycle_nodes) - 1,
                    'strength': cycle_strength,
                    'types': list(cycle_types),
                    'is_critical': any(self.components.get(n, ComponentNode("", "", "")).is_critical 
                                     for n in cycle_nodes[:-1])
                })
                return
            
            if node in visited:
                return
                
            visited.add(node)
            path.append(node)
            path_set.add(node)
            
            # Идем по исходящим зависимостям
            node_obj = self.components.get(node)
            if node_obj:
                for neighbor in node_obj.outgoing:
                    if neighbor in self.components:
                        dfs(neighbor)
            
            path.pop()
            path_set.remove(node)
        
        # Запускаем DFS для всех компонентов
        for component in self.components:
            if component not in visited:
                dfs(component)
        
        # Сортируем циклы по важности
        cycles.sort(key=lambda c: (c['is_critical'], c['strength'], c['length']), reverse=True)
        
        return cycles[:10]  # Топ 10 циклов
    
    def _find_critical_path(self) -> List[str]:
        """🎯 Поиск критического пути"""
        # Критический путь = цепочка наиболее важных компонентов
        critical_components = [
            name for name, comp in self.components.items() 
            if comp.is_critical
        ]
        
        # Используем топологическую сортировку с весами
        in_degree = {}
        for comp in critical_components:
            in_degree[comp] = len(self.components[comp].incoming & set(critical_components))
        
        # Сортируем по входящей степени (основы системы идут первыми)
        path = sorted(critical_components, key=lambda x: in_degree[x])
        
        return path
    
    def _calculate_metrics(self) -> Dict[str, Any]:
        """📊 Расчет метрик"""
        total_components = len(self.components)
        total_dependencies = len(self.dependencies)
        
        if total_components == 0:
            return {'error': 'No components found'}
        
        # Связанность
        avg_outgoing = sum(len(comp.outgoing) for comp in self.components.values()) / total_components
        avg_incoming = sum(len(comp.incoming) for comp in self.components.values()) / total_components
        
        # Сложность зависимостей
        dependency_strength = sum(dep.strength for dep in self.dependencies)
        avg_strength = dependency_strength / max(total_dependencies, 1)
        
        # Критические метрики
        critical_count = sum(1 for comp in self.components.values() if comp.is_critical)
        critical_deps = sum(1 for dep in self.dependencies if dep.is_critical)
        
        return {
            'total_components': total_components,
            'total_dependencies': total_dependencies,
            'avg_outgoing_dependencies': round(avg_outgoing, 2),
            'avg_incoming_dependencies': round(avg_incoming, 2),
            'coupling_ratio': round(total_dependencies / total_components, 2),
            'dependency_strength': dependency_strength,
            'avg_dependency_strength': round(avg_strength, 2),
            'critical_components': critical_count,
            'critical_dependencies': critical_deps,
            'critical_coupling': round(critical_deps / max(critical_count, 1), 2),
            'dependency_types': {
                dep_type: sum(1 for dep in self.dependencies if dep.dependency_type == dep_type)
                for dep_type in ['import', 'inheritance', 'composition', 'call']
            }
        }
    
    def _calculate_migration_order(self) -> List[Dict[str, Any]]:
        """📋 Расчет порядка миграции"""
        # Топологическая сортировка с учетом критичности
        
        # 1. Вычисляем входящую степень
        in_degree = {comp: len(node.incoming) for comp, node in self.components.items()}
        
        # 2. Находим компоненты без входящих зависимостей
        queue = deque([comp for comp, degree in in_degree.items() if degree == 0])
        
        migration_order = []
        processed = set()
        
        while queue:
            # Сортируем очередь по критичности и алфавиту
            current_batch = list(queue)
            queue.clear()
            
            # Критические компоненты идут первыми в каждом батче
            current_batch.sort(key=lambda x: (
                not self.components[x].is_critical,  # Критические первыми
                x  # Алфавитный порядок
            ))
            
            batch_info = {
                'batch_id': len(migration_order) + 1,
                'components': [],
                'can_parallel': True,
                'estimated_effort': 0
            }
            
            for component in current_batch:
                comp_node = self.components[component]
                
                # Примерная оценка сложности
                effort_score = (
                    len(comp_node.incoming) * 2 +  # Входящие зависимости
                    len(comp_node.outgoing) +      # Исходящие зависимости
                    (10 if comp_node.is_critical else 5)  # Базовая сложность
                )
                
                batch_info['components'].append({
                    'name': component,
                    'type': comp_node.component_type,
                    'file_path': comp_node.file_path,
                    'is_critical': comp_node.is_critical,
                    'effort_score': effort_score,
                    'dependencies_count': len(comp_node.incoming)
                })
                
                batch_info['estimated_effort'] += effort_score
                processed.add(component)
                
                # Обновляем входящую степень соседей
                for neighbor in comp_node.outgoing:
                    if neighbor in in_degree:
                        in_degree[neighbor] -= 1
                        if in_degree[neighbor] == 0 and neighbor not in processed:
                            queue.append(neighbor)
            
            if batch_info['components']:
                migration_order.append(batch_info)
        
        # Обработка оставшихся компонентов (в циклах)
        remaining = set(self.components.keys()) - processed
        if remaining:
            cycle_batch = {
                'batch_id': len(migration_order) + 1,
                'components': [
                    {
                        'name': comp,
                        'type': self.components[comp].component_type,
                        'file_path': self.components[comp].file_path,
                        'is_critical': self.components[comp].is_critical,
                        'effort_score': 15,  # Высокая сложность из-за циклов
                        'dependencies_count': len(self.components[comp].incoming),
                        'note': 'В циклической зависимости'
                    }
                    for comp in remaining
                ],
                'can_parallel': False,
                'estimated_effort': len(remaining) * 15,
                'note': 'Компоненты с циклическими зависимостями'
            }
            migration_order.append(cycle_batch)
        
        return migration_order
    
    def _generate_recommendations(self, cycles: List[Dict], critical_path: List[str]) -> List[str]:
        """💡 Генерация рекомендаций"""
        recommendations = []
        
        # Рекомендации по циклам
        if cycles:
            recommendations.append(f"🔄 Найдено {len(cycles)} циклических зависимостей - требуют рефакторинга")
            
            critical_cycles = [c for c in cycles if c['is_critical']]
            if critical_cycles:
                recommendations.append(f"🚨 {len(critical_cycles)} критических циклов требуют немедленного внимания")
        
        # Рекомендации по связанности
        high_coupling = [
            name for name, comp in self.components.items()
            if len(comp.outgoing) > 10
        ]
        if high_coupling:
            recommendations.append(f"🔗 {len(high_coupling)} компонентов с высокой связанностью (>10 зависимостей)")
        
        # Рекомендации по критическому пути
        if len(critical_path) > 15:
            recommendations.append("🎯 Критический путь слишком длинный - рассмотрите разделение на модули")
        
        # Общие рекомендации
        metrics = self._calculate_metrics()
        if metrics.get('coupling_ratio', 0) > 3:
            recommendations.append("📊 Высокий коэффициент связанности - нужна декомпозиция")
        
        recommendations.extend([
            "🏗️ Создайте интерфейсы для слабой связанности",
            "💉 Внедрите dependency injection для управления зависимостями",
            "🧪 Добавьте unit тесты для компонентов с высокой связанностью",
            "📦 Рассмотрите паттерн Adapter для legacy компонентов"
        ])
        
        return recommendations
    
    def _node_to_dict(self, node: ComponentNode) -> Dict[str, Any]:
        """📄 Конвертация узла в словарь"""
        return {
            'name': node.name,
            'file_path': node.file_path,
            'component_type': node.component_type,
            'incoming_count': len(node.incoming),
            'outgoing_count': len(node.outgoing),
            'incoming': list(node.incoming),
            'outgoing': list(node.outgoing),
            'is_critical': node.is_critical,
            'depth': node.depth,
            'cyclic_group': node.cyclic_group
        }
    
    def _dependency_to_dict(self, dep: DependencyInfo) -> Dict[str, Any]:
        """📄 Конвертация зависимости в словарь"""
        return {
            'source': dep.source,
            'target': dep.target,
            'type': dep.dependency_type,
            'location': dep.location,
            'strength': dep.strength,
            'is_critical': dep.is_critical
        }
    
    def save_analysis(self, analysis: Dict[str, Any], output_file: str = "dependency_analysis.json") -> None:
        """💾 Сохранение анализа"""
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(analysis, f, indent=2, ensure_ascii=False)
        
        print(f"📄 Анализ зависимостей сохранен в {output_file}")


def main():
    """🚀 Главная функция"""
    analyzer = DependencyAnalyzer()
    analysis = analyzer.analyze_dependencies()
    
    # Печатаем краткий отчет
    print("\n" + "="*60)
    print("🔗 АНАЛИЗ ЗАВИСИМОСТЕЙ")
    print("="*60)
    
    metrics = analysis['metrics']
    print(f"📦 Компонентов: {metrics['total_components']}")
    print(f"🔗 Зависимостей: {metrics['total_dependencies']}")
    print(f"📊 Коэффициент связанности: {metrics['coupling_ratio']}")
    print(f"🎯 Критических компонентов: {metrics['critical_components']}")
    print(f"🚨 Критических зависимостей: {metrics['critical_dependencies']}")
    
    # Циклы
    cycles = analysis['cycles']
    print(f"\n🔄 ЦИКЛИЧЕСКИЕ ЗАВИСИМОСТИ: {len(cycles)}")
    for i, cycle in enumerate(cycles[:3], 1):
        nodes_str = " → ".join(cycle['nodes'])
        print(f"  {i}. {nodes_str} (сила: {cycle['strength']})")
    
    # Критический путь
    critical_path = analysis['critical_path']
    print(f"\n🎯 КРИТИЧЕСКИЙ ПУТЬ ({len(critical_path)} компонентов):")
    for i, comp in enumerate(critical_path[:5], 1):
        print(f"  {i}. {comp}")
    
    # Порядок миграции
    migration_order = analysis['migration_order']
    print(f"\n📋 ПОРЯДОК МИГРАЦИИ ({len(migration_order)} батчей):")
    for batch in migration_order[:3]:
        comp_count = len(batch['components'])
        effort = batch['estimated_effort']
        parallel = "✓" if batch['can_parallel'] else "✗"
        print(f"  Батч {batch['batch_id']}: {comp_count} компонентов, усилия: {effort}, параллельно: {parallel}")
    
    # Рекомендации
    recommendations = analysis['recommendations']
    print(f"\n💡 РЕКОМЕНДАЦИИ:")
    for i, rec in enumerate(recommendations[:5], 1):
        print(f"  {i}. {rec}")
    
    # Сохраняем анализ
    analyzer.save_analysis(analysis)
    
    print(f"\n🚀 Следующие шаги:")
    print(f"  1. Изучите dependency_analysis.json")
    print(f"  2. Разрешите циклические зависимости")
    print(f"  3. Следуйте порядку миграции")
    
    return analysis


if __name__ == "__main__":
    main()