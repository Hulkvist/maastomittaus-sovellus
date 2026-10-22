"""Sovelluksen savutestit Streamlitin AppTestillä: kirjautuminen, kiinteistöhaku,
omien kiintopisteiden tuonti ja JobXML-osio oikeilla tiedostoilla.

Verkko- ja kantakutsut korvataan mockeilla, joten testit eivät tarvitse MML-avainta,
verkkoyhteyttä eikä tietokantaa."""
import os
import sys
from unittest import mock

import pytest

HAKEMISTO = os.path.dirname(os.path.abspath(__file__))
JUURI = os.path.dirname(HAKEMISTO)
sys.path.insert(0, JUURI)
pytest.importorskip("streamlit")
from shapely.geometry import box
from streamlit.testing.v1 import AppTest

import hae_kiintopisteet as hk

E0, N0 = 25497130.0, 6677370.0
SALASANA = "testi"


@pytest.fixture(autouse=True)
def ymparisto(monkeypatch):
    monkeypatch.chdir(JUURI)  # app.py lukee kuvat/koirat.jpg suhteellisella polulla
    monkeypatch.setattr(hk, "MML_API_KEY", "testiavain")
    # ei verkkoa: taustakartat epäonnistuvat hallitusti
    monkeypatch.setattr(hk, "hae_helsinki_kantakartta", mock.Mock(side_effect=OSError("ei verkkoa")))
    monkeypatch.setattr(hk, "hae_helsinki_rakennukset", mock.Mock(side_effect=OSError("ei verkkoa")))


def sovellus(kirjautunut=True):
    at = AppTest.from_file(os.path.join(JUURI, "app.py"), default_timeout=120)
    at.secrets["SOVELLUKSEN_SALASANA"] = SALASANA
    if kirjautunut:
        at.session_state["_kirjautunut"] = True
    return at.run()


def virheet(at):
    return [e.value for e in at.error] + [e.value for e in at.exception]


def test_kirjautuminen():
    at = sovellus(kirjautunut=False)
    assert len(at.text_input) == 1 and not at.title
    at.text_input[0].set_value("väärä").run()
    assert any("Väärä salasana" in e.value for e in at.error)
    at.text_input[0].set_value(SALASANA).run()
    assert at.title[0].value == "Kiintopisteiden, rajamerkkien ja rakennusten nurkkien haku"
    assert not at.exception


def test_kiinteistohaku_helsinki(monkeypatch):
    rakennus = box(E0 - 20, N0 - 10, E0 + 20, N0 + 10)
    rakennukset = [{"nro": 1, "tyyppi": "Asuinrakennus", "osoite": "Testikatu 1", "polygoni": rakennus}]
    kiintopisteet = [("K123", 11, N0 + 40, E0, 10.0, "E2", 40.0),
                     ("OMA7", 11, N0 - 40, E0, 9.0, hk.OMA_KIINTOPISTE_LUOKKA, 40.0)]
    for nimi, arvo in {
        "hae_kiinteiston_sijainti": [E0, N0], "hae_kiintopisteet_saateella": kiintopisteet,
        "hae_kiinteiston_rajamerkit": [("r1", E0 + 25, N0 + 15)],
        "hae_kiinteiston_rajaviivat": [[(E0 - 30, N0 - 20), (E0 + 30, N0 - 20)]],
        "hae_kiinteiston_alue": box(E0 - 30, N0 - 20, E0 + 30, N0 + 20),
        "hae_kiinteiston_rakennukset": rakennukset,
    }.items():
        monkeypatch.setattr(hk, nimi, mock.Mock(return_value=arvo))
    for nimi in ("tallenna_kiinteiston_sijainti", "tallenna_haku_tulokset", "tallenna_rajamerkit_kantaan",
                 "tallenna_rajaviivat_kantaan", "paivita_kiintopisteet_alueelle"):
        monkeypatch.setattr(hk, nimi, mock.Mock())
    txt = {}
    alkuperainen = hk.kirjoita_yhdistetty_krd

    def talteen(*a, **k):
        alkuperainen(*a, **k)
        with open(a[2], encoding=hk.KRD_MERKISTO) as f:
            txt["sisalto"] = f.read()
    monkeypatch.setattr(hk, "kirjoita_yhdistetty_krd", talteen)

    at = sovellus()
    at.text_input[0].set_value("091-25-840-8")
    at.button[0].click().run()

    assert not virheet(at), virheet(at)
    hk.paivita_kiintopisteet_alueelle.assert_not_called()
    assert hk.hae_kiintopisteet_saateella.call_args[0][3] == hk.OMA_KIINTOPISTE_LUOKKA  # vain kaupungin pisteet
    assert any("Löytyi **1** rakennusta, **4** nurkkapistettä" in m.value for m in at.markdown)
    assert any(e.label.startswith("Rakennusten nurkat") for e in at.expander)
    rivit = [r.split() for r in txt["sisalto"].splitlines()]
    assert rivit[0][2:4] == ["11", "123"] and rivit[1][2:4] == ["11", "OMA7"]  # oma piste koko tunnuksella
    assert rivit[2][2:4] == ["12", "r1"]
    assert [r[2:4] for r in rivit[3:]] == [["4", "1"], ["4", "2"], ["4", "3"], ["4", "4"]]


