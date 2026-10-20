"""LiDAR-keilauksen tulokset (Lidar-repon lidarpipe: <nimi>_seinat.dxf, <nimi>.las ja
<nimi>_raportti.json samassa kansiossa). DXF luetaan QGIS:n omalla lukijalla (GDAL), joten
lisäkirjastoja ei tarvita. Koordinaatit ovat ETRS-GK25:ssä (EPSG:3879) kuten keilauksessa."""

import os

from qgis.core import QgsVectorLayer

SEINA = "SEINA"
EPAVARMA = "EPAVARMA"
PAATELTY = "PAATELTY"   # lidarpipen ääriviivan päätellyt osat: vain järjestyksen apuna, ei vertailuun
DXF_PAATE = "_seinat.dxf"


def viereiset_tiedostot(dxf_polku):
    """Saman keilauksen pistepilvi ja raportti DXF:n vierestä: {"las", "raportti"} (None, jos puuttuu)."""
    pohja = dxf_polku[:-len(DXF_PAATE)] if dxf_polku.lower().endswith(DXF_PAATE) else os.path.splitext(dxf_polku)[0]
    tulos = {}
    for avain, polku in (("las", pohja + ".las"), ("raportti", pohja + "_raportti.json")):
        tulos[avain] = polku if os.path.isfile(polku) else None
    return tulos


def lue_seinat(dxf_polku):
    """Seinäjanat DXF:stä tasoittain: {"SEINA": [((e0, n0), (e1, n1)), ...], "EPAVARMA": [...], "PAATELTY": [...]}.
    Murtoviivat pilkotaan janoiksi; muut tasot (esim. TAHYKSET) ohitetaan."""
    taso = QgsVectorLayer(f"{dxf_polku}|layername=entities|geometrytype=LineString", "seinat", "ogr")
    if not taso.isValid():
        raise RuntimeError(f"LiDAR-seinien DXF:ää ei voitu lukea: {dxf_polku}")
    janat = {SEINA: [], EPAVARMA: [], PAATELTY: []}
    for f in taso.getFeatures():
        # DXF:n tasonimissä kirjainkoolla ei ole väliä (Seina = SEINA), kuten sovelluksen lue_lidar_dxf:ssä
        nimi = str(f["Layer"]).upper() if f.fields().indexOf("Layer") >= 0 else ""
        if nimi not in janat or f.geometry() is None or f.geometry().isEmpty():
            continue
        g = f.geometry()
        osat = g.asMultiPolyline() if g.isMultipart() else [g.asPolyline()]
        for osa in osat:
            janat[nimi].extend(((a.x(), a.y()), (b.x(), b.y())) for a, b in zip(osa, osa[1:]))
    return janat

