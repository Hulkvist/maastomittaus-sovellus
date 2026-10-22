import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pytest.importorskip("shapely")
import hae_kiintopisteet as hk

N, E = 6677376.960, 25497150.768


@pytest.mark.parametrize("rivi", [
    f"KP1 {N} {E} 12.345",
    f"KP1 {E} {N} 12.345",
    f"KP1 11 {N} {E} 12.345",
    f"KP1;{N:.3f};{E:.3f};12,345".replace(".", ","),
    f"KP1\t{N}\t{E}\t12.345",
    f"KP1,{N},{E},12.345",
    f"KP1, {N}, {E}, 12.345",
    f"KP1 {str(N).replace('.', ',')} {str(E).replace('.', ',')} 12,345",
])
def test_jasennin_tunnistaa_sarakkeet(rivi):
    pisteet, ohitetut = hk.jasenna_kiintopiste_txt(rivi)
    assert ohitetut == []
    assert [{k: p[k] for k in ("tunnus", "n", "e", "korkeus")} for p in pisteet] == [
        {"tunnus": "KP1", "n": pytest.approx(N), "e": pytest.approx(E), "korkeus": pytest.approx(12.345)}]


def test_jasennin_ohittaa_otsikot_ja_puuttuva_korkeus():
    teksti = f"Tunnus N E Z\n# kommentti\n\nKP2 {N} {E}\nKP3 {N + 1} {E + 1} -1.5\n"
    pisteet, ohitetut = hk.jasenna_kiintopiste_txt(teksti)
    assert [p["tunnus"] for p in pisteet] == ["KP2", "KP3"]
    assert pisteet[0]["korkeus"] is None and pisteet[1]["korkeus"] == -1.5
    assert [nro for nro, _ in ohitetut] == [1, 2]


def test_omat_kiintopisteet_eivat_suodatu_varamerkkeina():
    oma = ("K123A", 11, N, E, 1.0, hk.OMA_KIINTOPISTE_LUOKKA, 10.0)
    mml_vara = ("K123A", 11, N, E, 1.0, "E2", 10.0)
    assert not hk.on_paamerkki("K123A")
    assert hk.suodata_paamerkit([oma, mml_vara], sisallyta_varamerkit=False) == [oma]


def test_omien_kiintopisteiden_nimi_kokonaan(tmp_path):
    assert hk.kiintopisteen_nimi("K123A", hk.OMA_KIINTOPISTE_LUOKKA) == "K123A"
    assert hk.kiintopisteen_nimi("K123", "E2") == "123"
    polku = tmp_path / "kiintopisteet.krd"
    hk.kirjoita_yhdistetty_krd([("K123A", 11, N, E, 1.0, hk.OMA_KIINTOPISTE_LUOKKA, 5.0)], [], str(polku),
                               kohde_epsg=hk.DB_SRID)
    assert polku.read_text().split()[2:4] == ["11", "K123A"]


def test_krd_rivi_kuten_esimerkki():
    """Sama tekstimuoto kuin käyttäjän krd-tiedostossa (välit, 3 desimaalia, CRLF)."""
    assert (hk.krd_rivi("1000", "100", 25495795.048, 6680659.379, 30.945)
            == "       1       0     100    1000  25495795.048   6680659.379        30.945\r\n")
    assert hk.krd_koodi("9 1") == "9" and hk.krd_koodi(None) == "0" and hk.krd_koodi(11) == "11"
    rivi = hk.krd_rivi("1111111111111", "9", 25495768.161, 6680641.865, None)
    assert rivi.split() == ["1", "0", "9", "1111111111111", "25495768.161", "6680641.865", "0.000"]
    assert hk.krd_rivi("a b", 5, 1.0, 2.0, 3.0).split()[3] == "a_b"


def test_krd_luetaan_takaisin(tmp_path):
    polku = tmp_path / "kiintopisteet.krd"
    hk.kirjoita_yhdistetty_krd([("K123A", 11, N, E, 1.5, hk.OMA_KIINTOPISTE_LUOKKA, 5.0)], [("r1", E + 1, N + 1)],
                               str(polku), kohde_epsg=hk.DB_SRID)
    pisteet, ohitetut = hk.jasenna_kiintopiste_txt(polku.read_text())
    assert ohitetut == []
    assert [(p["tunnus"], p["koodi"]) for p in pisteet] == [("K123A", "11"), ("r1", "12")]
    assert pisteet[0]["e"] == pytest.approx(E) and pisteet[0]["n"] == pytest.approx(N)


def test_krd_muoto():
    """krd: 1 0 koodi numero E N Z, kiinteä leveys ja CRLF. Tunnus on numero, ei ensimmäinen kenttä."""
    teksti = (f"       1       0     100       1  {E:.3f}   {N:.3f}        27.843\r\n"
              f"       1       0       9   11111  {E + 1:.3f}   {N + 1:.3f}        29.632\r\n"
              f"       1       0       5     100  {E + 2:.3f}   {N + 2:.3f}        29.059\r\n")
    pisteet, ohitetut = hk.jasenna_kiintopiste_txt(teksti)
    assert ohitetut == []
    assert [(p["tunnus"], p["koodi"]) for p in pisteet] == [("1", "100"), ("11111", "9"), ("100", "5")]
    assert pisteet[0]["e"] == pytest.approx(E) and pisteet[0]["n"] == pytest.approx(N)
    assert pisteet[0]["korkeus"] == pytest.approx(27.843)


def test_nimi_ja_koodi_ennen_koordinaatteja():
    """Sovelluksen oma kiintopisteet.txt (nimi koodi N E Z): tunnus on nimi, koodi toinen kenttä."""
    pisteet, _ = hk.jasenna_kiintopiste_txt(f"123 11 {N} {E} 1.0\nR7 {N} {E}\n")
    assert [(p["tunnus"], p["koodi"]) for p in pisteet] == [("123", "11"), ("R7", None)]


def test_wms_aikakatkaisu_ohittaa_seuraavat_asemakartat(tmp_path, monkeypatch):
    """Jos Helsingin WMS ei vastaa (Streamlit Cloudista yhteys voi takkuilla), vain ensimmäinen
    asemapistekartta odottaa (10 s aikaraja); seuraavat piirretään heti ilman taustaa."""
    import requests

    import hae_kiintopisteet as hk
    kutsut = []

    def aikakatkaisu(*a, **k):
        kutsut.append(k.get("timeout"))
        raise requests.Timeout("aikakatkaisu")

    monkeypatch.setattr(hk.requests, "get", aikakatkaisu)
    monkeypatch.setattr(hk, "_wms_tauko_asti", [0.0])
    hk._hae_wms_kuva.cache_clear()
    for i in range(4):
        assert hk.piirra_asemapisteen_pienikartta(6680630.0 + i, 25496280.0, [], [], str(tmp_path / f"a{i}.png"))
    assert kutsut == [10]
