import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pytest.importorskip("folium")
import hae_kiintopisteet as hk
import seinalinja as sl

# Helsingin keskustan tuntumassa (ETRS-GK25)
E0, N0 = 25496000.0, 6672000.0


def piste(nimi, koodi, x, y, kategoria="Kartoituspiste"):
    return {"nimi": nimi, "koodi": koodi, "e": E0 + x, "n": N0 + y, "korkeus": 12.5, "kategoria": kategoria}


def test_ei_koordinaatteja_palauttaa_none():
    assert hk.luo_jobxml_interaktiivinen_kartta([{"nimi": "1", "e": None, "n": None}]) is None


def test_kartta_helsingissa_ja_wms_tasot():
    pisteet = [
        piste("A1", None, -20, -20, kategoria="Asemapiste"),
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "5", 10, 6),
    ]
    kartta = hk.luo_jobxml_interaktiivinen_kartta(pisteet, sl.muodosta_seinalinjat(pisteet))
    (lat1, lon1), (lat2, lon2) = kartta.get_bounds()
    for lat in (lat1, lat2):
        assert 60.1 < lat < 60.3
    for lon in (lon1, lon2):
        assert 24.8 < lon < 25.2

    html = kartta.get_root().render()
    assert hk.HELSINKI_KANTAKARTTA_LAYER in html
    assert hk.HELSINKI_WMS_URL in html
    assert "Sein\\u00e4linja" in html  # tasovalitsimen nimet ovat JSON-koodattuja


def test_symbolit_kartalla_ja_tasovalitsimessa():
    pisteet = [
        piste("A1", None, -20, -20, kategoria="Asemapiste"),
        piste("K1", None, 5, 5, kategoria="Korkeusliitos"),
        piste("1", "5", 0, 0),
    ]
    html = hk.luo_jobxml_interaktiivinen_kartta(pisteet).get_root().render()
    assert html.count("#FFD700") >= 2  # tähti kartalla + tasovalitsimessa
    assert "polygon" in html  # tähti ja kolmio (osin JSON-koodattuna)
    assert "Asemapiste" in html and "Korkeusliitos" in html


@pytest.mark.parametrize("merkki", ["o", "*", "^", "s", "D", "x"])
def test_symboli_svg(merkki):
    svg = hk._symboli_svg(merkki, "red", 14)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert 'fill="red"' in svg


# ---------------------------------------------------------------------------
# Taustakartat ja kiintopiste-/rajamerkkihaun kartta
# ---------------------------------------------------------------------------

def test_helsingin_alue():
    assert hk.on_helsingin_alueella(E0, N0)
    assert not hk.on_helsingin_alueella(23460000.0, 6820000.0)  # Turku (GK23-alue)


def _kiinteisto_kartta(**kw):
    kiintopisteet = [("KP-123", 11, N0 + 50, E0 + 30, 12.3, "E2", 58.3)]
    rajamerkit = [("RM1", E0 - 10, N0 - 10), ("RM2", E0 + 10, N0 - 10)]
    rajaviivat = [[(E0 - 10, N0 - 10), (E0 + 10, N0 - 10)]]
    return hk.luo_kiinteisto_interaktiivinen_kartta((E0, N0), kiintopisteet, rajamerkit, rajaviivat,
                                                    sade_m=100, **kw).get_root().render()


def test_kiinteistokartta_tasot():
    html = _kiinteisto_kartta(helsinki=True, api_key=None)
    for nimi in ("Kiintopisteet", "Rajamerkit", "Kiinteist\\u00f6n rajat", "Hakus\\u00e4de 100 m", "RM1"):
        assert nimi in html
    assert hk.HELSINKI_KANTAKARTTA_LAYER in html


def test_mml_taustakartat_vain_avaimella():
    assert "avoin-karttakuva.maanmittauslaitos.fi" not in _kiinteisto_kartta(helsinki=False, api_key=None)
    html = _kiinteisto_kartta(helsinki=False, api_key="testiavain")
    assert "taustakartta/default/WGS84_Pseudo-Mercator" in html
    assert "ortokuva/default/WGS84_Pseudo-Mercator" in html


