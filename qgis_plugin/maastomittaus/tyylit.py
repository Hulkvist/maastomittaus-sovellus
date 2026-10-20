"""Tulostasojen tyylit, jotka asetetaan, kun Processing lataa tasot karttaan."""

from qgis.core import (Qgis, QgsCategorizedSymbolRenderer, QgsColorRampShader, QgsContrastEnhancement,
                       QgsCoordinateReferenceSystem, QgsFillSymbol, QgsGradientColorRamp, QgsGradientStop,
                       QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsPointCloudAttributeByRampRenderer,
                       QgsPointCloudLayer, QgsPointCloudRgbRenderer, QgsProcessingLayerPostProcessorInterface,
                       QgsProperty, QgsRendererCategory,
                       QgsSingleSymbolRenderer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor

from . import ydin

SEINAN_KORKEUS_M = 3.0   # Seinät 3D -taso näin korkeana seinänä, keskellä mitattu korkeus


def _nimiot(layer, kentta):
    asetukset = QgsPalLayerSettings()
    asetukset.fieldName = kentta
    layer.setLabeling(QgsVectorLayerSimpleLabeling(asetukset))
    layer.setLabelsEnabled(True)


def _luokittain(kentta, luokat, symboli):
    """Luokiteltu tyyli: luokat = [(arvo, väri)], symboli(väri) -> QgsSymbol."""
    return QgsCategorizedSymbolRenderer(kentta, [QgsRendererCategory(arvo, symboli(vari), arvo)
                                                 for arvo, vari in luokat])


def _piste(vari):
    return QgsMarkerSymbol.createSimple({"name": "circle", "color": vari, "size": "1.6", "outline_style": "no"})


_EI_VERTAILUA = "#9a9a9a"   # Seinät 3D: pala, jonka kohdalta pistepilvestä tai LiDARista ei löytynyt seinää


def _seina_3d(layer, luokat=None):
    """Seinät 3D -taso (ydin.seinapalat): 3D-näkymässä SEINAN_KORKEUS_M korkea läpinäkyvä seinä,
    jonka keskellä on mitattu korkeus (kenttä korkeus_m). Mitatut pisteet ovat seinäpinnalla
    (prisman tai prismattoman mittauksen osumakohta, esim. 1-2 m maasta), joten seinä osuu
    pistepilven seinäpinnan kohdalle. Korkeus annetaan kentästä monikulmiolle, koska QGIS ei
    käytä viivan omia korkeuksia leveälle viivalle eikä kenttäkorkeutta viivasymbolille.
    Jos paloilla on vertailun luokka (kenttä luokka), seinä väritetään poikkeaman mukaan samoin
    värein kuin poikkeamatasot (harmaa = ei vertailukohtaa); muuten seinä on punainen.
    2D-kartalla taso ei näy. Jos 3D-tukea ei ole (tai rajapinta on eri), taso vain piilotetaan."""
    layer.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple(
        {"style": "no", "outline_style": "no"})))
    try:
        from qgis._3d import (QgsPhongMaterialSettings, QgsPolygon3DSymbol, QgsRuleBased3DRenderer,
                              QgsVectorLayer3DRenderer)
        try:
            from qgis.core import QgsAbstract3DSymbol
        except ImportError:
            from qgis._3d import QgsAbstract3DSymbol

        def symboli(vari, ambient=None):
            s = QgsPolygon3DSymbol()
            s.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
            s.setExtrusionHeight(SEINAN_KORKEUS_M)
            ominaisuus = QgsAbstract3DSymbol.Property.Height if hasattr(QgsAbstract3DSymbol, "Property") \
                else QgsAbstract3DSymbol.PropertyHeight
            maaritykset = s.dataDefinedProperties()
            maaritykset.setProperty(ominaisuus, QgsProperty.fromExpression(
                f'coalesce("korkeus_m", 0) - {SEINAN_KORKEUS_M / 2}'))
            s.setDataDefinedProperties(maaritykset)
            materiaali = QgsPhongMaterialSettings()
            materiaali.setAmbient(ambient or QColor(vari).darker(130))
            materiaali.setDiffuse(QColor(vari))
            materiaali.setOpacity(0.6)
            s.setMaterialSettings(materiaali)
            return s

        luokiteltu = layer.fields().indexOf("luokka") >= 0 and any(
            f["luokka"] not in (None, "") for f in layer.getFeatures())
        if not luokiteltu:
            layer.setRenderer3D(QgsVectorLayer3DRenderer(symboli("#e64632", QColor(200, 40, 30))))
            return
        juuri = QgsRuleBased3DRenderer.Rule(None)
        for _, luokka, vari in luokat or ydin.POIKKEAMALUOKAT:
            juuri.appendChild(QgsRuleBased3DRenderer.Rule(
                symboli(vari), f"\"luokka\" = '{luokka}'", luokka))
        muut = QgsRuleBased3DRenderer.Rule(symboli(_EI_VERTAILUA), "", "ei vertailukohtaa")
        muut.setIsElse(True)
        juuri.appendChild(muut)
        layer.setRenderer3D(QgsRuleBased3DRenderer(juuri))
    except Exception:
        pass


