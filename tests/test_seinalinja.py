import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seinalinja as sl

# ETRS-GK25-tyyppinen origo, jotta testit käyttävät todellisen kokoisia koordinaatteja
E0, N0 = 25496000.0, 6672000.0


def piste(nimi, koodi, x, y, z=10.0):
    return {"nimi": nimi, "koodi": koodi, "e": E0 + x, "n": N0 + y, "korkeus": z}


def karjet_xy(viiva):
    return [(round(k["e"] - E0, 3), round(k["n"] - N0, 3)) for k in viiva["karjet"]]


def samat_kierrot(a, b):
    """Suljettu viiva: sama kärkijoukko samassa kiertojärjestyksessä (kumpaan suuntaan tahansa)."""
    if len(a) != len(b):
        return False
    for kierto in (b, list(reversed(b))):
        for i in range(len(kierto)):
            if a == kierto[i:] + kierto[:i]:
                return True
    return False


def test_koodi_numeroksi():
    assert sl.koodi_numeroksi("5") == 5
    assert sl.koodi_numeroksi(" 100 ") == 100
    assert sl.koodi_numeroksi("5 KULMA") == 5
    assert sl.koodi_numeroksi("PUU") is None
    assert sl.koodi_numeroksi(None) is None


def test_ei_8_pistetta_ei_laukaise():
    pisteet = [piste("1", "5", 0, 0), piste("2", "5", 10, 0)]
    assert not sl.on_seinalinjapisteita(pisteet)
    assert sl.muodosta_seinalinjat(pisteet)["viivat"] == []


def test_yksi_8_suljettu_lyhin_reitti_sekoitetusta_jarjestyksesta():
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 6),
        piste("3", "5", 10, 0),
        piste("4", "5", 0, 6),
        piste("PUU", "PUU", 50, 50),  # muut koodit eivät kuulu seinälinjaan
    ]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="lyhin")
    assert len(tulos["viivat"]) == 1
    viiva = tulos["viivat"][0]
    assert viiva["suljettu"]
    assert karjet_xy(viiva)[0] == (0, 0)
    assert samat_kierrot(karjet_xy(viiva), [(0, 0), (10, 0), (10, 6), (0, 6)])


def test_mittausjarjestys_sailyttaa_jarjestyksen():
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 6),
        piste("3", "5", 10, 0),
        piste("4", "5", 0, 6),
    ]
    viiva = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")["viivat"][0]
    assert karjet_xy(viiva) == [(0, 0), (10, 6), (10, 0), (0, 6)]


def test_kaksi_8_avoin_viiva():
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "5", 10, 6),
        piste("4", "8", 0, 6),
    ]
    viiva = sl.muodosta_seinalinjat(pisteet)["viivat"][0]
    assert not viiva["suljettu"]
    assert karjet_xy(viiva) == [(0, 0), (10, 0), (10, 6), (0, 6)]


def test_kolme_8_jatkuu_keskimmaisen_kautta():
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "8", 10, 6),
        piste("4", "5", 0, 6),
        piste("5", "8", 0, 3),
    ]
    viiva = sl.muodosta_seinalinjat(pisteet)["viivat"][0]
    assert not viiva["suljettu"]
    assert karjet_xy(viiva) == [(0, 0), (10, 0), (10, 6), (0, 6), (0, 3)]


def test_pisteet_8_alueen_ulkopuolella_jatetaan_pois():
    pisteet = [
        piste("0", "5", -5, -5),
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "8", 10, 6),
    ]
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert [p["nimi"] for p in tulos["pois_jatetyt"]] == ["0"]
    assert tulos["varoitukset"]
    assert karjet_xy(tulos["viivat"][0]) == [(0, 0), (10, 0), (10, 6)]


def test_kaksi_linjapistetta_leikkauspiste():
    # Kulma (10, 6) on piilossa: linjapisteet (10, 4) ja (8, 6)
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "100", 10, 4),
        piste("4", "100", 8, 6),
        piste("5", "5", 0, 6),
    ]
    viiva = sl.muodosta_seinalinjat(pisteet)["viivat"][0]
    xy = karjet_xy(viiva)
    assert samat_kierrot(xy, [(0, 0), (10, 0), (10, 6), (0, 6)])
    laskettu = [k for k in viiva["karjet"] if k["laji"] == "laskettu"]
    assert len(laskettu) == 1
    assert laskettu[0]["e"] - E0 == pytest.approx(10, abs=0.001)
    assert laskettu[0]["n"] - N0 == pytest.approx(6, abs=0.001)


def test_piilokulma_kierron_yli_suljetussa_viivassa():
    # Kulma (0, 6) piilossa viimeisen kulman ja 8-pisteen välissä
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "5", 10, 6),
        piste("4", "100", 3, 6),
        piste("5", "100", 0, 3),
    ]
    viiva = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")["viivat"][0]
    assert viiva["suljettu"]
    assert karjet_xy(viiva) == [(0, 0), (10, 0), (10, 6), (0, 6)]


def test_kolme_linjapistetta_leikkauspiste():
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "100", 10, 2),
        piste("4", "100", 10, 4),
        piste("5", "100", 7, 6),
        piste("6", "5", 0, 6),
    ]
    viiva = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")["viivat"][0]
    assert karjet_xy(viiva) == [(0, 0), (10, 0), (10, 6), (0, 6)]


def test_yksi_linjapiste_suoralla_ei_lisaa_karkea():
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "100", 10, 3),
        piste("4", "5", 10, 6),
        piste("5", "5", 0, 6),
    ]
    viiva = sl.muodosta_seinalinjat(pisteet)["viivat"][0]
    assert samat_kierrot(karjet_xy(viiva), [(0, 0), (10, 0), (10, 6), (0, 6)])


def test_yksi_linjapiste_suoran_ulkopuolella_suora_kulma():
    # Kulma (10, 6) piilossa, vain yksi linjapiste (10, 4) A:n seinältä
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "100", 10, 4),
        piste("4", "5", 0, 6),
    ]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    assert karjet_xy(tulos["viivat"][0]) == [(0, 0), (10, 0), (10, 6), (0, 6)]
    assert any("90" in v for v in tulos["varoitukset"])


def test_yksi_linjapiste_b_n_seinalla():
    # Kulma (10, 6) piilossa, linjapiste (4, 6) B:n puoleiselta seinältä
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "100", 4, 6),
        piste("4", "5", 0, 6),
    ]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    assert karjet_xy(tulos["viivat"][0]) == [(0, 0), (10, 0), (10, 6), (0, 6)]


def test_heuristinen_jarjestys_isolla_pistemaaralla():
    # 20 kulmaa ympyrän kehällä sekoitetussa järjestyksessä -> lyhin reitti kiertää kehän
    import math
    import random
    kehapisteet = [(20 * math.cos(2 * math.pi * i / 20), 20 * math.sin(2 * math.pi * i / 20)) for i in range(20)]
    jarjestys = list(range(1, 20))
    random.Random(1).shuffle(jarjestys)
    pisteet = [piste("0", "8", *kehapisteet[0])] + [piste(str(i), "5", *kehapisteet[i]) for i in jarjestys]
    viiva = sl.muodosta_seinalinjat(pisteet)["viivat"][0]
    odotettu = [(round(E0 + x, 3) - E0, round(N0 + y, 3) - N0) for x, y in kehapisteet]
    odotettu = [(round(x, 3), round(y, 3)) for x, y in odotettu]
    assert samat_kierrot(karjet_xy(viiva), odotettu)


