"""Asema tunnetulla pisteellä (Trimblen StationSetup): Resection-tietuetta ei ole, joten aseman
koordinaatit tulevat samannimisestä pisteestä (mitattu ennen asemaa tai Reductions-osio)."""
from collections import Counter

from test_kojeasennot import E, GNSS_LAATU, N, Tyo


def _kartoitus(tyo, asema):
    for k, (dn, de) in enumerate([(8, 3), (9, 9), (3, 8)], 1):
        tyo.piste(str(k), "100", N + dn, E + de, asema=asema)


def test_asema_rtk_pisteella():
    tyo = Tyo()
    tyo.piste("100", "ASP", N, E, method="GpsStaticObservation", face=None, lisa=GNSS_LAATU)
    tyo.piste("200", "LIP", N + 30, E, method="GpsStaticObservation", face=None, lisa=GNSS_LAATU)
    a = tyo.asema("100", "StationSetup")
    tyo.kahdesti("200", N + 30, E, a)
    tyo.mta("200", N + 30, E, a)
    _kartoitus(tyo, a)
    raportti, pisteet, _ = tyo.jasenna()

    [asema] = raportti["asemapisteet"]
    assert (asema["nimi"], asema["e"], asema["n"], asema["station_record_id"]) == ("100", E, N, a)
    assert asema["maarittely"] == "Tunnettu asemapiste" and asema["tunnettu"]
    assert asema["liitospisteet"] == ["200"] and asema["kojeasento_liitospisteet"] == ["200"]
    # yksi liitospiste riittää suunnaksi: ei kulmapeitto- eikä määrävaroitusta
    assert asema["laatu"]["varoitukset"] == [
        "Asema tunnetulla pisteellä: ei residuaaleja, laatu vain liitospisteiden PDOP:sta"]
    assert asema["laatu"]["luokka"] == "Erinomainen" and asema["laatu"]["kulmapeitto_deg"] is None

    kategoriat = {(p["nimi"], p["kategoria"]) for p in pisteet}
    assert ("100", "Asemapiste") in kategoriat and ("100", "Kartoituspiste") not in kategoriat
    assert [p["mittaustapa"] for p in pisteet if p["nimi"] == "100"] == ["RTK"]
    assert Counter(p["kategoria"] for p in pisteet if p["nimi"] == "200") == {
        "Liitospiste": 1, "Liitospiste (alkuperäinen RTK-mittaus)": 1}
    assert all(p["asema"]["nimi"] == "100" for p in pisteet if p["nimi"] in ("1", "2", "3"))


def test_asema_reductions_pisteella_ja_vapaa_asema_samassa_tyossa():
    tyo = Tyo()
    tyo.lopullinen("K1", N - 50, E - 50)
    a = tyo.asema("A")
    for k, (dn, de) in enumerate([(10, 0), (0, 10), (-10, 0)]):
        tyo.piste(f"L{k}", "LIP", N + dn, E + de, luokka="BackSight", asema=a)
    tyo.resektio("A", a)
    _kartoitus(tyo, a)
    b = tyo.asema("K1", "StationSetup")
    tyo.piste("L0", "LIP", N + 10, E, luokka="BackSight", asema=b)
    tyo.piste("9", "100", N - 45, E - 45, asema=b)
    raportti, pisteet, _ = tyo.jasenna()

    asemat = [(x["nimi"], x["station_record_id"], x["tunnettu"], x["e"], x["n"]) for x in raportti["asemapisteet"]]
    assert asemat == [("A", a, False, E, N), ("K1", b, True, E - 50, N - 50)]
    assert raportti["asemapisteet"][1]["koodi"] == "KP"
    assert [p["asema"]["nimi"] for p in pisteet if p["nimi"] == "9"] == ["K1"]


def test_asema_ilman_havaintoja_tai_koordinaatteja_ohitetaan():
    tyo = Tyo()
    tyo.asema("New", "StationSetup")                 # pikamittauksen tyhjä asema
    a = tyo.asema("X", "StationSetup")              # pistettä X ei ole
    _kartoitus(tyo, a)
    raportti, pisteet, _ = tyo.jasenna()
    assert raportti["asemapisteet"] == []
    assert len(pisteet) == 3
