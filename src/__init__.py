# делаем src полноценным пакетом и «успокаиваем» IDE
from . import core as core
from . import infrastructure as infrastructure  
from . import domain as domain
from . import application as application
from . import presentation as presentation

# Опциональные модули с безопасным импортом
try:
    from . import integrations as integrations
except ImportError:
    integrations = None  # type: ignore

try:
    from . import analysis as analysis
except ImportError:
    analysis = None  # type: ignore

try:
    from . import plot as plot
except ImportError:
    plot = None  # type: ignore

try:
    from . import monitoring as monitoring
except ImportError:
    monitoring = None  # type: ignore

__all__ = ["core", "infrastructure", "domain", "application", "presentation"]
