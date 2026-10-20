"""Tekee kannan mittaustasojen QGIS-tyylit: <taulu>.qml-tiedostot ja tyylit_kantaan.sql, joka
tallentaa ne kannan layer_styles-tauluun oletustyyleiksi (QGIS ottaa ne käyttöön tason lisäyksessä).
Ajetaan QGIS:n Pythonilla, esim. macOS:llä:

    cd qgis_tyylit && QT_QPA_PLATFORM=offscreen /Applications/QGIS-final-4_2_1.app/Contents/MacOS/python -P tee_tyylit.py

- asemapisteet: kolmio laatuluokan värillä, reunus aseman omalla värillä, nimiö aseman nimi
- asemien_liitokset: viiva asemalta liitospisteeseen aseman omalla värillä (korkeusliitos katkoviivana),
  nimiö liitospiste ja dHz (yli 20 mm punaisella)
- mittausraportit: iso violetti tähti, nimiö "Raportti" ja lähdetiedosto
- kentalla_mitatut_pisteet: ympyrä aseman värillä (asemattomat GNSS-pisteet harmaina), pistetunnus lähellä

Asemapisteillä, liitosviivoilla ja mitatuilla pisteillä on aika-asetus (sarake animaatioaika, jonka kanta
laskee mittausjärjestyksestä jarjestys): QGIS:n aikasäädin (Temporal Controller) toistaa mittauksen
tasaisessa tahdissa, yksi asema tai piste sekunnissa animaatioaikaa, ja aiemmat jäävät näkyviin.
(Lausekepohjainen aika ei suodata PostGIS-tasoa QGIS 4.2:ssa, joten aika luetaan sarakkeesta.)
"""
import os

from qgis.core import (QgsApplication, QgsCategorizedSymbolRenderer, QgsLineSymbol, QgsMapLayer,
                       QgsMarkerSymbol, QgsPalLayerSettings, QgsProperty, QgsRendererCategory,
                       QgsSimpleMarkerSymbolLayer, QgsSingleSymbolRenderer, QgsSymbolLayer, QgsTextBufferSettings,
                       QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling, Qgis)
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtXml import QDomDocument

KANSIO = os.path.dirname(os.path.abspath(__file__))
# Nimiöiden fontti, joka on sekä macOS:ssä että Windowsissa. Ilman sitä tyyliin tallentuu ajoympäristön
# oletus (näytöttömässä QGIS:ssä "Sans Serif"), jota QGIS yrittää ladata verkosta; QGIS 4.2 kaatui siihen
# Package layers -viennissä tyylien kanssa.
FONTTI = "Arial"
TYYLIN_NIMI = "Tietokanta"

LAATUVARIT = [("Erinomainen", "0,104,55"), ("Hyvä", "49,163,84"), ("Tyydyttävä", "254,196,79"),
              ("Heikko", "240,59,32"), ("Huono", "165,0,38"), ("Ei laskettavissa", "150,150,150")]
# Aseman oma väri järjestysnumerosta kiertäen kymmenen värin paletista (ei laatuluokkien vihreää
# eikä punaista, joka on varattu suurille residuaaleille)
ASEMAN_VARIT = ["#1f77b4", "#ff7f0e", "#9467bd", "#e377c2", "#17becf", "#8c564b", "#393b79", "#bcbd22",
                "#00796b", "#c51b7d"]
ASEMAN_VARI = (f"array_get(array({', '.join(repr(v) for v in ASEMAN_VARIT)}), "
               f"(coalesce(\"asema_nro\", 1) - 1) % {len(ASEMAN_VARIT)})")


def _animaatio(layer):
    """Aikasäätimen asetus: kohde näkyy järjestyksensä hetkestä alkaen ja jää näkyviin."""
    aika = layer.temporalProperties()
    aika.setIsActive(True)
    aika.setMode(Qgis.VectorTemporalMode.FeatureDateTimeInstantFromField)
    aika.setStartField("animaatioaika")   # vanhat rivit ilman järjestystä näkyvät koko ajan
    aika.setAccumulateFeatures(True)


