from qgis.core import QgsProcessingProvider

from .korjaus_algoritmi import KorjaaPistepilviAlgoritmi
from .pilvi_algoritmi import SeinatPilvestaAlgoritmi
from .ruutu_algoritmi import SeinatRuuduittainAlgoritmi
from .seinalinja_algoritmi import SeinalinjaJxlAlgoritmi
from .vertailu_algoritmi import VertaaSeinalinjaAlgoritmi


class MaastomittausProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # noqa: N802
        self.addAlgorithm(SeinalinjaJxlAlgoritmi())
        self.addAlgorithm(VertaaSeinalinjaAlgoritmi())
        self.addAlgorithm(SeinatPilvestaAlgoritmi())
        self.addAlgorithm(SeinatRuuduittainAlgoritmi())
        self.addAlgorithm(KorjaaPistepilviAlgoritmi())

    def id(self):
        return "maastomittaus"

    def name(self):
        return "Maastomittaus"

    def longName(self):  # noqa: N802
        return self.name()
