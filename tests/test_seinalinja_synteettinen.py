"""Synteettiset seinälinjatestit: tunnettu talo -> simuloitu maastomittaus ->
muodostettu seinälinja verrataan oikeaan muotoon (ks. tests/synteettiset.py).

A-D-testit ovat synteettisillä testeillä löydettyjä ja korjattuja tapauksia."""
import os
import sys

import pytest

HAKEMISTO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HAKEMISTO))
sys.path.insert(0, HAKEMISTO)
pytest.importorskip("shapely")
import seinalinja as sl
import synteettiset as st

TALOT = st.talot()
SALLITTU_M = 0.04   # 3 mm pistevirheellä mediaani ~7 mm, suurin havaittu ~3 cm (kaari)


@pytest.mark.parametrize("nimi", list(TALOT))
@pytest.mark.parametrize("tapa", ["mittaus", "lyhin"])
def test_generaattori_virheettomalla_datalla(nimi, tapa):
    """Ilman mittausvirhettä ja piilokulmia tuloksen pitää osua (tarkistaa myös generaattorin)."""
    talo = TALOT[nimi]
    rng = st.uusi_rng(1)
    pisteet, muunnos, _ = st.mittaa(talo, rng, piilotus=0, virhe_mm=0, liitospisteet=False, apupisteet=False)
    if tapa == "lyhin":
        pisteet = st.sekoitettu(pisteet, rng)
    tulos = sl.muodosta_seinalinjat(pisteet, tapa=tapa)
    assert st.poikkeama(tulos, talo, muunnos) < 0.002


@pytest.mark.parametrize("nimi", list(TALOT))
@pytest.mark.parametrize("tapa", ["mittaus", "lyhin"])
def test_piilokulmat_ja_mittausvirhe(nimi, tapa):
    """Satunnaiset piilokulmat, 3 mm mittausvirhe, kierto, liitospisteet ennen 8-pistettä ja
    9-koodiset apupisteet; data mittausjärjestyksessä kuten maastossa."""
    talo = TALOT[nimi]
    pielessa = []
    for siemen in range(40):
        rng = st.uusi_rng(siemen)
        pisteet, muunnos, piilossa = st.mittaa(talo, rng)
        tulos = sl.muodosta_seinalinjat(pisteet, tapa=tapa)
        p = st.poikkeama(tulos, talo, muunnos)
        if p >= SALLITTU_M:
            pielessa.append((siemen, sorted(piilossa), round(p, 3), tulos["varoitukset"]))
    assert not pielessa, pielessa


@pytest.mark.parametrize("nimi", ["suorakulmio", "vino", "L", "parveke", "erkkeri"])
def test_lyhin_reitti_sekoitetulla_datalla(nimi):
    talo = TALOT[nimi]
    for siemen in range(40):
        rng = st.uusi_rng(siemen)
        pisteet, muunnos, piilossa = st.mittaa(talo, rng, liitospisteet=False, apupisteet=False)
        tulos = sl.muodosta_seinalinjat(st.sekoitettu(pisteet, rng), tapa="lyhin")
        assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M, siemen


def test_apupisteet_9_eivat_vaikuta():
    talo = TALOT["L"]
    pisteet, _, _ = st.mittaa(talo, st.uusi_rng(3), liitospisteet=False, apupisteet=False)
    lisatty = pisteet[:4] + [dict(pisteet[2], nimi="apu", koodi="9", e=pisteet[2]["e"] + 1.3)] + pisteet[4:]
    a = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    b = sl.muodosta_seinalinjat(lisatty, tapa="mittaus")
    assert [(k["e"], k["n"]) for k in a["viivat"][0]["karjet"]] == [(k["e"], k["n"]) for k in b["viivat"][0]["karjet"]]


# --- Synteettisillä testeillä löydetyt ja korjatut tapaukset ------------------

