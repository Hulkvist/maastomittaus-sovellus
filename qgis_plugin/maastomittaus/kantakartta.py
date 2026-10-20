"""Kantakartan rakennukset seinälinjan vertailuun: QGIS:n rakennustasosta tai Helsingin
avoimesta WFS:stä. Palauttaa rakennukset samassa muodossa kuin sovellus
(hae_kiintopisteet.rakennusten_renkaat): [[ulkorengas, sisärenkaat...], ...], rengas = [(e, n), ...]."""

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeatureRequest,
                       QgsPointXY, QgsRectangle, QgsVectorLayer)

GK25 = "EPSG:3879"
HELSINKI_WFS_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"
HELSINKI_RAKENNUKSET_LAYER = "avoindata:Rakennukset_alue"
HELSINKI_BBOX_3067 = (370000, 6660000, 410000, 6690000)   # sama kuin hae_kiintopisteet.py


def _renkaat(geometria):
    """QgsGeometry (EPSG:3879) -> rakennukset renkaina; moniosaisen osat ovat omia rakennuksiaan."""
    if geometria.isEmpty():
        return []
    g = geometria
    g.convertToStraightSegment()   # kaarevat reunat murtoviivoiksi (muuttaa paikallaan)
    osat = g.asMultiPolygon() if g.isMultipart() else [g.asPolygon()]
    return [[[(p.x(), p.y()) for p in rengas] for rengas in osa] for osa in osat if osa]


def _rakennukset(lahde, lahde_crs, alue, transform_context, voimassa_kentta=None):
    gk25 = QgsCoordinateReferenceSystem(GK25)
    alue_gk25 = QgsRectangle(*alue)
    lahteeseen = QgsCoordinateTransform(gk25, lahde_crs, transform_context)
    gk25een = QgsCoordinateTransform(lahde_crs, gk25, transform_context)
    pyynto = QgsFeatureRequest().setFilterRect(lahteeseen.transformBoundingBox(alue_gk25))
    tulos = []
    for f in lahde.getFeatures(pyynto):
        if voimassa_kentta and f.fields().indexOf(voimassa_kentta) >= 0:
            tila = f[voimassa_kentta]
            if tila and str(tila) != "voimassa":
                continue
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        g.transform(gk25een)
        if not g.boundingBox().intersects(alue_gk25):
            continue
        tulos.extend(_renkaat(g))
    return tulos


def rakennukset_tasosta(lahde, alue, context):
    """Rakennukset QGIS:n polygonitasosta (mikä tahansa koordinaatisto) alueelta (EPSG:3879)."""
    return _rakennukset(lahde, lahde.sourceCrs(), alue, context.transformContext())


def on_helsingissa(alue, transform_context):
    """Onko alueen (EPSG:3879) keskipiste Helsingin kantakartan alueella."""
    muunnos = QgsCoordinateTransform(QgsCoordinateReferenceSystem(GK25), QgsCoordinateReferenceSystem("EPSG:3067"),
                                     transform_context)
    p = muunnos.transform(QgsPointXY((alue[0] + alue[2]) / 2, (alue[1] + alue[3]) / 2))
    x0, y0, x1, y1 = HELSINKI_BBOX_3067
    return x0 <= p.x() <= x1 and y0 <= p.y() <= y1


def hae_helsinki(alue, transform_context):
    """Helsingin kantakartan voimassa olevat rakennukset alueelta (WFS, QGIS:n oma yhteys)."""
    uri = (f"url='{HELSINKI_WFS_URL}' typename='{HELSINKI_RAKENNUKSET_LAYER}' version='2.0.0' "
           f"srsname='{GK25}' restrictToRequestBBOX='1'")
    taso = QgsVectorLayer(uri, "Helsingin rakennukset", "WFS")
    if not taso.isValid():
        raise RuntimeError("Helsingin kantakartan WFS-palveluun ei saatu yhteyttä")
    return _rakennukset(taso, taso.crs(), alue, transform_context, voimassa_kentta="tila")
