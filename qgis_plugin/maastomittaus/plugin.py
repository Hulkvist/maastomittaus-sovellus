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
        self.korjaus = QAction(KORJAUS[0], self.iface.mainWindow())
        self.korjaus.triggered.connect(lambda: self.avaa(KORJAUS[1]))
        self.iface.addPluginToMenu(VALIKKO, self.korjaus)

    def avaa(self, algoritmi=ALGORITMI, parametrit=None):
        from qgis import processing
        processing.execAlgorithmDialog(algoritmi, parametrit or {})

    def avaa_vertailu(self):
        """Vertailu: jos aktiivisella tasolla on valittuja kohteita (esim. talo kantakartalta), ne
        tulevat seinälinjaksi valmiiksi (Vain valitut kohteet)."""
        from qgis.core import QgsProcessingFeatureSourceDefinition, QgsVectorLayer
        taso = self.iface.activeLayer()
        if isinstance(taso, QgsVectorLayer) and taso.selectedFeatureCount():
            self.avaa(VERTAILU[1], {"SEINALINJA": QgsProcessingFeatureSourceDefinition(taso.id(), True)})
        else:
            self.avaa(VERTAILU[1])

    def unload(self):
        for toiminto in (self.toiminto, self.vertailu, self.korjaus):
            if toiminto is not None:
                self.iface.removePluginMenu(VALIKKO, toiminto)
        self.toiminto = self.vertailu = self.korjaus = None
        if self.tyokalupalkki is not None:
            self.tyokalupalkki.deleteLater()
            self.tyokalupalkki = None
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