def _tyylita(layer, laji, luokat=None):
    if laji == "viiva":
        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({"color": "0,0,0", "width": "0.6"})))
        _nimiot(layer, "nimi")
    elif laji == "seinat_3d":
        _seina_3d(layer, luokat)
    elif laji == "pilven_seina":
        # Pistepilvestä löydetty seinäpinta: syaani, erottuu mustasta seinälinjasta ja violetista LiDARista
        layer.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple({"color": "0,170,230", "width": "0.5"})))
    elif laji == "kulmat":
        layer.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple(
            {"name": "cross2", "color": "255,0,0", "size": "3"})))
    elif laji == "lidar_seinat":
        # PAATELTY = lidarpipen ääriviivan päätellyt osat (ei mitattu): harmaa katkoviiva
        layer.setRenderer(_luokittain("taso", [("SEINA", "148,103,189"), ("EPAVARMA", "190,170,210"),
                                               ("PAATELTY", "150,150,150")],
                                      lambda vari: QgsLineSymbol.createSimple(
                                          {"color": vari, "width": "1.2" if vari.startswith("148") else "0.6",
                                           "line_style": "solid" if vari.startswith("148") else "dash"})))
    elif laji == "poikkeama":
        layer.setRenderer(_luokittain("luokka", [(luokka, vari) for _, luokka, vari in
                                                 (luokat or ydin.POIKKEAMALUOKAT)], _piste))
    layer.triggerRepaint()


class _Tyyli(QgsProcessingLayerPostProcessorInterface):
    """Tason tyyli; pistepilvi = (LAS-polku, tason nimi) lisätään samalla karttaan. Jälkikäsittely
    ajetaan pääsäikeessä: pistepilvitasoa ei voi luoda työkalun taustasäikeessä (QGIS kaatuu,
    kun ajon tilapäiset tasot siivotaan)."""

    def __init__(self, laji, pistepilvi=None, luokat=None):
        super().__init__()
        self.laji = laji
        self.pistepilvi = pistepilvi
        self.luokat = luokat

    def postProcessLayer(self, layer, context, feedback):  # noqa: N802
        _tyylita(layer, self.laji, self.luokat)
        if self.pistepilvi:
            lisaa_pistepilvi(*self.pistepilvi[:2], context.project(), feedback, *self.pistepilvi[2:])


# Pistepilven korkeusväritys (viridis): ei punaista, joten Seinät 3D -tason punainen seinä erottuu
_KORKEUSVARIT = ["#440154", "#3b528b", "#21918c", "#5ec962", "#fde725"]


def lisaa_pistepilvi(polku, nimi, projekti, feedback=None, korkeudet=None, suodatin=None, varitys="rgb"):
    """Pistepilvi karttaan pääsäikeessä: koordinaatisto otsikosta, väritys (varitys "rgb" =
    keilauksen värit, jos pilvessä on niitä, "korkeus" = korkeuden mukaan; korkeudet = (alin, ylin),
    muuten otsikosta) ja sama väritys 3D-näkymään valmiiksi, jotta sitä ei tarvitse vaihtaa
    jälkikäteen (QGIS 4.2 voi kaatua, kun 3D-tyyli vaihtuu kesken piirron). suodatin = tason
    suodatin (esim. maanpinta piiloon)."""
    pilvi = QgsPointCloudLayer(polku, nimi, "pdal")
    if not pilvi.isValid():
        if feedback:
            feedback.reportError(f"Pistepilveä ei voitu avata: {polku}")
        return None
    _pilven_koordinaatisto(pilvi, polku)
    if suodatin and not pilvi.setSubsetString(suodatin) and not pilvi.dataProvider().setSubsetString(suodatin) \
            and feedback:
        feedback.pushWarning(f"Pistepilven suodatinta ({suodatin}) ei voitu asettaa.")
    korkeudet = korkeudet or ydin.las_korkeusalue(polku)
    if varitys == "rgb" and ydin.las_on_rgb(polku):
        _rgb_varitys(pilvi)
    elif korkeudet and korkeudet[1] > korkeudet[0]:
        _korkeusvaritys(pilvi, *korkeudet)
    _pilvi_3d(pilvi)
    projekti.addMapLayer(pilvi)
    return pilvi


