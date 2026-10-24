"""QGIS-lisäosan (qgis_plugin/maastomittaus) QGIS:stä riippumaton osa. Itse Processing-työkalu
testataan QGIS:ssä, ks. README."""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

HAKEMISTO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HAKEMISTO)
import seinalinja as sl  # noqa: E402

# Ydin ladataan kopiosta ilman lib-kansiota: rakennusskriptin tekemä lib (karsitut kopiot)
# vaihtaisi muuten jaetut moduulit koko testiajon ajaksi. Testit käyttävät repon moduuleja.
_YDIN = os.path.join(tempfile.mkdtemp(), "ydin.py")
shutil.copy(os.path.join(HAKEMISTO, "qgis_plugin", "maastomittaus", "ydin.py"), _YDIN)
spec = importlib.util.spec_from_file_location("maastomittaus_ydin", _YDIN)
ydin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ydin)

DATA = os.path.join(HAKEMISTO, "tests", "data", "jobxml")
E0, N0 = 25496000.0, 6672000.0


@pytest.mark.oikeat_aineistot
def test_jaettu_koodi_ei_vaadi_lisakirjastoja():
    # Työpaikan QGIS:ssä (Windows) ei välttämättä ole psycopg2:ta, requestsia eikä shapelya
    koodi = ("import builtins\n"
             "alkup = builtins.__import__\n"
             "def esto(nimi, *a, **k):\n"
             "    if nimi.split('.')[0] in ('psycopg2', 'requests', 'shapely', 'pyproj', 'hae_kiintopisteet'):\n"
             "        raise ImportError(nimi)\n"
             "    return alkup(nimi, *a, **k)\n"
             "builtins.__import__ = esto\n"
             "import jobxml_tuonti as jx, seinalinja as sl\n"
             f"r, p, _ = jx.jasenna_tyo(open({os.path.join(DATA, 'lepolantie79.jxl')!r}, 'rb').read(), 'x')\n"
             "kk = [[[(0, 0), (10, 0), (10, 6), (0, 6), (0, 0)]]]\n"
             "t = sl.muodosta_seinalinjat(p, kantakartta=kk)\n"
             "sl.poikkeama_kantakartasta(t, kk); sl.kantakartan_riskit(kk, p)\n"
             "print(len(t['viivat']))\n")
    tulos = subprocess.run([sys.executable, "-c", koodi], cwd=HAKEMISTO, capture_output=True, text=True)
    assert tulos.returncode == 0, tulos.stderr
    assert tulos.stdout.strip() == "1"


@pytest.mark.oikeat_aineistot
def test_lue_jxl_ja_muodosta():
    raportti, pisteet, _ = ydin.lue_jxl(os.path.join(DATA, "lepolantie79.jxl"))
    assert raportti["job_nimi"] == "lepolantie79"
    tulokset = ydin.muodosta(pisteet)
    assert [v["nimi"] for v in tulokset["tulos"]["viivat"]] == ["Viiva 1"]
    assert tulokset["poikkeamat"] == {} and tulokset["riskit"] == []
    x0, y0, x1, y1 = ydin.seinalinjan_alue(pisteet)
    assert all(x0 < p["e"] < x1 and y0 < p["n"] < y1 for p in sl.seinalinjan_pisteet(pisteet))


def test_poikkeama_viivoittain_ja_luokat():
    # talo 10 x 6 m, kantakartassa sama talo 8 cm itään siirrettynä
    pisteet = [{"nimi": str(i), "koodi": "8" if i == 0 else "5", "e": E0 + x, "n": N0 + y, "korkeus": 1.0}
               for i, (x, y) in enumerate([(0, 0), (10, 0), (10, 6), (0, 6)])]
    kantakartta = [[[(E0 + x + 0.08, N0 + y) for x, y in [(0, 0), (10, 0), (10, 6), (0, 6), (0, 0)]]]]
    tulokset = ydin.muodosta(pisteet, kantakartta=kantakartta)
    p = tulokset["poikkeamat"]["Viiva 1"]
    assert p["suurin_m"] == pytest.approx(0.08, abs=1e-6)
    assert len(p["naytteet"]) == 129   # 32 m / 0,25 m + 1
    assert {ydin.poikkeamaluokka(d)[0] for _, _, d in p["naytteet"]} == {"alle 5 cm", "5–15 cm"}
    assert ydin.poikkeamaluokka(0.2) == ("yli 15 cm", "#d62728")


def test_viivan_tiedot():
    assert ydin.viivan_tiedot({"avain": ("RAK", ("Sokkeli",), 2)}) == \
        {"kohde": "RAK", "rakennetyyppi": "Sokkeli", "numero": 2}
    assert ydin.viivan_tiedot({"avain": ("", (), 1)}) == {"kohde": None, "rakennetyyppi": None, "numero": 1}


