"""Seinälinjan muokkauskartan selaintesti (Playwright + Chrome): kynällä (maastotabletti, esim. Trimble TSC7)
ja hiirellä. Kynä emuloidaan Chromen DevTools-protokollalla (Input.dispatchMouseEvent, pointerType "pen").

Ajetaan vain, kun Playwright ja Chrome ovat asennettuina (ei CI:ssä):
    pip install playwright && pytest tests/test_selain_muokkain.py
Kartta lataa Leafletin CDN:stä, joten testi tarvitsee verkkoyhteyden."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

HAKEMISTO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HAKEMISTO)
sys.path.insert(0, os.path.dirname(HAKEMISTO))
import selain_muokkain_sovellus as sov  # (vain vakiot; Streamlit-koodi ei aja ilman ajonaikaa)

import hae_kiintopisteet as hk

pytestmark = pytest.mark.selain


@pytest.fixture(scope="module")
def osoite():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        portti = s.getsockname()[1]
    prosessi = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", os.path.join(HAKEMISTO, "selain_muokkain_sovellus.py"),
         "--server.headless", "true", "--server.port", str(portti), "--browser.gatherUsageStats", "false"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{portti}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(url + "/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        else:
            pytest.skip("Streamlit ei käynnistynyt")
        yield url
    finally:
        prosessi.terminate()
        prosessi.wait(10)


@pytest.fixture
def sivu(osoite):
    with sync_api.sync_playwright() as p:
        try:
            selain = p.chromium.launch(channel="chrome")
        except sync_api.Error as e:
            pytest.skip(f"Chrome puuttuu: {e}")
        sivu = selain.new_page(viewport={"width": 1280, "height": 720}, has_touch=True)
        sivu.goto(osoite)
        sivu.wait_for_selector(".slm-kahva", timeout=30000)
        sivu.wait_for_timeout(500)
        yield sivu
        selain.close()


class Kyna:
    """Kynän napautus ja raahaus sivun koordinaateissa (CDP)."""

    def __init__(self, sivu):
        self.cdp = sivu.context.new_cdp_session(sivu)
        self.sivu = sivu

    def _tapahtuma(self, tyyppi, x, y, **lisa):
        self.cdp.send("Input.dispatchMouseEvent", {"type": tyyppi, "x": x, "y": y, "pointerType": "pen",
                                                   "button": "left", **lisa})

    def napauta(self, x, y):
        self._tapahtuma("mouseMoved", x, y, button="none")
        self._tapahtuma("mousePressed", x, y, buttons=1, clickCount=1)
        self._tapahtuma("mouseReleased", x, y, buttons=0, clickCount=1)
        self.sivu.wait_for_timeout(250)

    def raahaa(self, x0, y0, x1, y1, askelia=12):
        self._tapahtuma("mouseMoved", x0, y0, button="none")
        self._tapahtuma("mousePressed", x0, y0, buttons=1, clickCount=1)
        for i in range(1, askelia + 1):
            self._tapahtuma("mouseMoved", x0 + (x1 - x0) * i / askelia, y0 + (y1 - y0) * i / askelia, buttons=1)
            self.sivu.wait_for_timeout(20)
        self._tapahtuma("mouseReleased", x1, y1, buttons=0, clickCount=1)
        self.sivu.wait_for_timeout(250)


def kohta(sivu, de, dn):
    """Paikallisen pisteen (m talon kulmasta) sijainti sivulla pikseleinä."""
    lat, lon = hk._latlon_muunnin()(sov.E0 + de, sov.N0 + dn)
    return sivu.evaluate("""([lat, lon]) => {
        const el = document.querySelector(".slm-kartta");
        const p = el.parentElement.__slm.kartta.latLngToContainerPoint([lat, lon]);
        const r = el.getBoundingClientRect();
        return [r.left + p.x, r.top + p.y];
    }""", [lat, lon])


def tapahtumat(sivu, maara, aikaraja=15):
    """Odottaa, että tapahtumia on vähintään maara, ja palauttaa ne."""
    loppu = time.time() + aikaraja
    while True:
        teksti = sivu.locator('[data-testid="stCode"]').inner_text()
        lista = json.loads(teksti)
        if len(lista) >= maara or time.time() > loppu:
            return lista
        sivu.wait_for_timeout(200)


def nappi(sivu, kyna, avain):
    laatikko = sivu.locator(f'.slm-tyokalut [data-t="{avain}"], .slm-tyokalut [data-a="{avain}"]').bounding_box()
    assert laatikko["height"] >= 44 and laatikko["width"] >= 44    # kynällä ja sormella osuttava
    kyna.napauta(laatikko["x"] + laatikko["width"] / 2, laatikko["y"] + laatikko["height"] / 2)


def test_kynalla_raahaus_napsahtaa_pisteeseen(sivu):
    kyna = Kyna(sivu)
    x0, y0 = kohta(sivu, 20, 0)
    x1, y1 = kohta(sivu, 23, 4)
    kyna.raahaa(x0, y0, x1 + 15, y1 - 10)      # 18 px pisteen ohi: kynän napsahdussäde riittää
    t = tapahtumat(sivu, 1)
    assert t[-1] == {"tyyppi": "siirra", "viiva": "Viiva 1", "karki": 1, "piste": 4}


def test_kynan_napautus_viivaan_ei_muokkaa(sivu):
    kyna = Kyna(sivu)
    x, y = kohta(sivu, 10, 0)
    kyna.napauta(x, y + 6)
    sivu.wait_for_timeout(800)
    assert tapahtumat(sivu, 0, aikaraja=0) == []
    assert "Viiva 1: jana 1" in sivu.locator(".slm-ohje").inner_text()


def test_lisaa_karki(sivu):
    kyna = Kyna(sivu)
    nappi(sivu, kyna, "lisaa")
    x, y = kohta(sivu, 10, 0)
    kyna.napauta(x, y + 8)                        # ohi viivasta 8 px
    t = tapahtumat(sivu, 1)
    assert t[-1]["tyyppi"] == "lisaa" and t[-1]["viiva"] == "Viiva 1" and t[-1]["jalkeen"] == 0
    assert "lat" in t[-1]


def test_poista_vaatii_vahvistuksen(sivu):
    kyna = Kyna(sivu)
    nappi(sivu, kyna, "poista")
    x, y = kohta(sivu, 20, 10)
    kyna.napauta(x + 12, y + 8)                   # kärjen ohi 14 px
    sivu.wait_for_timeout(800)
    assert tapahtumat(sivu, 0, aikaraja=0) == []
    assert "kärki 3" in sivu.locator(".slm-ohje").inner_text()
    kyna.napauta(x, y)
    assert tapahtumat(sivu, 1)[-1] == {"tyyppi": "poista", "viiva": "Viiva 1", "karki": 2}
    # jana: valinta ja vahvistus napista (avoimen viivan yläsivu kärjestä 3 kärkeen 4)
    x, y = kohta(sivu, 10, 10)
    kyna.napauta(x, y - 6)
    nappi(sivu, kyna, "vahvista")
    assert tapahtumat(sivu, 2)[-1] == {"tyyppi": "poista_jana", "viiva": "Viiva 1", "jana": 2}


def test_suorakulmio_kolmella_napautuksella(sivu):
    kyna = Kyna(sivu)
    nappi(sivu, kyna, "suorakulmio")
    for de, dn in [(0, 0), (20, 0), (23, 4)]:
        x, y = kohta(sivu, de, dn)
        kyna.napauta(x + 5, y - 5)
    t = tapahtumat(sivu, 1)[-1]
    assert t["tyyppi"] == "suorakulmio" and len(t["kulmat"]) == 3
    assert {"piste": 4} in t["kulmat"]


def test_uusi_viiva_valmis_napista(sivu):
    kyna = Kyna(sivu)
    nappi(sivu, kyna, "piirra")
    for de, dn in [(0, 0), (23, 4), (10, 5)]:
        x, y = kohta(sivu, de, dn)
        kyna.napauta(x, y)
    nappi(sivu, kyna, "valmis")
    t = tapahtumat(sivu, 1)[-1]
    assert t["tyyppi"] == "uusi_viiva" and not t["suljettu"] and len(t["karjet"]) == 3
    assert t["karjet"][1] == {"piste": 4} and "lat" in t["karjet"][2]


def test_uusi_viiva_osoitin_nayttaa_napsahduksen(sivu):
    """Piirrossa hiiren (tai leijuvan kynän) alla oleva napsahduskohde näkyy ennen napautusta: vihreä rengas,
    kohteen nimi ja käsiosoitin, myös pelkässä pisteessä (P9 ei ole viivan kärki). Apuviiva edellisestä."""
    kyna = Kyna(sivu)
    nappi(sivu, kyna, "piirra")
    x, y = kohta(sivu, 23, 4)
    sivu.mouse.move(x + 8, y - 5)
    sivu.wait_for_timeout(200)
    vihje = sivu.locator(".slm-vihje")
    assert vihje.is_visible() and vihje.inner_text() == "P9"
    assert "slm-osuu" in sivu.locator(".slm-kartta").get_attribute("class")
    assert sivu.evaluate("getComputedStyle(document.querySelector('.slm-kartta')).cursor") == "pointer"
    x0, y0 = kohta(sivu, 10, 5)
    sivu.mouse.move(x0, y0)                       # tyhjä kohta: ei renkaata
    sivu.wait_for_timeout(200)
    assert not vihje.is_visible()
    assert "slm-osuu" not in sivu.locator(".slm-kartta").get_attribute("class")
    sivu.mouse.click(x, y)                        # ensimmäinen kärki P9:ään
    sivu.mouse.move(x0, y0)
    sivu.wait_for_timeout(200)
    apuviivoja = sivu.evaluate("""() => {
        const t = document.querySelector('.slm-kartta').parentElement.__slm;
        let n = 0; t.kartta.eachLayer((l) => { if (l.options && l.options.dashArray === "4 6") n++; });
        return n; }""")
    assert apuviivoja == 1


def test_hiiren_pikatoiminnot_toimivat(sivu):
    x, y = kohta(sivu, 20, 10)
    sivu.mouse.click(x, y, button="right")
    assert tapahtumat(sivu, 1)[-1] == {"tyyppi": "poista", "viiva": "Viiva 1", "karki": 2}
    x, y = kohta(sivu, 10, 0)
    sivu.mouse.click(x, y)
    t = tapahtumat(sivu, 2)[-1]
    assert t["tyyppi"] == "lisaa" and t["jalkeen"] == 0


def test_siirra_napautus_nayttaa_pituuden_ja_kulman(sivu):
    kyna = Kyna(sivu)
    x, y = kohta(sivu, 10, 0)
    kyna.napauta(x, y + 5)
    assert "pituus 20,000 m" in sivu.locator(".slm-ohje").inner_text()
    x, y = kohta(sivu, 20, 0)
    kyna.napauta(x, y)
    assert "kärki 2 (piste 2), kulma 90,0°" in sivu.locator(".slm-ohje").inner_text()


def test_mittaa_kahden_pisteen_etaisyys(sivu):
    kyna = Kyna(sivu)
    nappi(sivu, kyna, "mittaa")
    for de, dn in [(0, 0), (23, 4)]:
        x, y = kohta(sivu, de, dn)
        kyna.napauta(x + 4, y - 4)
    teksti = sivu.locator(".slm-ohje").inner_text()
    assert "23,345 m (ΔE 23,000, ΔN 4,000)" in teksti and "P9" in teksti
    assert tapahtumat(sivu, 0, aikaraja=0) == []


def test_sivumitta_kartalla(sivu):
    kyna = Kyna(sivu)
    nappi(sivu, kyna, "sivumitta")
    assert not sivu.locator(".slm-sivu").is_visible()
    for de, dn in [(0, 0), (20, 0)]:
        x, y = kohta(sivu, de, dn)
        kyna.napauta(x, y)
    sivu.locator('[data-i="a"]').fill("5")
    sivu.locator('[data-i="b"]').fill("2,5")            # pilkku käy desimaalierottimena
    assert "Uusi piste: E 25497135.000 N 6677367.500" in sivu.locator(".slm-ohje").inner_text()
    nappi(sivu, kyna, "lisaapiste")
    t = tapahtumat(sivu, 1)[-1]
    assert t == {"tyyppi": "sivumitta", "a": {"piste": 0}, "b": {"piste": 1}, "a_nimi": "1", "b_nimi": "2",
                 "a_mitta": 5, "b_mitta": 2.5}


def test_kumoa_nappi(sivu):
    kyna = Kyna(sivu)
    kumoa = sivu.locator('[data-a="kumoa"]')
    assert kumoa.is_disabled()                          # ei muokkauksia
    x, y = kohta(sivu, 20, 10)
    sivu.mouse.click(x, y, button="right")
    tapahtumat(sivu, 1)
    sivu.wait_for_timeout(500)
    assert kumoa.is_enabled()
    nappi(sivu, kyna, "kumoa")
    assert tapahtumat(sivu, 2)[-1] == {"tyyppi": "kumoa"}


def test_kartta_ei_hypi_tyokalua_vaihdettaessa(sivu):
    """Ohje ja toimintorivi vievät aina saman tilan: kartta pysyy paikallaan kynän alla."""
    kyna = Kyna(sivu)
    def ylareuna():
        return sivu.locator(".slm-kartta").bounding_box()["y"]

    alku = ylareuna()
    for avain in ("lisaa", "poista", "suorakulmio", "piirra", "jatka", "yhdista", "mittaa", "sivumitta"):
        nappi(sivu, kyna, avain)
        assert ylareuna() == alku, avain
    for de, dn in [(0, 0), (20, 0)]:                    # Sivumitan a- ja b-kentät näkyviin
        x, y = kohta(sivu, de, dn)
        kyna.napauta(x, y)
    assert sivu.locator(".slm-sivu").is_visible() and ylareuna() == alku


def test_paikallinen_esikatselu_vastaa_pythonia(sivu):
    """Kartta näyttää yksinkertaiset muokkaukset heti itse: tuloksen pitää olla sama kuin Pythonin
    (muokkaukseksi + seinalinja.sovella_muokkaukset), jonka palvelin lopulta lähettää."""
    import seinalinja as sl
    import seinalinjan_muokkain as slm

    def viiva(nimi, xy, suljettu):
        return {"nimi": nimi, "suljettu": suljettu, "numero": None, "avain": ("", (), 1),
                "karjet": [{"e": sov.E0 + x, "n": sov.N0 + y, "z": None, "nimi": f"{nimi}{i}", "laji": "mitattu",
                            "bulge": 0.0} for i, (x, y) in enumerate(xy)]}
    tulos = {"viivat": [viiva("A", [(0, 0), (20, 0), (20, 10), (0, 10)], False),
                        viiva("B", [(30, 0), (40, 0), (40, 8), (30, 8)], True)], "varoitukset": []}
    kohteet = [("P1", "RAK 5", sov.E0 + 23, sov.N0 + 4, None), ("P2", "RAK 5", sov.E0 + 5, sov.N0 + 5, None)]
    lat, lon = hk._latlon_muunnin()(sov.E0 + 10, sov.N0 + 12)
    tapahtumat = [
        {"tyyppi": "siirra", "viiva": "A", "karki": 1, "piste": 0},
        {"tyyppi": "siirra", "viiva": "B", "karki": 0, "kohde_viiva": "A", "kohde_karki": 3},
        {"tyyppi": "siirra", "viiva": "A", "karki": 2, "lat": lat, "lon": lon},
        {"tyyppi": "lisaa", "viiva": "A", "jalkeen": 0, "piste": 1},
        {"tyyppi": "lisaa", "viiva": "B", "jalkeen": 3, "lat": lat, "lon": lon},
        {"tyyppi": "poista", "viiva": "A", "karki": 2},
        {"tyyppi": "poista", "viiva": "B", "karki": 0},
        {"tyyppi": "poista_jana", "viiva": "A", "jana": 1},
        {"tyyppi": "poista_jana", "viiva": "A", "jana": 0},
        {"tyyppi": "poista_jana", "viiva": "A", "jana": 2},
        {"tyyppi": "poista_jana", "viiva": "B", "jana": 2},
        {"tyyppi": "uusi_viiva", "suljettu": True, "karjet": [{"piste": 0}, {"kohde_viiva": "B", "kohde_karki": 1},
                                                              {"lat": lat, "lon": lon}]},
        {"tyyppi": "uusi_viiva", "suljettu": False, "karjet": [{"piste": 1}, {"piste": 0}]},
    ]
    data = slm.kartan_data(tulos, kohteet)

    def vertailtava(viivat):
        return [(v["nimi"], v["suljettu"], [(round(k[0], 7), round(k[1], 7), k[2], k[3]) for k in v["karjet"]])
                for v in viivat]

    for t in tapahtumat:
        m = slm.muokkaukseksi(t, tulos, kohteet, uuden_nimi="Uusi viiva 1")
        odotettu = vertailtava(slm.kartan_data(sl.sovella_muokkaukset(tulos, [m]), kohteet)["viivat"])
        selain = sivu.evaluate("""([d, m]) => {
            const tila = document.querySelector('.slm-kartta').parentElement.__slm;
            return tila.paikallisesti(d, m, "Uusi viiva 1") ? d.viivat : null; }""", [data, t])
        assert selain is not None, t
        assert vertailtava(selain) == odotettu, t