def test_oletustausta_sijainnin_mukaan():
    import folium
    for helsinki, api_key, odotettu in ((True, "x", "Helsingin kantakartta"),
                                        (False, "x", "MML taustakartta"),
                                        (False, None, "OpenStreetMap")):
        kartta = folium.Map(tiles=None)
        hk._lisaa_taustakartat(kartta, api_key, helsinki)
        nakyvat = [c.layer_name for c in kartta._children.values()
                   if getattr(c, "overlay", True) is False and getattr(c, "show", False)]
        assert nakyvat == [odotettu]


def test_jobxml_kartta_seinalinja_kaarella():
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 8, 0), piste("3", "4", 10, -2),
               piste("4", "5", 12, 0), piste("5", "5", 12, 6), piste("6", "5", 0, 6)]
    kartta = hk.luo_jobxml_interaktiivinen_kartta(pisteet, sl.muodosta_seinalinjat(pisteet))
    viivat = [c for c in kartta._children.values() if hasattr(c, "_children")
              for v in c._children.values() if type(v).__name__ == "PolyLine" for c in [v]]
    assert viivat and len(viivat[0].locations) > 20  # kaari tihennetty


def test_kiintopiste_bbox_kattaa_hakualueen():
    x0, y0, x1, y1 = hk.kiintopiste_bbox_3067(E0, N0, 500)
    x, y = hk._muunnin(hk.DB_SRID, 3067).transform(E0, N0)
    assert x0 < x < x1 and y0 < y < y1
    # neliö keskipiste ± säde + 10 %; GK25- ja TM35-ruudukkojen ~1,7° kierto kasvattaa bboxia ~3 %
    assert 1100 <= x1 - x0 < 1150
    assert 1100 <= y1 - y0 < 1150


def test_rakennusten_nurkat_ilman_suoran_valipisteita():
    from shapely.geometry import Polygon
    # suorakulmio, jonka eteläsivulla on välipiste (ei nurkka)
    poly = Polygon([(E0, N0), (E0 + 5, N0), (E0 + 10, N0), (E0 + 10, N0 + 6), (E0, N0 + 6)])
    nurkat = hk.rakennusten_nurkat([{"nro": 1, "polygoni": poly}])
    assert [t for t, *_ in nurkat] == ["1", "2", "3", "4"]
    assert all(nro == 1 for *_, nro in nurkat)
    assert (E0 + 5, N0) not in [(e, n) for _, e, n, _ in nurkat]


def test_rakennusten_nurkat_sisapiha():
    from shapely.geometry import Polygon
    ulko = [(E0, N0), (E0 + 30, N0), (E0 + 30, N0 + 30), (E0, N0 + 30)]
    piha = [(E0 + 10, N0 + 10), (E0 + 20, N0 + 10), (E0 + 20, N0 + 20), (E0 + 10, N0 + 20)]
    nurkat = hk.rakennusten_nurkat([{"nro": 2, "polygoni": Polygon(ulko, [piha])}])
    assert len(nurkat) == 8
    assert nurkat[-1][0] == "8"


def test_kiinteiston_rakennukset_rajalla_oleva_pois(monkeypatch):
    from shapely.geometry import box, mapping

    alue = box(E0, N0, E0 + 50, N0 + 50)
    sisalla = box(E0 + 10, N0 + 10, E0 + 20, N0 + 20)
    rajalla = box(E0 + 45, N0 + 10, E0 + 60, N0 + 20)      # 5/15 kiinteistöllä
    purettu = box(E0 + 30, N0 + 30, E0 + 40, N0 + 40)

    class Vastaus:
        def raise_for_status(self):
            pass

        def json(self):
            return {"features": [
                {"geometry": mapping(sisalla), "properties": {"tila": "voimassa", "tyyppi": "Asuinrakennus",
                                                              "katunimi_suomi": "Testikatu", "osoitenumero": "1"}},
                {"geometry": mapping(rajalla), "properties": {"tila": "voimassa"}},
                {"geometry": mapping(purettu), "properties": {"tila": "purettu"}},
            ]}

    monkeypatch.setattr(hk.requests, "get", lambda *a, **k: Vastaus())
    rakennukset = hk.hae_kiinteiston_rakennukset(alue)
    assert len(rakennukset) == 1
    assert rakennukset[0]["nro"] == 1 and rakennukset[0]["osoite"] == "Testikatu 1"