def test_murtoviiva_vastaa_shapelya():
    shapely = pytest.importorskip("shapely.geometry")
    pts = [(0, 0), (10, 0), (10, 6), (3, 6)]
    oma, ref = sl._Murtoviiva(pts), shapely.LineString(pts)
    assert oma.length == pytest.approx(ref.length)
    for p in [(5, 1), (12, 3), (-1, -1), (6, 6.5)]:
        assert oma.distance(p) == pytest.approx(ref.distance(shapely.Point(p)))
        assert oma.project(p) == pytest.approx(ref.project(shapely.Point(p)))
    for m in [0, 4.5, 13, 23]:
        assert oma.interpolate(m) == pytest.approx(tuple(ref.interpolate(m).coords[0]))


def test_skriptiversio_syntyy(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "rakenna_zip", os.path.join(HAKEMISTO, "qgis_plugin", "rakenna_zip.py"))
    rakenna = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rakenna)
    polku = rakenna.rakenna_skripti(str(tmp_path / rakenna.SKRIPTIN_NIMI))
    with open(polku, encoding="utf-8") as f:
        lahde = f.read()
    compile(lahde, polku, "exec")
    # merkkijonot ASCII-koodattuina; vain kommenteissa saa olla ääkkösiä
    assert all(rivi.lstrip().startswith("#") for rivi in lahde.splitlines() if not rivi.isascii())
    for nimi, _ in rakenna.SKRIPTIN_MODUULIT:
        assert repr(nimi) in lahde
    assert "class SeinalinjaJxl(" in lahde


def test_skriptiversio_ei_kayta_tyokansion_lib_kansiota(tmp_path):
    # Skriptiversiossa ydin-moduulilla ei ole tiedostoa. Jos QGIS:n työkansiossa on lib-kansio,
    # se ei saa korvata skriptiin pakattuja seinalinja- ja jobxml_tuonti-moduuleja.
    rakenna = _rakenna_moduuli()
    # seinalinja_algoritmi vaatii QGIS:n, joten skriptiin vain jaetut moduulit ja ydin
    rakenna.SKRIPTIN_MODUULIT = [m for m in rakenna.SKRIPTIN_MODUULIT
                                 if m[0] in ("seinalinja", "jobxml_tuonti", "maastomittaus_skripti.ydin")]
    skripti = rakenna.rakenna_skripti(str(tmp_path / "skripti.py"))
    tyokansio = tmp_path / "tyokansio"
    (tyokansio / "lib").mkdir(parents=True)
    (tyokansio / "lib" / "seinalinja.py").write_text("raise ImportError('työkansion seinalinja')\n", encoding="utf-8")
    koodi = ("import sys\n"
             f"exec(open({skripti!r}, encoding='utf-8').read().split('\\nclass SeinalinjaJxl(')[0])\n"
             "try:\n"
             "    _lataa_algoritmi()\n"
             "except KeyError:\n"
             "    pass  # seinalinja_algoritmi jätettiin pois\n"
             "ydin = sys.modules['maastomittaus_skripti.ydin']\n"
             "print(ydin.sl is sys.modules['seinalinja'], ydin.sl.__file__, ydin.jx.__file__)\n")
    tulos = subprocess.run([sys.executable, "-c", koodi], cwd=str(tyokansio), capture_output=True, text=True)
    assert tulos.returncode == 0, tulos.stderr
    assert tulos.stdout.split() == ["True", "<seinalinja>", "<jobxml_tuonti>"]



def _rakenna_moduuli():
    spec = importlib.util.spec_from_file_location(
        "rakenna_zip", os.path.join(HAKEMISTO, "qgis_plugin", "rakenna_zip.py"))
    rakenna = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rakenna)
    return rakenna


