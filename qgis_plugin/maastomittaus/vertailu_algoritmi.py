"""Processing-työkalu: Vertaa seinälinjaa LiDARiin. Mikä tahansa viivataso (esim. QGIS:iin avattu
DXF) tai rakennukset aluetasolta (esim. kantakartta, myös vain valitut talot) verrataan LiDAR-keilauksen
seiniin samalla tavalla kuin LNS vertaa JXL:n seinälinjaa: poikkeama 25 cm välein, seinät 3D-näkymään
ja valittaessa pistepilvi karttaan. LiDAR voi olla lidarpipen seinä-DXF, pistepilvi (LAS/LAZ) tai
molemmat. Ilman tasoa rakennukset haetaan Helsingin kantakartasta keilauksen alueelta."""

import json
import math
import os
import time

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature,
                       QgsFeatureSink, QgsGeometry, QgsPointXY, QgsProcessing, QgsProcessingAlgorithm,
                       QgsProcessingException, QgsProcessingUtils,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum, QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterField, QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination, QgsProcessingParameterNumber,
                       QgsProcessingParameterString, QgsRectangle, Qgis)

from . import kantakartta as kk
from . import lidar as ld
from . import ydin
from .seinalinja_algoritmi import (GK25, KOKONAISLUKU, LIDARKENTAT, LUKU, POIKKEAMAKENTAT, SEINA3DKENTAT, TEKSTI,
                                   _cm, _kentat, lisaa_seinapalat)
from .tyylit import SEINAN_KORKEUS_M, aseta_tyylit
from .ydin import sl

VERTAILUKENTAT = _kentat(("nimi", TEKSTI), ("pituus_m", LUKU), ("karkia", KOKONAISLUKU), ("korkeus_m", LUKU),
                         ("poikkeama_lidar_ka_cm", LUKU), ("poikkeama_lidar_max_cm", LUKU),
                         ("lidar_peitto_pct", LUKU), ("poikkeama_pilvi_ka_cm", LUKU),
                         ("poikkeama_pilvi_max_cm", LUKU), ("pilvi_peitto_pct", LUKU))
PILVIKENTAT = _kentat(("viiva", TEKSTI), ("poikkeama_cm", LUKU), ("luokka", TEKSTI), ("ero_cm", LUKU))
PILVEN_SEINAKENTAT = _kentat(("viiva", TEKSTI), ("ero_ka_cm", LUKU))
PILVEN_RAJAUS_M = 1.7      # pistepilvestä luetaan seinälinjan ympäriltä (seinäpinta + maanpinta)
SIIVOUS_RAJAUS_M = 5.0     # siivottu pistepilvi karttaan: talot ja niiden ympäristö
SIIVOUKSEN_TYOKALUT = ("pdal:clip", "pdal:filternoisestatistical", "pdal:classifyground")
SIIVOUS_HARVENNUS = 2      # karttaan joka 2. piste (pdal:thinbydecimate, jos on): kevyempi 3D ja nopeampi siivous
# (nimi, tyylit.lisaa_pistepilvi-väritys); pilvi ilman värejä väritetään aina korkeuden mukaan
VARITYKSET = [("Keilauksen värit (RGB)", "rgb"), ("Korkeuden mukaan", "korkeus")]
MAA_PIILOON = "Classification != 2"   # siivotun pilven maanpinta (luokka 2) piilotetaan kartalla
SUURIN_HAKUALUE_KM2 = 1.0  # kantakartan haku pistepilven alueelta (kokonaiset laserkeilaustiedostot ovat isoja)


def _pisteet(geometria):
    """Viivageometrian osat [(e, n, korkeus tai None)]-listoina. Korkeus None, jos osalla ei
    ole korkeuksia (2D tai kaikki 0, kuten DXF:n tasoviivoissa yleensä)."""
    osat = []
    for osa in geometria.constParts():
        pisteet = [(p.x(), p.y(), p.z() if osa.is3D() and not math.isnan(p.z()) else None) for p in osa.vertices()]
        if all(z in (None, 0.0) for _, _, z in pisteet):
            pisteet = [(e, n, None) for e, n, _ in pisteet]
        osat.append(pisteet)
    return osat


def _gk25_alue(alue, koord, context):
    """Pistepilven otsikon alue (x0, y0, x1, y1) ETRS-GK25:ssä (koord = ydin.las_koordinaatisto)."""
    if alue is None or koord is None:
        return alue
    x0, y0, x1, y1 = alue
    if koord["epsg"] != ydin.GK25_EPSG:
        r = QgsCoordinateTransform(QgsCoordinateReferenceSystem(f"EPSG:{koord['epsg']}"),
                                   QgsCoordinateReferenceSystem(GK25),
                                   context.transformContext()).transformBoundingBox(QgsRectangle(x0, y0, x1, y1))
        return r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum()
    return x0 + koord["siirto_x"], y0, x1 + koord["siirto_x"], y1