def test_kiinteistohaku_lataa_kiintopisteet_kun_kanta_tyhja(monkeypatch):
    haku = mock.Mock(side_effect=[[], [("A1", 11, N0, E0, 1.0, "E2", 0.0)]])
    for nimi, arvo in {"hae_kiinteiston_sijainti": mock.Mock(return_value=[25433902.0, 6821568.0]),
                       "hae_kiintopisteet_saateella": haku,
                       "paivita_kiintopisteet_alueelle": mock.Mock(return_value=1),
                       "hae_kiinteiston_rajamerkit": mock.Mock(return_value=[]),
                       "hae_kiinteiston_rajaviivat": mock.Mock(return_value=[]),
                       # MML:n taustakartta haettaisiin verkosta: kirjoitetaan tyhjä kuva
                       "piirra_kartta": mock.Mock(side_effect=lambda *a, **k: _tyhja_png(a[3]))}.items():
        monkeypatch.setattr(hk, nimi, arvo)
    for nimi in ("tallenna_kiinteiston_sijainti", "tallenna_haku_tulokset", "tallenna_rajamerkit_kantaan",
                 "tallenna_rajaviivat_kantaan"):
        monkeypatch.setattr(hk, nimi, mock.Mock())
    at = sovellus()
    at.text_input[0].set_value("837-1-1-1")
    at.button[0].click().run()
    assert not virheet(at), virheet(at)
    assert any("Kantaan tuotiin 1 kiintopistettä" in i.value for i in at.info)
    assert haku.call_count == 2
    assert any("vain Helsingistä" in c.value for c in at.caption)


def _tyhja_png(polku):
    from PIL import Image
    Image.new("RGB", (4, 4), "white").save(polku)


class Ladattu:
    def __init__(self, nimi, sisalto):
        self.name, self._sisalto, self.size = nimi, sisalto, len(sisalto)

    def getvalue(self):
        return self._sisalto


def ladattu_tiedosto(avain, tiedosto):
    alkuperainen = __import__("streamlit").file_uploader

    def korvike(label, *a, **k):
        if k.get("key") == avain:
            return tiedosto
        return alkuperainen(label, *a, **k)
    return mock.patch("streamlit.file_uploader", side_effect=korvike)


def test_omat_kiintopisteet_tallennus(monkeypatch):
    tallenna = mock.Mock(return_value=2)
    monkeypatch.setattr(hk, "tallenna_omat_kiintopisteet", tallenna)
    tiedosto = Ladattu("kp.txt", f"Tunnus N E Z\nK1 {N0} {E0} 1,5\nK2 {N0 + 1} {E0 + 1}\n".encode("latin-1"))
    at = sovellus()
    with ladattu_tiedosto("oma_kp_tiedosto", tiedosto):
        at.run()
        [b for b in at.button if b.key == "oma_kp_tallenna"][0].click().run()
    assert any("Tunnistettiin **2** kiintopistettä, **1** riviä ohitettiin" in m.value for m in at.markdown)
    assert [p["tunnus"] for p in tallenna.call_args[0][0]] == ["K1", "K2"]
    assert not virheet(at), virheet(at)


