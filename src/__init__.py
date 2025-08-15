# делаем src полноценным пакетом и «успокаиваем» IDE
from . import integrations as integrations
from . import core as core
from . import analysis as analysis
from . import plot as plot
from . import presentation as presentation

__all__ = ["integrations", "core", "analysis", "plot", "presentation"]