def _nimio(layer, lauseke, sijoittelu, koko=9, vari=None, lahella=False):
    asetukset = QgsPalLayerSettings()
    asetukset.fieldName = lauseke
    asetukset.isExpression = True
    asetukset.placement = sijoittelu
    asetukset.dist = 1.5
    muoto = QgsTextFormat()
    muoto.setFont(QFont(FONTTI))
    muoto.setSize(koko)
    puskuri = QgsTextBufferSettings()
    puskuri.setEnabled(True)
    puskuri.setSize(1)
    puskuri.setColor(QColor("white"))
    muoto.setBuffer(puskuri)
    asetukset.setFormat(muoto)
    if vari:
        asetukset.dataDefinedProperties().setProperty(QgsPalLayerSettings.Property.Color, QgsProperty.fromExpression(vari))
    if lahella:   # vain lähelle zoomattuna (mittakaava 1:500 tai tarkempi)
        asetukset.scaleVisibility = True
        asetukset.minimumScale = 500
        asetukset.maximumScale = 0
    layer.setLabeling(QgsVectorLayerSimpleLabeling(asetukset))
    layer.setLabelsEnabled(True)


def asemapisteet():
    layer = QgsVectorLayer("Point?crs=EPSG:3879&field=asema:string&field=asema_nro:integer&field=laatuluokka:string"
                           "&field=jarjestys:integer&field=animaatioaika:datetime", "asemapisteet", "memory")
    luokat = []
    for luokka, vari in LAATUVARIT:
        # alla iso kolmio aseman värillä (reunus, sama kuin liitosviivoissa), päällä laatuluokan väri
        symboli = QgsMarkerSymbol.createSimple(
            {"name": "triangle", "color": vari, "outline_color": "35,35,35", "outline_width": "0.3", "size": "4.2"})
        reunus = QgsSimpleMarkerSymbolLayer.create(
            {"name": "triangle", "color": "0,0,0", "outline_color": "35,35,35", "outline_width": "0.3", "size": "7.5"})
        reunus.setDataDefinedProperty(QgsSymbolLayer.Property.FillColor, QgsProperty.fromExpression(ASEMAN_VARI))
        symboli.insertSymbolLayer(0, reunus)
        luokat.append(QgsRendererCategory(luokka, symboli, luokka))
    layer.setRenderer(QgsCategorizedSymbolRenderer("laatuluokka", luokat))
    _nimio(layer, '"asema"', Qgis.LabelPlacement.AroundPoint)
    _animaatio(layer)
    return layer


def asemien_liitokset():
    layer = QgsVectorLayer("LineString?crs=EPSG:3879&field=asema_nro:integer&field=liitospiste:string"
                           "&field=tyyppi:string&field=dhz_mm:double&field=jarjestys:integer&field=animaatioaika:datetime", "asemien_liitokset", "memory")
    symboli = QgsLineSymbol.createSimple({"line_color": "0,0,0", "line_width": "0.6"})
    viiva = symboli.symbolLayer(0)
    viiva.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor, QgsProperty.fromExpression(ASEMAN_VARI))
    viiva.setDataDefinedProperty(QgsSymbolLayer.Property.StrokeStyle,
                                 QgsProperty.fromExpression("if(\"tyyppi\" = 'korkeusliitos', 'dash', 'solid')"))
    layer.setRenderer(QgsSingleSymbolRenderer(symboli))
    _nimio(layer, '"liitospiste" || coalesce(\' \' || format_number("dhz_mm", 1) || \' mm\', \'\')',
           Qgis.LabelPlacement.Line, koko=8, vari="if(\"dhz_mm\" >= 20, '215,25,28,255', '0,0,0,255')")
    _animaatio(layer)
    return layer


def kentalla_mitatut_pisteet():
    layer = QgsVectorLayer("Point?crs=EPSG:3879&field=pistetunnus:string&field=asema_nro:integer"
                           "&field=jarjestys:integer&field=animaatioaika:datetime", "kentalla_mitatut_pisteet", "memory")
    symboli = QgsMarkerSymbol.createSimple({"name": "circle", "color": "120,120,120", "outline_color": "35,35,35",
                                            "outline_width": "0.2", "size": "2"})
    symboli.symbolLayer(0).setDataDefinedProperty(
        QgsSymbolLayer.Property.FillColor,
        QgsProperty.fromExpression(f'if("asema_nro" IS NULL, \'120,120,120\', {ASEMAN_VARI})'))
    layer.setRenderer(QgsSingleSymbolRenderer(symboli))
    _nimio(layer, '"pistetunnus"', Qgis.LabelPlacement.AroundPoint, koko=7, lahella=True)
    _animaatio(layer)
    return layer


