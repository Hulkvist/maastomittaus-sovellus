"""Muokkauskartan tapahtumat seinälinjan muokkauksiksi (EPSG:3879): napsautettu kärki saa pisteen
koordinaatit sellaisenaan, vapaasti raahattu muunnetaan latlonista."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import hae_kiintopisteet as hk  # noqa: E402
import seinalinja as sl  # noqa: E402
import seinalinjan_muokkain as slm  # noqa: E402

E0, N0 = 25496000.0, 6672000.0


def _tulos():
    pisteet = [{"nimi": n, "koodi": k, "e": E0 + x, "n": N0 + y, "korkeus": 10.0}
               for n, k, x, y in (("1", "8", 0, 0), ("2", "5", 10, 0), ("3", "5", 10, 8), ("4", "5", 0, 8))]
    return sl.muodosta_seinalinjat(pisteet), pisteet


def test_napsautus_pisteeseen_ja_kärkeen():
    tulos, pisteet = _tulos()
    kohteet = slm.napsahduspisteet(pisteet + [{"nimi": "77", "koodi": "100", "e": E0 + 5.123456, "n": N0 + 0.001,
                                               "korkeus": 11.5}])
    viiva = tulos["viivat"][0]["nimi"]
    m = slm.muokkaukseksi({"tyyppi": "siirra", "viiva": viiva, "karki": 1, "piste": 4}, tulos, kohteet)
    assert (m["e"], m["n"], m["z"], m["nimi"]) == (E0 + 5.123456, N0 + 0.001, 11.5, "77")
    m = slm.muokkaukseksi({"tyyppi": "lisaa", "viiva": viiva, "jalkeen": 0, "kohde_viiva": viiva,
                           "kohde_karki": 2}, tulos, kohteet)
    k = tulos["viivat"][0]["karjet"][2]
    assert (m["e"], m["n"], m["jalkeen"]) == (k["e"], k["n"], 0)
    assert "uusi kärki" in slm.kuvaus(m)


def test_vapaa_siirto_latlonista():
    tulos, pisteet = _tulos()
    lat, lon = hk._latlon_muunnin()(E0 + 3.0, N0 + 4.0)
    m = slm.muokkaukseksi({"tyyppi": "siirra", "viiva": tulos["viivat"][0]["nimi"], "karki": 0, "lat": lat,
                           "lon": lon}, tulos, slm.napsahduspisteet(pisteet))
    assert (m["e"], m["n"]) == pytest.approx((E0 + 3.0, N0 + 4.0), abs=0.002) and m["nimi"] is None
    assert slm.muokkaukseksi({"tyyppi": "poista", "viiva": "x", "karki": 1}, tulos, []) == \
        {"tyyppi": "poista", "viiva": "x", "karki": 1}


def test_piirretty_uusi_viiva():
    tulos, pisteet = _tulos()
    kohteet = slm.napsahduspisteet(pisteet)
    lat, lon = hk._latlon_muunnin()(E0 + 20.0, N0 + 1.0)
    m = slm.muokkaukseksi({"tyyppi": "uusi_viiva", "suljettu": True,
                           "karjet": [{"piste": 0}, {"kohde_viiva": tulos["viivat"][0]["nimi"], "kohde_karki": 1},
                                      {"lat": lat, "lon": lon}]}, tulos, kohteet, "Uusi viiva 1")
    assert m["nimi"] == "Uusi viiva 1" and m["suljettu"]
    assert [k["laji"] for k in m["karjet"]] == ["mitattu", "mitattu", "käsin"]
    assert (m["karjet"][0]["e"], m["karjet"][0]["nimi"]) == (E0, "1")
    assert m["karjet"][2]["e"] == pytest.approx(E0 + 20.0, abs=0.002)
    uusi = sl.sovella_muokkaukset(tulos, [m])
    assert uusi["viivat"][-1]["suljettu"] and len(uusi["viivat"][-1]["karjet"]) == 3
    assert "uusi suljettu viiva (3 kärkeä)" in slm.kuvaus(m)


def test_laskettu_piste_napsahduskohteena():
    tulos, pisteet = _tulos()
    viiva = tulos["viivat"][0]["nimi"]
    m = {"tyyppi": "piste", "nimi": "L1", "e": E0 + 5.0, "n": N0 - 2.0, "a": "Piste 1 (8)", "b": "Piste 2 (5)",
         "a_mitta": 5.0, "b_mitta": 2.0}
    uusi = sl.sovella_muokkaukset(tulos, [m])
    kohteet = slm.napsahduspisteet(pisteet, uusi)
    assert kohteet[-1] == ("L1", sl.LASKETTU_KOODI, E0 + 5.0, N0 - 2.0, None)
    s = slm.muokkaukseksi({"tyyppi": "siirra", "viiva": viiva, "karki": 1, "piste": len(kohteet) - 1}, uusi, kohteet)
    assert (s["e"], s["n"], s["nimi"], s["laji"]) == (E0 + 5.0, N0 - 2.0, "L1", "laskettu")
    u = slm.muokkaukseksi({"tyyppi": "uusi_viiva", "karjet": [{"piste": 0}, {"piste": len(kohteet) - 1}]},
                          uusi, kohteet)
    assert [k["laji"] for k in u["karjet"]] == ["mitattu", "laskettu"]
    assert "laskettu piste L1" in slm.kuvaus(m)