def test_helsinki_rakennukset_ja_renkaat(monkeypatch):
    from shapely.geometry import box, mapping
    piha = box(E0 + 2, N0 + 2, E0 + 4, N0 + 4)
    sisapihallinen = box(E0, N0, E0 + 10, N0 + 10).difference(piha)
    purettu = box(E0 + 30, N0 + 30, E0 + 40, N0 + 40)

    class Vastaus:
        def raise_for_status(self):
            pass

        def json(self):
            return {"features": [
                {"geometry": mapping(sisapihallinen), "properties": {"tila": "voimassa"}},
                {"geometry": mapping(purettu), "properties": {"tila": "purettu"}},
            ]}

    pyynnot = []
    monkeypatch.setattr(hk.requests, "get", lambda url, params, timeout: pyynnot.append(params) or Vastaus())
    rakennukset = hk.hae_helsinki_rakennukset((E0 - 5, N0 - 5, E0 + 50, N0 + 50))
    assert len(rakennukset) == 1
    assert pyynnot[0]["bbox"].startswith(f"{E0 - 5},{N0 - 5},")
    renkaat = hk.rakennusten_renkaat(rakennukset)
    assert len(renkaat) == 1 and len(renkaat[0]) == 2   # ulkorengas + sisäpiha


def test_yhdistetty_txt_nurkat(tmp_path):
    polku = tmp_path / "kiintopisteet.krd"
    hk.kirjoita_yhdistetty_krd([], [], str(polku), kohde_epsg=hk.DB_SRID, nurkat=[("1", E0 + 1.5, N0 + 2.25, 1)])
    assert polku.read_bytes() == f"       1       0       4       1{E0 + 1.5:>14.3f}{N0 + 2.25:>14.3f}         0.000\r\n".encode()


def test_hakukartta_rakennusten_nurkat():
    from shapely.geometry import box
    rakennukset = [{"nro": 1, "osoite": "Testikatu 1", "polygoni": box(E0, N0, E0 + 10, N0 + 10)}]
    nurkat = hk.rakennusten_nurkat(rakennukset)
    html = hk.luo_kiinteisto_interaktiivinen_kartta((E0, N0), [], [], rakennukset=rakennukset,
                                                   nurkat=nurkat).get_root().render()
    assert "Rakennusten nurkat" in html and "Rakennus 1, Testikatu 1" in html


def test_karttamerkit_block_elementteina():
    # Inline-SVG valuisi tekstirivin verran alaspäin koordinaatista; tasovalitsimessa inline on oikein.
    html = hk.luo_kiinteisto_interaktiivinen_kartta(
        (E0, N0), [], [("rm1", E0 + 5, N0 + 5)]).get_root().render()
    assert "display:block" in html
    assert "vertical-align:middle" in html


def test_rakennusten_nurkat_juokseva_numerointi_rakennusten_yli():
    from shapely.geometry import box
    rakennukset = [{"nro": 1, "polygoni": box(E0, N0, E0 + 10, N0 + 10)},
                   {"nro": 2, "polygoni": box(E0 + 20, N0, E0 + 25, N0 + 5)}]
    nurkat = hk.rakennusten_nurkat(rakennukset)
    assert [t for t, *_ in nurkat] == [str(i) for i in range(1, 9)]
    assert [nro for *_, nro in nurkat] == [1, 1, 1, 1, 2, 2, 2, 2]


def test_png_kartan_taustatiilet_tammelassa(tmp_path, monkeypatch):
    """Helsingin ulkopuolella: zoom Web Mercator -metreistä (ennen 81 tiiltä, nyt ~25)
    ja tiilet ladataan rinnakkain."""
    import numpy as np
    import contextily

    kutsut = []

    def bounds2img(w, s, e, n, **k):
        kutsut.append(k)
        return np.zeros((8, 8, 3), dtype=np.uint8), (w, e, s, n)

    monkeypatch.setattr(contextily, "bounds2img", bounds2img)
    e, n = hk._muunnin(4326, 3879).transform(23.758, 60.808)
    polku = tmp_path / "kartta.png"
    hk.piirra_kartta((e, n), [], [], str(polku), "avain", sade_m=1000, kiinteistotunnus="834-434-1-158")
    assert polku.exists()
    assert kutsut[0]["zoom"] == 15 and kutsut[0]["n_connections"] == 4
    hk.piirra_kartta((e, n), [], [], str(polku), "avain", sade_m=100, kiinteistotunnus="834-434-1-158")
    assert kutsut[1]["zoom"] == 16  # MML:n tiilet enintään tasolle 16