def test_A_liitospisteet_ennen_8_pistetta_suljetussa_talossa():
    """Ennen 8-pistettä mitatut 100-koodiset liitospisteet eivät kuulu suljettuun viivaan."""
    talo = TALOT["suorakulmio"]
    pisteet, muunnos, _ = st.mittaa(talo, st.uusi_rng(5), piilotus=0, liitospisteet=True, apupisteet=False)
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M
    assert [p["nimi"] for p in tulos["pois_jatetyt"]] == ["L1", "L2", "L3"]


def test_A_liitospisteiden_kategoria_ei_kuulu_viivaan():
    """Liitos-, asema- ja RTK-pisteet jäävät pois koodista riippumatta, myös keskeltä viivaa."""
    talo = TALOT["L"]
    pisteet, muunnos, _ = st.mittaa(talo, st.uusi_rng(2), liitospisteet=False, apupisteet=False)
    liitos = dict(pisteet[3], nimi="L9", koodi="100", e=pisteet[3]["e"] + 30, kategoria="Liitospiste")
    tulos = sl.muodosta_seinalinjat(pisteet[:4] + [liitos] + pisteet[4:], tapa="mittaus")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M


def test_B_vain_8_piste_nakyy():
    talo = TALOT["suorakulmio"]
    pisteet, muunnos, piilossa = st.mittaa(talo, st.uusi_rng(4), liitospisteet=False, apupisteet=False)
    assert piilossa == {1, 2, 3}
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M
    assert [k["laji"] for k in tulos["viivat"][0]["karjet"]].count("laskettu") == 3


def test_C_lyhin_reitti_loytaa_lyhimman():
    """T-talo, 13 välipistettä: likimääräinen haku ei ennen löytänyt lyhintä reittiä."""
    talo = TALOT["T"]
    rng = st.uusi_rng(0)
    pisteet, muunnos, piilossa = st.mittaa(talo, rng, liitospisteet=False, apupisteet=False)
    assert piilossa == {3, 7}
    tulos = sl.muodosta_seinalinjat(st.sekoitettu(pisteet, rng), tapa="lyhin")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M


def test_C_ristiin_meneva_lyhin_reitti_vaihtuu_mittausjarjestykseen():
    """T-talo, jossa oikea kierros on pidempi kuin lyhin reitti: vanhalla menetelmällä
    lyhimmästä reitistä tuleva viiva menee ristiin, joten käytetään mittausjärjestystä."""
    talo = TALOT["T"]
    rng = st.uusi_rng(43)
    pisteet, muunnos, _ = st.mittaa(talo, rng, liitospisteet=False, apupisteet=False)
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="lyhin_vanha")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M
    assert any("käytettiin mittausjärjestystä" in v for v in tulos["varoitukset"])


def test_C_sekoitettu_data_varoittaa_ristiin_menosta():
    """Vanha menetelmä: jos pisteet eivät ole mittausjärjestyksessä, oikeaa kierrosta ei voi
    päätellä, mutta ristiin menevästä viivasta varoitetaan."""
    talo = TALOT["T"]
    rng = st.uusi_rng(43)
    pisteet, muunnos, _ = st.mittaa(talo, rng, liitospisteet=False, apupisteet=False)
    tulos = sl.muodosta_seinalinjat(st.sekoitettu(pisteet, rng), tapa="lyhin_vanha")
    assert any("menee ristiin" in v for v in tulos["varoitukset"])


def test_C_seinalinjoista_paatelty_sekoitetusta_datasta():
    """Sama T-talo: automaattinen järjestys päättelee kierroksen seinälinjoista (myös
    piilokulmat 100-pisteistä), joten mittausjärjestyksellä ei ole väliä."""
    talo = TALOT["T"]
    rng = st.uusi_rng(43)
    pisteet, muunnos, _ = st.mittaa(talo, rng, liitospisteet=False, apupisteet=False)
    tulos = sl.muodosta_seinalinjat(st.sekoitettu(pisteet, rng), tapa="lyhin")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M
    assert tulos["varoitukset"] == []


