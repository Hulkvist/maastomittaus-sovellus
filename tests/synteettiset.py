"""Synteettiset talot ja niiden "maastomittaus" seinälinjan testaamiseen.

Talo on suljettu monikulmio paikallisissa koordinaateissa (metrejä). Osa sivuista voi
olla kaaria (nuoli = kaaren keskikohdan etäisyys jänteestä, + vasemmalle). mittaa()
tuottaa pisteet koodeineen niin kuin ne maastossa mitattaisiin:

    8 = ensimmäinen kulma (viiva alkaa ja päättyy tähän), 5 = näkyvä kulma,
    100 = kaksi pistettä jokaiselta seinältä, jonka toinen pää on piilossa,
    4 = kaaripisteet README:n taulukon mukaan.

Lisäksi mittausvirhe, kierto, skaalaus ja muut kuin seinälinjan pisteet (100-koodiset
liitospisteet ennen ensimmäistä 8-pistettä, 9-koodiset apupisteet viivan keskellä)."""
import math
import random
from dataclasses import dataclass, field

from shapely.geometry import LineString

E0, N0 = 25496000.0, 6672000.0


@dataclass
class Talo:
    nimi: str
    karjet: list                               # [(x, y)], vastapäivään
    kaaret: dict = field(default_factory=dict)  # {sivun indeksi: nuoli}
    piilo_pakko: set = field(default_factory=set)  # kärjet, joita ei voi mitata (pyöristys)