def _rgb_varitys(pilvi):
    """Keilauksen omat värit (16-bittiset, kuten LAS:ssa yleensä)."""
    piirtaja = QgsPointCloudRgbRenderer()
    for asetus, kentta in ((piirtaja.setRedAttribute, "Red"), (piirtaja.setGreenAttribute, "Green"),
                           (piirtaja.setBlueAttribute, "Blue")):
        asetus(kentta)
    try:
        venytys = QgsContrastEnhancement.ContrastEnhancementAlgorithm.StretchToMinimumMaximum
    except AttributeError:      # QGIS 3.x (PyQt5): luettelon jäsenet luokassa
        venytys = QgsContrastEnhancement.StretchToMinimumMaximum
    for asetus in (piirtaja.setRedContrastEnhancement, piirtaja.setGreenContrastEnhancement,
                   piirtaja.setBlueContrastEnhancement):
        kontrasti = QgsContrastEnhancement(Qgis.DataType.UInt16)
        kontrasti.setMinimumValue(0)
        kontrasti.setMaximumValue(65535)
        kontrasti.setContrastEnhancementAlgorithm(venytys)
        asetus(kontrasti)
    pilvi.setRenderer(piirtaja)


def _korkeusvaritys(pilvi, alin, ylin):
    ramppi = QgsGradientColorRamp(QColor(_KORKEUSVARIT[0]), QColor(_KORKEUSVARIT[-1]), False,
                                  [QgsGradientStop(i / (len(_KORKEUSVARIT) - 1), QColor(v))
                                   for i, v in enumerate(_KORKEUSVARIT[1:-1], start=1)])
    varjostin = QgsColorRampShader(alin, ylin, ramppi)
    varjostin.classifyColorRamp(len(_KORKEUSVARIT), -1)
    piirtaja = QgsPointCloudAttributeByRampRenderer()
    piirtaja.setAttribute("Z")
    piirtaja.setMinimum(alin)
    piirtaja.setMaximum(ylin)
    piirtaja.setColorRampShader(varjostin)
    pilvi.setRenderer(piirtaja)


def _pilvi_3d(pilvi):
    """3D-näkymän piirtäjä kartan värityksestä. QGIS tekee sen itse vain käsin avatulle pilvelle, ja
    indeksoimattomalle pilvelle siitä tulee tyhjä (kartalla vielä pelkkä alueen reuna)."""
    try:
        from qgis._3d import QgsPointCloudLayer3DRenderer
        piirtaja = QgsPointCloudLayer3DRenderer()
        piirtaja.convertFrom2DRenderer(pilvi.renderer())
        if piirtaja.symbol() is not None:
            pilvi.setRenderer3D(piirtaja)
        pilvi.setSync3DRendererTo2DRenderer(True)   # värityksen muutokset myös 3D-näkymään
    except Exception:
        pass   # ei 3D-tukea


def _pilven_koordinaatisto(pilvi, polku):
    """Pistepilvitason koordinaatisto otsikon luvuista (ydin.las_koordinaatisto): Stonexin pilvi
    ilman kaistan tunnusta on EPSG:3132 (QGIS siirtää sen tarkasti EPSG:3879:ään), ja EPSG:3132:ksi
    merkitty pilvi, jossa tunnus on mukana, on EPSG:3879. Muuten keilaus on ETRS-GK25:ssä kuten
    seinälinja, jos koordinaatistoa ei ole."""
    try:
        epsg = ydin.las_koordinaatisto(polku)["kerros_epsg"]
    except (OSError, ValueError):
        epsg = None if pilvi.crs().isValid() else ydin.GK25_EPSG
    if epsg and pilvi.crs().authid() != f"EPSG:{epsg}":
        pilvi.setCrs(QgsCoordinateReferenceSystem(f"EPSG:{epsg}"))


# QGIS ottaa jälkikäsittelijän omistukseensa ja tuhoaa sen ajon lopuksi, joten jokainen taso saa
# joka ajossa oman olionsa (uudelleen käytetty olio on jo tuhottu: "wrapped C/C++ object of type
# _Tyyli has been deleted", ja yhteinen olio kahdelle tasolle kaataisi QGIS:n). Python-puolen
# viittaus pidetään tallessa, jotta postProcessLayer on käytettävissä latauksessa.
_ELOSSA = []


def aseta_tyylit(context, tasot, pistepilvi=None, luokat=None):
    """tasot = [(tason dest_id, laji)]: tyyli asetetaan, kun Processing lataa tason karttaan.
    pistepilvi = (LAS-polku, nimi) lisätään karttaan ensimmäisen ladattavan tason yhteydessä.
    luokat = poikkeamatasojen luokat (ydin.poikkeamaluokat), oletuksena sovelluksen luokat.
    Palauttaa, lisätäänkö pistepilvi (False, jos mitään tasoa ei ladata karttaan)."""
    lisatty = False
    for dest_id, laji in tasot:
        if dest_id and context.willLoadLayerOnCompletion(dest_id):
            tyyli = _Tyyli(laji, pistepilvi if pistepilvi and not lisatty else None, luokat)
            _ELOSSA.append(tyyli)
            context.layerToLoadOnCompletionDetails(dest_id).setPostProcessor(tyyli)
            lisatty = lisatty or bool(tyyli.pistepilvi)
    del _ELOSSA[:-50]   # vain viimeisimmät ajot
    return lisatty