SUORAKULMAISET = {
    "suorakulmio": TALOT["suorakulmio"], "L": TALOT["L"], "T": TALOT["T"], "parveke": TALOT["parveke"],
    "syvennys": TALOT["syvennys"],
    "kapea T": st.Talo("kapea T", [(0, 0), (12, 0), (12, 8), (7, 8), (7, 14), (5, 14), (5, 8), (0, 8)]),
    "iso T": st.Talo("iso T", [(0, 0), (20, 0), (20, 5), (12, 5), (12, 17), (8, 17), (8, 5), (0, 5)]),
    "U": st.Talo("U", [(0, 0), (16, 0), (16, 12), (9.5, 12), (9.5, 4), (6.5, 4), (6.5, 12), (0, 12)]),
    "risti": st.Talo("risti", [(4, 0), (7, 0), (7, 4), (11, 4), (11, 7), (7, 7), (7, 11), (4, 11),
                               (4, 7), (0, 7), (0, 4), (4, 4)]),
}


@pytest.mark.parametrize("nimi", list(SUORAKULMAISET))
def test_suorakulmainen_piilokulmat_sekoitettuna(nimi):
    """Piilokulmat (100-pisteet), 3 mm virhe, satunnainen mittausjärjestys: järjestys
    päätellään seinälinjoista ilman varoituksia. (Vanhalla lyhimmällä reitillä esim. U
    onnistui vain noin joka viidennessä.)"""
    talo = SUORAKULMAISET[nimi]
    pielessa = []
    for siemen in range(30):
        rng = st.uusi_rng(1000 + siemen)
        pisteet, muunnos, piilossa = st.mittaa(talo, rng, liitospisteet=False, apupisteet=False)
        tulos = sl.muodosta_seinalinjat(st.sekoitettu(pisteet, rng), tapa="lyhin")
        if st.poikkeama(tulos, talo, muunnos) >= SALLITTU_M or tulos["varoitukset"]:
            pielessa.append((siemen, sorted(piilossa), tulos["varoitukset"]))
    assert not pielessa, pielessa


def test_D_monta_perakkaista_piilokulmaa():
    talo = TALOT["parveke"]
    pisteet, muunnos, piilossa = st.mittaa(talo, st.uusi_rng(45), liitospisteet=False, apupisteet=False)
    assert piilossa == {2, 3, 4, 5, 6, 7}
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="mittaus")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M


# Piilokulma, kun seinältä on vain yksi 100-piste: suoran kulman voi olettaa kummankin kulman
# viereen, ja tulkinnan ratkaisevat viereisten seinien suunnat. Seuraavan seinän suunta tulee
# B-kulman jälkeisestä kärjestä (ensimmäiseltä kierrokselta); pelkkä B:n jälkeinen 100-piste
# voi olla seuraavan piilokulman takana (Osuuskunnantie 60), mutta useimmiten se on oikealla
# seinällä. Nämä tapaukset menivät väärin, kun 100-pisteen suunta jätettiin kokonaan pois.
YKSI_100_TAPAUKSET = [
    ("suorakulmio", "lyhin", 0.5, 42), ("suorakulmio", "lyhin", 0.5, 55), ("suorakulmio", "lyhin", 0.5, 61),
    ("suorakulmio", "lyhin", 0.5, 72), ("suorakulmio", "lyhin", 0.7, 3), ("suorakulmio", "lyhin", 0.7, 74),
    ("suorakulmio", "lyhin", 0.7, 77), ("suorakulmio", "mittaus", 0.5, 42), ("suorakulmio", "mittaus", 0.5, 55),
    ("suorakulmio", "mittaus", 0.5, 61), ("suorakulmio", "mittaus", 0.5, 71), ("suorakulmio", "mittaus", 0.7, 3),
    ("suorakulmio", "mittaus", 0.7, 77), ("L", "lyhin", 0.5, 61), ("L", "mittaus", 0.5, 61),
    ("L", "mittaus", 0.7, 77), ("erkkeri", "lyhin", 0.5, 76),
]