@pytest.mark.oikeat_aineistot
def test_karsitut_kopiot_toimivat_ilman_kanta_ja_kuvakoodia(tmp_path):
    # Lisäosaan pakataan karsitut kopiot: ei kantaan tallennusta (SQL), krd:tä, kuvia eikä DXF:ää.
    # Niillä pitää syntyä sama seinälinja kuin alkuperäisillä.
    rakenna = _rakenna_moduuli()
    for nimi in rakenna.JAETUT:
        lahde = rakenna.jaettu_lahde(os.path.join(HAKEMISTO, nimi))
        for poistettu in rakenna.KARSITTAVAT[nimi]:
            assert f"def {poistettu}(" not in lahde and f"\n{poistettu} = " not in lahde
        for kielletty in ("INSERT", "DELETE", "TRUNCATE", "kentalla_mitatut", "psycopg2", "import ezdxf",
                          "matplotlib"):
            assert kielletty not in lahde, (nimi, kielletty)
        (tmp_path / nimi).write_text(lahde, encoding="utf-8")
    koodi = ("import json, sys\n"
             f"sys.path.insert(0, {str(tmp_path)!r})\n"
             "import jobxml_tuonti as jx, seinalinja as sl\n"
             f"r, p, _ = jx.jasenna_tyo(open({os.path.join(DATA, 'lepolantie79.jxl')!r}, 'rb').read(), 'x')\n"
             "kk = [[[(25495760, 6680640), (25495800, 6680640), (25495800, 6680680), (25495760, 6680680)]]]\n"
             "t = sl.muodosta_seinalinjat(p, kantakartta=kk)\n"
             "print(json.dumps([sl.__file__, [[k['e'], k['n']] for k in t['viivat'][0]['karjet']], t['varoitukset'],"
             " sl.poikkeama_kantakartasta(t, kk)]))\n")
    tulos = subprocess.run([sys.executable, "-c", koodi], cwd=str(tmp_path), capture_output=True, text=True)
    assert tulos.returncode == 0, tulos.stderr
    import json
    tiedosto, karjet, varoitukset, poikkeama = json.loads(tulos.stdout)
    assert tiedosto.startswith(str(tmp_path))
    import jobxml_tuonti as jx
    _, pisteet, _ = jx.jasenna_tyo(open(os.path.join(DATA, "lepolantie79.jxl"), "rb").read(), "x")
    kk = [[[(25495760, 6680640), (25495800, 6680640), (25495800, 6680680), (25495760, 6680680)]]]
    alkuperainen = sl.muodosta_seinalinjat(pisteet, kantakartta=kk)
    assert karjet == [[k["e"], k["n"]] for k in alkuperainen["viivat"][0]["karjet"]]
    assert varoitukset == alkuperainen["varoitukset"]
    assert poikkeama == sl.poikkeama_kantakartasta(alkuperainen, kk)


def test_karsinta_pysahtyy_virheeseen():
    rakenna = _rakenna_moduuli()
    lahde = "def a():\n    return b()\n\n\ndef b():\n    return 1\n\n\nX = 2\n"
    assert rakenna.karsi(lahde, ["X"]) == "def a():\n    return b()\n\n\ndef b():\n    return 1\n"
    with pytest.raises(ValueError, match="viitataan"):
        rakenna.karsi(lahde, ["b"])
    with pytest.raises(ValueError, match="ei löytynyt"):
        rakenna.karsi(lahde, ["c"])


def test_muodosta_lidarin_kanssa():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import synteettiset as syn
    talo = syn.talot()["vino"]
    rng = syn.uusi_rng(1)
    pisteet, muunnos, _ = syn.mittaa(talo, rng, piilotus=0.5, ohita_seinat={rng.randrange(4)}, apupisteet=False)
    lidar = syn.lidar_seinat(talo, muunnos, rng, katko=True)
    tulokset = ydin.muodosta(syn.sekoitettu(pisteet, rng), lidar=lidar)
    assert tulokset["lidar_aariviiva"]
    [p] = tulokset["poikkeamat_lidar"].values()
    assert p["suurin_m"] < 0.05 and p["peitto"] > 0.8
    assert ydin.muodosta(pisteet)["poikkeamat_lidar"] == {}


def test_keilausraportti(tmp_path):
    import json
    polku = tmp_path / "x_raportti.json"
    polku.write_text(json.dumps({
        "points": 6734228, "frames": 21606,
        "closure": {"before_m": {"1": 0.077, "T1": 0.129}, "after_m": {"1": 0.0006, "T1": 0.0079}},
        "track": {"points": 362, "rms_h_m": 0.0255, "rms_v_m": 0.0329},
        "optimization": {"max_correction_m": 0.2466, "targets": 316}}), encoding="utf-8")
    assert ydin.keilausraportti(str(polku)) == [
        "6 734 228 pistettä, 21606 ruutua",
        "sulkuvirhe 129 mm -> 7.9 mm optimoinnin jälkeen",
        "georeferointi seurannasta (362 pistettä): RMS vaaka 2.5 cm, pysty 3.3 cm",
        "suurin korjaus optimoinnissa 25 cm, tähyksiä 316"]
    polku.write_text("{}", encoding="utf-8")
    assert ydin.keilausraportti(str(polku)) == []


def test_lisaosa_kayttaa_omaa_lib_kansiotaan(tmp_path):
    # QGIS:ssä voi olla muistissa vanha seinalinja-moduuli (lisäosa päivitetty ilman QGIS:n
    # uudelleenkäynnistystä); lisäosan pitää silti käyttää omaa lib-kansionsa versiota.
    rakenna = _rakenna_moduuli()
    kansio = tmp_path / "maastomittaus"
    (kansio / "lib").mkdir(parents=True)
    (kansio / "ydin.py").write_text(
        open(os.path.join(HAKEMISTO, "qgis_plugin", "maastomittaus", "ydin.py"), encoding="utf-8").read(), encoding="utf-8")
    for nimi in rakenna.JAETUT:
        (kansio / "lib" / nimi).write_text(rakenna.jaettu_lahde(os.path.join(HAKEMISTO, nimi)), encoding="utf-8")
    koodi = ("import sys, types, importlib.util\n"
             "vanha = types.ModuleType('seinalinja'); vanha.__file__ = '/vanha/seinalinja.py'\n"
             "sys.modules['seinalinja'] = vanha\n"
             f"spec = importlib.util.spec_from_file_location('ydin', {str(kansio / 'ydin.py')!r})\n"
             "ydin = importlib.util.module_from_spec(spec); spec.loader.exec_module(ydin)\n"
             "print(ydin.sl.__file__); print(ydin.jx.sl is ydin.sl)\n")
    tulos = subprocess.run([sys.executable, "-c", koodi], cwd=str(tmp_path), capture_output=True, text=True)
    assert tulos.returncode == 0, tulos.stderr
    tiedosto, sama = tulos.stdout.split()
    assert tiedosto.startswith(str(kansio / "lib")) and sama == "True"