@pytest.mark.oikeat_aineistot
@pytest.mark.parametrize("nimi", sorted(os.listdir(os.path.join(HAKEMISTO, "data", "jobxml")))
                         if os.path.isdir(os.path.join(HAKEMISTO, "data", "jobxml")) else ["testi2.jxl"])
@pytest.mark.oikeat_aineistot
def test_jobxml_osio_oikeilla_tiedostoilla(nimi, monkeypatch):
    monkeypatch.setattr(hk, "tunnista_kiinteisto_pisteparvesta", mock.Mock(return_value=("09102509510003", {}, 3)))
    with open(os.path.join(HAKEMISTO, "data", "jobxml", nimi), "rb") as f:
        tiedosto = Ladattu(nimi, f.read())
    at = sovellus()
    with ladattu_tiedosto("jobxml_tiedosto", tiedosto):
        at.run()
    assert not virheet(at), virheet(at)
    assert any("jäsennetty" in s.value for s in at.success)
    assert at.session_state["jobxml_tunnus"] == "09102509510003"
    seinalinja = any(e.label.startswith("Seinälinja") for e in at.expander)
    assert seinalinja == (nimi in ("testi2.jxl", "lepolantie79.jxl", "osuuskunnantie60.jxl"))
    assert any(b.label.startswith("Lataa pisteet (krd") for b in at.get("download_button"))
    assert any(b.label == "Lataa mittausraportti (PDF)" for b in at.get("download_button"))
    assert not any(b.label == "Luo PDF-raportti" for b in at.button)


def _testi2(monkeypatch):
    monkeypatch.setattr(hk, "tunnista_kiinteisto_pisteparvesta", mock.Mock(return_value=("09102509510003", {}, 3)))
    with open(os.path.join(HAKEMISTO, "data", "jobxml", "testi2.jxl"), "rb") as f:
        return Ladattu("testi2.jxl", f.read())


@pytest.mark.oikeat_aineistot
def test_mittausten_tallennus_vie_seinalinjan(monkeypatch):
    import jobxml_tuonti as jx

    pisteet = mock.Mock(return_value=10)
    viivat = mock.Mock(return_value=1)
    monkeypatch.setattr(jx, "tallenna_mittaukset_kantaan", pisteet)
    monkeypatch.setattr(jx, "tallenna_seinalinjat_kantaan", viivat)
    raportti = mock.Mock(return_value=2)
    monkeypatch.setattr(jx, "tallenna_raportti_kantaan", raportti)
    tiedosto = _testi2(monkeypatch)
    at = sovellus()
    with ladattu_tiedosto("jobxml_tiedosto", tiedosto):
        at.run()
        [b for b in at.button if b.label == "Tallenna mittaukset kantaan"][0].click().run()
    assert not virheet(at), virheet(at)
    tunnus, tulos, lahdetiedosto, _, poikkeamat = viivat.call_args[0]
    assert (tunnus, lahdetiedosto, poikkeamat) == ("09102509510003", "testi2.jxl", [])
    assert tulos["viivat"]
    assert pisteet.call_args[0][0] == "09102509510003"
    assert pisteet.call_args[0][3]["lahdetiedosto"] == "testi2.jxl"   # raportti mukaan: asema ja järjestys
    tunnus, raportin_tiedot, _, _, pdf, _ = raportti.call_args[0]
    assert (tunnus, raportin_tiedot["lahdetiedosto"]) == ("09102509510003", "testi2.jxl")
    assert pdf.startswith(b"%PDF")
    assert any("10 pistettä" in s.value and "1 seinälinjaa seinalinjat-tauluun" in s.value
               and "2 asemapistettä" in s.value for s in at.success)