def _yksi_100_mittaus(talo, tapa, piilotus, siemen):
    rng = st.uusi_rng(1000 * siemen + int(piilotus * 10) + 7)
    pisteet, muunnos, _ = st.mittaa(talo, rng, piilotus=piilotus, ohita_seinat={rng.randrange(len(talo.karjet))},
                                 yksi_100=0.6)
    return (st.sekoitettu(pisteet, rng) if tapa == "lyhin" else pisteet), muunnos


@pytest.mark.parametrize("nimi, tapa, piilotus, siemen", YKSI_100_TAPAUKSET)
def test_piilokulma_yhdella_linjapisteella_seuraava_100_piste(nimi, tapa, piilotus, siemen):
    talo = TALOT[nimi]
    pisteet, muunnos = _yksi_100_mittaus(talo, tapa, piilotus, siemen)
    tulos = sl.muodosta_seinalinjat(pisteet, tapa=tapa)
    assert st.poikkeama(tulos, talo, muunnos) < 0.05, tulos["varoitukset"]


@pytest.mark.parametrize("nimi", ["suorakulmio", "L", "T", "parveke", "vino", "erkkeri", "U", "H"])
def test_yhden_linjapisteen_seinat_laajasti(nimi):
    """Moni seinä yhdellä 100-pisteellä (240 mittausta talomuotoa kohden): oikeiden määrä ei
    saa laskea alle YKSI_100_ALARAJAT (kun B:n jälkeistä 100-pistettä ei käytetty lainkaan,
    suorakulmio 164, L 110, erkkeri 115). Osa ei ratkea lainkaan, koska yksi seinä jätetään
    kokonaan mittaamatta."""
    talo = TALOT[nimi]
    oikein = tapauksia = 0
    for piilotus in (0.3, 0.5, 0.7):
        for siemen in range(80):
            pisteet, muunnos = _yksi_100_mittaus(talo, "lyhin", piilotus, siemen)
            tulos = sl.muodosta_seinalinjat(pisteet)
            if tulos["viivat"]:
                tapauksia += 1
                oikein += st.poikkeama(tulos, talo, muunnos) < 0.05
    assert oikein >= YKSI_100_ALARAJAT[nimi], (oikein, tapauksia)


# Oikeat tulokset, kun yksinäisen 100-pisteen seinä päätellään suorasta kulmasta (ennen:
# suorakulmio 175, L 112, T 100, parveke 106, U 74, H 65; vino ja erkkeri eivät ole suorakulmaisia)
YKSI_100_ALARAJAT = {"suorakulmio": 184, "L": 155, "T": 154, "parveke": 159, "vino": 84, "erkkeri": 116,
                     "U": 128, "H": 150}


# Seinältä vain yksi 100-piste, eikä sillä ole linjakumppania: seinän suunta on suora kulma
# viereisiin seiniin, ja piilokulmat ovat linjojen leikkauspisteitä. Ennen päättely hylättiin
# ("100-piste ei ole samalla seinälinjalla...") ja lyhin reitti meni metrejä pieleen.
@pytest.mark.parametrize("nimi, siemen, kuvaus", [
    ("L", 7, "yksinäinen seinä kahden yhdensuuntaisen välissä (pisteet 8 ja 13)"),
    ("suorakulmio", 24, "kaksi peräkkäistä yksinäistä seinää; piste osuu sattumalta toisen seinän linjalle"),
])
def test_yksinainen_100_piste_seinalla(nimi, siemen, kuvaus):
    talo = TALOT[nimi]
    pisteet, muunnos, _ = st.mittaa(talo, st.uusi_rng(1000 * siemen + 7), piilotus=0.6, yksi_100=0.6)
    jakso = sl.jaa_jaksoihin(pisteet)[0][0]
    jarjestetty, syy = sl.jarjesta_suorakulmaisesti(jakso["alku"], jakso["valit"], jakso["loppu"])
    assert syy is None, (kuvaus, syy)
    tulos = sl.muodosta_seinalinjat(pisteet, tapa="lyhin")
    assert st.poikkeama(tulos, talo, muunnos) < SALLITTU_M, (kuvaus, tulos["varoitukset"])
    assert not any("Tarkista viiva" in v for v in tulos["varoitukset"]), tulos["varoitukset"]
