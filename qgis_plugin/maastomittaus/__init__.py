"""Maastomittaus-lisäosa QGIS:iin: seinälinja JobXML-tiedostosta (ks. README)."""


def classFactory(iface):  # noqa: N802 -- QGIS:n vaatima nimi
    # QGIS-riippuvuudet tuodaan vasta tässä, jotta ydin.py:tä voi testata ilman QGIS:iä
    from .plugin import MaastomittausPlugin
    return MaastomittausPlugin(iface)