@pytest.mark.oikeat_aineistot
def test_seinalinjan_muokkaus_dxf_ja_tallennus(monkeypatch):
    """Muokkauskartta päälle ei kaada; käsin tehty muokkaus (istunnossa) näkyy DXF-napissa ja menee
    tallennukseen."""
    import hashlib

    import jobxml_tuonti as jx
    import seinalinja as sl

    viivat = mock.Mock(return_value=1)
    for nimi in ("tallenna_mittaukset_kantaan", "tallenna_raportti_kantaan"):
        monkeypatch.setattr(jx, nimi, mock.Mock(return_value=1))
    monkeypatch.setattr(jx, "tallenna_seinalinjat_kantaan", viivat)
    tiedosto = _testi2(monkeypatch)
    at = sovellus()
    with ladattu_tiedosto("jobxml_tiedosto", tiedosto):
        at.run()
        [t for t in at.toggle if t.label == "Muokkaa viivaa kartalla"][0].set_value(True).run()
        assert not virheet(at), virheet(at)
        assert any(b.label == "Lisää kärki" for b in at.button)
        avain = "_sl_muokkaukset_" + hashlib.sha1(tiedosto.getvalue()).hexdigest()
        tila = at.session_state[avain]
        viiva = jx.muodosta_seinalinja(jx.jasenna_tyo(tiedosto.getvalue(), "testi2.jxl")[1])["viivat"][0]
        k = viiva["karjet"][0]
        tila["muokkaukset"].append({"tyyppi": "siirra", "viiva": viiva["nimi"], "karki": 0, "e": k["e"] + 0.5,
                                    "n": k["n"], "z": None, "nimi": None})
        at.session_state[avain] = tila
        at.run()
        assert not virheet(at), virheet(at)
        assert any(b.label == "Lataa seinälinja (DXF) (muokattu)" for b in at.get("download_button"))
        assert any("kärki 1 siirretty" in c.value for c in at.caption)
        [b for b in at.button if b.label == "Tallenna mittaukset kantaan"][0].click().run()
    tallennettu = viivat.call_args[0][1]
    assert tallennettu["muokattu"]
    assert tallennettu["viivat"][0]["karjet"][0]["e"] == pytest.approx(k["e"] + 0.5)
    assert sl.viivojen_tunniste(tallennettu) != sl.viivojen_tunniste({"viivat": [viiva]})


def test_tallennetut_raportit(monkeypatch):
    import datetime
    import jobxml_tuonti as jx

    rivit = [{"id": 7, "kiinteistotunnus": "091-1-1-1", "lahdetiedosto": "testi2.jxl", "tyon_nimi": "testi2",
              "mittauspaiva": "21.09.2026", "asemia": 1, "mitattuja_pisteita": 12,
              "huonoin_laatuluokka": "Tyydyttävä (65/100)", "tarkistukset": None, "pdf_kt": 1,
              "tallennettu": datetime.datetime(2026, 10, 20, 12, 0)}]
    haku = mock.Mock(return_value=rivit)
    pdf = mock.Mock(return_value=b"%PDF-1.4 testi")
    monkeypatch.setattr(jx, "hae_raportit", haku)
    monkeypatch.setattr(jx, "hae_raportin_pdf", pdf)
    at = sovellus()
    at.text_input(key="raportit_tunnus").set_value("091-1-1-1")
    [b for b in at.button if b.key == "raportit_hae"][0].click().run()
    assert not virheet(at), virheet(at)
    assert haku.call_args[0][1] == "091-1-1-1"
    assert pdf.call_args[0][:2] == ("091-1-1-1", "testi2.jxl")
    assert any(b.label == "Lataa mittausraportti (PDF, 1 kt)" for b in at.get("download_button"))
    # lista haetaan uudelleen joka ajolla; poistettu raportti ei kaada sovellusta
    pdf.return_value = None
    at.run()
    assert haku.call_count >= 2
    assert not virheet(at), virheet(at)
    assert any("ei löytynyt" in w.value for w in at.warning)


@pytest.mark.oikeat_aineistot
def test_seinalinja_kantakartta_ei_verkkoa(monkeypatch):
    tiedosto = _testi2(monkeypatch)
    at = sovellus()
    with ladattu_tiedosto("jobxml_tiedosto", tiedosto):
        at.run()
    assert not virheet(at), virheet(at)
    assert any(c.label == "Käytä kantakarttaa apuna" for c in at.checkbox)
    assert any("Kantakartan rakennuksia ei saatu" in c.value for c in at.caption)