def test_seinapalat():
    viiva = {"karjet": [{"e": 0, "n": 0, "z": 18.0, "bulge": 0.0}, {"e": 10, "n": 0, "z": 19.0, "bulge": 0.0},
                        {"e": 10, "n": 6, "z": None, "bulge": 0.0}], "suljettu": False}
    palat = ydin.seinapalat(viiva, leveys_m=0.2)
    assert len(palat) == 2
    (kulmat, korkeus, ero), (_, korkeus2, _) = palat
    assert kulmat == [(0, 0.1), (10, 0.1), (10, -0.1), (0, -0.1)] and korkeus == 18.5 and ero is None
    assert korkeus2 == pytest.approx(18.75)   # puuttuva korkeus = kärkien keskiarvo 18.5
    assert ydin.seinapalat({"karjet": [dict(k, z=None) for k in viiva["karjet"]], "suljettu": False})[0][1] is None


def test_seinapalat_poikkeaman_mukaan():
    # Pätkä pilkotaan 25 cm paloiksi, ja pala saa lähimmän näytteen eron (värit 3D-näkymään)
    viiva = {"karjet": [{"e": 0, "n": 0, "z": 18.0, "bulge": 0.0}, {"e": 2, "n": 0, "z": 19.0, "bulge": 0.0}],
             "suljettu": False}
    naytteet = [(0.125 + 0.25 * i, 0.0, 0.02 if i < 4 else None) for i in range(6)]
    palat = ydin.seinapalat(viiva, naytteet=naytteet)
    assert len(palat) == 8
    assert [ero for _, _, ero in palat] == [0.02] * 4 + [None] * 4   # näyte None tai yli 25 cm päässä
    assert palat[0][0][0] == (0, ydin.SEINAN_LEVEYS_M / 2) and palat[0][0][1] == pytest.approx((0.25, 0.01))
    assert palat[0][1] == pytest.approx(18.0625) and palat[-1][1] == pytest.approx(18.9375)


def test_viivat_pisteista_ja_las_korkeus(tmp_path):
    import struct
    tulos = ydin.viivat_pisteista([
        ("A", [(0, 0, None), (10, 0, None), (10, 6, None), (0, 6, None), (0, 0, None)]),   # suljettu
        ("B", [(20, 0, 17.0), (30, 0, 18.0)]), ("tyhjä", [(1, 1, None)])])
    a, b = tulos["viivat"]
    assert a["suljettu"] and len(a["karjet"]) == 4 and not b["suljettu"]
    assert sl.viivan_pisteet(a)[-1] == (0, 0)
    assert [p[2] for p in sl.viivan_pisteet_z(b)] == [17.0, 18.0]
    # vertailu toimii kuin JXL:n seinälinjalla
    [p] = [x for x in sl.poikkeamat_lidarista(tulos, [((0, 0.03), (10, 0.03))]) if x["nimi"] == "A"]
    assert p["suurin_m"] == pytest.approx(0.03)
    assert ydin.seinapalat(b)[0][1] == pytest.approx(17.5)
    # LAS-otsikon korkeusalue
    otsikko = bytearray(227)
    otsikko[:4] = b"LASF"
    otsikko[211:227] = struct.pack("<2d", 20.07, 16.37)
    (tmp_path / "x.las").write_bytes(bytes(otsikko))
    assert ydin.las_korkeusalue(str(tmp_path / "x.las")) == (16.37, 20.07)
    (tmp_path / "y.las").write_bytes(b"ei las")
    assert ydin.las_korkeusalue(str(tmp_path / "y.las")) is None