def kaaren_piste(a, b, nuoli, t):
    """Piste kaarella a -> b parametrilla t (0 = a, 1 = b). Kaaren keskikohta on
    jänteen keskipisteestä nuolen verran vasemmalla (negatiivinen nuoli = oikealla)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    janne = math.hypot(dx, dy)
    huippu = ((a[0] + b[0]) / 2 - dy / janne * nuoli, (a[1] + b[1]) / 2 + dx / janne * nuoli)
    # ympyrä kolmen pisteen kautta
    ax, ay = a
    bx, by = huippu
    cx, cy = b
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    ux = ((ax ** 2 + ay ** 2) * (by - cy) + (bx ** 2 + by ** 2) * (cy - ay) + (cx ** 2 + cy ** 2) * (ay - by)) / d
    uy = ((ax ** 2 + ay ** 2) * (cx - bx) + (bx ** 2 + by ** 2) * (ax - cx) + (cx ** 2 + cy ** 2) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    a0 = math.atan2(ay - uy, ax - ux)
    am = math.atan2(by - uy, bx - ux)
    a1 = math.atan2(cy - uy, cx - ux)
    vastapaivaan = (a1 - a0) % (2 * math.pi)
    kierto = vastapaivaan if (am - a0) % (2 * math.pi) <= vastapaivaan else vastapaivaan - 2 * math.pi
    kulma = a0 + kierto * t
    return ux + r * math.cos(kulma), uy + r * math.sin(kulma)


def totuus(talo, askel=0.05):
    """Talon reunaviiva tiheänä suljettuna pisteketjuna (paikalliset koordinaatit)."""
    pts = []
    n = len(talo.karjet)
    for i in range(n):
        a, b = talo.karjet[i], talo.karjet[(i + 1) % n]
        if i in talo.kaaret:
            maara = max(8, int(math.hypot(b[0] - a[0], b[1] - a[1]) / askel))
            pts.extend(kaaren_piste(a, b, talo.kaaret[i], k / maara) for k in range(maara))
        else:
            pts.append(a)
    pts.append(pts[0])
    return pts


def pyoristetty_kulma(karjet, indeksi, sade):
    """Korvaa kärjen kahdella sivuamispisteellä ja niiden välisellä kaarella."""
    n = len(karjet)
    c = karjet[indeksi]
    edel, seur = karjet[indeksi - 1], karjet[(indeksi + 1) % n]

    def yksikko(p):
        d = math.hypot(p[0] - c[0], p[1] - c[1])
        return (p[0] - c[0]) / d, (p[1] - c[1]) / d

    u1, u2 = yksikko(edel), yksikko(seur)
    kulma = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1])))
    d = sade / math.tan(kulma / 2)
    t1 = (c[0] + u1[0] * d, c[1] + u1[1] * d)
    t2 = (c[0] + u2[0] * d, c[1] + u2[1] * d)
    janne = math.hypot(t2[0] - t1[0], t2[1] - t1[1])
    nuoli = sade - math.sqrt(sade ** 2 - janne ** 2 / 4)
    # kupera kulma vastapäivään kiertävässä monikulmiossa -> kaari pullistuu oikealle
    uudet = karjet[:indeksi] + [t1, t2] + karjet[indeksi + 1:]
    return uudet, indeksi, -nuoli


def talot():
    """Testattavat talomuodot."""
    t = {}
    t["suorakulmio"] = Talo("suorakulmio", [(0, 0), (12, 0), (12, 8), (0, 8)])
    t["L"] = Talo("L", [(0, 0), (14, 0), (14, 6), (6, 6), (6, 12), (0, 12)])
    t["T"] = Talo("T", [(0, 0), (18, 0), (18, 6), (12, 6), (12, 14), (6, 14), (6, 6), (0, 6)])
    t["parveke"] = Talo("parveke", [(0, 0), (16, 0), (16, 10), (11, 10), (11, 12), (5, 12), (5, 10), (0, 10)])
    t["syvennys"] = Talo("syvennys", [(0, 0), (16, 0), (16, 10), (11, 10), (11, 8), (5, 8), (5, 10), (0, 10)])
    t["vino"] = Talo("vino", [(0, 0), (12, 0), (15, 7), (2, 9)])
    t["erkkeri"] = Talo("erkkeri", [(0, 0), (4, 0), (10, 0), (16, 0), (16, 10), (0, 10)], kaaret={1: -2.0})
    k, i, nuoli = pyoristetty_kulma([(0, 0), (12, 0), (12, 8), (0, 8)], 2, 2.0)
    t["pyoristys"] = Talo("pyoristys", k, kaaret={i: nuoli}, piilo_pakko={i, i + 1})
    t["U"] = Talo("U", [(0, 0), (18, 0), (18, 12), (13, 12), (13, 5), (5, 5), (5, 12), (0, 12)])
    t["Z"] = Talo("Z", [(0, 0), (10, 0), (10, 5), (16, 5), (16, 12), (6, 12), (6, 7), (0, 7)])
    t["H"] = Talo("H", [(0, 0), (5, 0), (5, 4), (11, 4), (11, 0), (16, 0), (16, 12), (11, 12), (11, 8), (5, 8),
                        (5, 12), (0, 12)])
    t["porras"] = Talo("porras", [(0, 0), (16, 0), (16, 4), (12, 4), (12, 8), (8, 8), (8, 12), (0, 12)])
    t["kaksi_syvennysta"] = Talo("kaksi_syvennysta", [(0, 0), (20, 0), (20, 10), (16, 10), (16, 8), (12, 8),
                                                      (12, 10), (8, 10), (8, 8), (4, 8), (4, 10), (0, 10)])
    return t


def _kaaripisteiden_maara(talo, i, piilossa):
    n = len(talo.karjet)
    a_piilo, b_piilo = i in piilossa, (i + 1) % n in piilossa
    if not a_piilo and not b_piilo:
        return 2
    if a_piilo != b_piilo:
        return 2
    # molemmat piilossa: sama seinälinja (erkkeri) vaatii 3, eri seinät (pyöristys) 1
    edel = talo.karjet[i - 1]
    a, b = talo.karjet[i], talo.karjet[(i + 1) % n]
    seur = talo.karjet[(i + 2) % n]
    ristitulo = (a[0] - edel[0]) * (seur[1] - b[1]) - (a[1] - edel[1]) * (seur[0] - b[0])
    return 3 if abs(ristitulo) < 1e-6 else 1


def mittaa(talo, rng, piilotus=0.4, virhe_mm=3.0, kierto=None, skaala=1.0,
           liitospisteet=True, apupisteet=True, ohita_seinat=(), yksi_100=0.0):
    """Palauttaa (pisteet mittausjärjestyksessä, muunnos, piilossa olevat kärjet).
    muunnos(x, y) -> (e, n) vie paikalliset koordinaatit GK25:een. yksi_100 = todennäköisyys,
    jolla seinälle mitataan vain yksi 100-piste (kuten Osuuskunnantie 60:ssä)."""
    n = len(talo.karjet)
    kierto = rng.uniform(0, 2 * math.pi) if kierto is None else kierto
    c, s = math.cos(kierto), math.sin(kierto)

    def muunnos(x, y):
        x, y = x * skaala, y * skaala
        return E0 + x * c - y * s, N0 + x * s + y * c

    piilossa = set(talo.piilo_pakko)
    for i in range(1, n):
        if rng.random() < piilotus:
            piilossa.add(i)

    pisteet = []
    nro = [0]

    def lisaa(x, y, koodi, nimi=None):
        e, n_ = muunnos(x, y)
        nro[0] += 1
        sigma = virhe_mm / 1000
        de = max(-3 * sigma, min(3 * sigma, rng.gauss(0, sigma))) if sigma else 0.0
        dn = max(-3 * sigma, min(3 * sigma, rng.gauss(0, sigma))) if sigma else 0.0
        pisteet.append({"nimi": nimi or str(nro[0]), "koodi": str(koodi), "e": e + de, "n": n_ + dn,
                        "korkeus": 10.0, "kategoria": "Kartoituspiste"})

    if liitospisteet:
        for k in range(3):
            kulma = rng.uniform(0, 2 * math.pi)
            lisaa(8 + 50 * math.cos(kulma), 5 + 50 * math.sin(kulma), 100, nimi=f"L{k + 1}")

    for i in range(n):
        a, b = talo.karjet[i], talo.karjet[(i + 1) % n]
        if i not in piilossa:
            lisaa(*a, 8 if i == 0 else 5)
        if i in talo.kaaret:
            m = _kaaripisteiden_maara(talo, i, piilossa)
            for k in range(m):
                lisaa(*kaaren_piste(a, b, talo.kaaret[i], (k + 1) / (m + 1)), 4)
        elif (i in piilossa or (i + 1) % n in piilossa) and i not in ohita_seinat:
            if yksi_100 and rng.random() < yksi_100:
                ts = (rng.uniform(0.3, 0.7),)
            else:
                ts = (rng.uniform(0.2, 0.4), rng.uniform(0.6, 0.8))
            for t in ts:
                lisaa(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 100)
        if apupisteet and rng.random() < 0.3:
            lisaa(a[0] + rng.uniform(-3, 3), a[1] + rng.uniform(-3, 3), 9, nimi=f"apu{i}")
    return pisteet, muunnos, piilossa


def lidar_seinat(talo, muunnos, rng, kohina_m=0.01, seinat=None, katko=False):
    """Simuloitu LiDAR-keilaus (esim. lidarpipen seinälinja-DXF): talon suorat sivut janoina
    GK25:ssä. Janan päät poikkeavat sivun suorasta kohinan verran (suunta siis hieman
    vino), päät lyhenevät 0-30 cm (nurkka katveessa). seinat = sivujen indeksit (None =
    kaikki suorat sivut). katko = sivu pätkitään kahtia ovi- tai kasvillisuusaukon kohdalta."""
    n = len(talo.karjet)
    janat = []
    for i in range(n) if seinat is None else seinat:
        if i in talo.kaaret:
            continue
        a, b = talo.karjet[i], talo.karjet[(i + 1) % n]
        pituus = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / pituus, (b[1] - a[1]) / pituus
        valit = [(rng.uniform(0, 0.3), pituus - rng.uniform(0, 0.3))]
        if katko and pituus > 3:
            keski = pituus * rng.uniform(0.4, 0.6)
            valit = [(valit[0][0], keski - 0.5), (keski + 0.5, valit[0][1])]
        for t0, t1 in valit:
            paat = []
            for t in (t0, t1):
                siirto = rng.gauss(0, kohina_m)
                paat.append(muunnos(a[0] + ux * t - uy * siirto, a[1] + uy * t + ux * siirto))
            janat.append(tuple(paat))
    return janat


def poikkeama(tulos, talo, muunnos):
    """Hausdorff-etäisyys (m) muodostetun seinälinjan ja oikean reunan välillä."""
    from seinalinja import viivan_pisteet

    viiva = LineString(viivan_pisteet(tulos["viivat"][0]))
    oikea = LineString([muunnos(x, y) for x, y in totuus(talo)])
    return viiva.hausdorff_distance(oikea)


def sekoitettu(pisteet, rng):
    """Seinälinjan pisteet satunnaisessa järjestyksessä; 8-piste ja sitä ennen mitatut
    pysyvät alussa (ne määräävät jakson)."""
    i8 = next(i for i, p in enumerate(pisteet) if p["koodi"] == "8")
    alku, loput = pisteet[:i8 + 1], pisteet[i8 + 1:]
    loput = loput[:]
    rng.shuffle(loput)
    return alku + loput


def uusi_rng(siemen):
    return random.Random(siemen)