def _rajausalue(alue, koord, nimi, context):
    """Rajausalue (ETRS-GK25) pdal:clip-työkalulle GeoJSON-tilapäistiedostoksi pistepilven omina
    lukuina ja otsikon koordinaatistossa, joten rajaus osuu, muuntaako PDAL rajausalueen tai ei."""
    alue = QgsGeometry(alue)
    if koord["epsg"] != ydin.GK25_EPSG:
        alue.transform(QgsCoordinateTransform(QgsCoordinateReferenceSystem(GK25),
                                              QgsCoordinateReferenceSystem(f"EPSG:{koord['epsg']}"),
                                              context.transformContext()))
    alue.translate(-koord["siirto_x"], 0)
    merkinta = koord["otsikko_epsg"] or koord["kerros_epsg"]
    polku = QgsProcessingUtils.generateTempFilename(nimi, context)
    with open(polku, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection",
                   "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{merkinta}"}},
                   "features": [{"type": "Feature", "properties": {}, "geometry": json.loads(alue.asJson(3))}]}, f)
    return polku


def rajaa_pilvi(polku, alue, koord, nimi, context, feedback):
    """Pistepilvi (LAS/LAZ/COPC) rajattuna alueelle (QgsGeometry, ETRS-GK25) pakkaamattomaksi LAS:ksi
    QGIS:n pdal:clip-työkalulla, muunnettuna ETRS-GK25:een (pdal:reproject), jos otsikossa on muu
    koordinaatisto (koord = ydin.las_koordinaatisto). Palauttaa (luettava polku, onko tilapäinen) tai
    None, jos käyttäjä perui. Jos PDAL puuttuu, pakkaamaton LAS luetaan kokonaan."""
    import processing

    muunnettava = koord["epsg"] != ydin.GK25_EPSG
    rajaus = _rajausalue(alue, koord, f"{nimi}_alue.geojson", context)
    rajattu = QgsProcessingUtils.generateTempFilename(f"{nimi}.las", context)
    try:
        processing.run("pdal:clip", {"INPUT": polku, "OVERLAY": rajaus, "OUTPUT": rajattu},
                       context=context, feedback=feedback, is_child_algorithm=True)
        if not os.path.isfile(rajattu):
            raise RuntimeError("rajattua pistepilveä ei syntynyt")
        if muunnettava:
            muunnettu = QgsProcessingUtils.generateTempFilename(f"{nimi}_gk25.las", context)
            feedback.pushInfo(f"Muunnetaan rajattu pistepilvi EPSG:{koord['epsg']} -> EPSG:3879 "
                              "(pdal:reproject)...")
            processing.run("pdal:reproject", {"INPUT": rajattu, "CRS": GK25, "OUTPUT": muunnettu},
                           context=context, feedback=feedback, is_child_algorithm=True)
            os.remove(rajattu)
            rajattu = muunnettu
        return rajattu, True
    except Exception as e:
        if feedback.isCanceled():
            return None
        if not muunnettava and not polku.lower().endswith((".laz", ".copc")):
            feedback.pushWarning(f"Pistepilven rajaus ei onnistunut ({e}); luetaan koko LAS.")
            return polku, False
        raise QgsProcessingException(f"Pistepilveä ei voitu rajata ({e}). LAZ-tiedoston lukuun "
                                     "tarvitaan QGIS:n PDAL-työkalut (QGIS 3.32 tai uudempi).")