def test_dxf_vienti(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    pisteet = [
        piste("1", "8", 0, 0),
        piste("2", "5", 10, 0),
        piste("3", "100", 10, 4),
        piste("4", "100", 8, 6),
        piste("5", "5", 0, 6),
    ]
    tulos = sl.muodosta_seinalinjat(pisteet)
    polku = sl.kirjoita_dxf(tulos, str(tmp_path / "seinalinja.dxf"))

    doc = ezdxf.readfile(polku)
    msp = doc.modelspace()
    viivat = msp.query('LWPOLYLINE[layer=="SEINALINJA"]')
    assert len(viivat) == 1
    assert viivat[0].closed
    assert len(viivat[0]) == 4
    assert len(msp.query('POINT[layer=="MITATUT_PISTEET"]')) == 5
    assert len(msp.query('POINT[layer=="LASKETUT_KULMAT"]')) == 1
    # Tekstit omalla tasollaan (QGIS näyttää ne pisteinä, joten ne pitää voida piilottaa)
    assert len(msp.query('TEXT[layer=="PISTETEKSTIT"]')) == 5
    assert len(msp.query('TEXT[layer=="MITATUT_PISTEET"]')) == 0


def test_esikatselukuva(tmp_path):
    pytest.importorskip("matplotlib")
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 10, 0), piste("3", "5", 10, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet)
    polku = sl.piirra_seinalinja_kartta(tulos, str(tmp_path / "seinalinja.png"))
    assert os.path.getsize(polku) > 0


def test_esikatselukuva_taustakartalla(tmp_path):
    np = pytest.importorskip("numpy")
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 10, 0), piste("3", "5", 10, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet)
    pyydetyt = []

    def tausta(bbox):
        pyydetyt.append(bbox)
        return np.full((10, 10, 3), 200, dtype=np.uint8)

    polku = sl.piirra_seinalinja_kartta(tulos, str(tmp_path / "a.png"), hae_tausta=tausta)
    assert os.path.getsize(polku) > 0
    xmin, ymin, xmax, ymax = pyydetyt[0]
    assert xmax - xmin == pytest.approx(ymax - ymin)  # neliö, jotta kuva ei veny
    assert xmin < E0 and xmax > E0 + 10 and ymin < N0 and ymax > N0 + 6


def test_esikatselukuva_taustan_virhe_ei_kaada(tmp_path):
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 10, 0), piste("3", "5", 10, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet)

    def rikki(bbox):
        raise RuntimeError("WMS ei vastaa")

    polku = sl.piirra_seinalinja_kartta(tulos, str(tmp_path / "b.png"), hae_tausta=rikki)
    assert os.path.getsize(polku) > 0


# ---------------------------------------------------------------------------
# Useampi seinälinja kulmien välissä (parveke, syvennys)
# ---------------------------------------------------------------------------

def _uloke(suunta):
    """Seinä y=0, uloke x=8..12 syvyydeltään 3 m (suunta -1 = parveke ulos, +1 = syvennys)."""
    s = suunta
    return [
        piste("1", "8", 0, 0),
        piste("2", "100", 8, 1 * s), piste("3", "100", 8, 2.5 * s),
        piste("4", "100", 9, 3 * s), piste("5", "100", 11, 3 * s),
        piste("6", "100", 12, 2.5 * s), piste("7", "100", 12, 1 * s),
        piste("8", "5", 20, 0), piste("9", "5", 20, 10), piste("10", "5", 0, 10),
    ]


@pytest.mark.parametrize("tapa", ["mittaus", "lyhin"])
@pytest.mark.parametrize("suunta", [-1, 1])
def test_parveke_ja_syvennys(tapa, suunta):
    tulos = sl.muodosta_seinalinjat(_uloke(suunta), tapa=tapa)
    s = 3 * suunta
    assert samat_kierrot(karjet_xy(tulos["viivat"][0]),
                         [(0, 0), (8, 0), (8, s), (12, s), (12, 0), (20, 0), (20, 10), (0, 10)])
    assert tulos["varoitukset"] == []


def test_kolme_linjapistetta_piilokulman_ympari():
    # 8 -> 100 -> (piilokulma 10,0) -> 100 -> 100 -> 5
    pisteet = [
        piste("1", "8", 0, 0), piste("2", "100", 5, 0), piste("3", "100", 10, 3),
        piste("4", "100", 10, 6), piste("5", "5", 10, 8), piste("6", "5", 0, 8),
    ]
    for tapa in ("mittaus", "lyhin"):
        viiva = sl.muodosta_seinalinjat(pisteet, tapa=tapa)["viivat"][0]
        assert samat_kierrot(karjet_xy(viiva), [(0, 0), (10, 0), (10, 8), (0, 8)])


def test_apupisteet_eivat_vaikuta():
    pisteet = [
        piste("1", "8", 0, 0), piste("2", "5", 10, 0), piste("A1", "1", 6, 3),
        piste("3", "5", 10, 6), piste("A2", "APU", 3, 7.5), piste("4", "5", 0, 6),
    ]
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert samat_kierrot(karjet_xy(tulos["viivat"][0]), [(0, 0), (10, 0), (10, 6), (0, 6)])
    assert {p["nimi"] for p in tulos["pisteet"]} == {"1", "2", "3", "4"}


# ---------------------------------------------------------------------------
# Kaaret (koodi 4)
# ---------------------------------------------------------------------------
import math


def _ympyralla(cx, cy, r, kulma):
    return cx + r * math.cos(math.radians(kulma)), cy + r * math.sin(math.radians(kulma))


def _lahin_etaisyys_viivaan(viiva, x, y):
    """Etäisyys tihennetyn viivan lähimpään janaan."""
    pts = [(px - E0, py - N0) for px, py in sl.viivan_pisteet(viiva)]
    lahin = float("inf")
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        dx, dy = x2 - x1, y2 - y1
        t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1)))
        lahin = min(lahin, math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)))
    return lahin


def _kaaren_karki(viiva):
    return [k for k in viiva["karjet"] if abs(k["bulge"]) > 1e-9]


