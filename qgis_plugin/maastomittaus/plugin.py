"""Lisäosan rekisteröinti: Processing-työkalu näkyy työkalulaatikossa kohdassa Maastomittaus,
ja sen saa auki omasta työkalupalkista (LNS) ja Lisäosat-valikosta."""

import os

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon

from .provider import MaastomittausProvider

try:
    from qgis.PyQt.QtGui import QAction        # Qt6 (QGIS 4)
except ImportError:
    from qgis.PyQt.QtWidgets import QAction    # Qt5 (QGIS 3)

VALIKKO = "&Maastomittaus"
NIMI = "Lännen nopein seinälinja"
NAPIN_TEKSTI = "LNS"
ALGORITMI = "maastomittaus:seinalinja_jxl"
VERTAILU = ("Vertaa seinälinjaa LiDARiin", "maastomittaus:vertaa_seinalinjaa_lidariin")
KORJAUS = ("Korjaa pistepilven koordinaatisto", "maastomittaus:korjaa_pistepilven_koordinaatisto")
PILVESTA = ("Seinälinjat pistepilvestä", "maastomittaus:seinalinjat_pistepilvesta")
RUUDUITTAIN = ("Seinälinjat isosta pistepilvestä (ruuduittain)", "maastomittaus:seinalinjat_ruuduittain")
RAJAA = "Seinälinjat pistepilvestä: rajaa alue kartalta"
VIIMEISIN_PILVI = "maastomittaus/viimeisin_pilvi"   # QgsSettings: edellisen ajon pistepilvi

# Etsintäkuulutuksen näköinen nappi: paperin värinen tausta, ruskea kehys ja lännen fontti.
# Tausta on aina vaalea, joten teksti erottuu myös tummassa teemassa.
TYYLI = """
QToolButton {
    background-color: #f4e4c1;
    border: 1px solid #8b5a2b;
    border-radius: 4px;
    color: #4a2410;
    font-family: "Rockwell", "Rockwell Extra Bold", "Georgia", serif;
    font-weight: bold;
    padding: 2px 8px 2px 4px;
    margin: 1px 3px;
}
QToolButton:hover { background-color: #ecd49c; }
QToolButton:pressed { background-color: #d9b56a; }
"""


def _teksti_kuvakkeen_vieressa():
    try:
        return Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    except AttributeError:      # vanhempi PyQt5
        return Qt.ToolButtonTextBesideIcon


class MaastomittausPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.provider = None
        self.toiminto = None
        self.vertailu = None
        self.korjaus = None
        self.pilvesta = None
        self.ruuduittain = None
        self.rajaa = None
        self.rajaustyokalu = None
        self.edellinen_tyokalu = None
        self.tyokalupalkki = None

    def initProcessing(self):  # noqa: N802
        self.provider = MaastomittausProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # noqa: N802
        self.initProcessing()
        kuvake = QIcon(os.path.join(os.path.dirname(__file__), "icon.svg"))
        self.toiminto = QAction(kuvake, NIMI, self.iface.mainWindow())
        self.toiminto.setIconText(NAPIN_TEKSTI)     # työkalupalkissa lyhyt teksti, valikossa koko nimi
        self.toiminto.setToolTip(f"{NIMI} – seinälinja JXL-tiedostosta")
        self.toiminto.triggered.connect(lambda: self.avaa(ALGORITMI))
        # Oma työkalupalkki, jotta napissa näkyy teksti kuvakkeen vieressä
        self.tyokalupalkki = self.iface.addToolBar("Maastomittaus")
        self.tyokalupalkki.setObjectName("MaastomittausTyokalupalkki")
        self.tyokalupalkki.setToolButtonStyle(_teksti_kuvakkeen_vieressa())
        self.tyokalupalkki.setStyleSheet(TYYLI)
        self.tyokalupalkki.addAction(self.toiminto)
        self.iface.addPluginToMenu(VALIKKO, self.toiminto)
        # Vertailu vain valikkoon, jotta työkalupalkki pysyy pienenä
        self.vertailu = QAction(VERTAILU[0], self.iface.mainWindow())
        self.vertailu.triggered.connect(self.avaa_vertailu)
        self.iface.addPluginToMenu(VALIKKO, self.vertailu)
        self.pilvesta = QAction(PILVESTA[0], self.iface.mainWindow())
        self.pilvesta.triggered.connect(lambda: self.avaa_valinnalla(PILVESTA[1], "ALUE", self._pilvi()))
        self.iface.addPluginToMenu(VALIKKO, self.pilvesta)
        self.ruuduittain = QAction(RUUDUITTAIN[0], self.iface.mainWindow())
        self.ruuduittain.setToolTip("Kaupungin ajoneuvo- ja ilmakeilaus: koko pilvi ruutu kerrallaan, katot "
                                    "pudottavat aidat")
        self.ruuduittain.triggered.connect(lambda: self.avaa(RUUDUITTAIN[1], self._pilvi()))
        self.iface.addPluginToMenu(VALIKKO, self.ruuduittain)
        self.rajaa = QAction(RAJAA, self.iface.mainWindow())
        self.rajaa.setToolTip("Vedä suorakaide kartalle: Seinälinjat pistepilvestä aukeaa rajaus valmiina")
        self.rajaa.triggered.connect(self.aloita_rajaus)
        self.iface.addPluginToMenu(VALIKKO, self.rajaa)
        self.korjaus = QAction(KORJAUS[0], self.iface.mainWindow())
        self.korjaus.triggered.connect(lambda: self.avaa(KORJAUS[1]))
        self.iface.addPluginToMenu(VALIKKO, self.korjaus)

    def avaa(self, algoritmi=ALGORITMI, parametrit=None):
        from qgis import processing
        processing.execAlgorithmDialog(algoritmi, parametrit or {})

    def avaa_vertailu(self):
        """Vertailu: jos aktiivisella tasolla on valittuja kohteita (esim. talo kantakartalta), ne
        tulevat seinälinjaksi valmiiksi (Vain valitut kohteet)."""
        self.avaa_valinnalla(VERTAILU[1], "SEINALINJA")

    def avaa_valinnalla(self, algoritmi, parametri, muut=None):
        """Työkalu auki niin, että aktiivisen tason valitut kohteet ovat parametrissa valmiina."""
        from qgis.core import QgsProcessingFeatureSourceDefinition, QgsVectorLayer
        parametrit = dict(muut or {})
        taso = self.iface.activeLayer()
        if isinstance(taso, QgsVectorLayer) and taso.selectedFeatureCount():
            parametrit[parametri] = QgsProcessingFeatureSourceDefinition(taso.id(), True)
        self.avaa(algoritmi, parametrit)

    @staticmethod
    def _pilvi():
        """Edellisen ajon pistepilvi valmiiksi (pilvi_algoritmi tallentaa), jos tiedosto on yhä olemassa."""
        from qgis.core import QgsSettings
        polku = QgsSettings().value(VIIMEISIN_PILVI, "")
        return {"PILVI": polku} if polku and os.path.isfile(polku) else {}

    def aloita_rajaus(self):
        """Suorakaiteen piirto kartalle (QgsMapToolExtent); valmis alue avaa Seinälinjat pistepilvestä."""
        from qgis.gui import QgsMapToolExtent
        kartta = self.iface.mapCanvas()
        self.edellinen_tyokalu = kartta.mapTool()
        self.rajaustyokalu = QgsMapToolExtent(kartta)
        self.rajaustyokalu.extentChanged.connect(self._rajaus_valmis)
        kartta.setMapTool(self.rajaustyokalu)
        self.iface.messageBar().pushInfo(NIMI, "Vedä kartalle suorakaide alueen ympäri (paina hiiri pohjaan ja "
                                               "vedä vastakkaiseen kulmaan).")

    def _rajaus_valmis(self, alue):
        if alue.isEmpty() or alue.width() <= 0 or alue.height() <= 0:
            return
        kartta = self.iface.mapCanvas()
        crs = kartta.mapSettings().destinationCrs().authid()
        if self.edellinen_tyokalu is not None:
            kartta.setMapTool(self.edellinen_tyokalu)
        else:
            kartta.unsetMapTool(self.rajaustyokalu)
        laajuus = f"{alue.xMinimum()},{alue.xMaximum()},{alue.yMinimum()},{alue.yMaximum()} [{crs}]"
        self.avaa(PILVESTA[1], {**self._pilvi(), "LAAJUUS": laajuus})

    def unload(self):
        for toiminto in (self.toiminto, self.vertailu, self.pilvesta, self.ruuduittain, self.rajaa, self.korjaus):
            if toiminto is not None:
                self.iface.removePluginMenu(VALIKKO, toiminto)
        self.toiminto = self.vertailu = self.pilvesta = self.ruuduittain = self.rajaa = self.korjaus = None
        if self.rajaustyokalu is not None:
            self.iface.mapCanvas().unsetMapTool(self.rajaustyokalu)
            self.rajaustyokalu = None
        if self.tyokalupalkki is not None:
            self.tyokalupalkki.deleteLater()
            self.tyokalupalkki = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