class VertaaSeinalinjaAlgoritmi(QgsProcessingAlgorithm):
    SEINALINJA = "SEINALINJA"
    NIMIKENTTA = "NIMIKENTTA"
    LIDAR = "LIDAR"
    PILVI = "PILVI"
    KORKEUS = "KORKEUS"
    LUOKAT = "LUOKAT"
    PISTEPILVI = "PISTEPILVI"
    SIIVOA = "SIIVOA"
    VARITYS = "VARITYS"
    DXF = "DXF"
    VERTAILU = "VERTAILU"
    SEINAT_3D = "SEINAT_3D"
    LIDAR_SEINAT = "LIDAR_SEINAT"
    POIKKEAMA_LIDAR = "POIKKEAMA_LIDAR"
    POIKKEAMA_PILVI = "POIKKEAMA_PILVI"
    PILVEN_SEINA = "PILVEN_SEINA"

    def createInstance(self):  # noqa: N802
        return VertaaSeinalinjaAlgoritmi()

    def name(self):
        return "vertaa_seinalinjaa_lidariin"

    def displayName(self):  # noqa: N802
        return "Vertaa seinälinjaa LiDARiin"

    def shortHelpString(self):  # noqa: N802
        return ("Vertaa mitä tahansa seinälinjaa LiDAR-keilaukseen: lidarpipen seiniin (<nimi>_seinat.dxf), "
                "suoraan pistepilveen (LAS tai LAZ) tai molempiin. Seinälinjan ei tarvitse tulla JXL:stä.\n\n"
                "Pistepilvi: seinäpinta etsitään 25 cm välein seinälinjan kummaltakin puolelta (60 cm), "
                "maanpinnan ja räystään väliltä (0,4–2,5 m maasta), kohdasta, jossa pisteitä on eniten eri "
                "korkeuksilla. Pistepilvestä luetaan vain seinälinjan ympäristö (QGIS:n PDAL-työkalu pdal:clip), "
                "joten myös iso LAZ käy. Pistepilven koordinaatisto päätellään otsikosta: ETRS-GK25 käy myös "
                "ilman kaistan tunnusta 25 (esim. Stonexin GOpost, EPSG:3132), ja muut merkityt koordinaatistot "
                "muunnetaan. Pysyvästi korjatun kopion saa työkalulla Korjaa pistepilven koordinaatisto.\n\n"
                "Seinälinja: viivataso (esim. QGIS:iin avattu DXF, shapefile, tietokannan taso) tai rakennukset "
                "aluetasolta (esim. kantakartta; talon ulkoreuna on seinälinja). Valitse talo kartalta ja rastita "
                "'Vain valitut kohteet' (tai avaa työkalu Lisäosat-valikosta, kun talo on valittuna). Jos tasoa ei "
                "valita, rakennukset haetaan Helsingin kantakartasta keilauksen alueelta (mukaan talot, joiden "
                "reunalla on LiDAR-seinää tai pistepilvestä löytyy seinäpintaa). Seinälinjat voi tallentaa DXF:ksi.\n\n"
                "Tulokset: Seinälinja (vertailu) poikkeamineen viivoittain, Poikkeama LiDARista ja Poikkeama "
                "pistepilvestä 25 cm välein (luokkarajat valittavissa, oletuksena 3, 5 ja 15 cm: tummanvihreä, "
                "vaaleanvihreä, keltainen ja punainen; kohdat "
                "ilman seinää jäävät pois; ero_cm + = seinä on seinälinjaa ulompana), LiDAR-seinät ja Seinät 3D "
                "(3 m korkea seinä 3D-näkymään).\n\n"
                "Pistepilvi karttaan: keilauksen värit (RGB) tai korkeuden mukaan, myös 3D-näkymässä (valitse "
                "väritys tässä: värityksen vaihto tason ominaisuuksista 3D-näkymän ollessa auki voi kaataa "
                "QGIS 4.2:n; Stonexin pilvissä värit ovat usein valkoisia).\n\n"
                "Siivous (valinnainen): talojen ympäristö 5 m rajataan, kohina poistetaan ja "
                "maanpinta luokitellaan ja piilotetaan (suodatin Classification != 2, maan saa näkyviin "
                "tyhjentämällä tason suodattimen). Siivottu pilvi on tilapäistiedosto. Vertailu lasketaan aina "
                "siivoamattomasta pilvestä. Jos QGIS:ssä ei ole PDAL-työkaluja, siivous ohitetaan ja syy "
                "kerrotaan lokissa.\n\n"
                "Seinän korkeus 3D-näkymässä: viivan omat korkeudet; jos niitä ei ole (DXF ja kantakartta yleensä "
                "2D), annettu korkeus; muuten seinä alkaa maanpinnasta (pistepilvestä nurkan kohdalta, tai "
                "seinä-DXF:n vieressä olevan LAS:n alimmasta korkeudesta). "
                "Seinälinjan koordinaatisto muunnetaan ETRS-GK25:een; jos tasolla ei ole koordinaatistoa "
                "(DXF), sen oletetaan olevan ETRS-GK25.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.SEINALINJA, "Seinälinja tai rakennukset (tyhjä = Helsingin kantakartta keilauksen alueelta)",
            [QgsProcessing.SourceType.TypeVectorLine, QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterField(
            self.NIMIKENTTA, "Viivan nimi -kenttä (valinnainen)", parentLayerParameterName=self.SEINALINJA,
            optional=True))
        self.addParameter(QgsProcessingParameterFile(
            self.LIDAR, "LiDAR-seinät (lidarpipen _seinat.dxf, valinnainen)",
            behavior=QgsProcessingParameterFile.Behavior.File, fileFilter="LiDAR-seinät (*_seinat.dxf *.dxf)",
            optional=True))
        self.addParameter(QgsProcessingParameterFile(
            self.PILVI, "Pistepilvi (LAS/LAZ, valinnainen)", behavior=QgsProcessingParameterFile.Behavior.File,
            fileFilter="Pistepilvi (*.las *.laz *.LAS *.LAZ)", optional=True))
        self.addParameter(QgsProcessingParameterNumber(
            self.KORKEUS, "Seinän keskikorkeus 3D-näkymässä (m), jos viivalla ei ole korkeuksia",
            type=QgsProcessingParameterNumber.Type.Double, optional=True))
        self.addParameter(QgsProcessingParameterString(
            self.LUOKAT, "Poikkeaman luokkarajat (cm, välilyönnein, esim. 3 5 15)",
            defaultValue=ydin.LUOKKARAJAT_OLETUS, optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.PISTEPILVI, "Lataa pistepilvi karttaan (valittu, tai LAS seinä-DXF:n kansiosta)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.VARITYS, "Pistepilven väritys kartalla ja 3D-näkymässä", options=[n for n, _ in VARITYKSET],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SIIVOA, "Siivoa karttaan ladattava pistepilvi: vain talot ja ympäristö (5 m), kohina pois, "
            "maanpinta piiloon (QGIS:n PDAL-työkalut)", defaultValue=False))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.DXF, "Tallenna seinälinjat DXF:ksi (valinnainen)", fileFilter="DXF (*.dxf)", optional=True,
            createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.VERTAILU, "Seinälinja (vertailu)", QgsProcessing.SourceType.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.POIKKEAMA_LIDAR, "Poikkeama LiDARista", QgsProcessing.SourceType.TypeVectorPoint, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.POIKKEAMA_PILVI, "Poikkeama pistepilvestä", QgsProcessing.SourceType.TypeVectorPoint,
            optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.PILVEN_SEINA, "Pistepilven seinälinja", QgsProcessing.SourceType.TypeVectorLine, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SEINAT_3D, "Seinät 3D", QgsProcessing.SourceType.TypeVectorPolygon, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.LIDAR_SEINAT, "LiDAR-seinät", QgsProcessing.SourceType.TypeVectorLine, optional=True))

    def _viivat(self, parameters, context, feedback, lahde):
        """Seinälinjan viivat EPSG:3879:ssä [(nimi, [(e, n, z)])]. Aluetasolta (rakennukset) seinälinja
        on alueen reuna."""
        nimikentta = self.parameterAsString(parameters, self.NIMIKENTTA, context)
        gk25 = QgsCoordinateReferenceSystem(GK25)
        muunnos = None
        if not lahde.sourceCrs().isValid():
            feedback.pushInfo("Seinälinjatasolla ei ole koordinaatistoa (esim. DXF): oletetaan ETRS-GK25 (EPSG:3879).")
        elif lahde.sourceCrs() != gk25:
            muunnos = QgsCoordinateTransform(lahde.sourceCrs(), gk25, context.transformContext())
        viivat = []
        for f in lahde.getFeatures():
            g = QgsGeometry(f.geometry())
            # DXF:ssä on samassa tasossa myös pisteitä ja tekstejä (esim. pistenumerot)
            if g.isEmpty() or g.type() not in (Qgis.GeometryType.Line, Qgis.GeometryType.Polygon):
                continue
            alue = g.type() == Qgis.GeometryType.Polygon
            g.convertToStraightSegment()
            if muunnos is not None:
                g.transform(muunnos)
            if alue:
                g = QgsGeometry(g.constGet().boundary())
            osat = _pisteet(g)
            nimi = str(f[nimikentta]) if nimikentta and f[nimikentta] not in (None, "") else \
                f"{'Rakennus' if alue else 'Viiva'} {len({n.split('.')[0] for n, _ in viivat}) + 1}"
            for j, pisteet in enumerate(osat, start=1):
                viivat.append((nimi if len(osat) == 1 else f"{nimi}.{j}", pisteet))
        return viivat

    def _kantakartan_talot(self, lidar, pilvi, koord, context, feedback):
        """Helsingin kantakartan rakennukset keilauksen alueelta (LiDAR-seinistä tai pistepilven
        otsikosta) seinälinjoiksi [(nimi, pisteet)]."""
        if lidar:
            xs = [p[0] for jana in lidar for p in jana]
            ys = [p[1] for jana in lidar for p in jana]
            alue = (min(xs) - 5, min(ys) - 5, max(xs) + 5, max(ys) + 5)
        else:
            alue = _gk25_alue(ydin.las_alue(pilvi), koord, context) if pilvi else None
            if alue is None:
                raise QgsProcessingException("Keilauksen aluetta ei saatu (ei LiDAR-seiniä eikä luettavaa "
                                             "pistepilveä), joten kantakartan rakennuksia ei voi hakea. Valitse "
                                             "seinälinja- tai rakennustaso.")
            if (alue[2] - alue[0]) * (alue[3] - alue[1]) > SUURIN_HAKUALUE_KM2 * 1e6:
                raise QgsProcessingException(
                    f"Pistepilven alue on {(alue[2] - alue[0]) * (alue[3] - alue[1]) / 1e6:.1f} km², liian iso "
                    "kantakartan hakuun. Valitse vertailtavat talot kartalta (rakennustaso ja 'Vain valitut "
                    "kohteet').")
        if not kk.on_helsingissa(alue, context.transformContext()):
            raise QgsProcessingException("Keilaus ei ole Helsingissä, joten kantakartan rakennuksia ei voi hakea. "
                                         "Valitse seinälinja- tai rakennustaso.")
        feedback.pushInfo("Haetaan Helsingin kantakartan rakennukset keilauksen alueelta...")
        try:
            rakennukset = kk.hae_helsinki(alue, context.transformContext())
        except Exception as e:
            raise QgsProcessingException(f"Kantakartan rakennuksia ei saatu: {e}")
        viivat = []
        for i, renkaat in enumerate(rakennukset, start=1):
            for j, rengas in enumerate(renkaat):
                viivat.append((f"Rakennus {i}" + (f".{j}" if j else ""), [(e, n, None) for e, n in rengas]))
        return viivat

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        dxf = self.parameterAsFile(parameters, self.LIDAR, context)
        pilvi = self.parameterAsFile(parameters, self.PILVI, context)
        if not dxf and not pilvi:
            raise QgsProcessingException("Valitse LiDAR-seinät (DXF), pistepilvi (LAS/LAZ) tai molemmat.")
        try:
            rajat = ydin.lue_luokkarajat(self.parameterAsString(parameters, self.LUOKAT, context))
            luokat = ydin.poikkeamaluokat(rajat)
        except ValueError as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo("Poikkeaman luokat: " + ", ".join(nimi for _, nimi, _ in luokat) + ".")
        koord = None
        if pilvi:
            try:
                koord = ydin.las_koordinaatisto(pilvi)
            except (OSError, ValueError) as e:
                raise QgsProcessingException(str(e))
            if koord["epsg"] != ydin.GK25_EPSG and not QgsCoordinateReferenceSystem(f"EPSG:{koord['epsg']}").isValid():
                raise QgsProcessingException(f"Pistepilven koordinaatisto EPSG:{koord['epsg']} ei ole QGIS:n tuntema.")
            feedback.pushInfo(f"Pistepilven koordinaatisto: {koord['selitys']}.")
        lidar_tasot = {ld.SEINA: [], ld.EPAVARMA: []}
        viereiset = {"las": None, "raportti": None}
        if dxf:
            try:
                lidar_tasot = ld.lue_seinat(dxf)
            except Exception as e:
                raise QgsProcessingException(f"LiDAR-seiniä ei voitu lukea: {e}")
            viereiset = ld.viereiset_tiedostot(dxf)
        lidar = lidar_tasot[ld.SEINA]
        lahde = self.parameterAsSource(parameters, self.SEINALINJA, context)
        kantakartasta = lahde is None
        viivat = (self._kantakartan_talot(lidar, pilvi, koord, context, feedback) if kantakartasta
                  else self._viivat(parameters, context, feedback, lahde))
        if not viivat:
            raise QgsProcessingException("Seinälinjatasossa ei ole viivoja tai rakennuksia.")
        feedback.pushInfo(f"Seinälinja: {len(viivat)} viivaa.")
        if dxf:
            feedback.pushInfo(f"LiDAR: {len(lidar)} seinää, {len(lidar_tasot[ld.EPAVARMA])} epävarmaa "
                              f"({os.path.basename(dxf)}).")
        if viereiset["raportti"]:
            try:
                for rivi in ydin.keilausraportti(viereiset["raportti"]):
                    feedback.pushInfo(f"Keilaus: {rivi}")
            except Exception as e:
                feedback.pushInfo(f"Keilauksen raporttia ei voitu lukea ({e}).")
        xyz = self._lue_pilvi(pilvi, viivat, koord, context, feedback) if pilvi else None
        if feedback.isCanceled():
            return {}

        # Korkeus viivoille, joilla sitä ei ole: annettu keskikorkeus, muuten maanpinta (pistepilvestä
        # pisteen kohdalta tai DXF:n vieressä olevan LAS:n alin korkeus) + puolet seinän korkeudesta
        oletus = self.parameterAsDouble(parameters, self.KORKEUS, context) \
            if parameters.get(self.KORKEUS) not in (None, "") else None
        maat = None
        if oletus is None and xyz is not None and len(xyz):
            maat = ydin.maanpinnat(viivat, xyz)
            feedback.pushInfo("Viivoilla ilman korkeuksia seinä alkaa maanpinnasta (pistepilvestä nurkittain).")
        elif oletus is None and viereiset["las"]:
            alue = ydin.las_korkeusalue(viereiset["las"])
            if alue:
                oletus = alue[0] + SEINAN_KORKEUS_M / 2
                feedback.pushInfo(f"Viivoilla ilman korkeuksia seinä alkaa pistepilven alimmasta korkeudesta "
                                  f"{alue[0]:.2f} m.")
        if maat is not None:
            uudet = []
            for (nimi, pisteet), korkeudet in zip(viivat, maat):
                # Nurkka ilman pisteitä (esim. katveessa): viivan muiden nurkkien keskiarvo
                tunnetut = [k for k in korkeudet if k is not None]
                varalla = sum(tunnetut) / len(tunnetut) if tunnetut else None
                korkeudet = [varalla if k is None else k for k in korkeudet]
                uudet.append((nimi, [(e, n, z if z is not None else None if k is None else k + SEINAN_KORKEUS_M / 2)
                                     for (e, n, z), k in zip(pisteet, korkeudet)]))
            viivat = uudet
        else:
            viivat = [(nimi, [(e, n, oletus if z is None else z) for e, n, z in pisteet]) for nimi, pisteet in viivat]
        if any(z is None for _, pisteet in viivat for _, _, z in pisteet):
            feedback.pushWarning("Osalla viivoista ei ole korkeuksia eikä korkeutta annettu (eikä maanpintaa "
                                 "saatu pistepilvestä), joten ne ovat 3D-näkymässä korkeudella 0.")

        tulos = ydin.viivat_pisteista(viivat)
        poikkeamat = {p["nimi"]: p for p in sl.poikkeamat_lidarista(tulos, lidar)} if dxf else {}
        pilvesta = {p["nimi"]: p for p in ydin.poikkeamat_pistepilvesta(tulos, xyz)} \
            if xyz is not None and len(xyz) else {}
        if kantakartasta:
            # Haetulla alueella voi olla naapuritaloja, joita ei keilattu: mukaan vain keilatut
            keilatut = {nimi for vertailu in (poikkeamat, pilvesta) for nimi, p in vertailu.items()
                        if p["keskiarvo_m"] is not None}
            tulos = {"viivat": [v for v in tulos["viivat"] if v["nimi"] in keilatut]}
            poikkeamat = {nimi: p for nimi, p in poikkeamat.items() if nimi in keilatut}
            pilvesta = {nimi: p for nimi, p in pilvesta.items() if nimi in keilatut}
            feedback.pushInfo(f"Kantakartasta {len(keilatut)} rakennusta, jotka keilauksessa näkyvät.")
            if not keilatut:
                feedback.pushWarning("Yhtäkään kantakartan rakennusta ei löytynyt keilauksesta.")
        for viiva in tulos["viivat"]:
            nimi = viiva["nimi"]
            for vertailu, mista, peittaa in ((poikkeamat, "LiDAR-seinistä", "LiDAR kattaa"),
                                             (pilvesta, "pistepilven seinäpinnasta", "seinäpinta löytyi")):
                p = vertailu.get(nimi)
                if p is None:
                    continue
                if p["keskiarvo_m"] is None:
                    feedback.pushInfo(f"{nimi}: ei vertailukohtaa ({mista}).")
                else:
                    feedback.pushInfo(f"{nimi}: poikkeaa {mista} keskimäärin {p['keskiarvo_m'] * 100:.1f} cm, "
                                      f"enimmillään {p['suurin_m'] * 100:.1f} cm ({peittaa} "
                                      f"{p['peitto'] * 100:.0f} % viivasta).")

        crs = QgsCoordinateReferenceSystem(GK25)
        tulokset_id = {}
        vertailu, tulokset_id[self.VERTAILU] = self.parameterAsSink(parameters, self.VERTAILU, context,
                                                                    VERTAILUKENTAT, Qgis.WkbType.LineString, crs)
        for viiva in tulos["viivat"]:
            xy = sl.viivan_pisteet(viiva)
            geom = QgsGeometry.fromPolylineXY([QgsPointXY(e, n) for e, n in xy])
            p = poikkeamat.get(viiva["nimi"]) or {}
            q = pilvesta.get(viiva["nimi"]) or {}
            korkeudet = [k["z"] for k in viiva["karjet"] if k["z"] is not None]
            f = QgsFeature(VERTAILUKENTAT)
            f.setGeometry(geom)
            f.setAttributes([viiva["nimi"], round(geom.length(), 3), len(viiva["karjet"]),
                             round(sum(korkeudet) / len(korkeudet), 3) if korkeudet else None,
                             _cm(p.get("keskiarvo_m")), _cm(p.get("suurin_m")),
                             round(p["peitto"] * 100, 0) if p else None,
                             _cm(q.get("keskiarvo_m")), _cm(q.get("suurin_m")),
                             round(q["peitto"] * 100, 0) if q else None])
            vertailu.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        dxf_polku = self.parameterAsFileOutput(parameters, self.DXF, context)
        if dxf_polku:
            tulokset_id[self.DXF] = self._tallenna_dxf(tulos, dxf_polku, context, feedback)

        if dxf:
            naytteet, naytteet_id = self.parameterAsSink(parameters, self.POIKKEAMA_LIDAR, context,
                                                         POIKKEAMAKENTAT, Qgis.WkbType.Point, crs)
            if naytteet is not None:
                tulokset_id[self.POIKKEAMA_LIDAR] = naytteet_id
                for nimi, p in poikkeamat.items():
                    for e, n, d in p["naytteet"]:
                        if d is None:
                            continue
                        f = QgsFeature(POIKKEAMAKENTAT)
                        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(e, n)))
                        f.setAttributes([nimi, round(d * 100, 1), ydin.poikkeamaluokka(d, luokat)[0]])
                        naytteet.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        if pilvesta:
            naytteet, naytteet_id = self.parameterAsSink(parameters, self.POIKKEAMA_PILVI, context, PILVIKENTAT,
                                                         Qgis.WkbType.Point, crs)
            if naytteet is not None:
                tulokset_id[self.POIKKEAMA_PILVI] = naytteet_id
                for nimi, p in pilvesta.items():
                    for (e, n, d), ero in zip(p["naytteet"], p["etumerkki"]):
                        if d is None:
                            continue
                        f = QgsFeature(PILVIKENTAT)
                        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(e, n)))
                        f.setAttributes([nimi, round(d * 100, 1), ydin.poikkeamaluokka(d, luokat)[0],
                                         round(ero * 100, 1)])
                        naytteet.addFeature(f, QgsFeatureSink.Flag.FastInsert)
            # Löydetty seinäpinta viivana: kartalla näkyy rako seinälinjaan
            pinnat, pinnat_id = self.parameterAsSink(parameters, self.PILVEN_SEINA, context, PILVEN_SEINAKENTAT,
                                                     Qgis.WkbType.LineString, crs)
            if pinnat is not None:
                tulokset_id[self.PILVEN_SEINA] = pinnat_id
                for nimi, p in pilvesta.items():
                    erot = dict(zip(p["seinapinta"], p["etumerkki"]))
                    for osa in ydin.pilven_seinaviivat(p):
                        f = QgsFeature(PILVEN_SEINAKENTAT)
                        f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(e, n) for e, n in osa]))
                        f.setAttributes([nimi, round(sum(erot[q] for q in osa) / len(osa) * 100, 1)])
                        pinnat.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        seinat3d, seinat3d_id = self.parameterAsSink(parameters, self.SEINAT_3D, context, SEINA3DKENTAT,
                                                     Qgis.WkbType.Polygon, crs)
        if seinat3d is not None:
            tulokset_id[self.SEINAT_3D] = seinat3d_id
            for viiva in tulos["viivat"]:
                # Seinä väritetään poikkeaman mukaan: pistepilvestä (etumerkillinen), muuten LiDAR-seinistä
                p, q = pilvesta.get(viiva["nimi"]), poikkeamat.get(viiva["nimi"])
                naytteet = [(e, n, ero) for (e, n, _), ero in zip(p["naytteet"], p["etumerkki"])] if p else \
                    q["naytteet"] if q else None
                lisaa_seinapalat(seinat3d, viiva, naytteet, luokat)

        if dxf:
            seinat, seinat_id = self.parameterAsSink(parameters, self.LIDAR_SEINAT, context, LIDARKENTAT,
                                                     Qgis.WkbType.LineString, crs)
            if seinat is not None:
                tulokset_id[self.LIDAR_SEINAT] = seinat_id
                for taso, janat in lidar_tasot.items():
                    for a, b in janat:
                        f = QgsFeature(LIDARKENTAT)
                        f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*a), QgsPointXY(*b)]))
                        f.setAttributes([taso, round(f.geometry().length(), 3)])
                        seinat.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        pistepilvi = None
        if self.parameterAsBoolean(parameters, self.PISTEPILVI, context):
            karttaan = pilvi or viereiset.get("las")
            if karttaan:
                lahde = os.path.basename(karttaan)
                nimi, suodatin = f"Pistepilvi ({lahde})", None
                if self.parameterAsBoolean(parameters, self.SIIVOA, context):
                    siivottu = self._siivoa_pilvi(karttaan, koord if karttaan == pilvi else None, tulos["viivat"],
                                                  context, feedback)
                    if siivottu:
                        karttaan, nimi, suodatin = siivottu, f"Pistepilvi siivottu ({lahde})", MAA_PIILOON
                # Korkeusväritys seinien kohdalta (maanpinnasta katolle), muuten koko pilven otsikosta
                korkeudet = None
                if xyz is not None and len(xyz) > 100:
                    import numpy as np
                    korkeudet = tuple(float(z) for z in np.percentile(xyz[:, 2], [1, 99]))
                varitys = VARITYKSET[self.parameterAsEnum(parameters, self.VARITYS, context)][1]
                pistepilvi = (karttaan, nimi, korkeudet, suodatin, varitys)
                feedback.pushInfo("Pistepilvi lisätään karttaan ajon jälkeen. QGIS tekee ensimmäisellä "
                                  "avauksella indeksin (iso LAZ: muutama minuutti), joten pisteet tulevat "
                                  "näkyviin hetken kuluttua. 3D-näkymä: Näytä -> 3D-karttanäkymät.")
            else:
                feedback.pushWarning("Pistepilveä (.las) ei löytynyt LiDAR-seinien DXF:n vierestä.")
        aseta_tyylit(context, [(tulokset_id.get(self.VERTAILU), "viiva"),
                               (tulokset_id.get(self.SEINAT_3D), "seinat_3d"),
                               (tulokset_id.get(self.LIDAR_SEINAT), "lidar_seinat"),
                               (tulokset_id.get(self.POIKKEAMA_LIDAR), "poikkeama"),
                               (tulokset_id.get(self.POIKKEAMA_PILVI), "poikkeama"),
                               (tulokset_id.get(self.PILVEN_SEINA), "pilven_seina")], pistepilvi, luokat)
        return tulokset_id

    def _lue_pilvi(self, polku, viivat, koord, context, feedback):
        """Pistepilven pisteet seinälinjan ympäriltä (PILVEN_RAJAUS_M) numpy-taulukkona (n x 3)
        ETRS-GK25:ssä (koord = ydin.las_koordinaatisto). Rajaus QGIS:n pdal:clip-työkalulla
        pakkaamattomaksi LAS:ksi, joten LAZ/COPC käy; jos PDAL puuttuu, pakkaamaton LAS luetaan
        kokonaan. Rajausalue annetaan pistepilven omina lukuina ja otsikon koordinaatistossa, joten
        rajaus osuu, muuntaako PDAL rajausalueen tai ei."""
        kaista = QgsGeometry.unaryUnion([
            QgsGeometry.fromPolylineXY([QgsPointXY(e, n) for e, n, _ in pisteet]).buffer(PILVEN_RAJAUS_M, 4)
            for _, pisteet in viivat if len(pisteet) > 1])
        feedback.pushInfo(f"Luetaan pistepilvi {os.path.basename(polku)} seinälinjan ympäriltä "
                          f"({PILVEN_RAJAUS_M} m, pdal:clip)...")
        rajaus = rajaa_pilvi(polku, kaista, koord, "seinalinjan_pistepilvi", context, feedback)
        if rajaus is None:
            return None
        luettava, rajattu = rajaus
        try:
            xyz = ydin.lue_las_xyz(luettava)
            if koord["siirto_x"]:
                xyz[:, 0] += koord["siirto_x"]
        except Exception as e:
            raise QgsProcessingException(f"Pistepilveä ei voitu lukea: {e}")
        finally:
            if rajattu:
                try:
                    os.remove(luettava)   # pakkaamaton rajaus on iso (satoja megatavuja)
                except OSError:
                    pass
        feedback.pushInfo(f"Pistepilvestä {len(xyz):,} pistettä seinälinjan ympäriltä.".replace(",", " "))
        if not len(xyz):
            feedback.pushWarning("Pistepilvessä ei ole pisteitä seinälinjan kohdalla (eri alue?).")
        return xyz

    def _siivoa_pilvi(self, polku, koord, viivat, context, feedback):
        """Siivottu pistepilvi karttaan (tilapäistiedosto, COPC): talot ja SIIVOUS_RAJAUS_M ympäriltä,
        kohina poistettu ja maanpinta luokassa 2. None (syy lokiin), jos PDAL-työkaluja ei ole tai
        siivous ei onnistu: silloin karttaan tulee siivoamaton pilvi."""
        import processing

        rekisteri = QgsApplication.processingRegistry()
        puuttuvat = [t for t in SIIVOUKSEN_TYOKALUT if rekisteri.algorithmById(t) is None]
        if puuttuvat:
            feedback.pushWarning(f"Pistepilveä ei siivottu: QGIS:stä puuttuu {', '.join(puuttuvat)} "
                                 "(PDAL-työkalut). Karttaan ladataan siivoamaton pistepilvi.")
            return None
        if koord is None:
            try:
                koord = ydin.las_koordinaatisto(polku)
            except (OSError, ValueError) as e:
                feedback.pushWarning(f"Pistepilveä ei siivottu ({e}). Karttaan ladataan siivoamaton pistepilvi.")
                return None
        alueet = []
        for viiva in viivat:
            pisteet = [QgsPointXY(e, n) for e, n in sl.viivan_pisteet(viiva)]
            if len(pisteet) < 2:
                continue
            # Suljettu viiva (talo) alueena, jotta myös katto tulee mukaan
            g = QgsGeometry.fromPolygonXY([pisteet]) if viiva["suljettu"] and len(pisteet) > 3 \
                else QgsGeometry.fromPolylineXY(pisteet)
            alueet.append(g.buffer(SIIVOUS_RAJAUS_M, 4))
        if not alueet:
            return None
        valivaiheet = []
        try:
            alku = time.time()
            rajaus = _rajausalue(QgsGeometry.unaryUnion(alueet), koord, "siivous_alue.geojson", context)
            rajattu = QgsProcessingUtils.generateTempFilename("siivous_rajattu.las", context)
            harvennettu = QgsProcessingUtils.generateTempFilename("siivous_harvennettu.las", context)
            ilman_kohinaa = QgsProcessingUtils.generateTempFilename("siivous_kohina.las", context)
            siivottu = QgsProcessingUtils.generateTempFilename("pistepilvi_siivottu.copc.laz", context)
            valivaiheet = [rajaus, rajattu, harvennettu, ilman_kohinaa]
            feedback.pushInfo(f"Siivotaan pistepilvi karttaan: talot ja {SIIVOUS_RAJAUS_M:g} m ympäriltä "
                              "(pdal:clip)...")
            processing.run("pdal:clip", {"INPUT": polku, "OVERLAY": rajaus, "OUTPUT": rajattu},
                           context=context, feedback=feedback, is_child_algorithm=True)
            if feedback.isCanceled():
                return None
            kohinaan = rajattu
            if rekisteri.algorithmById("pdal:thinbydecimate") is None:
                feedback.pushInfo("Harvennus ohitetaan: QGIS:stä puuttuu pdal:thinbydecimate.")
            else:
                feedback.pushInfo(f"Harvennetaan: joka {SIIVOUS_HARVENNUS}. piste (pdal:thinbydecimate)...")
                processing.run("pdal:thinbydecimate", {"INPUT": rajattu, "POINTS_NUMBER": SIIVOUS_HARVENNUS,
                                                       "OUTPUT": harvennettu},
                               context=context, feedback=feedback, is_child_algorithm=True)
                kohinaan = harvennettu
            if feedback.isCanceled():
                return None
            feedback.pushInfo("Poistetaan kohina (pdal:filternoisestatistical)...")
            processing.run("pdal:filternoisestatistical", {"INPUT": kohinaan, "REMOVE_NOISE_POINTS": True,
                                                           "OUTPUT": ilman_kohinaa},
                           context=context, feedback=feedback, is_child_algorithm=True)
            if feedback.isCanceled():
                return None
            korjatut = ydin.korjaa_paluunumerot(ilman_kohinaa)
            if korjatut:
                feedback.pushInfo(f"Paluunumero 1 asetettu {ydin.luku(korjatut)} pisteelle (puuttui "
                                  "keilauksesta, maanpinnan luokittelu vaatii sen).")
            feedback.pushInfo("Luokitellaan maanpinta (pdal:classifyground)...")
            processing.run("pdal:classifyground", {"INPUT": ilman_kohinaa, "OUTPUT": siivottu},
                           context=context, feedback=feedback, is_child_algorithm=True)
            if not os.path.isfile(siivottu):
                raise RuntimeError("siivottua pistepilveä ei syntynyt")
            ennen, jalkeen = ydin.las_pistemaara(kohinaan), ydin.las_pistemaara(ilman_kohinaa)
            maara = f"{ydin.luku(jalkeen)} pistettä" if jalkeen is not None else "valmis"
            if ennen is not None and jalkeen is not None:
                maara += f", kohinaa poistettu {ydin.luku(ennen - jalkeen)}"
            feedback.pushInfo(f"Pistepilvi siivottu {time.time() - alku:.0f} s:ssa ({maara}). Maanpinta "
                              "piilotetaan kartalla (tason suodatin Classification != 2).")
            return siivottu
        except Exception as e:
            if not feedback.isCanceled():
                feedback.pushWarning(f"Pistepilveä ei voitu siivota ({e}). Karttaan ladataan siivoamaton "
                                     "pistepilvi.")
            return None
        finally:
            for tiedosto in valivaiheet:
                try:
                    os.remove(tiedosto)   # pakkaamattomat välivaiheet ovat isoja
                except OSError:
                    pass

    def _tallenna_dxf(self, tulos, polku, context, feedback):
        """Seinälinjat DXF:ksi (R12, taso SEINALINJA, ETRS-GK25)."""
        try:
            ydin.kirjoita_dxf_r12([(v["nimi"], sl.viivan_pisteet(v)[:-1] if v["suljettu"] else sl.viivan_pisteet(v),
                                    v["suljettu"]) for v in tulos["viivat"]], polku)
        except OSError as e:
            feedback.pushWarning(f"DXF:ää ei voitu tallentaa ({e}).")
            return None
        feedback.pushInfo(f"Seinälinjat tallennettu: {polku}")
        return polku