def test_kaari_yksi_kaaripiste_paat_nakyvat():
    # Puoliympyräerkkeri (8,0)-(12,0), kaaripiste (10,-2)
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 8, 0), piste("3", "4", 10, -2),
               piste("4", "5", 12, 0), piste("5", "5", 20, 0), piste("6", "5", 20, 6), piste("7", "5", 0, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    viiva = tulos["viivat"][0]
    assert tulos["varoitukset"] == []
    kaaret = _kaaren_karki(viiva)
    assert len(kaaret) == 1 and kaaret[0]["nimi"] == "2"
    assert abs(kaaret[0]["bulge"]) == pytest.approx(1.0, abs=1e-6)  # puoliympyrä
    assert _lahin_etaisyys_viivaan(viiva, 10, -2) < 0.005


def test_kaari_kaksi_kaaripistetta_paat_nakyvat():
    p1, p2 = _ympyralla(10, 0, 2, -135), _ympyralla(10, 0, 2, -45)
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 8, 0), piste("3", "4", *p1), piste("4", "4", *p2),
               piste("5", "5", 12, 0), piste("6", "5", 20, 0), piste("7", "5", 20, 6), piste("8", "5", 0, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    viiva = tulos["viivat"][0]
    assert tulos["varoitukset"] == []
    assert len(_kaaren_karki(viiva)) == 1
    for x, y in (p1, p2, (10, -2)):
        assert _lahin_etaisyys_viivaan(viiva, x, y) < 0.005


def test_kaari_piilopaat_kolme_kaaripistetta():
    # Ympyrä keskipiste (10,1), säde 2.6 -> leikkaa seinän y=0 kohdissa 10 ± 2.4
    kp = [_ympyralla(10, 1, 2.6, t) for t in (-120, -90, -60)]
    pisteet = [piste("1", "8", 0, 0), piste("2", "100", 4, 0), piste("3", "100", 6, 0)] + \
        [piste(str(4 + i), "4", *p) for i, p in enumerate(kp)] + \
        [piste("7", "100", 14, 0), piste("8", "100", 16, 0), piste("9", "5", 20, 0),
         piste("10", "5", 20, 6), piste("11", "5", 0, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    viiva = tulos["viivat"][0]
    assert tulos["varoitukset"] == []
    lasketut = [(round(k["e"] - E0, 3), round(k["n"] - N0, 3)) for k in viiva["karjet"] if k["laji"] == "laskettu"]
    assert lasketut == [(7.6, 0.0), (12.4, 0.0)]
    for x, y in kp:
        assert _lahin_etaisyys_viivaan(viiva, x, y) < 0.005


def test_kaari_piilopaat_kaksi_kaaripistetta_puoliympyra_varoitus():
    kp = [_ympyralla(10, 0, 2.5, t) for t in (-135, -45)]
    pisteet = [piste("1", "8", 0, 0), piste("2", "100", 4, 0), piste("3", "100", 6, 0),
               piste("4", "4", *kp[0]), piste("5", "4", *kp[1]),
               piste("6", "100", 14, 0), piste("7", "100", 16, 0), piste("8", "5", 20, 0),
               piste("9", "5", 20, 6), piste("10", "5", 0, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    lasketut = [(round(k["e"] - E0, 3), round(k["n"] - N0, 3))
                for k in tulos["viivat"][0]["karjet"] if k["laji"] == "laskettu"]
    assert lasketut == [(7.5, 0.0), (12.5, 0.0)]
    assert any("puoliympyrä" in v for v in tulos["varoitukset"])


def test_kaari_piilopaat_yksi_kaaripiste_samalla_seinalla_ei_riita():
    pisteet = [piste("1", "8", 0, 0), piste("2", "100", 4, 0), piste("3", "100", 6, 0),
               piste("4", "4", 10, -2), piste("5", "100", 14, 0), piste("6", "100", 16, 0),
               piste("7", "5", 20, 0), piste("8", "5", 20, 6), piste("9", "5", 0, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    assert any("vähintään 3 kaaripistettä" in v for v in tulos["varoitukset"])
    assert not _kaaren_karki(tulos["viivat"][0])


def test_kaari_pyoristetty_kulma_yksi_kaaripiste():
    # Kulma (20,0) pyöristetty säteellä 3: kaari sivuaa seiniä kohdissa (17,0) ja (20,3)
    kp = _ympyralla(17, 3, 3, -45)
    pisteet = [piste("1", "8", 0, 0), piste("2", "100", 10, 0), piste("3", "100", 14, 0),
               piste("4", "4", *kp), piste("5", "100", 20, 6), piste("6", "100", 20, 9),
               piste("7", "5", 20, 12), piste("8", "5", 0, 12)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    viiva = tulos["viivat"][0]
    lasketut = [(round(k["e"] - E0, 3), round(k["n"] - N0, 3)) for k in viiva["karjet"] if k["laji"] == "laskettu"]
    assert lasketut == [(17.0, 0.0), (20.0, 3.0)]
    assert any("sivuaa" in v for v in tulos["varoitukset"])
    assert _lahin_etaisyys_viivaan(viiva, *kp) < 0.005


def test_kaari_toinen_paa_piilossa_kaksi_kaaripistetta():
    # Kaari alkaa näkyvästä kulmasta (8,0), loppupää piilossa seinällä y=0
    kp = [_ympyralla(10, 0, 2, t) for t in (-150, -60)]
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 8, 0), piste("3", "4", *kp[0]), piste("4", "4", *kp[1]),
               piste("5", "100", 14, 0), piste("6", "100", 16, 0), piste("7", "5", 20, 0),
               piste("8", "5", 20, 6), piste("9", "5", 0, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    lasketut = [(round(k["e"] - E0, 3), round(k["n"] - N0, 3))
                for k in tulos["viivat"][0]["karjet"] if k["laji"] == "laskettu"]
    assert lasketut == [(12.0, 0.0)]
    assert tulos["varoitukset"] == []


def test_kaari_dxf_bulge(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from ezdxf.math import bulge_to_arc
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 8, 0), piste("3", "4", 10, -2),
               piste("4", "5", 12, 0), piste("5", "5", 20, 0), piste("6", "5", 20, 6), piste("7", "5", 0, 6)]
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    doc = ezdxf.readfile(sl.kirjoita_dxf(tulos, str(tmp_path / "kaari.dxf")))
    viiva = doc.modelspace().query('LWPOLYLINE[layer=="SEINALINJA"]')[0]
    kaaret = [(i, p) for i, p in enumerate(viiva.get_points("xyb")) if abs(p[2]) > 1e-9]
    assert len(kaaret) == 1
    i, (x, y, b) = kaaret[0]
    seuraava = viiva.get_points("xyb")[i + 1]
    keski, _, _, sade = bulge_to_arc((x, y), seuraava[:2], b)
    assert keski.x - E0 == pytest.approx(10, abs=0.001)
    assert keski.y - N0 == pytest.approx(0, abs=0.001)
    assert sade == pytest.approx(2, abs=0.001)


# --- järjestys seinälinjoista (suorakulmainen talo) ----------------------------

def _kierra(xy, kulma_aste=17.0):
    import math
    a = math.radians(kulma_aste)
    return [(round(x * math.cos(a) - y * math.sin(a), 3), round(x * math.sin(a) + y * math.cos(a), 3)) for x, y in xy]


def _kulmapisteet(xy, jarjestys, kahdeksat):
    """Kulmapisteet (koodi 5, kahdeksat-indekseissä 8) annetussa mittausjärjestyksessä."""
    return [piste(f"P{i}", "8" if i in kahdeksat else "5", *xy[i]) for i in jarjestys]


SUORAKULMAISET = {
    "kapea T": [(0, 0), (12, 0), (12, 8), (7, 8), (7, 14), (5, 14), (5, 8), (0, 8)],
    "iso T": [(0, 0), (20, 0), (20, 5), (12, 5), (12, 17), (8, 17), (8, 5), (0, 5)],
    "U": [(0, 0), (16, 0), (16, 12), (9.5, 12), (9.5, 4), (6.5, 4), (6.5, 12), (0, 12)],
    "L": [(0, 0), (12, 0), (12, 4), (4, 4), (4, 10), (0, 10)],
}


@pytest.mark.parametrize("nimi", list(SUORAKULMAISET))
def test_suorakulmainen_suljettu_sekoitettuna(nimi):
    """Lyhin reitti oikaisi näissä ulokkeen poikki; seinälinjoista päätelty järjestys ei
    riipu mittausjärjestyksestä."""
    import random
    xy = _kierra(SUORAKULMAISET[nimi])
    rng = random.Random(1)
    for _ in range(20):
        jarj = list(range(1, len(xy)))
        rng.shuffle(jarj)
        tulos = sl.muodosta_seinalinjat(_kulmapisteet(xy, [0] + jarj, {0}), tapa="lyhin")
        assert samat_kierrot(karjet_xy(tulos["viivat"][0]), xy)
        assert tulos["varoitukset"] == []


@pytest.mark.parametrize("nimi, polku", [
    ("kapea T", [2, 3, 4, 5, 6, 7]),   # julkisivu ja uloke
    ("kapea T", [3, 4, 5, 6]),         # vain uloke, päät samalla seinälinjalla
    ("U", [2, 3, 4, 5, 6, 7]),         # sisäpiha
    ("iso T", [1, 2, 3, 4, 5, 6]),     # kolme sivua
])
def test_suorakulmainen_avoin_sekoitettuna(nimi, polku):
    import random
    xy = _kierra([SUORAKULMAISET[nimi][i] for i in polku])
    rng = random.Random(2)
    for _ in range(20):
        valit = list(range(1, len(xy) - 1))
        rng.shuffle(valit)
        tulos = sl.muodosta_seinalinjat(_kulmapisteet(xy, [0] + valit + [len(xy) - 1], {0, len(xy) - 1}), tapa="lyhin")
        assert karjet_xy(tulos["viivat"][0]) == xy
        assert tulos["varoitukset"] == []


def test_suorakulmainen_avoin_8_keskella_seinaa():
    xy = _kierra([(12, 4), (12, 8), (7, 8), (7, 14), (5, 14), (5, 8), (0, 8), (0, 3)])
    pisteet = _kulmapisteet(xy, [0, 4, 2, 6, 1, 5, 3, 7], {0, 7})
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="lyhin")
    assert karjet_xy(tulos["viivat"][0]) == xy


def test_vinot_seinat_lyhin_reitti_ja_varoitus():
    xy = [(0, 0), (12, 0), (12, 8), (8, 8), (7, 9.2), (5, 9.2), (4, 8), (0, 8)]  # viisto erkkeri
    tulos = sl.muodosta_seinalinjat(_kulmapisteet(xy, [0, 3, 6, 1, 5, 7, 2, 4], {0}), tapa="lyhin")
    assert samat_kierrot(karjet_xy(tulos["viivat"][0]), [(float(x), float(y)) for x, y in xy])
    assert any("ei voitu päätellä seinälinjoista" in v for v in tulos["varoitukset"])
    assert any("vinoja kulmia" in v for v in tulos["varoitukset"])


def test_kaksi_erillista_taloa_varoittaa():
    xy = [(0, 0), (10, 0), (10, 6), (0, 6), (20, 0), (26, 0), (26, 4), (20, 4)]
    tulos = sl.muodosta_seinalinjat(_kulmapisteet(xy, range(8), {0}), tapa="lyhin")
    assert any("useampi erillinen rengas" in v for v in tulos["varoitukset"])


def test_suorakulmainen_ranni_seinalla():
    """100-pisteet seinällä kahden mitatun kulman välissä (esim. ränni)."""
    import random
    xy = SUORAKULMAISET["kapea T"]
    pisteet = ([piste("A", "8", *xy[0])] + [piste(f"K{i}", "5", *xy[i]) for i in range(1, 8)]
               + [piste("R1", "100", 6, 0), piste("R2", "100", 12, 3)])
    for siemen in range(10):
        valit = pisteet[1:]
        random.Random(siemen).shuffle(valit)
        tulos = sl.muodosta_seinalinjat([pisteet[0]] + valit, tapa="lyhin")
        assert samat_kierrot(karjet_xy(tulos["viivat"][0]), [(float(x), float(y)) for x, y in xy])
        assert tulos["varoitukset"] == []


def test_suorakulmainen_piilokulma_yksi_100_kummallakin_seinalla():
    """Ulokkeen kulma (7, 14) piilossa; kummallakin viereisellä seinällä vain yksi 100-piste."""
    import random
    xy = SUORAKULMAISET["kapea T"]
    pisteet = ([piste("A", "8", *xy[0])] + [piste(f"K{i}", "5", *xy[i]) for i in (1, 2, 3, 5, 6, 7)]
               + [piste("S1", "100", 7, 11), piste("S2", "100", 6, 14)])
    for siemen in range(10):
        valit = pisteet[1:]
        random.Random(siemen).shuffle(valit)
        tulos = sl.muodosta_seinalinjat([pisteet[0]] + valit, tapa="lyhin")
        assert samat_kierrot(karjet_xy(tulos["viivat"][0]), [(float(x), float(y)) for x, y in xy])
        assert tulos["varoitukset"] == []


def test_lyhin_vanha_ohittaa_paattelyn():
    xy = _kierra(SUORAKULMAISET["kapea T"])
    pisteet = _kulmapisteet(xy, [0, 3, 6, 1, 5, 7, 2, 4], {0})
    assert samat_kierrot(karjet_xy(sl.muodosta_seinalinjat(pisteet, tapa="lyhin")["viivat"][0]), xy)
    assert not samat_kierrot(karjet_xy(sl.muodosta_seinalinjat(pisteet, tapa="lyhin_vanha")["viivat"][0]), xy)


def test_kaari_ohittaa_paattelyn():
    a = piste("A", "8", 0, 0)
    valit = [piste("B", "4", 5, -1), piste("C", "5", 10, 0), piste("D", "5", 10, 6), piste("E", "5", 0, 6)]
    assert sl.jarjesta_suorakulmaisesti(a, valit, a) == (None, None)


def _vinoutettu(xy, aste):
    """Pystyseinät kallistuvat aste astetta (talo ei ole aivan suorakulmainen)."""
    import math
    t = math.tan(math.radians(aste))
    return [(round(x + y * t, 3), float(y)) for x, y in xy]


def _paatelty_sekoitettuna(xy, toistoja=10):
    """(kaikki oikein, kaikki päätelty seinälinjoista) satunnaisilla mittausjärjestyksillä."""
    import random
    oikein = paatelty = True
    for siemen in range(toistoja):
        jarj = list(range(1, len(xy)))
        random.Random(siemen).shuffle(jarj)
        tulos = sl.muodosta_seinalinjat(_kulmapisteet(xy, [0] + jarj, {0}), tapa="lyhin")
        oikein &= samat_kierrot(karjet_xy(tulos["viivat"][0]), [(float(x), float(y)) for x, y in xy])
        paatelty &= not any("ei voitu päätellä" in v for v in tulos["varoitukset"])
    return oikein, paatelty


@pytest.mark.parametrize("aste", [0.5, 1.0])
def test_toleranssi_vino_talo(aste):
    """12 m seinä 1° vinossa = 21 cm: raja kasvaa etäisyyden mukaan (1,5°, enintään 25 cm)."""
    assert _paatelty_sekoitettuna(_vinoutettu(SUORAKULMAISET["U"], aste)) == (True, True)


def test_toleranssi_liian_vino_talo_varoittaa():
    oikein, paatelty = _paatelty_sekoitettuna(_vinoutettu(SUORAKULMAISET["U"], 1.5))
    assert not paatelty   # 12 m * tan(1,5°) = 31 cm > 25 cm: lyhin reitti ja varoitus


def _porras(syvyys):
    return [(0, 0), (12, 0), (12, 4), (12 + syvyys, 4), (12 + syvyys, 8), (7, 8), (7, 14), (5, 14), (5, 8), (0, 8)]


def test_toleranssi_7_cm_porras_erottuu():
    """Portaan kulmat ovat lähekkäin, joten niiden välillä raja on 5 cm; vaikka seinien
    kaukaiset päät mahtuisivat samalle linjalle, porras ei ketjuunnu niihin."""
    assert _paatelty_sekoitettuna(_porras(0.07)) == (True, True)


def test_toleranssi_4_cm_porras_varoittaa():
    oikein, paatelty = _paatelty_sekoitettuna(_porras(0.04))
    assert not paatelty


# --- kantakartta apuna ----------------------------------------------------------

def _kartta(*renkaat_rakennuksittain):
    """Kantakartta testikoordinaateista: jokainen argumentti on rakennus [ulko, sisä...]."""
    return [[[(E0 + x, N0 + y) for x, y in rengas] for rengas in rakennus] for rakennus in renkaat_rakennuksittain]


ERKKERI = [(0, 0), (12, 0), (12, 8), (8, 8), (7, 9.2), (5, 9.2), (4, 8), (0, 8)]


def _sekoitettu_suljettu(xy, siemen):
    import random
    jarj = list(range(1, len(xy)))
    random.Random(siemen).shuffle(jarj)
    return _kulmapisteet(xy, [0] + jarj, {0})


def test_kantakartta_jarjestaa_viiston_erkkerin():
    kartta = _kartta([[(x + 0.2, y - 0.1) for x, y in ERKKERI]])   # kartta 20 cm sivussa
    for siemen in range(10):
        tulos = sl.muodosta_seinalinjat(_sekoitettu_suljettu(ERKKERI, siemen), "lyhin", kantakartta=kartta)
        assert samat_kierrot(karjet_xy(tulos["viivat"][0]), [(float(x), float(y)) for x, y in ERKKERI])
        assert any("otettiin kantakartasta" in v for v in tulos["varoitukset"])


def test_kantakartta_vino_talo_ja_100_pisteet():
    """3° vino talo, piilokulma (8, 12) 100-pisteillä: seinälinjapäättely luovuttaa."""
    import math
    xy = [(0, 0), (12, 0), (12 + 8 * math.tan(math.radians(3)), 8), (8, 8), (8, 12), (4, 12), (4, 8), (0, 8)]
    kartta = _kartta([xy])
    pisteet = ([piste("A", "8", *xy[0])] + [piste(f"K{i}", "5", *xy[i]) for i in (1, 2, 3, 5, 6, 7)]
               + [piste("S1", "100", 8, 10), piste("S2", "100", 6, 12)])
    import random
    for siemen in range(10):
        valit = pisteet[1:]
        random.Random(siemen).shuffle(valit)
        tulos = sl.muodosta_seinalinjat([pisteet[0]] + valit, "lyhin", kantakartta=kartta)
        assert samat_kierrot(karjet_xy(tulos["viivat"][0]), [(round(x, 3), float(y)) for x, y in xy])


def test_kantakartta_ei_osu_kayttaa_lyhinta_reittia():
    kartta = _kartta([[(100, 100), (110, 100), (110, 110), (100, 110)]])
    tulos = sl.muodosta_seinalinjat(_sekoitettu_suljettu(ERKKERI, 1), "lyhin", kantakartta=kartta)
    assert any("käytettiin lyhintä reittiä" in v and "ei osu kantakartan taloon" in v for v in tulos["varoitukset"])


def test_kantakartta_laajennus_puuttuu_varoittaa():
    """Päättely onnistuu (kapea T), mutta kartalla on vain suorakaide: varoitus."""
    xy = _kierra(SUORAKULMAISET["kapea T"])
    kartta = [[[(E0 + x, N0 + y) for x, y in _kierra([(0, 0), (12, 0), (12, 8), (0, 8)])]]]
    tulos = sl.muodosta_seinalinjat(_sekoitettu_suljettu(xy, 3), "lyhin", kantakartta=kartta)
    assert samat_kierrot(karjet_xy(tulos["viivat"][0]), xy)
    assert any("eivät vastaa kantakartan taloa" in v for v in tulos["varoitukset"])


def test_kantakartta_avoin_viiva_erkkerilla():
    polku = ERKKERI[2:] + [(0, 3)]
    import random
    for siemen in range(10):
        valit = list(range(1, len(polku) - 1))
        random.Random(siemen).shuffle(valit)
        pisteet = _kulmapisteet(polku, [0] + valit + [len(polku) - 1], {0, len(polku) - 1})
        tulos = sl.muodosta_seinalinjat(pisteet, "lyhin", kantakartta=_kartta([ERKKERI]))
        assert karjet_xy(tulos["viivat"][0]) == [(float(x), float(y)) for x, y in polku]


def test_kantakartta_kaari():
    """Kaari (4-pisteet) järjestetään kantakartan mukaan; kartalla kaari on tihennetty."""
    import math
    kaari = [(6 + 3 * math.cos(math.radians(a)), 8 + 3 * math.sin(math.radians(a))) for a in range(0, 181, 15)]
    talo = [(0, 0), (12, 0), (12, 8)] + kaari[:1] + kaari[1:-1] + kaari[-1:] + [(0, 8)]
    pisteet = [piste("A", "8", 0, 0), piste("B", "5", 12, 8), piste("C", "5", 9, 8), piste("D", "5", 3, 8),
               piste("E", "4", 6, 11), piste("F", "5", 0, 8), piste("G", "5", 12, 0),
               piste("H", "4", *kaari[3]), piste("I", "4", *kaari[9])]
    tulos = sl.muodosta_seinalinjat(pisteet, "lyhin", kantakartta=_kartta([talo]))
    nimet = [k["nimi"] for k in tulos["viivat"][0]["karjet"]]
    assert nimet in (["A", "G", "B", "C", "D", "F"], ["A", "F", "D", "C", "B", "G"])
    assert any(abs(k.get("bulge") or 0) > 0.1 for k in tulos["viivat"][0]["karjet"])


def test_poikkeama_kantakartasta():
    xy = [(0, 0), (12, 0), (12, 8), (0, 8)]
    tulos = sl.muodosta_seinalinjat(_kulmapisteet(xy, range(4), {0}), "lyhin")
    p = sl.poikkeama_kantakartasta(tulos, _kartta([[(x, y + 0.10) if y == 8 else (x, y) for x, y in xy]]))
    assert p["suurin_m"] == pytest.approx(0.10, abs=0.005)
    assert 0.0 < p["keskiarvo_m"] < 0.10
    assert sl.poikkeama_kantakartasta(tulos, []) is None


def test_kantakartan_riskit():
    pisteet = _kulmapisteet(ERKKERI, range(len(ERKKERI)), {0})
    riskit = sl.kantakartan_riskit(_kartta([ERKKERI]), pisteet)
    assert any("vinoa kulmaa" in r for r in riskit)
    piha = [(2, 2), (2, 4), (4, 4), (4, 2)]
    riskit = sl.kantakartan_riskit(_kartta([[(0, 0), (12, 0), (12, 8), (0, 8)], piha]),
                                   _kulmapisteet([(0, 0), (12, 0), (12, 8), (0, 8)], range(4), {0}))
    assert any("sisäpiha" in r for r in riskit) and not any("vinoa" in r for r in riskit)
    assert sl.kantakartan_riskit(_kartta([[(100, 100), (110, 100), (110, 110)]]), pisteet) == []


def test_kantakartan_pikkukohde_ohitetaan():
    """Lepolantie 79: kartan 0,6 x 0,35 m kohde talon kulman vieressä antoi riskit 'kaareva seinä'
    (neljä alle 1 m seinää) ja '2 rakennukseen'."""
    talo = [(0, 0), (12, 0), (12, 8), (0, 8)]
    pikku = [(12.3, 8.3), (12.9, 8.3), (12.9, 8.65), (12.3, 8.65)]
    pisteet = _kulmapisteet(talo, range(4), {0})
    assert sl.kantakartan_riskit(_kartta([talo], [pikku]), pisteet) == []
    tulos = sl.muodosta_seinalinjat(pisteet, "lyhin", kantakartta=_kartta([talo], [pikku]))
    assert sl.poikkeama_kantakartasta(tulos, _kartta([pikku])) is None


def test_sama_jarjestys():
    a, b, c, d = ({"nimi": n} for n in "abcd")
    assert sl._sama_jarjestys([a, b, c, d], [a, d, c, b], suljettu=True)
    assert not sl._sama_jarjestys([a, b, c, d], [a, d, c, b], suljettu=False)
    assert not sl._sama_jarjestys([a, b, c, d], [a, c, b, d], suljettu=True)


# ---------------------------------------------------------------------------
# Viivan numero: useampi talo samaan tiedostoon ("8 2", "5 2")
# ---------------------------------------------------------------------------

TALO_A = [(0, 0), (10, 0), (10, 6), (0, 6)]
TALO_B = [(20, 0), (32, 0), (32, 4), (26, 4), (26, 9), (20, 9)]


def _kaksi_taloa():
    """Talo A ilman viivanumeroa, talo B numerolla 2; mittaukset vuorotellen."""
    a = [piste(f"A{i}", "8" if i == 0 else "5", *xy) for i, xy in enumerate(TALO_A)]
    b = [piste(f"B{i}", "8 2" if i == 0 else "5 2", *xy) for i, xy in enumerate(TALO_B)]
    sekaisin = []
    for i in range(max(len(a), len(b))):
        sekaisin += a[i:i + 1] + b[i:i + 1]
    return sekaisin


def test_viivan_numero():
    assert [sl.viivan_numero(k) for k in ("5", "5 2", "100 3", "5 KULMA", None, "")] == [1, 2, 3, 1, 1, 1]


def test_kaksi_taloa_omilla_viivoilla():
    tulos = sl.muodosta_seinalinjat(_kaksi_taloa())
    assert tulos["varoitukset"] == []
    assert [(v["numero"], v["suljettu"]) for v in tulos["viivat"]] == [(1, True), (2, True)]
    assert samat_kierrot(karjet_xy(tulos["viivat"][0]), TALO_A)
    assert samat_kierrot(karjet_xy(tulos["viivat"][1]), TALO_B)
    assert len(tulos["pisteet"]) == len(TALO_A) + len(TALO_B)


def test_avoin_viiva_2_suljetun_rinnalla():
    pisteet = [piste(f"A{i}", "8" if i == 0 else "5", *xy) for i, xy in enumerate(TALO_A)]
    pisteet += [piste("C0", "8 2", 40, 0), piste("C1", "5 2", 50, 0), piste("C2", "8 2", 50, 5)]
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert [(v["numero"], v["suljettu"]) for v in tulos["viivat"]] == [(1, True), (2, False)]
    assert karjet_xy(tulos["viivat"][1]) == [(40, 0), (50, 0), (50, 5)]


def test_viiva_ilman_8_pistetta_varoittaa():
    pisteet = _kaksi_taloa() + [piste("D0", "5 3", 60, 0), piste("D1", "5 3", 65, 0)]
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert [v["numero"] for v in tulos["viivat"]] == [1, 2]
    assert tulos["varoitukset"] == ["Viivalla 3 ei ole 8-pistettä, joten sen pisteitä ei otettu viivaan: D0, D1"]


def test_viivakohtaiset_varoitukset_numeroidaan():
    pisteet = [piste("X", "5 2", 19, -3)] + _kaksi_taloa()   # ennen viivan 2 8-pistettä
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert any(v.startswith("Viiva 2: Ensimmäistä 8-pistettä ennen") and v.endswith(": X")
               for v in tulos["varoitukset"])


def test_kaksi_taloa_dxf_ja_kuva(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    tulos = sl.muodosta_seinalinjat(_kaksi_taloa())
    doc = ezdxf.readfile(sl.kirjoita_dxf(tulos, str(tmp_path / "talot.dxf")))
    assert len(doc.modelspace().query("LWPOLYLINE")) == 2
    assert any(t.dxf.text == "B1 (5 2)" for t in doc.modelspace().query("TEXT"))
    assert sl.piirra_seinalinja_kartta(tulos, str(tmp_path / "talot.png"))


def test_kantakartan_riski_kaksi_rakennusta():
    kartta = _kartta([TALO_A], [TALO_B])
    yksi_viiva = [dict(p, koodi=str(sl.koodi_numeroksi(p["koodi"]))) for p in _kaksi_taloa()]
    assert any("oma viivanumero" in r for r in sl.kantakartan_riskit(kartta, yksi_viiva))
    assert not any("oma viivanumero" in r for r in sl.kantakartan_riskit(kartta, _kaksi_taloa()))


# ---------------------------------------------------------------------------
# Kohdekoodit (RAK 8, KATOS 5) ja ominaisuustiedot (Rakennetyyppi = Sokkeli)
# ---------------------------------------------------------------------------
def test_koodin_osat():
    assert sl._koodin_osat("5") == (None, 5, 1)
    assert sl._koodin_osat("5 2") == (None, 5, 2)
    assert sl._koodin_osat("5 KULMA") == (None, 5, 1)
    assert sl._koodin_osat("RAK 100") == ("RAK", 100, 1)
    assert sl._koodin_osat("RAK 8 2") == ("RAK", 8, 2)
    assert sl._koodin_osat("RAK") == ("RAK", None, 1)
    assert sl._koodin_osat(None) == (None, None, 1)
    assert sl.koodi_numeroksi("RAK 5") == 5 and sl.koodi_numeroksi("RAK") is None


def _rak(nimi, koodi, x, y, rakennetyyppi="Sokkeli"):
    p = piste(nimi, koodi, x, y)
    p["ominaisuudet"] = [{"kohde": "RAK", "nimi": "Rakennetyyppi", "arvo": rakennetyyppi, "tyyppi": "Menu"},
                         {"kohde": "RAK", "nimi": "Lisätieto", "arvo": f"teksti {nimi}", "tyyppi": "Text"}]
    return p


def _sokkeli_ja_katos():
    a = [_rak(f"A{i}", "RAK 8" if i == 0 else "RAK 5", *xy) for i, xy in enumerate(TALO_A)]
    b = [piste(f"B{i}", "KATOS 8" if i == 0 else "KATOS 5", *xy) for i, xy in enumerate(TALO_B)]
    return a + [_rak("R1", "RAK", 5, 3)] + b


def test_kohdekoodit_ja_rakennetyyppi_erottavat_viivat():
    tulos = sl.muodosta_seinalinjat(_sokkeli_ja_katos())
    assert tulos["varoitukset"] == []          # pelkkä RAK on tavallinen piste, ei varoitusta
    assert [(v["nimi"], v["suljettu"]) for v in tulos["viivat"]] == [("KATOS", True), ("RAK Sokkeli", True)]
    assert samat_kierrot(karjet_xy(tulos["viivat"][1]), TALO_A)
    assert samat_kierrot(karjet_xy(tulos["viivat"][0]), TALO_B)
    assert "R1" not in {p["nimi"] for p in tulos["pisteet"]}


def test_rakennetyyppi_ja_numero():
    # sama kohdekoodi, eri rakennetyyppi -> eri viivat; numero erottaa kaksi samanlaista
    pisteet = ([_rak(f"A{i}", "RAK 8" if i == 0 else "RAK 5", *xy) for i, xy in enumerate(TALO_A)]
               + [_rak(f"B{i}", "RAK 8" if i == 0 else "RAK 5", *xy, rakennetyyppi="Seinä")
                  for i, xy in enumerate(TALO_B)]
               + [_rak(f"C{i}", "RAK 8 2" if i == 0 else "RAK 5 2", x + 40, y) for i, (x, y) in enumerate(TALO_A)])
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert [v["nimi"] for v in tulos["viivat"]] == ["RAK Seinä", "RAK Sokkeli", "RAK Sokkeli 2"]
    assert [p["nimi"] for p in sl.rajaa_viivaan(tulos, "RAK Sokkeli 2")["pisteet"]] == ["C0", "C1", "C2", "C3"]


def test_kohdekoodit_dxf_tasoille(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    tulos = sl.muodosta_seinalinjat(_sokkeli_ja_katos())
    msp = ezdxf.readfile(sl.kirjoita_dxf(tulos, str(tmp_path / "kohteet.dxf"))).modelspace()
    assert {e.dxf.layer for e in msp.query("LWPOLYLINE")} == {"SEINALINJA_RAK_SOKKELI", "SEINALINJA_KATOS"}
    assert any(t.dxf.text == "A1 (RAK 5)" for t in msp.query("TEXT"))
    assert sl.dxf_taso(("", (), 2)) == "SEINALINJA"
    assert sl.dxf_taso(("RAK", ("Sokkeli: vanha",), 1)) == "SEINALINJA_RAK_SOKKELI__VANHA"


# --- Käsin tehdyt muokkaukset (muokkauskartta) ----------------------------------

def _neliö():
    pisteet = [piste("1", "8", 0, 0), piste("2", "5", 10, 0), piste("3", "5", 10, 8), piste("4", "5", 0, 8)]
    return sl.muodosta_seinalinjat(pisteet)


def test_suorakulmainen_piste_etumerkit():
    # A→B itään: + oikealle = etelään; A→B pohjoiseen: + oikealle = itään
    assert sl.suorakulmainen_piste((0, 0), (10, 0), 2, 1) == pytest.approx((2, -1))
    assert sl.suorakulmainen_piste((0, 0), (0, 10), 2, -1) == pytest.approx((-1, 2))
    assert sl.suorakulmainen_piste((E0, N0), (E0 + 3, N0 + 4), 5, 0) == pytest.approx((E0 + 3, N0 + 4))
    with pytest.raises(ValueError):
        sl.suorakulmainen_piste((1, 1), (1, 1), 1, 1)


def test_sovella_muokkaukset_siirto_lisays_poisto():
    tulos = _neliö()
    viiva = tulos["viivat"][0]["nimi"]
    alku = karjet_xy(tulos["viivat"][0])
    muokkaukset = [
        {"tyyppi": "siirra", "viiva": viiva, "karki": 1, "e": E0 + 10.5, "n": N0, "z": 9.0, "nimi": "99"},
        {"tyyppi": "lisaa", "viiva": viiva, "jalkeen": 0, "e": E0 + 5, "n": N0 - 1, "z": None, "nimi": None},
        {"tyyppi": "poista", "viiva": viiva, "karki": 4},
    ]
    uusi = sl.sovella_muokkaukset(tulos, muokkaukset)
    assert karjet_xy(tulos["viivat"][0]) == alku            # alkuperäinen ennallaan
    karjet = uusi["viivat"][0]["karjet"]
    assert [(round(k["e"] - E0, 3), round(k["n"] - N0, 3)) for k in karjet] == [(0, 0), (5, -1), (10.5, 0), (10, 8)]
    assert (karjet[1]["laji"], karjet[2]["laji"], karjet[2]["nimi"], karjet[2]["z"]) == ("käsin", "mitattu", "99", 9.0)
    assert uusi["muokattu"] and uusi["viivat"][0]["suljettu"]
    assert sl.viivojen_tunniste(uusi) != sl.viivojen_tunniste(tulos)


def test_sovella_muokkaukset_uusi_viiva_ja_ohitus():
    tulos = _neliö()
    viiva = tulos["viivat"][0]["nimi"]
    uusi = sl.sovella_muokkaukset(tulos, [
        {"tyyppi": "uusi_viiva", "nimi": "Lisätty viiva 1", "pohja": viiva,
         "karjet": [{"e": E0, "n": N0 + 1, "laji": "laskettu", "nimi": "b1"},
                    {"e": E0 + 10, "n": N0 + 1, "laji": "laskettu", "nimi": "b1"}]},
        {"tyyppi": "poista", "viiva": "ei ole", "karki": 0},
        {"tyyppi": "siirra", "viiva": viiva, "karki": 17, "e": 0, "n": 0},
    ])
    lisatty = uusi["viivat"][-1]
    assert lisatty["nimi"] == "Lisätty viiva 1" and not lisatty["suljettu"] and len(lisatty["karjet"]) == 2
    assert lisatty["avain"] == tulos["viivat"][0]["avain"]       # sama DXF-taso
    assert sum("Muokkaus ohitettiin" in v for v in uusi["varoitukset"]) == 2
    # viivaan ei jätetä alle kahta kärkeä
    kaksi = sl.sovella_muokkaukset(uusi, [{"tyyppi": "poista", "viiva": "Lisätty viiva 1", "karki": 0}])
    assert len(kaksi["viivat"][-1]["karjet"]) == 2


def test_sovella_muokkaukset_poista_jana():
    tulos = _neliö()
    viiva = tulos["viivat"][0]["nimi"]
    k = karjet_xy(tulos["viivat"][0])          # 4 kärkeä, suljettu
    # suljettu aukeaa: jana kärjestä 2 kärkeen 3 pois -> avoin 3-4-1-2
    auki = sl.sovella_muokkaukset(tulos, [{"tyyppi": "poista_jana", "viiva": viiva, "jana": 1}])
    v = auki["viivat"][0]
    assert not v["suljettu"] and karjet_xy(v) == [k[2], k[3], k[0], k[1]]
    # avoin katkeaa kahdeksi: 3-4 | 1-2
    kaksi = sl.sovella_muokkaukset(auki, [{"tyyppi": "poista_jana", "viiva": viiva, "jana": 1}])
    assert [(x["nimi"], karjet_xy(x)) for x in kaksi["viivat"]] == [
        (viiva, [k[2], k[3]]), (f"{viiva} (osa 2)", [k[0], k[1]])]
    assert kaksi["viivat"][1]["avain"] == v["avain"]
    # yhden janan viiva poistuu kokonaan
    pois = sl.sovella_muokkaukset(kaksi, [{"tyyppi": "poista_jana", "viiva": f"{viiva} (osa 2)", "jana": 0}])
    assert [x["nimi"] for x in pois["viivat"]] == [viiva]


def _viivat(**viivat):
    return {"viivat": [{"nimi": nimi, "suljettu": False, "numero": 1, "avain": ("", (), 1),
                        "karjet": [{"e": E0 + x, "n": N0 + y, "z": None, "laji": "mitattu", "nimi": f"{nimi}{i}",
                                    "bulge": 0.0} for i, (x, y) in enumerate(xy)]}
                       for nimi, xy in viivat.items()], "pisteet": [], "varoitukset": []}


def test_jatka_viiva_lahimpaan():
    tulos = _viivat(A=[(0, 0), (10, 0)], B=[(12, -5), (12, 5)], C=[(20, -5), (20, 5)])
    uusi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "jatka", "viiva": "A", "paa": "loppu"}])
    a = uusi["viivat"][0]
    assert karjet_xy(a) == [(0, 0), (10, 0), (12, 0)] and a["karjet"][-1]["laji"] == "laskettu"
    assert "B" in a["karjet"][-1]["nimi"]
    # alku jatkuu taaksepäin; ei osumaa -> varoitus
    ohi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "jatka", "viiva": "A", "paa": "alku"}])
    assert karjet_xy(ohi["viivat"][0]) == [(0, 0), (10, 0)] and any("Jatko ohitettiin" in v for v in ohi["varoitukset"])


def test_yhdista_leikkauspisteessa():
    # A:ta jatketaan ja C:tä jatketaan -> yksi viiva leikkauspisteen kautta
    tulos = _viivat(A=[(0, 0), (10, 0)], C=[(11, 3), (11, 8)])
    uusi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "leikkaus", "viiva1": "A", "viiva2": "C"}])
    assert [v["nimi"] for v in uusi["viivat"]] == ["A"]
    assert karjet_xy(uusi["viivat"][0]) == [(0, 0), (10, 0), (11, 0), (11, 3), (11, 8)]
    # A menee leikkauspisteen ohi -> lyhennetään
    tulos = _viivat(A=[(0, 0), (13, 0)], C=[(11, 8), (11, 3)])
    uusi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "leikkaus", "viiva1": "A", "viiva2": "C"}])
    assert karjet_xy(uusi["viivat"][0]) == [(0, 0), (11, 0), (11, 3), (11, 8)]
    # yhdensuuntaiset -> varoitus, ei muutosta
    tulos = _viivat(A=[(0, 0), (10, 0)], C=[(12, 1), (20, 1)])
    uusi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "leikkaus", "viiva1": "A", "viiva2": "C"}])
    assert len(uusi["viivat"]) == 2 and any("yhdensuuntaiset" in v for v in uusi["varoitukset"])
    # lähes yhdensuuntaiset (5°): leikkaus kaukana -> ohitetaan
    tulos = _viivat(A=[(0, 0), (10, 0)], C=[(12, 1), (22, 1 + 10 * 0.0875)])
    uusi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "leikkaus", "viiva1": "A", "viiva2": "C"}])
    assert len(uusi["viivat"]) == 2 and any("yhdensuuntaiset" in v for v in uusi["varoitukset"])
    # jatke yli 30 m -> ei osu
    tulos = _viivat(A=[(0, 0), (10, 0)], B=[(45, -5), (45, 5)])
    uusi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "jatka", "viiva": "A", "paa": "loppu"}])
    assert any("Jatko ohitettiin" in v for v in uusi["varoitukset"])


