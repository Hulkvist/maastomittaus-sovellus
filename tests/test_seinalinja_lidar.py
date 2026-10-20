"""LiDAR-seinät seinälinjan apuna (seinalinja.muodosta_seinalinjat(..., lidar=...))."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import seinalinja as sl  # noqa: E402
import synteettiset as syn  # noqa: E402

pytest.importorskip("shapely")


# Piilokulmatesteissä pisteet ovat mittausjärjestyksessä, jotta testi koskee vain kulmaa;
# järjestyksen päättely (myös LiDARista) testataan erikseen.
TAPA = "mittaus"


def _kulmat(tulos):
    return sorted((round(k["e"], 6), round(k["n"], 6)) for k in tulos["viivat"][0]["karjet"])


def _piilokulmatapaukset(talo, siemenet=range(40)):
    """Mittaukset, joissa piilokulma joudutaan olettamaan suoraksi (100-pisteet puuttuvat
    toiselta seinältä): (pisteet, muunnos, rng)."""
    tapaukset = []
    for siemen in siemenet:
        rng = syn.uusi_rng(siemen)
        n = len(talo.karjet)
        ohita = {rng.randrange(n)}
        pisteet, muunnos, _ = syn.mittaa(talo, rng, piilotus=0.5, ohita_seinat=ohita, apupisteet=False)
        tulos = sl.muodosta_seinalinjat(pisteet, tapa=TAPA)
        if tulos["viivat"] and any("oletettu suora kulma" in v for v in tulos["varoitukset"]):
            tapaukset.append((pisteet, muunnos, rng))
    return tapaukset


def test_piilokulma_lidarista_vinossa_talossa():
    talo = syn.talot()["vino"]
    tapaukset = _piilokulmatapaukset(talo)
    assert len(tapaukset) >= 3
    for pisteet, muunnos, rng in tapaukset:
        ilman = sl.muodosta_seinalinjat(pisteet, tapa=TAPA)
        kanssa = sl.muodosta_seinalinjat(pisteet, tapa=TAPA, lidar=syn.lidar_seinat(talo, muunnos, rng, katko=True))
        assert not any("oletettu suora kulma" in v for v in kanssa["varoitukset"])
        assert any("otettiin LiDARista" in v for v in kanssa["varoitukset"]), kanssa["varoitukset"]
        virhe_ilman = syn.poikkeama(ilman, talo, muunnos)
        virhe_kanssa = syn.poikkeama(kanssa, talo, muunnos)
        assert virhe_kanssa < 0.05, virhe_kanssa      # LiDARin 1 cm kohina, 3 mm mittausvirhe
        assert virhe_ilman > 0.2                      # 90°:n oletus vinossa talossa menee ohi


@pytest.mark.parametrize("nimi", ["suorakulmio", "L", "T", "parveke", "syvennys"])
def test_suorakulmaisessa_talossa_lidar_vahvistaa_kulman(nimi):
    talo = syn.talot()[nimi]
    for pisteet, muunnos, rng in _piilokulmatapaukset(talo, range(15)):
        kanssa = sl.muodosta_seinalinjat(pisteet, tapa=TAPA,
                                         lidar=syn.lidar_seinat(talo, muunnos, rng, katko=True))
        assert not any("oletettu suora kulma" in v for v in kanssa["varoitukset"])
        assert any("LiDAR vahvistaa suoran kulman" in v for v in kanssa["varoitukset"])
        # Suora kulma pidetään tarkkana: sama tulos kuin ilman LiDARia
        assert _kulmat(kanssa) == _kulmat(sl.muodosta_seinalinjat(pisteet, tapa=TAPA))


def test_vaarat_lidar_seinat_eivat_kelpaa():
    talo = syn.talot()["vino"]
    pisteet, muunnos, rng = _piilokulmatapaukset(talo)[0]
    tulos_ilman = sl.muodosta_seinalinjat(pisteet, tapa=TAPA)
    # Kaukana oleva seinä, liian lyhyt jana ja kulmapisteen kautta kulkeva mutta tunnetun seinän
    # suuntainen jana eivät kelpaa: tulos on sama kuin ilman LiDARia.
    vaarat = [(muunnos(30, 30), muunnos(40, 30)), (muunnos(0, 0), muunnos(0.1, 0.1))]
    for p in pisteet:
        if p["koodi"] in ("5", "8"):
            vaarat.append(((p["e"] - 5, p["n"]), (p["e"] + 5, p["n"])))
    for lidar in (vaarat[:2], vaarat[2:]):
        tulos = sl.muodosta_seinalinjat(pisteet, tapa=TAPA, lidar=lidar)
        assert tulos["varoitukset"] == tulos_ilman["varoitukset"]
        assert _kulmat(tulos) == _kulmat(tulos_ilman)


def test_lidar_janat_ja_suunta():
    janat = sl._lidar_janat([((0, 0), (10, 0)), ((0, 0), (0.1, 0))])
    assert len(janat) == 1 and janat[0][2] == (1.0, 0.0)
    # Kulmapiste (0, 0); tunnettu seinä pystysuunnassa x = 10 -> LiDAR-seinä johtaa sinne
    pysty = ((10, 3), (0, 1))
    suunta, poikkeama = sl._lidar_suunta((0, 0.05), pysty, janat)
    assert poikkeama == pytest.approx(0.0) and suunta == pytest.approx((-1.0, 0.0))  # tarkka kohtisuora
    assert sl._lidar_suunta((0, 0.2), pysty, janat) is None             # liian kaukana suorasta
    assert sl._lidar_suunta((-1, 0), pysty, janat) is None              # janan pään ohi
    assert sl._lidar_suunta((0, 0), ((10, 3), (1, 0.05)), janat) is None  # lähes saman suuntainen
    assert sl._lidar_suunta((0, 0), ((20, 3), (0, 1)), janat) is None   # jana ei johda piilokulmaan
    vino = ((10, 3), (math.cos(math.radians(70)), math.sin(math.radians(70))))
    suunta, poikkeama = sl._lidar_suunta((0, 0), vino, janat)
    assert suunta == (1.0, 0.0) and poikkeama == pytest.approx(20.0)


def test_poikkeama_lidarista_ja_peitto():
    pisteet = [{"nimi": str(i), "koodi": "8" if i == 0 else "5", "e": syn.E0 + x, "n": syn.N0 + y, "korkeus": 1.0}
               for i, (x, y) in enumerate([(0, 0), (10, 0), (10, 6), (0, 6)])]
    tulos = sl.muodosta_seinalinjat(pisteet)
    # LiDAR kattaa eteläseinän 2 cm siirrettynä ja puolet itäseinästä; muut seinät keilaamatta
    lidar = [((syn.E0, syn.N0 + 0.02), (syn.E0 + 10, syn.N0 + 0.02)), ((syn.E0 + 10, syn.N0), (syn.E0 + 10, syn.N0 + 3))]
    [p] = sl.poikkeamat_lidarista(tulos, lidar)
    assert p["suurin_m"] == pytest.approx(0.02, abs=1e-9)
    assert p["peitto"] == pytest.approx(13 / 32, abs=0.03)        # 10 m + 3 m / 32 m
    assert sum(d is None for _, _, d in p["naytteet"]) > len(p["naytteet"]) / 2
    assert sl.poikkeamat_lidarista(tulos, []) == []
    # kantakartta: peitto aina koko viiva
    [k] = sl.poikkeamat_kantakartasta(tulos, [[[(syn.E0 + x, syn.N0 + y) for x, y in [(0, 0), (10, 0), (10, 6), (0, 6)]]]])
    assert k["peitto"] == 1.0 and k["suurin_m"] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("nimi", ["suorakulmio", "L", "T", "parveke", "syvennys", "vino"])
def test_lidar_aariviiva(nimi):
    talo = syn.talot()[nimi]
    rng = syn.uusi_rng(3)
    _, muunnos, _ = syn.mittaa(talo, rng)
    [[rengas]] = sl.lidar_aariviivat(syn.lidar_seinat(talo, muunnos, rng, katko=True))
    oikeat = [muunnos(x, y) for x, y in talo.karjet]
    assert len(rengas) - 1 == len(oikeat)
    assert all(min(math.dist(k, o) for o in oikeat) < 0.05 for k in rengas)
    # osittainen keilaus: ei suljettua ääriviivaa
    assert sl.lidar_aariviivat(syn.lidar_seinat(talo, muunnos, rng, seinat=range(len(talo.karjet) - 1))) == []


def _talo_14x8(etela):
    """Talo 14 x 8 m LiDAR-seininä (nurkat 20 cm katveessa); etela = eteläseinän pätkät (x0, x1)."""
    e, n = syn.E0, syn.N0
    return [((e + x0, n), (e + x1, n)) for x0, x1 in etela] + [
        ((e + 14, n + 0.2), (e + 14, n + 7.8)), ((e + 13.8, n + 8), (e + 0.2, n + 8)), ((e, n + 7.8), (e, n + 0.2))]


def _nurkat(renkaat):
    [[rengas]] = renkaat
    return sorted((round(e - syn.E0, 2), round(n - syn.N0, 2)) for e, n in rengas[:-1])


def test_lidar_aariviiva_lyhyt_pala_yhdistaa_seinat():
    # Pitkät pätkät 5,5 m päässä toisistaan (eri seiniksi), lyhyempi pala niiden välissä yhdistää ne
    renkaat = sl.lidar_aariviivat(_talo_14x8([(0.2, 4.0), (9.5, 13.8), (5.0, 8.0)]))
    assert _nurkat(renkaat) == [(0, 0), (0, 8), (14, 0), (14, 8)]


def test_lidar_aariviiva_epaselva_nurkka_muualla():
    # Aita tai naapurin nurkka 50 m päässä: kaksi seinää päättyy saman seinän saman pään lähelle
    e, n = syn.E0, syn.N0 + 50
    muualla = [((e, n), (e + 10, n)), ((e + 10.3, n + 0.3), (e + 10.3, n + 10)),
               ((e + 10.6, n - 0.2), (e + 10.6, n - 10))]
    assert _nurkat(sl.lidar_aariviivat(_talo_14x8([(0.2, 13.8)]) + muualla)) == [(0, 0), (0, 8), (14, 0), (14, 8)]


@pytest.mark.parametrize("nimi, korjattuja", [("vino", 15), ("suorakulmio", 0), ("L", 0), ("parveke", 0)])
def test_lidar_ei_riko_ja_korjaa_vinon_talon(nimi, korjattuja):
    """Automaattinen järjestys sekoitetuilla pisteillä, piilokulmia ja seinä ilman 100-pisteitä.
    Vinossa talossa järjestystä ei saada seinälinjoista, ja 90°:n oletus vie piilokulman
    ohi; LiDAR-ääriviivasta ja -seinistä tulos korjautuu. LiDAR ei saa rikkoa yhtään oikeaa
    tulosta. (Väärin jäävissä on 3-5 piilokulmaa; ne menevät väärin myös ilman LiDARia.)"""
    talo = syn.talot()[nimi]
    korjatut = 0
    for siemen in range(60):
        rng = syn.uusi_rng(siemen)
        pisteet, muunnos, _ = syn.mittaa(talo, rng, piilotus=0.5, ohita_seinat={rng.randrange(len(talo.karjet))},
                                         apupisteet=False)
        pisteet = syn.sekoitettu(pisteet, rng)
        ilman = sl.muodosta_seinalinjat(pisteet)
        if not ilman["viivat"]:
            continue
        kanssa = sl.muodosta_seinalinjat(pisteet, lidar=syn.lidar_seinat(talo, muunnos, rng, katko=True))
        oikein_ilman = syn.poikkeama(ilman, talo, muunnos) < 0.05
        oikein_kanssa = syn.poikkeama(kanssa, talo, muunnos) < 0.05
        assert oikein_kanssa or not oikein_ilman, (siemen, kanssa["varoitukset"])
        korjatut += oikein_kanssa and not oikein_ilman
    assert korjatut >= korjattuja


def test_jarjestys_lidar_aariviivasta():
    talo = syn.talot()["vino"]
    viestit = []
    for siemen in range(60):
        rng = syn.uusi_rng(siemen)
        pisteet, muunnos, _ = syn.mittaa(talo, rng, piilotus=0.5, ohita_seinat={rng.randrange(4)}, apupisteet=False)
        kanssa = sl.muodosta_seinalinjat(syn.sekoitettu(pisteet, rng),
                                         lidar=syn.lidar_seinat(talo, muunnos, rng, katko=True))
        if any("otettiin LiDAR-ääriviivasta" in v for v in kanssa["varoitukset"]):
            viestit.append(syn.poikkeama(kanssa, talo, muunnos))
    assert len(viestit) >= 5
    assert sum(v < 0.05 for v in viestit) >= 0.7 * len(viestit)


def test_viivan_pisteet_z():
    karjet = [{"e": 0, "n": 0, "z": 10.0, "bulge": 0.0}, {"e": 10, "n": 0, "z": 12.0, "bulge": 0.5},
              {"e": 10, "n": 6, "z": None, "bulge": 0.0}]
    viiva = {"karjet": karjet, "suljettu": True}
    pisteet = sl.viivan_pisteet_z(viiva)
    assert [(e, n) for e, n, _ in pisteet] == sl.viivan_pisteet(viiva)
    assert pisteet[0] == (0, 0, 10.0) and pisteet[-1] == (0, 0, 10.0)
    kaari = [z for _, _, z in pisteet[2:-2]]
    assert all(11.0 <= z <= 12.0 for z in kaari) and kaari == sorted(kaari, reverse=True)  # 12 -> 11 (keskiarvo)
    assert sl.viivan_pisteet_z({"karjet": [dict(k, z=None) for k in karjet], "suljettu": False})[0][2] is None


def test_lue_lidar_dxf(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    msp.add_line((0, 0, 0), (10, 0, 0), dxfattribs={"layer": "SEINA"})
    msp.add_lwpolyline([(10, 0), (10, 6), (0, 6)], dxfattribs={"layer": "SEINA"})
    msp.add_line((0, 6, 0), (0, 3, 0), dxfattribs={"layer": "EPAVARMA"})
    msp.add_point((5, 3), dxfattribs={"layer": "TAHYKSET"})
    msp.add_line((50, 50), (60, 50), dxfattribs={"layer": "MUU"})
    polku = str(tmp_path / "x_seinat.dxf")
    doc.saveas(polku)
    janat = sl.lue_lidar_dxf(polku)
    assert janat["SEINA"] == [((0, 0), (10, 0)), ((10, 0), (10, 6)), ((10, 6), (0, 6))]
    assert janat["EPAVARMA"] == [((0, 6), (0, 3))]


def test_lue_lidar_dxf_polyline_ja_pienet_kirjaimet(tmp_path):
    # R12-kirjoittajat tekevät murtoviivat POLYLINEina (ei LWPOLYLINE); tasonimen kirjainkoko ei ratkaise
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R12")
    msp = doc.modelspace()
    msp.add_polyline2d([(0, 0), (10, 0), (10, 6)], close=True, dxfattribs={"layer": "Seina"})
    msp.add_polyline2d([(0, 6), (0, 3)], dxfattribs={"layer": "epavarma"})
    polku = str(tmp_path / "x_seinat.dxf")
    doc.saveas(polku)
    janat = sl.lue_lidar_dxf(polku)
    assert janat["SEINA"] == [((0, 0), (10, 0)), ((10, 0), (10, 6)), ((10, 6), (0, 0))]
    assert janat["EPAVARMA"] == [((0, 6), (0, 3))]


def test_poikkeamaluokka():
    assert sl.poikkeamaluokka(0.049)[0] == "alle 5 cm"
    assert sl.poikkeamaluokka(0.05)[0] == "5–15 cm"
    assert sl.poikkeamaluokka(0.2) == ("yli 15 cm", "#d62728")


def test_lidarpipen_aariviiva_paatellyt_osat(tmp_path):
    # lidarpipen ääriviiva: mitatut osat SEINA-tasolla, aukon liitos ja katvenurkan jatkeet PAATELTY-tasolla.
    # Yhdessä ne muodostavat päistään yhtyvän kierroksen, joka kelpaa järjestyksen avuksi sellaisenaan
    # (kärjet DXF:stä, myös ajelehtimisen 12 cm porras); vertailu käyttää vain SEINA-tasoa.
    ezdxf = pytest.importorskip("ezdxf")
    e, n = syn.E0, syn.N0
    seina = [[(e, n + 6), (e, n), (e + 4, n)], [(e + 5, n + 0.12), (e + 10, n + 0.12), (e + 10, n + 4.5)],
             [(e + 8.5, n + 6), (e, n + 6)]]
    paatelty = [[(e + 4, n), (e + 5, n + 0.12)], [(e + 10, n + 4.5), (e + 10, n + 6), (e + 8.5, n + 6)]]
    doc = ezdxf.new("R2010")
    for taso, viivat in (("SEINA", seina), ("PAATELTY", paatelty)):
        for v in viivat:
            doc.modelspace().add_lwpolyline(v, dxfattribs={"layer": taso})
    polku = str(tmp_path / "x_seinat.dxf")
    doc.saveas(polku)
    janat = sl.lue_lidar_dxf(polku)
    assert len(janat["SEINA"]) == 5 and len(janat["PAATELTY"]) == 3
    [[rengas]] = sl.lidar_aariviivat(janat["SEINA"], janat["PAATELTY"])
    assert len(rengas) == 9 and rengas[0] == rengas[-1]   # 8 kärkeä + sulkeva
    karjet = {(round(x - e, 3), round(y - n, 3)) for x, y in rengas}
    assert {(4.0, 0.0), (5.0, 0.12), (10.0, 6.0)} <= karjet
    # avoin ketju (yksi jana puuttuu) ei kelpaa valmiiksi kierrokseksi
    assert sl._valmiit_renkaat(janat["SEINA"] + janat["PAATELTY"][1:]) == []
