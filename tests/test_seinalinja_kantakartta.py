"""Seinälinjan järjestyksen päättely oikeilla Helsingin rakennuksilla (kantakartta,
tests/data/kantakartta_talot.json). Jokaiselle talolle simuloidaan kokonaan kiertävä mittaus:
ensimmäinen kulma 8, muut 5, piilossa olevien kulmien viereisille seinille kaksi 100-pistettä,
mittausvirhe ja satunnainen mittausjärjestys. Kantakarttaa ei käytetä apuna, koska tässä
testataan pelkkää päättelyä seinälinjoista.

Päättely saa luovuttaa (silloin käytetään lyhintä reittiä ja varoitetaan), mutta se ei saa
tuottaa merkittävästi väärää viivaa ilman varoitusta. Aineistossa ovat mukana talot, jotka
kehityksessä paljastivat ongelmia (kentässä "huomio"), esim. Malmin talo, jossa kaksi seinää
on samalla linjalla ja peräkkäiset kulmat piilossa."""
import json
import math
import os
import random
import sys

import pytest

HAKEMISTO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HAKEMISTO))
shapely = pytest.importorskip("shapely")
from shapely.geometry import LineString, Point

import seinalinja as sl

with open(os.path.join(HAKEMISTO, "data", "kantakartta_talot.json"), encoding="utf-8") as f:
    TALOT = json.load(f)["talot"]

HILJAINEN_VIRHE_MAX_M = 0.10   # väärä viiva ilman varoitusta saa poiketa talosta enintään näin


def vinoutettu(kulmat, aste):
    """Talon pystyseinät (pääsuunnassa) kallistuvat aste astetta: talo ei ole suorakulmainen."""
    kulma = sl._paasuunta(kulmat)
    r = sl._kierretty(kulmat, -kulma)
    y0 = min(y for _, y in r)
    t = math.tan(math.radians(aste))
    return sl._kierretty([(x + (y - y0) * t, y) for x, y in r], kulma)


def mittaa(kulmat, rng, piilotus, virhe_m):
    """Kokonaan kiertävä mittaus satunnaisessa järjestyksessä (8-piste ensin)."""
    n = len(kulmat)
    piilossa = {i for i in range(1, n) if rng.random() < piilotus}
    pisteet = []

    def lisaa(nimi, koodi, xy):
        pisteet.append({"nimi": nimi, "koodi": koodi, "e": xy[0] + rng.gauss(0, virhe_m),
                        "n": xy[1] + rng.gauss(0, virhe_m), "korkeus": 10.0})

    for i in range(n):
        a, b = kulmat[i], kulmat[(i + 1) % n]
        if i not in piilossa:
            lisaa(f"K{i}", "8" if i == 0 else "5", a)
        if i in piilossa or (i + 1) % n in piilossa:
            for t in (0.3, 0.7):
                lisaa(f"S{i}_{t}", "100", (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    valit = pisteet[1:]
    rng.shuffle(valit)
    return [pisteet[0]] + valit


def arvioi(kulmat, pisteet, tulos):
    """(järjestys oikein, viivan suurin etäisyys talon reunasta)."""
    reuna = LineString(list(kulmat) + [kulmat[0]])
    alku = reuna.project(Point(pisteet[0]["e"], pisteet[0]["n"]))
    odotettu = [p["nimi"] for p in sorted(
        pisteet, key=lambda p: (reuna.project(Point(p["e"], p["n"])) - alku) % reuna.length)]
    saatu = [k["nimi"] for k in tulos["viivat"][0]["karjet"] if k["laji"] == "mitattu"]
    odotettu = [nimi for nimi in odotettu if nimi in saatu]
    kulmapisteet = {p["nimi"] for p in pisteet if p["koodi"] in ("5", "8")}
    oikein = (saatu in (odotettu, odotettu[:1] + odotettu[:0:-1])) and kulmapisteet <= set(saatu)
    return oikein, LineString(sl.viivan_pisteet(tulos["viivat"][0])).hausdorff_distance(reuna)


SKENAARIOT = {
    "kulmat näkyvissä, 3 cm": dict(piilotus=0.0, virhe_m=0.03, vino=0.0),
    "30 % piilossa, 1 cm": dict(piilotus=0.3, virhe_m=0.01, vino=0.0),
    "1° vino + 30 % piilossa, 2 cm": dict(piilotus=0.3, virhe_m=0.02, vino=1.0),
}
# päätellyt (ei luovutettu) 40 talosta; raja hieman mitatun alapuolella, jotta heikkeneminen huomataan
# (2026-10-12: 28, 26 ja 15; toleranssilla max(5 cm, 1,5°) vain 23, 25 ja 13)
ALARAJAT = {"kulmat näkyvissä, 3 cm": 26, "30 % piilossa, 1 cm": 24, "1° vino + 30 % piilossa, 2 cm": 13}


@pytest.mark.parametrize("nimi", list(SKENAARIOT))
def test_oikeat_talot_ei_hiljaisia_virheita(nimi):
    asetukset = SKENAARIOT[nimi]
    paatteli = 0
    hiljaiset = []
    for k, talo in enumerate(TALOT):
        kulmat = [tuple(c) for c in talo["kulmat"]]
        if asetukset["vino"]:
            kulmat = vinoutettu(kulmat, asetukset["vino"])
        rng = random.Random(1000 + k)
        pisteet = mittaa(kulmat, rng, asetukset["piilotus"], asetukset["virhe_m"])
        tulos = sl.muodosta_seinalinjat(pisteet, "lyhin")
        oikein, virhe = arvioi(kulmat, pisteet, tulos)
        paatelty = not any("ei voitu päätellä" in v for v in tulos["varoitukset"])
        paatteli += paatelty
        if not oikein and not tulos["varoitukset"] and virhe > HILJAINEN_VIRHE_MAX_M:
            hiljaiset.append((k, talo["alue"], round(virhe, 2)))
    assert not hiljaiset, hiljaiset
    assert paatteli >= ALARAJAT[nimi], paatteli


def test_testi2_tyyppinen_vino_lyhyt_seina():
    """2,2 m seinä 1,3° vinossa (kuten testi2:ssa) ja 2 cm mittausvirhe: raja 5 cm + 1,5°
    sallii sen (pelkkä max(5 cm, 1,5°) = 5,7 cm ei sallinut)."""
    t = math.tan(math.radians(1.3))
    kulmat = [(0, 0), (12, 0), (12 + 2.2 * t, 2.2), (16, 2.2), (16, 9), (0, 9)]
    onnistui = 0
    for siemen in range(20):
        rng = random.Random(siemen)
        pisteet = [{"nimi": f"K{i}", "koodi": "8" if i == 0 else "5", "e": 25496000 + x + rng.gauss(0, 0.02),
                    "n": 6672000 + y + rng.gauss(0, 0.02), "korkeus": 10.0} for i, (x, y) in enumerate(kulmat)]
        valit = pisteet[1:]
        rng.shuffle(valit)
        tulos = sl.muodosta_seinalinjat([pisteet[0]] + valit, "lyhin")
        onnistui += not tulos["varoitukset"]
    assert onnistui >= 18, onnistui
