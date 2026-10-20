"""Mittausjärjestys QGIS-animaatiota varten (jobxml_tuonti.mittausjarjestys) keksityllä työllä."""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jobxml_tuonti as jx

T0 = datetime(2026, 10, 1, 8, 0, 0)


def _aika(min):
    return T0 + timedelta(minutes=min)


def _tyo():
    asemat = [
        {"nimi": "A1", "station_record_id": "s1", "e": 1.0, "n": 1.0, "aikaleima": _aika(1)},
        {"nimi": "A2", "station_record_id": "s2", "e": 2.0, "n": 2.0, "aikaleima": _aika(10)},
        {"nimi": "ILMAN", "station_record_id": "s3", "e": None, "n": None, "aikaleima": _aika(20)},
    ]
    pisteet = [
        {"nimi": "A1", "kategoria": "Asemapiste", "station_record_id": None, "aikaleima": _aika(3)},
        {"nimi": "100", "kategoria": "Liitospiste", "station_record_id": "s1", "aikaleima": _aika(0)},
        {"nimi": "1", "kategoria": "Kartoituspiste", "station_record_id": "s1", "aikaleima": _aika(5)},
        {"nimi": "G1", "kategoria": "Kartoituspiste", "station_record_id": None, "aikaleima": _aika(8)},
        {"nimi": "100", "kategoria": "Liitospiste (alkuperäinen RTK-mittaus)", "station_record_id": None,
         "aikaleima": _aika(-30)},
        {"nimi": "2", "kategoria": "Kartoituspiste", "station_record_id": "s2", "aikaleima": _aika(12)},
        {"nimi": "101", "kategoria": "Liitospiste", "station_record_id": "s2", "aikaleima": _aika(11)},
    ]
    return {"asemapisteet": asemat}, pisteet


def test_asema_ensin_sitten_sen_pisteet_tasaisin_askelin():
    raportti, pisteet = _tyo()
    asemat, tiedot = jx.mittausjarjestys(raportti, pisteet)
    # asema alkaa ensimmäisestä havainnostaan (liitospiste 100 ennen aseman omaa aikaleimaa)
    assert asemat == {1: 1, 2: 5}
    assert tiedot == [
        ("A1", 1, 1),          # Asemapiste-rivi saa asemansa järjestyksen
        ("A1", 1, 2),          # liitospiste
        ("A1", 1, 3),
        (None, None, 4),       # asematon GNSS-piste omalla ajallaan
        (None, None, None),    # RTK-alkuperäismittaus ei kuulu järjestykseen
        ("A2", 2, 7),
        ("A2", 2, 6),
    ]
    # asema_nro kuten asemapisteet-taulussa: koordinaatiton asema ei saa numeroa
    assert [a["nimi"] for a in jx._tallennettavat_asemat(raportti)] == ["A1", "A2"]


def test_ilman_aikaleimoja_jarjestys_sailyy():
    raportti, pisteet = _tyo()
    for p in pisteet:
        p["aikaleima"] = None
    for a in raportti["asemapisteet"]:
        a["aikaleima"] = None
    asemat, tiedot = jx.mittausjarjestys(raportti, pisteet)
    numerot = sorted(list(asemat.values()) + [t[2] for t in tiedot if t[2] and t[0] is None or
                                               (t[2] and t[2] not in asemat.values())])
    assert numerot == list(range(1, len(numerot) + 1))