def test_yhdista_saman_viivan_paat_sulkee():
    tulos = _viivat(U=[(2, 5), (0, 0), (10, 0), (8, 5)])
    uusi = sl.sovella_muokkaukset(tulos, [{"tyyppi": "leikkaus", "viiva1": "U", "viiva2": "U"}])
    u = uusi["viivat"][0]
    assert u["suljettu"] and karjet_xy(u) == [(5, 12.5), (2, 5), (0, 0), (10, 0), (8, 5)]



def test_sovella_muokkaukset_laskettu_piste():
    tulos = _viivat(A=[(0, 0), (10, 0)])
    m = {"tyyppi": "piste", "nimi": "L1", "e": E0 + 5, "n": N0 + 2, "a": "x", "b": "y", "a_mitta": 5, "b_mitta": -2}
    uusi = sl.sovella_muokkaukset(tulos, [m])
    assert uusi["lasketut_pisteet"] == [{"nimi": "L1", "e": E0 + 5, "n": N0 + 2}]
    assert karjet_xy(uusi["viivat"][0]) == [(0, 0), (10, 0)] and not uusi["varoitukset"]
    # kärki raahattu laskettuun pisteeseen: laji laskettu
    siirto = {"tyyppi": "siirra", "viiva": "A", "karki": 1, "e": E0 + 5, "n": N0 + 2, "z": None, "nimi": "L1",
              "laji": "laskettu"}
    k = sl.sovella_muokkaukset(tulos, [m, siirto])["viivat"][0]["karjet"][1]
    assert (k["nimi"], k["laji"]) == ("L1", "laskettu")

