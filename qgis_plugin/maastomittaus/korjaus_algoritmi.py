"""Processing-työkalu: Korjaa pistepilven koordinaatisto. Tekee LAS/LAZ-tiedostosta kopion
ETRS-GK25:ssä kaistan tunnuksen kanssa (EPSG:3879), esim. Stonexin GOpostin pilvestä, josta
tunnus 25 puuttuu (EPSG:3132). Pisteitä ei kirjoiteta uudelleen (ks. ydin.korjaa_las_gk25)."""

import os

from qgis.core import (QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingOutputFile,
                       QgsProcessingParameterBoolean, QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination)

from . import ydin
from .tyylit import lisaa_pistepilvi


class KorjaaPistepilviAlgoritmi(QgsProcessingAlgorithm):
    PILVI = "PILVI"
    KORJATTU = "KORJATTU"
    KARTTAAN = "KARTTAAN"
    TULOS = "TULOS"

    def __init__(self):
        super().__init__()
        self._karttaan = None

    def createInstance(self):  # noqa: N802
        return KorjaaPistepilviAlgoritmi()

    def name(self):
        return "korjaa_pistepilven_koordinaatisto"

    def displayName(self):  # noqa: N802
        return "Korjaa pistepilven koordinaatisto"

    def shortHelpString(self):  # noqa: N802
        return ("Tekee pistepilvestä (LAS tai LAZ) kopion ETRS-GK25:ssä kaistan tunnuksen kanssa (EPSG:3879), "
                "kuten kantakartta ja seinälinja.\n\n"
                "Koordinaatisto päätellään otsikon luvuista, ei tiedoston nimestä: jos itäkoordinaatit ovat "
                "noin 400 000–600 000 (esim. Stonexin GOpost, otsikossa EPSG:3132), kaistan tunnus 25 lisätään. "
                "Jos tunnus on jo mukana mutta otsikossa lukee väärä koordinaatisto, vain merkintä korjataan. "
                "Muut koordinaatistot (esim. ETRS-TM35FIN): QGIS:n työkalu Reproject point cloud.\n\n"
                "Pisteitä ei kirjoiteta uudelleen: tunnus lisätään otsikon siirtoon, joten tarkkuus säilyy ja "
                "iso LAZ korjautuu kopioinnin ajassa. Korkeusjärjestelmää (N2000) ei merkitä otsikkoon.\n\n"
                "Vertaa seinälinjaa LiDARiin -työkalu tekee saman päättelyn itse, joten korjattua kopiota ei "
                "tarvita vertailuun.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile(
            self.PILVI, "Pistepilvi (LAS/LAZ)", behavior=QgsProcessingParameterFile.Behavior.File,
            fileFilter="Pistepilvi (*.las *.laz *.LAS *.LAZ)"))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.KORJATTU, "Korjattu pistepilvi (tyhjä = samaan kansioon nimellä <nimi>_EPSG3879)",
            fileFilter="Pistepilvi (*.laz *.las)", optional=True, createByDefault=False))
        self.addParameter(QgsProcessingParameterBoolean(
            self.KARTTAAN, "Lataa korjattu pistepilvi karttaan", defaultValue=True))
        self.addOutput(QgsProcessingOutputFile(self.TULOS, "Korjattu pistepilvi"))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        lahde = self.parameterAsFile(parameters, self.PILVI, context)
        kohde = self.parameterAsFileOutput(parameters, self.KORJATTU, context)
        pohja, paate = os.path.splitext(lahde)
        if not kohde:
            kohde = f"{pohja}_EPSG3879{paate}"
        elif os.path.splitext(kohde)[1].lower() != paate.lower():
            # Pakkausta ei vaihdeta (pisteet kopioidaan sellaisinaan)
            kohde = os.path.splitext(kohde)[0] + paate
            feedback.pushInfo(f"Tiedostopääte pidetään samana kuin lähteessä: {os.path.basename(kohde)}")
        feedback.pushInfo(f"Kopioidaan {os.path.basename(lahde)} ({os.path.getsize(lahde) / 1e6:.0f} Mt)...")
        try:
            tiedot, muutokset = ydin.korjaa_las_gk25(lahde, kohde)
        except (OSError, ValueError) as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo(f"Koordinaatisto: {tiedot['selitys']}.")
        for muutos in muutokset:
            feedback.pushInfo(f"Korjattu: {muutos}.")
        feedback.pushInfo(f"Tallennettu: {kohde}")
        self._karttaan = kohde if self.parameterAsBoolean(parameters, self.KARTTAAN, context) else None
        return {self.TULOS: kohde}

    def postProcessAlgorithm(self, context, feedback):  # noqa: N802
        # Pääsäikeessä: pistepilvitasoa ei voi luoda taustasäikeessä (ks. tyylit._Tyyli)
        if self._karttaan:
            if lisaa_pistepilvi(self._karttaan, f"Pistepilvi ({os.path.basename(self._karttaan)})",
                                context.project(), feedback):
                feedback.pushInfo("Pistepilvi lisätty karttaan. QGIS tekee ensimmäisellä avauksella indeksin, "
                                  "joten pisteet tulevat näkyviin hetken kuluttua.")
        return {}