@pytest.mark.oikeat_aineistot
def test_seinalinja_kantakartta(monkeypatch):
    """Kantakartan talo testi2:n pisteiden ympärille (vino kulma): riskit ja poikkeama näkyvät."""
    import jobxml_tuonti as jx
    import seinalinja as sl
    from shapely.geometry import Polygon

    tiedosto = _testi2(monkeypatch)
    _, pisteet, _ = jx.jasenna_tyo(tiedosto.getvalue(), "testi2.jxl")
    viiva = jx.muodosta_seinalinja(pisteet)["viivat"][0]
    talo = Polygon(sl.viivan_pisteet(viiva) + [(viiva["karjet"][-1]["e"] + 5, viiva["karjet"][-1]["n"] + 9),
                                                (viiva["karjet"][0]["e"] + 4, viiva["karjet"][0]["n"] + 6)])
    haku = mock.Mock(return_value=[{"tyyppi": None, "osoite": None, "polygoni": talo.buffer(0)}])
    monkeypatch.setattr(hk, "hae_helsinki_rakennukset", haku)
    at = sovellus()
    with ladattu_tiedosto("jobxml_tiedosto", tiedosto):
        at.run()
    assert not virheet(at), virheet(at)
    assert any("poikkeaa kantakartasta keskimäärin" in c.value for c in at.caption)
    assert haku.call_count == 1   # haku kerran, vaikka seinälinja muodostetaan kahdesti
    kantakartta_pois = [c for c in at.checkbox if c.label == "Käytä kantakarttaa apuna"][0]
    kantakartta_pois.uncheck().run()
    assert not any("poikkeaa kantakartasta" in c.value for c in at.caption)
    assert not virheet(at), virheet(at)


def test_png_kartta_napista_ja_tulokset_pysyvat(monkeypatch):
    for nimi, arvo in {"hae_kiinteiston_sijainti": [E0, N0],
                       "hae_kiintopisteet_saateella": [("K123", 11, N0 + 40, E0, 10.0, "E2", 40.0)],
                       "hae_kiinteiston_rajamerkit": [], "hae_kiinteiston_rajaviivat": [],
                       "hae_kiinteiston_alue": box(E0 - 30, N0 - 20, E0 + 30, N0 + 20),
                       "hae_kiinteiston_rakennukset": []}.items():
        monkeypatch.setattr(hk, nimi, mock.Mock(return_value=arvo))
    for nimi in ("tallenna_kiinteiston_sijainti", "tallenna_haku_tulokset", "tallenna_rajamerkit_kantaan",
                 "tallenna_rajaviivat_kantaan"):
        monkeypatch.setattr(hk, nimi, mock.Mock())
    piirto = mock.Mock(side_effect=lambda *a, **k: _tyhja_png(a[3]))
    monkeypatch.setattr(hk, "piirra_kartta", piirto)

    at = sovellus()
    at.text_input[0].set_value("091-25-840-8")
    at.button[0].click().run()
    piirto.assert_not_called()  # haku ei enää piirrä PNG:tä
    assert not virheet(at), virheet(at)

    [b for b in at.button if b.key == "hakukartta_png"][0].click().run()
    piirto.assert_called_once()
    assert not virheet(at), virheet(at)
    # tulokset näkyvät edelleen napin painalluksen jälkeen
    assert any(s.value.startswith("Kartta (091-25-840-8)") for s in at.subheader)
    assert any(s.value.startswith("Kiintopisteet") for s in at.subheader)


def test_omat_kiintopisteet_krd_ja_kahdesti_esiintyva_tunnus(monkeypatch):
    tallenna = mock.Mock(return_value=3)
    monkeypatch.setattr(hk, "tallenna_omat_kiintopisteet", tallenna)
    rivit = "".join(f"       1       0     100    {t:>4}  {E0 + i:.3f}   {N0 + i:.3f}        27.843\r\n"
                    for i, t in enumerate(["1", "2", "2"]))
    at = sovellus()
    with ladattu_tiedosto("oma_kp_tiedosto", Ladattu("pisteet.krd", rivit.encode())):
        at.run()
    assert any("Tunnistettiin **3** kiintopistettä, **0** riviä ohitettiin" in m.value for m in at.markdown)
    assert any("1 tunnusta esiintyy useammin kuin kerran" in i.value for i in at.info)
    assert not virheet(at), virheet(at)