def test_suorakulmion_neljas():
    r = sl.suorakulmion_neljas((E0, N0 + 6), (E0 + 10, N0), (E0, N0))
    assert r["jarjestys"] == [0, 2, 1] and r["neljas"] == pytest.approx((E0 + 10, N0 + 6))
    assert r["kulma"] == pytest.approx(90) and r["lavistajaero"] == pytest.approx(0)
    # 1° vino hyväksytään, lävistäjät eroavat
    vino = sl.suorakulmion_neljas((E0, N0), (E0 + 10, N0), (E0 + 6 * math.sin(math.radians(1)), N0 + 6))
    assert vino["jarjestys"][1] == 0 and abs(vino["kulma"] - 90) == pytest.approx(1, abs=0.01)
    assert vino["lavistajaero"] > 0.1
    with pytest.raises(ValueError, match="suorakulmiota"):
        sl.suorakulmion_neljas((E0, N0), (E0 + 10, N0), (E0 + 6 * math.sin(math.radians(10)), N0 + 6))


def test_sovella_muokkaukset_suorakulmio():
    def karjet(*xy):
        return [{"e": E0 + x, "n": N0 + y, "z": None, "nimi": None, "laji": "laskettu"} for x, y in xy]
    # kolmen kulman avoin viiva (kulma lopussa) suljetaan kehän järjestyksessä
    tulos = _viivat(A=[(10, 0), (0, 0), (10, 6)], B=[(30, 0), (40, 0)])
    m = {"tyyppi": "suorakulmio", "nimi": "Suorakulmio 1", "pohja": "A",
         "karjet": karjet((0, 0), (10, 0), (10, 6), (0, 6))}
    uusi = sl.sovella_muokkaukset(tulos, [m])
    a = uusi["viivat"][0]
    assert a["suljettu"] and karjet_xy(a) == [(0, 0), (10, 0), (10, 6), (0, 6)] and a["karjet"][0]["nimi"] == "A1"
    assert len(uusi["viivat"]) == 2
    # muuten uusi suljettu viiva
    m["karjet"] = karjet((30, 0), (40, 0), (40, 5), (30, 5))
    uusi = sl.sovella_muokkaukset(tulos, [m])
    assert [v["nimi"] for v in uusi["viivat"]] == ["A", "B", "Suorakulmio 1"] and uusi["viivat"][2]["suljettu"]