def mittausraportit():
    layer = QgsVectorLayer("Point?crs=EPSG:3879&field=lahdetiedosto:string", "mittausraportit", "memory")
    symboli = QgsMarkerSymbol.createSimple({"name": "star", "color": "106,61,154", "outline_color": "255,255,255",
                                            "outline_width": "0.6", "size": "8"})
    layer.setRenderer(QgsSingleSymbolRenderer(symboli))
    _nimio(layer, "'Raportti: ' || \"lahdetiedosto\"", Qgis.LabelPlacement.AroundPoint)
    return layer


def qml(layer):
    doc = QDomDocument()
    virhe = layer.exportNamedStyle(doc, categories=QgsMapLayer.StyleCategory.Symbology
                                   | QgsMapLayer.StyleCategory.Labeling | QgsMapLayer.StyleCategory.Temporal)
    if virhe:
        raise RuntimeError(virhe)
    return doc.toString(2)


SQL_ALKU = """-- QGIS-oletustyylit kannan mittaustasoille (tehty: qgis_tyylit/tee_tyylit.py).
-- Aja kerran (Supabase: SQL Editor). Tämän jälkeen QGIS käyttää tyylejä automaattisesti,
-- kun taso lisätään. Jo lisätty taso: Layer Properties -> Style -> Load Style -> From Database.
CREATE TABLE IF NOT EXISTS public.layer_styles (
    id SERIAL PRIMARY KEY,
    f_table_catalog varchar,
    f_table_schema varchar,
    f_table_name varchar,
    f_geometry_column varchar,
    stylename text,
    styleqml xml,
    stylesld xml,
    useasdefault boolean,
    description text,
    owner varchar(63) DEFAULT CURRENT_USER,
    ui xml,
    update_time timestamp DEFAULT CURRENT_TIMESTAMP,
    type varchar,
    r_raster_column varchar
);
-- QGIS hakee tyylit myös tällä sarakkeella; vanhemman QGIS:n tekemästä taulusta se voi puuttua
ALTER TABLE public.layer_styles ADD COLUMN IF NOT EXISTS r_raster_column varchar;
"""


def sql(tyylit):
    osat = [SQL_ALKU]
    for taulu, teksti in tyylit:
        assert "$qml$" not in teksti
        # type jätetään tyhjäksi: QGIS ei löydä oletustyyliä, jos type ei vastaa sen omaa merkintää
        osat.append(f"""
UPDATE public.layer_styles SET useasdefault = false
    WHERE f_table_schema = 'public' AND f_table_name = '{taulu}';
DELETE FROM public.layer_styles
    WHERE f_table_schema = 'public' AND f_table_name = '{taulu}' AND stylename = '{TYYLIN_NIMI}';
INSERT INTO public.layer_styles
    (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, stylename, styleqml, useasdefault,
     description)
VALUES (current_database(), 'public', '{taulu}', 'geom', '{TYYLIN_NIMI}', XMLPARSE(DOCUMENT $qml${teksti}$qml$),
        true, 'Tietokanta-repon oletustyyli');
""")
    return "".join(osat)


def main():
    app = QgsApplication([], False)
    app.initQgis()
    tyylit = []
    for tee in (asemapisteet, asemien_liitokset, mittausraportit, kentalla_mitatut_pisteet):
        layer = tee()
        teksti = qml(layer)
        with open(os.path.join(KANSIO, f"{layer.name()}.qml"), "w", encoding="utf-8") as f:
            f.write(teksti)
        tyylit.append((layer.name(), teksti))
    with open(os.path.join(KANSIO, "tyylit_kantaan.sql"), "w", encoding="utf-8") as f:
        f.write(sql(tyylit))
    print("\n".join(f"{nimi}.qml" for nimi, _ in tyylit) + "\ntyylit_kantaan.sql")


if __name__ == "__main__":
    main()