def test_samannimiset_viivat_erotetaan():
    # DXF QGIS:ssä: nimikenttänä Layer, jolloin kaikki viivat ovat SEINALINJA. Vertailut kootaan
    # nimen mukaan, joten muuten viimeisen viivan tulos näkyisi jokaisella rivillä.
    tulos = ydin.viivat_pisteista([("SEINALINJA", [(0, 0, None), (10, 0, None)]),
                                   ("SEINALINJA", [(0, 50, None), (10, 50, None)]),
                                   ("SEINALINJA (2)", [(0, 90, None), (10, 90, None)]),
                                   ("SEINALINJA", [(0, 100, None), (10, 100, None)])])
    nimet = [v["nimi"] for v in tulos["viivat"]]
    assert nimet == ["SEINALINJA", "SEINALINJA (2)", "SEINALINJA (2) (2)", "SEINALINJA (3)"]
    assert tulos["viivat"][1]["karjet"][0]["nimi"] == "SEINALINJA (2)/1"
    poikkeamat = {p["nimi"]: p for p in sl.poikkeamat_lidarista(tulos, [((0, 0.02), (10, 0.02)),
                                                                       ((0, 50.07), (10, 50.07))])}
    assert poikkeamat["SEINALINJA"]["suurin_m"] == pytest.approx(0.02)
    assert poikkeamat["SEINALINJA (2)"]["suurin_m"] == pytest.approx(0.07)


