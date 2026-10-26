"""Regressiotestit oikeilla Trimble-tiedostoilla (tests/data/jobxml/).

Odotusarvot on tarkistettu käsin XML:ää vasten, esim. poistetut liitoshavainnot,
kahden kojeasennon Averaged-pisteet ja korkeusliitos naula2."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jobxml_tuonti as jx
import mittausraportti as mr
import seinalinja as sl

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "jobxml")
pytestmark = pytest.mark.oikeat_aineistot


def lue(nimi):
    with open(os.path.join(DATA, nimi), "rb") as f:
        return f.read()


def jasenna(nimi):
    return jx.jasenna_tyo(lue(nimi), nimi)


def asemat(raportti):
    return {a["nimi"]: a for a in raportti["asemapisteet"]}


def piste(pisteet, nimi, kategoria):
    osumat = [p for p in pisteet if p["nimi"] == nimi and p["kategoria"] == kategoria]
    assert len(osumat) == 1, (nimi, kategoria, len(osumat))
    return osumat[0]


@pytest.mark.parametrize("nimi, maara, hylatyt, kojeasento, tyojaksoja", [
    ("aleksanterinkatu 3.xml",
     {"Liitospiste (alkuperäinen RTK-mittaus)": 3, "Liitospiste": 3, "Korkeusliitos": 1, "Asemapiste": 1,
      "Kartoituspiste": 14, "Merkintäpiste": 2}, 52, 0, 1),
    ("kirkkokatu2.jxl",
     {"Liitospiste (alkuperäinen RTK-mittaus)": 5, "Liitospiste": 52, "Asemapiste": 17, "Kartoituspiste": 277},
     17, 3, 4),
    ("kirkkokatu3579.xml",
     {"Liitospiste (alkuperäinen RTK-mittaus)": 9, "Liitospiste": 17, "Asemapiste": 6, "Kartoituspiste": 71},
     207, 22, 3),
    ("testi2.jxl",
     {"Liitospiste (alkuperäinen RTK-mittaus)": 3, "Kartoituspiste": 9, "Liitospiste": 3, "Asemapiste": 1},
     1, 0, 1),
])
def test_yhteenveto(nimi, maara, hylatyt, kojeasento, tyojaksoja):
    raportti, _, _ = jasenna(nimi)
    assert raportti["maara"] == maara
    assert raportti["hylatyt_maara"] == hylatyt
    assert raportti["kahdesta_kojeasennosta_maara"] == kojeasento
    assert len(raportti["tyojaksot"]) == tyojaksoja
    assert raportti["varoitukset_2x"] == []


def test_aleksanterinkatu_asema_korkeusliitos_ja_poistettu_asemointi():
    raportti, pisteet, hylatyt = jasenna("aleksanterinkatu 3.xml")
    a = asemat(raportti)
    assert list(a) == ["1111"]  # ensimmäinen (Deleted=true) asemointi ei näy
    assert a["1111"]["liitospisteet"] == ["0901", "0902", "0903"]
    assert a["1111"]["korkeusliitokset"] == ["naula2"]
    assert a["1111"]["sijainti"] is not None
    syyt = {h["syy"].split(" (")[0] for h in hylatyt}
    assert syyt == {"Käsin syötetty", "Poistettu Trimblessa"}
    # RTK:n Averaged-keskiarvo jää kartoituspisteeksi, raakahavainnot eivät näy erikseen
    assert piste(pisteet, "0901", "Liitospiste (alkuperäinen RTK-mittaus)")["pdop"] is not None
    assert piste(pisteet, "0901", "Liitospiste")["pdop"] == pytest.approx(1.06, abs=0.01)


def test_kirkkokatu2_asemat():
    raportti, _, _ = jasenna("kirkkokatu2.jxl")
    a = asemat(raportti)
    assert len(a) == 17
    assert a["7777"]["liitospisteet"] == ["3200", "6300", "6400", "6200", "6100"]
    assert a["1616"]["liitospisteet"] == ["30400", "30300"]
    assert a["1616"]["sijainti"] is None  # alle 3 liitospistettä
    assert "Vain 2 liitospistettä" in a["1616"]["laatu"]["varoitukset"]


def test_kirkkokatu3579_kaksi_kojeasentoa_ja_poistetut_liitokset():
    raportti, pisteet, _ = jasenna("kirkkokatu3579.xml")
    a = asemat(raportti)
    # asemalla 8888 poistetut liitoshavainnot 1200/1300/1400/2300 eivät ole mukana
    assert a["8888"]["liitospisteet"] == ["2000", "5000", "6000"]
    assert a["9999"]["liitospisteet"] == ["8100", "8200"]
    # Face1 + Face2 -> MTA -> Averaged: yksi piste, ei hylätty "käsin syötettynä"
    for nimi in ("1100", "1200", "1300", "1500", "1600"):
        p = piste(pisteet, nimi, "Kartoituspiste")
        assert p["kahdesta_kojeasennosta"]
    # MTA ilman Averaged-tietuetta (1400) jää myös yhdeksi pisteeksi
    assert piste(pisteet, "1400", "Kartoituspiste")["kahdesta_kojeasennosta"]
    # RTK:lla kahdesti mitattu ja keskiarvotettu 20001
    assert piste(pisteet, "20001", "Kartoituspiste")["method"] == "GpsStaticObservation"


def test_testi2_seinalinja():
    raportti, pisteet, _ = jasenna("testi2.jxl")
    assert raportti["seinalinja_kaytettavissa"]
    tulos = sl.muodosta_seinalinjat(pisteet)
    karjet = tulos["viivat"][0]["karjet"]
    assert [k["nimi"] for k in karjet] == ["1", "2", "kulma (3-4)", "5", "6", "7", "8"]
    assert [k["laji"] for k in karjet].count("laskettu") == 1
    assert not tulos["viivat"][0]["suljettu"]


def test_testi2_seinalinja_sekoitettuna():
    """Piilokulma (5, 100, 100, 5) päätellään seinälinjoista mittausjärjestyksestä riippumatta.
    Talo on noin 1° vinossa, joten tämä testaa myös päättelyn toleranssin."""
    import random
    _, pisteet, _ = jasenna("testi2.jxl")
    jakso = sl.jaa_jaksoihin(pisteet)[0][0]
    for siemen in range(20):
        valit = jakso["valit"][:]
        random.Random(siemen).shuffle(valit)
        jarjestetty, syy = sl.jarjesta_suorakulmaisesti(jakso["alku"], valit, jakso["loppu"])
        assert syy is None
        assert [p["nimi"] for p in jarjestetty] == ["1", "2", "3", "4", "5", "6", "7", "8"]


def test_osuuskunnantie60_piilokulma_yhdella_linjapisteella():
    """Kulmien 15 ja 9 välissä on vain yläseinän 100-piste 13. Suora kulma oletetaan oikean
    seinän päähän (15), ei vinoa seinää 15-13 pitkin. Kulman 9 jälkeinen 100-piste 40 on
    piilokulman takana, joten sen suunta 9:stä ei saa ratkaista tulkintaa."""
    _, pisteet, _ = jasenna("osuuskunnantie60.jxl")
    tulos = sl.muodosta_seinalinjat(pisteet)
    rak = [v for v in tulos["viivat"] if v["suljettu"]][0]
    nimet = [k["nimi"] for k in rak["karjet"]]
    kulma = rak["karjet"][nimet.index("15") + 1]
    assert kulma["laji"] == "laskettu"
    assert abs(kulma["e"] - 25496308.47) < 0.05 and abs(kulma["n"] - 6680637.81) < 0.05
    assert not any("vinoja kulmia" in v for v in tulos["varoitukset"])


def test_lepolantie79_nakyvyys_asemapisteilta():
    """Automaattinen viiva (lyhin reitti, koska talossa on ~5° vino kohta) on näkyvyyden mukaan
    kunnossa; mittausjärjestyksen väärässä viivassa näkölinjoja kulkee seinän läpi."""
    _, pisteet, _ = jasenna("lepolantie79.jxl")
    assert all(p["asema"]["nimi"] for p in sl.seinalinjan_pisteet(pisteet))
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert any("Näkyvyys asemapisteiltä täsmää" in v for v in tulos["varoitukset"])
    vaara = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    assert len(sl.nakolinjat_seinan_lapi(vaara["viivat"][0], vaara["pisteet"])) >= 20
    assert any("kulkee seinälinjan läpi" in v for v in vaara["varoitukset"])


def test_osuuskunnantie60_jarjestys_paatellaan():
    """9 piilokulmaa: järjestys päätellään seinälinjoista (ennen haku luovutti "vaihtoehtoja on
    liikaa" ja käytti lyhintä reittiä). Tulos on sama viiva kuin lyhimmällä reitillä."""
    _, pisteet, _ = jasenna("osuuskunnantie60.jxl")
    jakso = [j for j in sl.jaa_jaksoihin(pisteet)[0] if j["suljettu"]][0]
    jarjestetty, syy = sl.jarjesta_suorakulmaisesti(jakso["alku"], jakso["valit"], jakso["loppu"])
    assert syy is None
    tulos = sl.muodosta_seinalinjat(pisteet)
    assert not any("ei voitu päätellä" in v for v in tulos["varoitukset"]), tulos["varoitukset"]
    vanha = sl.muodosta_seinalinjat(pisteet, tapa="lyhin_vanha")
    rak, rak_vanha = ([v for v in t["viivat"] if v["suljettu"]][0] for t in (tulos, vanha))
    assert sorted((round(k["e"], 3), round(k["n"], 3)) for k in rak["karjet"]) == \
        sorted((round(k["e"], 3), round(k["n"], 3)) for k in rak_vanha["karjet"])


@pytest.mark.parametrize("nimi", sorted(os.listdir(DATA)) if os.path.isdir(DATA) else ["testi2.jxl"])
def test_mittausraportti_pdf(nimi, monkeypatch):
    # asemien pienoiskartat hakisivat taustan verkosta; ne eivät kuulu tähän testiin
    monkeypatch.setattr(jx, "piirra_asemapiste_kartta", lambda *a, **k: None)
    raportti, pisteet, hylatyt = jasenna(nimi)
    pdf = mr.tee_pdf(raportti, pisteet, hylatyt)
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000


def test_raportin_jasennys_kuten_trimblen_raportti():
    """Lepolantie 79: arvot Trimble Accessin mittausraportista (lepolantie79.pdf)."""
    raportti, pisteet, _ = jasenna("lepolantie79.jxl")
    assert raportti["tyon_tiedot"]["ohjelmaversio"] == "26.10" and raportti["tyon_tiedot"]["kulmayksikko"] == "Gons"
    assert raportti["koordinaatisto"] == {"jarjestelma": "ETRS_GK", "kaista": "ETRS_GK25", "datumi": "ETRS89",
                                          "geoidi": "FIN2005N00"}
    takymetri, = raportti["kalusto"]["takymetrit"]
    assert (takymetri["malli"], takymetri["sarjanumero"], takymetri["firmware"]) == ("S7 2 DR Plus", "37350311", "H2.14.7")
    gnss, = raportti["kalusto"]["gnss"]
    assert (gnss["vastaanotin"], gnss["sarjanumero"]) == ("R980", "6424740464")
    assert 2.0336 in gnss["antennikorkeudet"]
    asema = asemat(raportti)["1111111111111"]
    assert asema["ilmasto"]["paine"] == pytest.approx(1019.4)
    assert asema["korkeus"] == pytest.approx(30.334, abs=0.0005)
    assert asema["se_korkeus_m"] == pytest.approx(0.005, abs=0.0005)
    assert asema["orientointi"][0]["keskivirhe_deg"] / 0.9 == pytest.approx(0.0029, abs=0.00005)
    r = next(r for r in asema["residuaalit"] if r["liitospiste"] == "1000")
    assert (r["delta_n"], r["delta_e"], r["delta_h"]) == pytest.approx((-0.007, -0.012, -0.010), abs=0.0005)
    assert (r["d_ha_deg"] / 0.9, r["d_va_deg"] / 0.9) == pytest.approx((-0.0004, 0.0180), abs=0.00005)
    assert r["d_sd_m"] == pytest.approx(-0.015, abs=0.0005)
    h = piste(pisteet, "1111", "Kartoituspiste")["havainto"]
    assert (h["ha_deg"] / 0.9, h["va_deg"] / 0.9, h["sd_m"]) == pytest.approx((316.1045, 102.0897, 13.277), abs=0.0005)
    assert (h["tahyskorkeus_m"], h["prismavakio_m"]) == (2.0, 0.01)
    rtk = piste(pisteet, "1000", "Liitospiste (alkuperäinen RTK-mittaus)")
    assert (rtk["tarkkuus_h"], rtk["tarkkuus_v"]) == pytest.approx((0.014, 0.019), abs=0.0005)
    g = rtk["gnss"]
    assert g["ecef"] == pytest.approx((2878467.721, 1337611.865, 5513765.371), abs=0.0005)
    assert (g["antennikorkeus"], g["sijainteja"]) == (2.0336, 31)
    assert (g["gdop"], g["tukiaseman_ika_s"]) == pytest.approx((1.9, 0.8), abs=0.05)
    assert g["vcv"]["xx"] == pytest.approx(0.000135, abs=0.0000005)
    kallistukset = [piste(pisteet, n, "Liitospiste (alkuperäinen RTK-mittaus)")["gnss"]["kallistusetaisyys"]
                    for n in ("1000", "2000", "3000")]
    assert kallistukset == pytest.approx([0.020, 0.014, 0.007], abs=0.0005)
    assert (h["lukittu"], h["lukitustyyppi"]) == ("true", "AutoLock")
    assert piste(pisteet, "1", "Kartoituspiste")["havainto"]["lukittu"] == "false"
    asetukset = raportti["asetukset"]
    assert asetukset["projektio"]["itakorjaus"] == 25500000 and asetukset["projektio"]["keskimeridiaani_deg"] == 25
    assert asetukset["ellipsoidi"]["litistyneisyys_1_per"] == pytest.approx(298.257222, abs=0.000001)
    assert asetukset["korjaukset"]["etaisyydet"] == "GroundDistance"
    assert asetukset["kartoitusasetukset"] == [{"korkeusmaski_deg": 10, "pdop_maski": 6}]
    assert raportti["kalusto"]["ilmastokorjaukset"] == [{"kaarevuus": "true", "refraktio": "true", "refraktiovakio": 0.142}]
    assert asema["maarittely"] == "Vapaa asemapiste" and asema["mittakaava"] == 1
    tapahtumat = [t["tapahtuma"] for t in raportti["tapahtumat"]]
    assert tapahtumat[:3] == ["Roveri käynnistetty", "VRS-yhteys", "RTK alustettu"]
    assert tapahtumat.count("RTK ei alustettu") == 2 and "Asemapiste 999999999999" in tapahtumat


def test_raportin_sisalto():
    raportti, pisteet, hylatyt = jasenna("lepolantie79.jxl")
    sisalto = mr.raportin_sisalto(raportti, pisteet, hylatyt)
    assert dict(sisalto["perustiedot"])["Koordinaatisto"] == "ETRS_GK / ETRS_GK25 / ETRS89"
    assert len(sisalto["liitospisteet"]) == 1 + 6                       # otsikko + RTK-pisteet
    assert len(sisalto["mitatut"]) == 1 + raportti["maara"]["Kartoituspiste"]
    assert len(sisalto["asemat"]) == 7
    asema = next(a for a in sisalto["asemat"] if a["nimi"] == "1111111111111")
    assert asema["residuaalit"][1][:5] == ["1000", "-7.4", "-11.8", "13.9", "-10.3"]  # dHz = sqrt(dN² + dE²)
    assert asema["residuaalit"][1][5:7] == ["-0.0004", "0.0180"]          # gon
    # asema 999999999999: korkeusresiduaalit 92, 91 ja -239 mm (laatuluokka arvioi vain tasoa)
    assert any(t.startswith("Asema 999999999999") and "7901 -239 mm" in t for t in sisalto["tarkistukset"])
    raaka = next(g for g in sisalto["raakahavainnot"] if g["asema"] == "1111111111111")
    assert ["1111", "100", "Kartoituspiste", "316.1045", "102.0897", "13.277"] == raaka["rivit"][4][:6]
    assert raaka["rivit"][4][-1] == "Autolock" and raaka["rivit"][5][-1] == "ei"   # 1111 prismaan, 1 DR
    assert dict(sisalto["asetukset"])["Korjaukset"].startswith("etäisyydet: maasto")
    assert len(sisalto["rtk_lisatiedot"]) == len(sisalto["vcv"]) == 1 + 6
    assert sisalto["tapahtumat"][1] == ["07:39:44", "Roveri käynnistetty", ""]


def test_suurimman_vaakaresiduaalin_varoitus_nimeaa_liitospisteen():
    # pajalahti10: dN -15.6 mm ja dE -25.9 mm -> vaakaresiduaali 30.2 mm, vaikka kumpikaan ei ylitä 30 mm
    residuaalit = [{"liitospiste": "1000", "delta_n": 0.0033, "delta_e": -0.0109},
                   {"liitospiste": "2000", "delta_n": -0.0156, "delta_e": -0.0259},
                   {"liitospiste": "3000", "delta_n": -0.0079, "delta_e": 0.0014}]
    laatu = jx.laske_asemapisteen_laatu((0, 0), [(10, 0, None), (0, 10, None), (-10, -3, None)], None, residuaalit)
    assert laatu["suurin_residuaali_liitospiste"] == "2000"
    assert "Suurin vaakaresiduaali 30.2 mm (liitospiste 2000)" in laatu["varoitukset"]


def test_2x_saannon_ylitys_havaitaan():
    """Siirretään testi2:n kartoituspiste 7 kauas asemasta: ylitys pitää näkyä."""
    sisalto = lue("testi2.jxl").decode("utf-8")
    raportti, pisteet, _ = jx.jasenna_tyo(sisalto.encode(), "testi2.jxl")
    p7 = piste(pisteet, "7", "Kartoituspiste")
    vanha_n = f"{p7['n']}".rstrip("0")
    osuma = re.search(rf"<Name>7</Name>.*?<North>({re.escape(vanha_n)}\d*)</North>", sisalto, re.S)
    assert osuma
    muokattu = sisalto[:osuma.start(1)] + f"{p7['n'] + 2000:.4f}" + sisalto[osuma.end(1):]
    raportti, _, _ = jx.jasenna_tyo(muokattu.encode(), "testi2.jxl")
    assert [v["piste"] for v in raportti["varoitukset_2x"]] == ["7"]


def test_krd_kuten_kayttajan_tiedosto():
    """Lepolantie 79: käyttäjä teki krd:n itse (tests/data/lepolantie79.krd). Sovelluksen krd on
    tavulleen sama (välit, CRLF, liitospisteet RTK-mittauksesta, järjestys), kun pois jätetään
    pisteet, jotka käyttäjä poisti käsin: 1111 ja 15 (kaksi koodia "9 1")."""
    raportti, pisteet, hylatyt = jasenna("lepolantie79.jxl")
    rivit, varoitukset = jx.krd_pisteet(pisteet)
    with open(os.path.join(os.path.dirname(DATA), "lepolantie79.krd"), "rb") as f:
        odotettu = f.read()
    assert jx.kirjoita_krd([r for r in rivit if r[0] not in ("1111", "15")]) == odotettu
    assert ("15", "9") in [r[:2] for r in rivit]
    assert varoitukset == ["Koodista otettiin vain pistetyyppi (muut osat poistettu): 15"]
    nimet = [r[0] for r in rivit]
    assert len(nimet) == len(set(nimet)) and "2222" not in nimet and "1111111111111" not in nimet


def test_krd_apupisteet_ja_asemapisteet():
    _, pisteet, hylatyt = jasenna("lepolantie79.jxl")
    rivit, varoitukset = jx.krd_pisteet(pisteet, asemapisteet=True, apupisteet=True)
    apu = [r for r in rivit if r[0] == "2222"]
    assert len(apu) == 1 and apu[0][2] == pytest.approx(25495798.017, abs=0.0005)   # kartoitusmittaus
    assert sum(r[0] == "1111111111111" for r in rivit) == 1
    assert any("Yli 8 merkin nimet" in v and "1111111111111" in v for v in varoitukset)
    assert jx.kirjoita_krd(rivit).count(b"\r\n") == len(rivit)


def test_krd_liitospiste_ilman_rtk_mittausta():
    """Aleksanterinkatu: naula2 on korkeusliitos (käsin syötetty vain korkeus); krd:hen yksi rivi
    ensimmäisestä liitoshavainnosta. Merkintäpisteet ovat mukana."""
    _, pisteet, _ = jasenna("aleksanterinkatu 3.xml")
    rivit, _ = jx.krd_pisteet(pisteet)
    ensimmainen = next(p for p in pisteet if p["nimi"] == "naula2")
    assert [r[2:5] for r in rivit if r[0] == "naula2"] == [(ensimmainen["e"], ensimmainen["n"], ensimmainen["korkeus"])]
    merkinta = {p["nimi"] for p in pisteet if p["kategoria"] == "Merkintäpiste"}
    assert merkinta and merkinta <= {r[0] for r in rivit}


def test_muona2_ominaisuustiedot_ja_kirjastot():
    # Työhön ladattu kaksi koodikirjastoa; RAK-pisteillä on ominaisuustieto Rakennetyyppi = Sokkeli
    raportti, pisteet, _ = jasenna("muona2.jxl")
    assert raportti["koodikirjasto"] == "KMO-KOODIT.fxl (09:22), MAA-koodit_2026.fxl (09:23)"
    p3 = piste(pisteet, "3", "Kartoituspiste")
    assert p3["koodi"] == "RAK 100"
    assert p3["ominaisuudet"] == [{"kohde": "RAK", "nimi": "Rakennetyyppi", "arvo": "Sokkeli", "tyyppi": "Menu"}]
    assert sl.ominaisuudet_tekstina(p3) == "Rakennetyyppi: Sokkeli"
    assert piste(pisteet, "6", "Kartoituspiste")["ominaisuudet"] == []
    assert not raportti["seinalinja_kaytettavissa"]   # ei RAK 8 -pistettä


@pytest.mark.parametrize("koodi, odotettu", [
    ("9 1", "9"), ("100", "100"), (None, "0"), ("RAK 5", "5"), ("RAK 100", "100"), ("RAK 8 2", "8"),
    ("RAK", "100"), ("rak", "100"), ("RAK AV", "100"), ("LIP", "100"), ("SK", "9"), ("TUNTEMATON", "9"),
])
def test_krd_koodi_kirjainkoodeista(koodi, odotettu):
    assert jx.krd_koodi(koodi) == odotettu


def test_muona2_krd_ilman_kirjaimia():
    _, pisteet, _ = jasenna("muona2.jxl")
    assert jx.krd_kirjainkoodit(pisteet) == {"RAK": 3, "LIP": 3, "AV": 1, "JV": 2, "SV": 1, "SK": 4}
    rivit, varoitukset = jx.krd_pisteet(pisteet)
    koodit = {r[0]: r[1] for r in rivit}
    assert all(k.isdigit() for k in koodit.values())
    assert [koodit[n] for n in ("1000", "1", "3", "4", "6")] == ["100", "100", "100", "5", "9"]
    assert "Koodista otettiin vain pistetyyppi (muut osat poistettu): 3, 4" in varoitukset
    # muokattu taulukko ja tuntematon koodi
    rivit, varoitukset = jx.krd_pisteet(pisteet, koodimuunnos={"RAK": "5", "LIP": "100"})
    assert {r[0]: r[1] for r in rivit}["1"] == "5"
    assert "Kirjainkoodeille ei ole muunnosta, kirjoitettu 9: AV, JV, SK, SV" in varoitukset


def test_osuuskunnantie60_jatkuva_topo_on_gnss():
    """Jatkuvan topon (GpsContinuousTimePoint) pisteet ovat RTK-pisteitä laatutietoineen,
    eivät takymetripisteitä."""
    _, pisteet, _ = jasenna("osuuskunnantie60.jxl")
    jatkuvat = [p for p in pisteet if p["method"] == "GpsContinuousTimePoint"]
    assert len(jatkuvat) == 398
    assert {p["mittaustapa"] for p in jatkuvat} == {"RTK (jatkuva)"}
    assert all(p.get("pdop") is not None and p.get("satelliitteja") for p in jatkuvat)
    takymetri = [p for p in pisteet if p["kategoria"] == "Kartoituspiste" and p["method"] == "DirectReading"]
    assert takymetri and {p["mittaustapa"] for p in takymetri} == {"Takymetri"}