def _kaksi_seinalinjaa():
    # viiva 1 origossa, viiva 2 sata metriä itään
    return [piste("1", "8", 0, 0), piste("2", "5", 10, 0), piste("3", "5", 10, 6), piste("4", "5", 0, 6),
            piste("11", "8 2", 100, 0), piste("12", "5 2", 108, 0), piste("13", "5 2", 108, 5),
            piste("14", "5 2", 100, 5)]


def _rajaus(kartta):
    return next(c.bounds for c in kartta._children.values() if type(c).__name__ == "FitBounds")


def test_seinalinjakartta_tyhja_palauttaa_none():
    assert hk.luo_seinalinja_interaktiivinen_kartta({"viivat": [], "pisteet": []}) is None


def test_seinalinjakartta_merkinnat():
    tulos = sl.muodosta_seinalinjat(_kaksi_seinalinjaa())
    kartta = hk.luo_seinalinja_interaktiivinen_kartta(tulos)
    html = kartta.get_root().render()
    assert "Viiva 1" in html and "Viiva 2" in html
    for vari, _ in (hk.SEINALINJA_KOODIVARIT[8], hk.SEINALINJA_KOODIVARIT[5]):
        assert vari in html
    assert "Pistenimet" in html
    viivat = [v for c in kartta._children.values() for v in getattr(c, "_children", {}).values()
              if type(v).__name__ == "PolyLine"]
    assert len(viivat) == 2


def test_seinalinjakartta_rajaus_viivaan():
    tulos = sl.muodosta_seinalinjat(_kaksi_seinalinjaa())
    latlon = hk._latlon_muunnin()
    (_, lon_min), (_, lon_max) = _rajaus(hk.luo_seinalinja_interaktiivinen_kartta(tulos))
    assert lon_min <= latlon(E0, N0)[1] and lon_max >= latlon(E0 + 108, N0)[1]

    (_, lon_min), (_, lon_max) = _rajaus(hk.luo_seinalinja_interaktiivinen_kartta(tulos, viiva="Viiva 2"))
    assert lon_min > latlon(E0 + 50, N0)[1]  # viiva 1 jää rajauksen ulkopuolelle
    assert lon_max >= latlon(E0 + 108, N0)[1]


def test_rajaa_viivaan():
    tulos = sl.muodosta_seinalinjat(_kaksi_seinalinjaa())
    rajattu = sl.rajaa_viivaan(tulos, "Viiva 2")
    assert [v["numero"] for v in rajattu["viivat"]] == [2]
    assert {p["nimi"] for p in rajattu["pisteet"]} == {"11", "12", "13", "14"}


def test_popupissa_ominaisuustiedot():
    pisteet = [piste("1", "RAK 8", 0, 0), piste("2", "RAK 5", 10, 0), piste("3", "RAK 5", 10, 6)]
    for p in pisteet:
        p["ominaisuudet"] = [{"kohde": "RAK", "nimi": "Rakennetyyppi", "arvo": "Sokkeli", "tyyppi": "Menu"}]
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert [v["nimi"] for v in tulos["viivat"]] == ["RAK Sokkeli"]
    for kartta in (hk.luo_seinalinja_interaktiivinen_kartta(tulos),
                   hk.luo_jobxml_interaktiivinen_kartta(pisteet, tulos)):
        assert "Rakennetyyppi: Sokkeli" in kartta.get_root().render()


def test_seinalinjakartta_lidar_tasot():
    tulos = sl.muodosta_seinalinjat(_kaksi_seinalinjaa())
    lidar = {"SEINA": [((E0, N0 + 0.03), (E0 + 10, N0 + 0.03))], "EPAVARMA": [((E0 + 10, N0), (E0 + 10, N0 + 6))]}
    poikkeamat = sl.poikkeamat_lidarista(tulos, lidar["SEINA"])
    html = hk.luo_seinalinja_interaktiivinen_kartta(tulos, lidar=lidar, poikkeamat_lidar=poikkeamat).get_root().render()
    assert "LiDAR-sein\\u00e4t" in html and "Poikkeama LiDARista" in html and "#9467bd" in html  # JSON-koodattu
    assert "3.0 cm" in html   # poikkeamapisteen vihje
    ilman = hk.luo_seinalinja_interaktiivinen_kartta(tulos).get_root().render()
    assert "LiDAR" not in ilman