def test_kirjoita_dxf_r12(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    polku = ydin.kirjoita_dxf_r12([("A", [(E0, N0), (E0 + 10, N0), (E0 + 10, N0 + 6)], True),
                                    ("B", [(E0 + 20, N0), (E0 + 30, N0)], False)], str(tmp_path / "s.dxf"))
    viivat = list(ezdxf.readfile(polku).modelspace().query("POLYLINE"))
    assert [v.is_closed for v in viivat] == [True, False]
    assert [tuple(p)[:2] for p in viivat[0].points()] == [(E0, N0), (E0 + 10, N0), (E0 + 10, N0 + 6)]
    assert {v.dxf.layer for v in viivat} == {"SEINALINJA"}
    # samaa muotoa lukee myös sovelluksen LiDAR-DXF-lukija
    assert len(sl.lue_lidar_dxf(polku)["SEINA"]) == 0   # eri taso, ei LiDAR-seiniä


def _kirjoita_las(polku, xyz, skaala=0.001, vlrt=(), luokat=None):
    """Pieni pakkaamaton LAS 1.2 (pistetyyppi 0) testejä varten; vlrt = [(user_id, record_id, data)],
    luokat = pisteiden luokat (tavu 15, ylimmät bitit synthetic/key point/withheld)."""
    import struct

    import numpy as np
    xyz = np.asarray(xyz, dtype=float)
    siirto = xyz.min(axis=0).round()
    otsikko = bytearray(227)
    otsikko[:4] = b"LASF"
    otsikko[24:26] = bytes([1, 2])
    otsikko[94:96] = struct.pack("<H", 227)
    vlr_tavut = b"".join(b"\0\0" + kayttaja.encode().ljust(16, b"\0") + struct.pack("<2H", tunnus, len(data))
                         + b"\0" * 32 + data for kayttaja, tunnus, data in vlrt)
    otsikko[96:100] = struct.pack("<I", 227 + len(vlr_tavut))
    otsikko[100:104] = struct.pack("<I", len(vlrt))
    otsikko[104] = 0
    otsikko[105:107] = struct.pack("<H", 20)
    otsikko[107:111] = struct.pack("<I", len(xyz))
    otsikko[131:155] = struct.pack("<3d", skaala, skaala, skaala)
    otsikko[155:179] = struct.pack("<3d", *siirto)
    yla, ala = xyz.max(axis=0), xyz.min(axis=0)
    otsikko[179:227] = struct.pack("<6d", yla[0], ala[0], yla[1], ala[1], yla[2], ala[2])
    pisteet = np.zeros((len(xyz), 20), dtype=np.uint8)
    pisteet[:, :12] = np.round((xyz - siirto) / skaala).astype("<i4").view(np.uint8).reshape(-1, 12)
    if luokat is not None:
        pisteet[:, 15] = np.asarray(luokat, dtype=np.uint8)
    with open(polku, "wb") as f:
        f.write(bytes(otsikko) + vlr_tavut + pisteet.tobytes())


def _synteettinen_talo():
    """Talo 10 x 6 m (maanpinta 10 m): etelä- ja pohjoisseinä 5 cm ulompana kuin seinälinja, muut
    seinät kohdallaan; räystäs 3 m korkeudella 40 cm ulompana ja maata talon ympärillä."""
    import numpy as np
    rng = np.random.default_rng(1)
    pisteet = []
    korkeudet = np.arange(10.05, 13.0, 0.05)
    for x in np.arange(0, 10, 0.02):
        for y in (-0.05, 6.05):
            pisteet += [(E0 + x, N0 + y, z) for z in korkeudet]
            pisteet.append((E0 + x, N0 + (y - 0.4 if y < 0 else y + 0.4), 13.0))   # räystäs
    for y in np.arange(0, 6, 0.02):
        for x in (0.0, 10.0):
            pisteet += [(E0 + x, N0 + y, z) for z in korkeudet]
    xs, ys = np.meshgrid(np.arange(-2, 12, 0.1), np.arange(-2, 8, 0.1))
    ulkona = (xs < -0.1) | (xs > 10.1) | (ys < -0.1) | (ys > 6.1)
    pisteet += [(E0 + x, N0 + y, 10.0) for x, y in zip(xs[ulkona], ys[ulkona])]
    xyz = np.array(pisteet)
    xyz[:, :2] += rng.normal(0, 0.005, (len(xyz), 2))
    return xyz


def test_lue_las_xyz_ja_las_alue(tmp_path):
    np = pytest.importorskip("numpy")
    xyz = np.array([(E0 + 1.234, N0 + 5.678, 12.345), (E0 - 3.0, N0, 10.0), (E0, N0 + 9.5, 15.5)])
    polku = str(tmp_path / "p.las")
    _kirjoita_las(polku, xyz)
    assert np.allclose(ydin.lue_las_xyz(polku), xyz, atol=1e-6)
    assert ydin.las_alue(polku) == pytest.approx((E0 - 3.0, N0, E0 + 1.234, N0 + 9.5))
    # LAZ (pakattu) tunnistetaan; alue saadaan silti otsikosta
    pakattu = bytearray(open(polku, "rb").read())
    pakattu[104] |= 0x80
    (tmp_path / "p.laz").write_bytes(bytes(pakattu))
    with pytest.raises(ValueError):
        ydin.lue_las_xyz(str(tmp_path / "p.laz"))
    assert ydin.las_alue(str(tmp_path / "p.laz")) == ydin.las_alue(polku)
    # Paikallinen float32-luku paloittain: kartan koordinaatti = paikallinen + siirto
    paikallinen, origo = ydin.lue_las_paikallinen(polku, osa=2)
    assert paikallinen.dtype == np.float32 and tuple(origo) == (E0 - 3.0, N0, 0.0)
    assert np.allclose(paikallinen + origo, xyz, atol=1e-5)
    # Luokat (pistemuoto 0: tavun 15 viisi alinta bittiä; ylimmät bitit ovat liputuksia)
    _kirjoita_las(polku, xyz, luokat=[6, 2 | 0x20, 1])
    _, _, luokka = ydin.lue_las_paikallinen(polku, osa=2, luokat=True)
    assert luokka.tolist() == [6, 2, 1]
    (tmp_path / "x.las").write_bytes(b"ei las")
    assert ydin.las_alue(str(tmp_path / "x.las")) is None


def test_poikkeamat_pistepilvesta():
    pytest.importorskip("numpy")
    xyz = _synteettinen_talo()
    talo = [(E0, N0, None), (E0 + 10, N0, None), (E0 + 10, N0 + 6, None), (E0, N0 + 6, None), (E0, N0, None)]
    viivat = [("Talo", talo), ("Ei keilattu", [(E0 + 50, N0, None), (E0 + 60, N0, None)])]
    tulos = ydin.viivat_pisteista(viivat)
    p, tyhja = ydin.poikkeamat_pistepilvesta(tulos, xyz)
    assert tyhja["keskiarvo_m"] is None and tyhja["peitto"] == 0.0
    assert p["peitto"] > 0.95
    # etelä- ja pohjoisseinä 5 cm ulompana (+), itä- ja länsiseinä kohdallaan; räystäs ei sotke
    etela = [ero for (e, n, _), ero in zip(p["naytteet"], p["etumerkki"]) if abs(n - N0) < 0.01 and ero is not None]
    ita = [ero for (e, n, _), ero in zip(p["naytteet"], p["etumerkki"]) if abs(e - E0 - 10) < 0.01 and ero is not None]
    assert len(etela) > 30 and all(ero == pytest.approx(0.05, abs=0.01) for ero in etela)
    assert len(ita) > 15 and all(abs(ero) < 0.01 for ero in ita)
    assert p["suurin_m"] < 0.07
    # löydetty seinäpinta: eteläseinä 5 cm talosta ulospäin (etelään); viivat seinittäin
    etelapinta = [q for q, j in zip(p["seinapinta"], p["jana"]) if q and j == 0]
    assert len(etelapinta) > 30 and all(q[1] == pytest.approx(N0 - 0.05, abs=0.01) for q in etelapinta)
    viivat_pinnasta = ydin.pilven_seinaviivat(p)
    assert len(viivat_pinnasta) == 4 and all(len(v) > 15 for v in viivat_pinnasta)
    assert all(z == pytest.approx(10.0, abs=0.01) for _, _, z in p["maanpinnat"])
    # maanpinta nurkittain 3D-seiniä varten; kaukana pistepilvestä ei arvoa
    talon_maat, kaukana = ydin.maanpinnat(viivat, xyz)
    assert all(z == pytest.approx(10.0, abs=0.01) for z in talon_maat) and kaukana == [None, None]


def test_pistepilven_peitto_keilaamattomat_seinat():
    # Vain eteläseinä ja sivuseinien alin 0,7 m keilattu: pohjoisseinä (ei pisteitä lähelläkään) kuuluu
    # peittoon keilaamattomana, jolloin peitto on keilattu osuus kehästä kuten poikkeamat_lidarista laskee
    pytest.importorskip("numpy")
    xyz = _synteettinen_talo()
    xyz = xyz[xyz[:, 1] < N0 + 0.7]
    talo = [(E0, N0, None), (E0 + 10, N0, None), (E0 + 10, N0 + 6, None), (E0, N0 + 6, None), (E0, N0, None)]
    [p] = ydin.poikkeamat_pistepilvesta(ydin.viivat_pisteista([("Talo", talo)]), xyz)
    pohjoinen = [d for _, n, d in p["naytteet"] if abs(n - N0 - 6) < 0.01]
    assert len(pohjoinen) > 30 and all(d is None for d in pohjoinen)
    assert p["peitto"] == pytest.approx((10 + 2 * 0.7) / 32, abs=0.02)
    assert len(p["naytteet"]) == len(p["etumerkki"]) == len(p["seinapinta"]) == len(p["jana"])


def test_luokkarajat():
    assert ydin.lue_luokkarajat("") == ydin.lue_luokkarajat(None) == [3.0, 5.0, 15.0]
    for teksti in ("3 5 15", "3; 5; 15", "3, 5, 15", "3,5,15", "15 3 5"):
        assert ydin.lue_luokkarajat(teksti) == [3.0, 5.0, 15.0], teksti
    assert ydin.lue_luokkarajat("2,5 5 15") == [2.5, 5.0, 15.0]
    for virhe in ("kolme", "0 5", "-1 5"):
        with pytest.raises(ValueError):
            ydin.lue_luokkarajat(virhe)
    luokat = ydin.poikkeamaluokat()
    assert [nimi for _, nimi, _ in luokat] == ["alle 3 cm", "3–5 cm", "5–15 cm", "yli 15 cm"]
    assert ydin.poikkeamaluokka(0.029, luokat)[0] == "alle 3 cm"
    assert ydin.poikkeamaluokka(0.03, luokat)[0] == "3–5 cm"
    assert ydin.poikkeamaluokka(0.2, luokat) == ("yli 15 cm", "#d62728")
    # kahdella rajalla samat luokat ja värit kuin sovelluksessa
    assert ydin.poikkeamaluokat([5, 15]) == [(r, n, v) for r, n, v in sl.POIKKEAMALUOKAT]
    assert [n for _, n, _ in ydin.poikkeamaluokat([2.5])] == ["alle 2,5 cm", "yli 2,5 cm"]
    assert len({v for _, _, v in ydin.poikkeamaluokat([1, 2, 3, 5, 15])}) == 6


def test_paattele_las_koordinaatisto():
    p = ydin.paattele_las_koordinaatisto
    # Stonex GOpost: ETRS-GK25 ilman kaistan tunnusta, otsikossa EPSG:3132
    k = p((497602.6, 6672900.4, 497872.5, 6673217.9), 3132)
    assert (k["siirto_x"], k["epsg"], k["kerros_epsg"], k["otsikko_epsg"]) == (25e6, 3879, 3132, 3132)
    assert "puuttuu kaistan tunnus 25 (X = 497 603" in k["selitys"]
    assert p((497602.6, 6672900.4, 497872.5, 6673217.9), None)["siirto_x"] == 25e6
    # tunnus mukana, mutta otsikossa EPSG:3132 (tai ei mitään): vain merkintä on väärin
    for epsg in (3132, None, 3879):
        k = p((25496058.7, 6678435.6, 25496207.9, 6678597.4), epsg)
        assert (k["siirto_x"], k["epsg"], k["kerros_epsg"]) == (0, 3879, 3879)
    assert "otsikossa EPSG:3132" in p((25496058.7, 6678435.6, 25496207.9, 6678597.4), 3132)["selitys"]
    # muu merkitty koordinaatisto muunnetaan (TM35FIN Helsingissä ~385 000)
    k = p((385000, 6672000, 385200, 6672200), 3067)
    assert (k["siirto_x"], k["epsg"]) == (0, 3067)
    # paikallinen tai merkitsemätön TM35FIN: ei arvata
    for alue, epsg in (((-3, -1, 5, 3), None), ((385000, 6672000, 385200, 6672200), None)):
        with pytest.raises(ValueError, match="ei voi päätellä"):
            p(alue, epsg)


STONEX_WKT = ('PROJCS["ETRS89 / ETRS-GK25FIN",GEOGCS["ETRS89",DATUM["European_Terrestrial_Reference_System_1989",'
              'SPHEROID["GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],TOWGS84[0,0,0,0,0,0,0],'
              'AUTHORITY["EPSG","6258"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",'
              '0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4258"]],PROJECTION["Transverse_Mercator"],'
              'PARAMETER["latitude_of_origin",0],PARAMETER["central_meridian",25],PARAMETER["scale_factor",1],'
              'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1,AUTHORITY["EPSG",'
              '"9001"]],AUTHORITY["EPSG","3132"]]')


def _geoavaimet(projektio):
    import struct
    avaimet = [(1024, 0, 1, 1), (1025, 0, 1, 1), (3072, 0, 1, projektio), (3076, 0, 1, 9001)]
    return struct.pack(f"<{4 + 4 * len(avaimet)}H", 1, 1, 0, len(avaimet), *[a for k in avaimet for a in k])


def test_korjaa_las_gk25(tmp_path):
    np = pytest.importorskip("numpy")
    xyz = np.array([(E0 + 1.234, N0 + 5.678, 12.345), (E0 - 3.0, N0, 10.0), (E0, N0 + 9.5, 15.5)])
    stonex = str(tmp_path / "stonex.las")
    _kirjoita_las(stonex, xyz - (25e6, 0, 0), vlrt=[("LASF_Projection", 34735, _geoavaimet(3132)),
                                                    ("liblas", 2112, STONEX_WKT.encode() + b"\0")])
    assert ydin.las_otsikko(stonex)["epsg"] == 3132
    korjattu = str(tmp_path / "korjattu.las")
    tiedot, muutokset = ydin.korjaa_las_gk25(stonex, korjattu)
    assert tiedot["siirto_x"] == 25e6
    assert muutokset == ["itäkoordinaatteihin lisätty 25 000 000", "GeoTIFF-avain EPSG:3132 -> EPSG:3879",
                         "WKT (liblas) -> EPSG:3879"]
    assert os.path.getsize(korjattu) == os.path.getsize(stonex)
    assert np.allclose(ydin.lue_las_xyz(korjattu), xyz, atol=1e-6)
    assert ydin.las_alue(korjattu) == pytest.approx((E0 - 3.0, N0, E0 + 1.234, N0 + 9.5))
    assert ydin.las_otsikko(korjattu)["epsg"] == 3879
    wkt = open(korjattu, "rb").read().split(b"PROJCS", 1)[1].split(b"\0")[0].decode()
    assert '"false_easting",25500000]' in wkt and wkt.endswith('AUTHORITY["EPSG","3879"]]')
    assert ydin.las_koordinaatisto(korjattu)["siirto_x"] == 0
    # korjattua ei korjata uudestaan, ja samaan tiedostoon ei kirjoiteta
    _, muutokset = ydin.korjaa_las_gk25(korjattu, str(tmp_path / "toinen.las"))
    assert muutokset[-1].startswith("otsikossa ei ole koordinaatistoa, jonka voisi vaihtaa")
    with pytest.raises(ValueError, match="eri tiedostoon"):
        ydin.korjaa_las_gk25(stonex, stonex)
    # TM35FIN: ei korjata (QGIS:n Reproject point cloud)
    tm35 = str(tmp_path / "tm35.las")
    _kirjoita_las(tm35, [(385000, 6672000, 10), (385010, 6672010, 11)],
                  vlrt=[("LASF_Projection", 34735, _geoavaimet(3067))])
    with pytest.raises(ValueError, match="Reproject point cloud"):
        ydin.korjaa_las_gk25(tm35, str(tmp_path / "x.las"))


def test_korjaa_paluunumerot_ja_pistemaara(tmp_path):
    import struct
    np = pytest.importorskip("numpy")
    polku = str(tmp_path / "p.las")
    _kirjoita_las(polku, [(E0, N0, 10.0), (E0 + 1, N0, 11.0), (E0 + 2, N0, 12.0)])
    assert ydin.las_pistemaara(polku) == 3
    data = bytearray(open(polku, "rb").read())
    data[227 + 14] = 0b001          # Stonex: paluunumero 1, paluiden määrä 0
    data[227 + 20 + 14] = 0b010001  # kunnossa (1/2)
    data[227 + 40 + 14] = 0b11000000  # muut bitit (esim. reunan lippu) säilyvät
    open(polku, "wb").write(bytes(data))
    assert ydin.korjaa_paluunumerot(polku) == 2
    tavut = open(polku, "rb").read()
    assert [tavut[227 + 20 * i + 14] for i in range(3)] == [0b001001, 0b010001, 0b11001001]
    assert ydin.korjaa_paluunumerot(polku) == 0
    assert np.allclose(ydin.lue_las_xyz(polku)[:, 2], [10, 11, 12])


def test_ruudut_ja_kattorasteri():
    np = pytest.importorskip("numpy")
    r = ydin.ruudut(E0 + 10, N0 - 5, E0 + 260, N0 + 140, 150)
    assert len(r) == 3 * 2 and (r[0][2], r[0][3]) == (150 * (E0 // 150), 150 * ((N0 - 5) // 150))
    assert all(e % 150 == 0 and n % 150 == 0 for _, _, e, n in r)
    katto = ydin.Kattorasteri((E0, N0, E0 + 10, N0 + 10), 0.5)
    katto.lisaa([(E0 + 1.2, N0 + 3.7), (E0 + 99, N0)])       # alueen ulkopuolinen jää pois
    assert katto.rasteri.sum() == 1 and katto.rasteri[2, 7]


def test_taysi_vauhti_ei_kaada():
    assert ydin.taysi_vauhti() in (True, False)