def test_helsinki_ei_lataa_mml_kiintopisteita(monkeypatch):
    """Helsingissä MML:n kiintopisteitä ei ladata, vaikka kaupungin pisteitä ei olisi ja
    "Päivitä kiintopisteet MML:ltä" olisi valittuna."""
    lataus = mock.Mock()
    for nimi, arvo in {"hae_kiinteiston_sijainti": mock.Mock(return_value=[E0, N0]),
                       "hae_kiintopisteet_saateella": mock.Mock(return_value=[]),
                       "lahin_oma_kiintopiste": mock.Mock(return_value=(0, None)),
                       "paivita_kiintopisteet_alueelle": lataus,
                       "hae_kiinteiston_rajamerkit": mock.Mock(return_value=[]),
                       "hae_kiinteiston_rajaviivat": mock.Mock(return_value=[]),
                       "hae_kiinteiston_alue": mock.Mock(return_value=box(E0 - 30, N0 - 20, E0 + 30, N0 + 20)),
                       "hae_kiinteiston_rakennukset": mock.Mock(return_value=[])}.items():
        monkeypatch.setattr(hk, nimi, arvo)
    for nimi in ("tallenna_kiinteiston_sijainti", "tallenna_haku_tulokset", "tallenna_rajamerkit_kantaan",
                 "tallenna_rajaviivat_kantaan"):
        monkeypatch.setattr(hk, nimi, mock.Mock())
    at = sovellus()
    at.text_input[0].set_value("091-25-840-8")
    [c for c in at.checkbox if c.label == "Päivitä kiintopisteet MML:ltä"][0].check()
    at.button[0].click().run()
    lataus.assert_not_called()
    assert any("Helsingin kaupungin kiintopisteitä ei ole kannassa" in w.value for w in at.warning)
    assert not virheet(at), virheet(at)


@pytest.mark.oikeat_aineistot
def test_seinalinja_lidar_dxf(monkeypatch, tmp_path):
    """LiDAR-seinien DXF Seinälinja-osioon: LiDAR-tiedot ja poikkeama näkyvät, ei virheitä."""
    ezdxf = pytest.importorskip("ezdxf")
    import jobxml_tuonti as jx
    import seinalinja as sl

    tiedosto = _testi2(monkeypatch)
    _, pisteet, _ = jx.jasenna_tyo(tiedosto.getvalue(), "testi2.jxl")
    viiva = jx.muodosta_seinalinja(pisteet)["viivat"][0]
    doc = ezdxf.new("R2010")
    xy = sl.viivan_pisteet(viiva)
    for (e0, n0), (e1, n1) in zip(xy, xy[1:]):    # LiDAR-seinät 2 cm seinälinjasta pohjoiseen
        doc.modelspace().add_line((e0, n0 + 0.02), (e1, n1 + 0.02), dxfattribs={"layer": "SEINA"})
    doc.saveas(str(tmp_path / "testi_seinat.dxf"))
    lidar = Ladattu("testi_seinat.dxf", (tmp_path / "testi_seinat.dxf").read_bytes())

    alkuperainen = __import__("streamlit").file_uploader

    def korvike(label, *a, **k):
        return {"jobxml_tiedosto": tiedosto, "seinalinja_lidar": lidar}.get(k.get("key")) or \
            alkuperainen(label, *a, **k)
    at = sovellus()
    at.session_state["seinalinja_lidar"] = lidar
    with mock.patch("streamlit.file_uploader", side_effect=korvike):
        at.run()
    assert not virheet(at), virheet(at)
    tekstit = [c.value for c in at.caption]
    assert any(t.startswith("LiDAR: ") for t in tekstit), tekstit
    assert any("poikkeaa LiDAR-seinistä keskimäärin" in t for t in tekstit), tekstit
