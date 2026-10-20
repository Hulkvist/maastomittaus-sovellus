"""
seinalinja.py -- Seinälinjan muodostus JobXML-pisteistä ja vienti DXF-muotoon
------------------------------------------------------------------------------
Koordinaatisto: ETRS-GK25 (EPSG:3879). DXF:ssä X = itä (E), Y = pohjoinen (N).

Pistekoodit (JobXML:n Code-kenttä):
    8   = viivan alku/loppu (on myös kulma)
    5   = talon kulma
    100 = piste seinälinjalla, EI kulma (esim. ränni kulman edessä)
    4   = piste kaarella (esim. kaareva erkkeri tai pyöristetty kulma)
    Muut koodit (esim. apupisteet) eivät vaikuta viivaan.
Tyyppinumeron edessä voi olla kohdekoodi (RAK 8, RAK 5, KATOS 100): eri kohdekoodit ja
niiden valikosta valitut ominaisuustiedot (esim. Rakennetyyppi = Sokkeli) ovat eri viivoja.
Pelkkä kohdekoodi ilman tyyppinumeroa (RAK) on tavallinen piste, ei viivan osa.

Viivan muodostus:
  - Yksi 8-piste: koko talo on yksi SULJETTU viiva, joka alkaa ja päättyy
    tähän 8-pisteeseen. Ennen 8-pistettä mitatut pisteet eivät kuulu viivaan.
  - Kaksi 8-pistettä: AVOIN viiva ensimmäisestä toiseen.
  - Kolme tai useampi: jatkuva viiva 8a -> 8b -> 8c ... Kunkin jakson
    pisteet ovat ne, jotka on mitattu kahden peräkkäisen 8-pisteen välissä.
  - Jakson sisällä pisteet järjestetään automaattisesti tai mittausjärjestyksessä.
    Automaattinen: järjestys päätellään seinälinjoista (suorakulmainen talo: jokaisella
    kulmalla yksi seinä pääsuunnassa ja yksi sitä vastaan kohtisuoraan, 100-pisteet
    seinillä, piilokulmat linjojen leikkauspisteinä). Jos se ei onnistu (vinot seinät,
    puuttuva kulma, 4-pisteitä), järjestys otetaan kantakartan talosta, jos kantakartta on
    annettu (Helsinki), ja viimeisenä käytetään lyhintä reittiä, joka käy jokaisessa
    pisteessä. Kantakartasta myös varoitetaan poikkeamista ja näytetään riskikohdat.

100-pisteet: kahden kulmapisteen (5/8) välissä olevat 100-pisteet eivät ole
kärkiä. Ne jaetaan peräkkäisiin seinälinjoihin, ja piilossa olevat kulmat
lasketaan linjojen leikkauspisteinä:
  - 5 -> 100 -> 100 -> 5: kulma A:n ja B:n puoleisen seinälinjan leikkauksessa,
  - parveke tai syvennys (esim. kolme 100-paria): kulmat jokaisen linjaparin
    leikkauksessa; seinä jatkuu ulokkeen molemmin puolin suoralla A-B,
  - seinälinja, jolta on vain kulmapiste: oletetaan suora kulma (90 astetta)
    ja annetaan varoitus.

LiDAR-seinät (valinnainen, ks. muodosta_seinalinjat): jos piilokulman toiselta seinältä
ei ole linjapistettä, seinän suunta otetaan kulmapisteen kautta kulkevasta LiDAR-seinästä
suoran kulman oletuksen sijaan.

4-pisteet: kaari kaaripisteiden kautta. Jos kaaren päät ovat kulmapisteitä,
yksi kaaripiste riittää. Jos pää on piilossa (vieressä 100-linja), pää lasketaan
ympyrän ja seinälinjan leikkauksena; tarvittavat kaaripisteet, ks. README.
DXF:ssä kaari on aito kaari (LWPOLYLINE + bulge).

Vaatimukset: pip install ezdxf matplotlib (vain kuva ja DXF; muodostus toimii ilman lisäkirjastoja,
esim. QGIS:n Python-ympäristössä)
"""

import math
from itertools import combinations

KOODI_ALKU_LOPPU = 8
KOODI_KULMA = 5
KOODI_LINJA = 100
KOODI_KAARI = 4
SEINALINJAKOODIT = {KOODI_ALKU_LOPPU, KOODI_KULMA, KOODI_LINJA, KOODI_KAARI}

LINJA_TOLERANSSI_M = 0.05     # pisteen suurin etäisyys suorasta, jotta se on "samalla linjalla"
YHDENSUUNTAISUUS_RAJA_ASTE = 5.0
MAX_JATKE_M = 20.0            # laskettu kulma kauempana lähimmästä pisteestä -> varoitus
TARKKA_JARJESTYS_MAX = 12     # välipisteitä enintään tämän verran -> tarkka lyhin reitti
JAKO_MAX_PISTEET = 60         # seinälinjoihin jaettavan ketjun enimmäispituus
JAKO_MAX_KOKEILUT = 200000    # läpikäytävien kelvollisten jakojen enimmäismäärä
# Järjestyksen päättely: kaksi pistettä on samalla seinälinjalla, jos sivuttaisero on enintään
# MIN + matka * tan(JARJESTYS_KULMA_ASTE), kuitenkin enintään MAX. MIN kattaa mittausvirheen,
# kulmaosa talon pienen vinouden; lähekkäiset pisteet erotetaan tarkasti, jotta pienet portaat
# erottuvat.
JARJESTYS_MIN_TOLERANSSI_M = 0.05
JARJESTYS_MAX_TOLERANSSI_M = 0.25
JARJESTYS_KULMA_ASTE = 1.5
JARJESTYS_TARKISTUS_M = 0.5    # muodosta_karjet:n kärjen suurin etäisyys päätellystä kärjestä
JARJESTYS_MAX_PIILOKULMAT = 6  # piilokulmia yhdellä seinälinjalla enintään
JARJESTYS_MAX_KOKEILUT = 200000  # järjestyksen päättelyn työmäärän yläraja (piilokulmavalintojen kokeilut)
KANTAKARTTA_RAJA_M = 1.0      # mitatun pisteen suurin etäisyys kantakartan talon reunasta
KANTAKARTTA_VINO_ASTE = 5.0   # kantakartan talon kulma poikkeaa suorasta -> riski
KANTAKARTTA_MIN_ALA_M2 = 2.0  # pienemmät kartan kohteet (esim. pylväs talon vieressä) eivät ole taloja
# LiDAR-seinät (janat esim. lidarpipen seinälinja-DXF:stä, EPSG:3879): piilokulman seinän suunta
LIDAR_MIN_PITUUS_M = 0.3      # lyhyemmät janat ohitetaan
LIDAR_PISTE_RAJA_M = 0.08     # kulmapisteen suurin etäisyys LiDAR-seinän suorasta
LIDAR_PAA_RAJA_M = 0.5        # kulmapiste saa olla enintään näin kaukana janan päästä
LIDAR_MIN_KULMA_ASTE = 20.0   # LiDAR-seinän ja tunnetun seinän pienin kulma (ei saman suuntainen)
LIDAR_PIILO_RAJA_M = 1.5      # LiDAR-janan pää enintään näin kaukana lasketusta piilokulmasta
LIDAR_SUORA_RAJA_ASTE = 1.0   # pienempi poikkeama suorasta kulmasta = LiDAR vahvistaa suoran kulman
LIDAR_SUUNTAINEN_ASTE = 5.0   # seinä on LiDAR-seinän suuntainen, jos kulma on tätä pienempi
LIDAR_TUKEMATON_KULMA = 20.0  # jaon pisteytys: laskettu kulma kaukana kaikista LiDAR-seinistä
LIDAR_PEITTO_RAJA_M = 0.3     # poikkeamavertailu: kauempana olevalla kohdalla ei ole LiDAR-seinää
LIDAR_PEITTO_KULMA_ASTE = 20.0  # poikkeamavertailu: vain seinälinjan suuntaiset LiDAR-seinät
# Poikkeaman luokat kartoille (sovellus ja QGIS-lisäosa): (yläraja m, luokka, väri)
POIKKEAMALUOKAT = [(0.05, "alle 5 cm", "#2ca02c"), (0.15, "5–15 cm", "#ffbf00"), (math.inf, "yli 15 cm", "#d62728")]
LIDAR_YHDISTA_ASTE = 10.0     # ääriviiva: saman seinän pätkät (suunta ja päiden sivuttaisero LIDAR_PISTE_RAJA_M)
LIDAR_YHDISTA_VALI_M = 5.0    # ääriviiva: saman seinän pätkien suurin aukko (ovi, kasvillisuus)


# ---------------------------------------------------------------------------
# Pisteiden tunnistus ja jako jaksoihin
# ---------------------------------------------------------------------------

def _kokonaisluku(teksti):
    try:
        return int(teksti)
    except (TypeError, ValueError):
        return None


def _koodin_osat(koodi):
    """(kohdekoodi, tyyppinumero, viivan numero) Code-kentästä:
    "5" -> (None, 5, 1), "5 2" -> (None, 5, 2), "5 KULMA" -> (None, 5, 1),
    "RAK 100" -> ("RAK", 100, 1), "RAK 8 2" -> ("RAK", 8, 2), "RAK" -> ("RAK", None, 1)."""
    osat = str(koodi).split() if koodi is not None else []
    if not osat:
        return None, None, 1
    kohde = None if _kokonaisluku(osat[0]) is not None else osat[0]
    if kohde:
        osat = osat[1:]
    tyyppi = _kokonaisluku(osat[0]) if osat else None
    numero = _kokonaisluku(osat[1]) if tyyppi is not None and len(osat) >= 2 else None
    return kohde, tyyppi, numero or 1


def koodi_numeroksi(koodi):
    """Pistetyyppi koodista ("5", "5 KULMA", "RAK 5" -> 5), muuten None."""
    return _koodin_osat(koodi)[1]


def viivan_numero(koodi):
    """Viivan numero tyyppinumeron jälkeen ("5 2", "RAK 5 2" -> 2). Ilman numeroa (tai jos
    osa ei ole luku, esim. "5 KULMA") viiva 1. Näin useamman talon voi mitata samaan tiedostoon."""
    return _koodin_osat(koodi)[2]


def viivan_avain(p):
    """Viiva, johon piste kuuluu: (kohdekoodi, valikosta valitut ominaisuustiedot, numero).
    Esim. RAK 8 + Rakennetyyppi = Sokkeli -> ("RAK", ("Sokkeli",), 1); pelkkä "8" -> ("", (), 1)."""
    kohde, _, numero = _koodin_osat(p.get("koodi"))
    valinnat = tuple(o["arvo"] for o in p.get("ominaisuudet") or []
                     if kohde and o.get("kohde") == kohde and o.get("tyyppi") == "Menu" and o.get("arvo"))
    return kohde or "", valinnat, numero


def viivan_nimi(avain):
    """Viivan nimi näytölle ja varoituksiin: ("", (), 2) -> "Viiva 2",
    ("RAK", ("Sokkeli",), 1) -> "RAK Sokkeli", ("RAK", ("Sokkeli",), 2) -> "RAK Sokkeli 2"."""
    kohde, valinnat, numero = avain
    if not kohde:
        return f"Viiva {numero}"
    return " ".join([kohde, *valinnat] + ([str(numero)] if numero != 1 else []))


def ominaisuudet_tekstina(p):
    """Pisteen ominaisuustiedot luettavana tekstinä ("Rakennetyyppi: Sokkeli"), tai ""."""
    return ", ".join(f"{o['nimi']}: {o['arvo']}" for o in p.get("ominaisuudet") or [] if o.get("arvo"))


# Mittauksen apuvälineet eivät ole seinäpisteitä, vaikka niillä olisi seinälinjan koodi
# (koodi 100 on käytännössä oletuskoodi, joten liitospisteillä on usein sama koodi).
EI_SEINALINJAAN = {"Asemapiste", "Liitospiste", "Korkeusliitos", "Liitospiste (alkuperäinen RTK-mittaus)"}


def _seinalinjapisteet(pisteet):
    return [
        p for p in pisteet
        if koodi_numeroksi(p.get("koodi")) in SEINALINJAKOODIT
        and p.get("kategoria") not in EI_SEINALINJAAN
        and p.get("e") is not None and p.get("n") is not None
    ]


def seinalinjan_pisteet(pisteet):
    """Seinälinjaan kuuluvat pisteet (koodit 8/5/100/4, ei mittauksen apuvälineitä)."""
    return _seinalinjapisteet(pisteet)


def on_seinalinjapisteita(pisteet):
    """Seinälinja muodostetaan vain, jos tiedostossa on vähintään yksi 8-piste."""
    return any(koodi_numeroksi(p.get("koodi")) == KOODI_ALKU_LOPPU for p in _seinalinjapisteet(pisteet))


def _viivan_jaksot(validit, avain):
    """Yhden viivan jaksot ja pois jätetyt pisteet (pisteet mittausjärjestyksessä)."""
    idx8 = [i for i, p in enumerate(validit) if koodi_numeroksi(p.get("koodi")) == KOODI_ALKU_LOPPU]
    if not idx8:
        return [], list(validit)
    if len(idx8) == 1:
        # Viiva alkaa 8-pisteestä: ennen sitä mitatut pisteet eivät kuulu siihen
        alku = validit[idx8[0]]
        return ([{"alku": alku, "valit": validit[idx8[0] + 1:], "loppu": alku, "suljettu": True, "viiva": avain}],
                validit[:idx8[0]])
    jaksot = [{"alku": validit[a], "valit": validit[a + 1:b], "loppu": validit[b], "suljettu": False, "viiva": avain}
              for a, b in zip(idx8, idx8[1:])]
    return jaksot, validit[:idx8[0]] + validit[idx8[-1] + 1:]


def jaa_jaksoihin(pisteet):
    """Palauttaa (jaksot, pois_jatetyt). Jakso = {"alku", "valit", "loppu", "suljettu", "viiva"}.
    Pisteet ryhmitellään viivoittain (viivan_avain); kukin viiva jaetaan jaksoihin
    8-pisteiden kohdalta (yksi 8-piste = suljettu viiva)."""
    viivoittain = {}
    for p in _seinalinjapisteet(pisteet):
        viivoittain.setdefault(viivan_avain(p), []).append(p)
    jaksot, pois_jatetyt = [], []
    for avain in sorted(viivoittain):
        j, pois = _viivan_jaksot(viivoittain[avain], avain)
        jaksot.extend(j)
        pois_jatetyt.extend(pois)
    return jaksot, pois_jatetyt


# ---------------------------------------------------------------------------
# Järjestys: lyhin reitti tai mittausjärjestys
# ---------------------------------------------------------------------------

def _etaisyys(p, q):
    return math.hypot(p["e"] - q["e"], p["n"] - q["n"])


def _lyhin_tarkka(alku, valit, loppu):
    """Held-Karp: lyhin polku alku -> (kaikki välit) -> loppu."""
    m = len(valit)
    d_alku = [_etaisyys(alku, v) for v in valit]
    d_loppu = [_etaisyys(v, loppu) for v in valit]
    d = [[_etaisyys(a, b) for b in valit] for a in valit]

    # paras[(joukko, j)] = (pituus, edellinen)
    paras = {(1 << j, j): (d_alku[j], None) for j in range(m)}
    for koko in range(2, m + 1):
        for osajoukko in combinations(range(m), koko):
            maski = 0
            for j in osajoukko:
                maski |= 1 << j
            for j in osajoukko:
                ilman = maski & ~(1 << j)
                paras[(maski, j)] = min(
                    (paras[(ilman, k)][0] + d[k][j], k) for k in osajoukko if k != j
                )

    taysi = (1 << m) - 1
    _, viimeinen = min((paras[(taysi, j)][0] + d_loppu[j], j) for j in range(m))
    jarjestys = []
    maski, j = taysi, viimeinen
    while j is not None:
        jarjestys.append(j)
        _, edellinen = paras[(maski, j)]
        maski &= ~(1 << j)
        j = edellinen
    return [valit[j] for j in reversed(jarjestys)]


def _polun_pituus(polku):
    return sum(_etaisyys(a, b) for a, b in zip(polku, polku[1:]))


def _paranna_polkua(polku):
    """2-opt ja or-opt (1-3 pisteen pätkän siirto, myös käännettynä) kunnes mikään siirto
    ei lyhennä polkua. Päätepisteet pysyvät paikallaan."""
    polku = list(polku)
    n = len(polku)
    parani = True
    while parani:
        parani = False
        for i in range(1, n - 2):
            for k in range(i + 1, n - 1):
                ennen = _etaisyys(polku[i - 1], polku[i]) + _etaisyys(polku[k], polku[k + 1])
                jalkeen = _etaisyys(polku[i - 1], polku[k]) + _etaisyys(polku[i], polku[k + 1])
                if jalkeen < ennen - 1e-9:
                    polku[i:k + 1] = reversed(polku[i:k + 1])
                    parani = True
        for pituus in (1, 2, 3):
            for i in range(1, n - pituus):
                patka = polku[i:i + pituus]
                loput = polku[:i] + polku[i + pituus:]
                nykyinen = _polun_pituus(polku)
                for k in range(1, len(loput)):
                    for p in (patka, patka[::-1]):
                        ehdokas = loput[:k] + p + loput[k:]
                        if _polun_pituus(ehdokas) < nykyinen - 1e-9:
                            polku, parani = ehdokas, True
                            break
                    if parani:
                        break
                if parani:
                    break
            if parani:
                break
    return polku


def _lyhin_heuristinen(alku, valit, loppu):
    """Kun pisteitä on liikaa tarkalle haulle: lähtöreitit lähimmän naapurin menetelmällä
    kummastakin päästä ja halvimmalla lisäyksellä, kukin parannetaan 2-opt- ja
    or-opt-siirroilla, ja lyhin valitaan."""
    def lahin_naapuri(alkupiste):
        jaljella, reitti, nykyinen = list(valit), [], alkupiste
        while jaljella:
            seuraava = min(jaljella, key=lambda p: _etaisyys(nykyinen, p))
            jaljella.remove(seuraava)
            reitti.append(seuraava)
            nykyinen = seuraava
        return reitti

    def halvin_lisays():
        polku = [alku, loppu]
        for p in sorted(valit, key=lambda q: -min(_etaisyys(q, alku), _etaisyys(q, loppu))):
            k = min(range(1, len(polku)), key=lambda k: _etaisyys(polku[k - 1], p) + _etaisyys(p, polku[k])
                    - _etaisyys(polku[k - 1], polku[k]))
            polku.insert(k, p)
        return polku[1:-1]

    lahdot = [lahin_naapuri(alku), lahin_naapuri(loppu)[::-1], halvin_lisays()]
    polut = [_paranna_polkua([alku] + r + [loppu]) for r in lahdot]
    return min(polut, key=_polun_pituus)[1:-1]


def jarjesta_jakso(alku, valit, loppu, tapa="lyhin"):
    """Palauttaa jakson pisteet järjestyksessä alku, ..., loppu.
    Suljetussa jaksossa (alku is loppu) loppua ei toisteta."""
    if tapa == "mittaus" or len(valit) < 2:
        jarjestetyt = list(valit)
    elif len(valit) <= TARKKA_JARJESTYS_MAX:
        jarjestetyt = _lyhin_tarkka(alku, valit, loppu)
    else:
        jarjestetyt = _lyhin_heuristinen(alku, valit, loppu)

    if alku is loppu:
        return [alku] + jarjestetyt
    return [alku] + jarjestetyt + [loppu]


# ---------------------------------------------------------------------------
# Järjestys seinälinjoista (suorakulmainen talo)
# ---------------------------------------------------------------------------

def _kierretty(xy, kulma_aste):
    a = math.radians(kulma_aste)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in xy]


def _paasuunta(xy):
    """Talon pääsuunta asteina (0-90). Ehdokkaina kaikkien pisteparien suunnat; valitaan se,
    jossa eniten pistepareja on samalla pysty- tai vaakalinjalla. Tarkennus linjassa olevien
    parien suuntien painotetulla keskiarvolla (pitkät parit painavat eniten)."""
    parit = [(i, j) for i in range(len(xy)) for j in range(i + 1, len(xy))
             if math.dist(xy[i], xy[j]) > 0.5]
    if not parit:
        return 0.0

    def suunta(i, j):
        return math.degrees(math.atan2(xy[j][1] - xy[i][1], xy[j][0] - xy[i][0]))

    def linjassa(kulma):
        r = _kierretty(xy, -kulma)
        return [(i, j) for i, j in parit
                if abs(r[i][0] - r[j][0]) < LINJA_TOLERANSSI_M or abs(r[i][1] - r[j][1]) < LINJA_TOLERANSSI_M]

    paras, tuki = 0.0, None
    for i, j in parit:
        kulma = suunta(i, j) % 90
        l = linjassa(kulma)
        avain = (len(l), sum(math.dist(xy[a], xy[b]) for a, b in l))
        if tuki is None or avain > tuki:
            paras, tuki = kulma, avain
    summa = paino = 0.0
    for i, j in linjassa(paras):
        w = math.dist(xy[i], xy[j]) ** 2
        summa += (((suunta(i, j) - paras + 45) % 90) - 45) * w
        paino += w
    return paras + summa / paino if paino else paras


def _linjatoleranssi(matka):
    """Suurin sallittu sivuttaisero kahdelle saman seinälinjan pisteelle, jotka ovat matka
    metrin päässä toisistaan linjan suunnassa: mittausvirhe (MIN) + talon vinous (kulma)."""
    return min(JARJESTYS_MAX_TOLERANSSI_M,
               JARJESTYS_MIN_TOLERANSSI_M + matka * math.tan(math.radians(JARJESTYS_KULMA_ASTE)))


def _samalla_linjalla(p, q, akseli):
    """Ovatko pisteet samalla pysty- (akseli 0, x vakio) tai vaakalinjalla (akseli 1)."""
    return abs(p[akseli] - q[akseli]) <= _linjatoleranssi(abs(p[1 - akseli] - q[1 - akseli]))


def _linjaryhmat(r, akseli, mukana):
    """Indeksit (joukosta mukana) ryhmiteltyinä samoille pysty- tai vaakalinjoille. Ensin
    tiukka ryhmittely (JARJESTYS_MIN_TOLERANSSI_M), sitten ryhmiä yhdistetään lähimmästä
    alkaen, jos jokainen pistepari on samalla linjalla (_samalla_linjalla); näin vino seinä
    pysyy yhtenä linjana, mutta pieni porras ei ketjuunnu siihen. Tulos ei riipu pisteiden
    järjestyksestä. Palauttaa {indeksi: ryhmän numero}, [ryhmän keskiarvo]."""
    ryhmat = []
    for i in sorted(mukana, key=lambda i: (r[i][akseli], r[i][1 - akseli])):
        if ryhmat and r[i][akseli] - r[ryhmat[-1][-1]][akseli] <= JARJESTYS_MIN_TOLERANSSI_M:
            ryhmat[-1].append(i)
        else:
            ryhmat.append([i])

    def keskiarvo(g):
        return sum(r[i][akseli] for i in g) / len(g)

    while True:
        parit = sorted((abs(keskiarvo(a) - keskiarvo(b)), m, n)
                       for m, a in enumerate(ryhmat) for n, b in enumerate(ryhmat) if m < n)
        yhdistettava = next(((m, n) for _, m, n in parit
                             if all(_samalla_linjalla(r[i], r[j], akseli) for i in ryhmat[m] for j in ryhmat[n])),
                            None)
        if yhdistettava is None:
            break
        m, n = yhdistettava
        ryhmat[m] = ryhmat[m] + ryhmat.pop(n)
    ryhmat.sort(key=keskiarvo)
    kuulu = {i: n for n, g in enumerate(ryhmat) for i in g}
    return kuulu, [keskiarvo(g) for g in ryhmat]


def _peittaa(seinat, sadat):
    """Onko jokainen 100-piste (paikka linjalla) jonkin seinän (a, b) sisällä."""
    tol = JARJESTYS_MIN_TOLERANSSI_M
    return all(any(a + tol < y < b - tol for a, b in seinat) for y in sadat)


def _linjan_vaihtoehdot(pakolliset, ehdokkaat, sadat):
    """Piilokulmat yhdelle linjalle: joukot ehdokkaista, joilla linjan kärjet pariutuvat
    seiniksi ja jokainen 100-piste on seinän sisällä. Pienin joukko ei aina ole oikea (se voi
    yhdistää kaksi erillistä seinää), joten mukaan otetaan enintään kaksi kulmaa suuremmat.
    pakolliset = [paikka], ehdokkaat = [(paikka, avain)], sadat = [paikka].
    Palauttaa [(koko, frozenset(avaimet))]."""
    loydetyt, pienin = [], None
    for koko in range(0, min(JARJESTYS_MAX_PIILOKULMAT, len(ehdokkaat)) + 1):
        if pienin is not None and koko > pienin + 2:
            break
        for valinta in combinations(ehdokkaat, koko):
            paikat = sorted(pakolliset + [p for p, _ in valinta])
            if len(paikat) % 2 == 0 and _peittaa(list(zip(paikat[::2], paikat[1::2])), sadat):
                loydetyt.append((koko, frozenset(k for _, k in valinta)))
                pienin = koko if pienin is None else pienin
    return loydetyt


def _yhteensopivat(linjat, budjetti):
    """Linjojen piilokulmavalinnat, jotka sopivat yhteen: piilokulma on sekä pysty- että
    vaakalinjalla, joten jos kummallakin on 100-pisteitä, molempien valintojen pitää sisältää
    se. linjat = [((akseli, linja), [(koko, joukko)])]. Palauttaa piilokulmajoukot pienimmästä
    suurimpaan. budjetti = [jäljellä olevat kokeilut]; loppuessa ValueError."""
    tulokset = []
    valitut = {}

    def linjalla(joukko, akseli, linja):
        return {k for k in joukko if k[akseli] == linja}

    def haku(n, yhdiste):
        if n == len(linjat):
            tulokset.append(yhdiste)
            return
        (akseli, linja), vaihtoehdot = linjat[n]
        for _, joukko in vaihtoehdot:
            budjetti[0] -= 1
            if budjetti[0] < 0:
                raise ValueError("liikaa vaihtoehtoja")
            if not linjalla(yhdiste, akseli, linja) <= joukko:
                continue
            if any(not linjalla(joukko, a, l) <= valittu for (a, l), valittu in valitut.items()):
                continue
            valitut[(akseli, linja)] = joukko
            haku(n + 1, yhdiste | joukko)
            del valitut[(akseli, linja)]

    haku(0, frozenset())
    return sorted(set(tulokset), key=len)


def _seinakarjet(r, kulmat, sijoitus, paat, budjetti):
    """Yhden 100-pisteiden suuntajaon (sijoitus = {indeksi: akseli}) ja avoimen viivan
    päiden suuntien (paat) ratkaisut piilokulmien määrän mukaan kasvavassa järjestyksessä.
    Akseli 0 = pystyseinä (x vakio), 1 = vaakaseinä (y vakio). Tuottaa
    (kärjet {(pystylinja, vaakalinja): mitatun indeksi tai None}, naapurit, keskiarvot)."""
    osallistuu = {0: [], 1: []}
    for i in kulmat:
        for akseli in (0, 1):
            if paat.get(i, akseli) == akseli:
                osallistuu[akseli].append(i)
    for i, akseli in sijoitus.items():
        osallistuu[akseli].append(i)
    ryhma, keski = {}, {}
    for akseli in (0, 1):
        ryhma[akseli], keski[akseli] = _linjaryhmat(r, akseli, osallistuu[akseli])

    mitatut = {}
    for i in kulmat:
        if i in paat:   # avoimen viivan pää: vain toinen linja; indeksi erottaa samalla linjalla olevat päät
            mitatut[(ryhma[0][i] if paat[i] == 0 else None, ryhma[1][i] if paat[i] == 1 else None, i)] = i
        else:
            mitatut[(ryhma[0][i], ryhma[1][i])] = i

    vaihtoehdot = []
    for akseli in (0, 1):
        muu = 1 - akseli
        linjat = {}
        for i, a in sijoitus.items():
            if a == akseli:
                linjat.setdefault(ryhma[akseli][i], []).append(r[i][muu])
        for linja, sadat in linjat.items():
            linjalla = {k: i for k, i in mitatut.items() if k[akseli] == linja}
            pakolliset = [r[i][muu] for i in linjalla.values()]
            kaytetyt = {k[muu] for k in linjalla}
            ehdokkaat = [(keski[muu][h], (linja, h) if akseli == 0 else (h, linja))
                         for h in range(len(keski[muu])) if h not in kaytetyt]
            v = _linjan_vaihtoehdot(pakolliset, ehdokkaat, sadat)
            if not v:
                return
            vaihtoehdot.append(((akseli, linja), v))

    for piilo in _yhteensopivat(vaihtoehdot, budjetti):
        if any(k in mitatut for k in piilo):
            continue
        karjet = dict(mitatut)
        karjet.update((k, None) for k in piilo)
        naapurit = _pariuta(r, karjet, keski, sijoitus, ryhma)
        if naapurit is not None:
            yield karjet, naapurit, keski


def _pariuta(r, karjet, keski, sijoitus, ryhma):
    """Kärjet pariutetaan linjoittain seiniksi (järjestetään linjaa pitkin, 1-2, 3-4, ...).
    Jokaisen 100-pisteen pitää olla jonkin seinän sisällä. Palauttaa naapurit tai None."""
    naapurit = {k: [] for k in karjet}
    for akseli in (0, 1):
        muu = 1 - akseli
        linjoilla = {}
        for k, i in karjet.items():
            if k[akseli] is None:
                continue
            paikka = r[i][muu] if i is not None else keski[muu][k[muu]]
            linjoilla.setdefault(k[akseli], []).append((paikka, k))
        sadat = {}
        for i, a in sijoitus.items():
            if a == akseli:
                sadat.setdefault(ryhma[akseli][i], []).append(r[i][muu])
        if any(linja not in linjoilla for linja in sadat):
            return None
        for linja, lista in linjoilla.items():
            if len(lista) % 2:
                return None
            lista.sort()
            seinat = list(zip(lista[::2], lista[1::2]))
            if not _peittaa([(a[0], b[0]) for a, b in seinat], sadat.get(linja, [])):
                return None
            for (_, k1), (_, k2) in seinat:
                naapurit[k1].append(k2)
                naapurit[k2].append(k1)
    return naapurit


def _kierros(naapurit, alku, loppu):
    """Kärkien järjestys alusta (suljettu: loppu None) tai alusta loppuun, kun jokaisella
    kärjellä on kaksi naapuria (päillä yksi). None, jos kaikki kärjet eivät ole samassa ketjussa."""
    if loppu is None:
        if any(len(v) != 2 for v in naapurit.values()):
            return None
        polku, ed, nyk = [alku], alku, naapurit[alku][0]
        while nyk != alku and len(polku) <= len(naapurit):
            polku.append(nyk)
            ed, nyk = nyk, naapurit[nyk][1] if naapurit[nyk][0] == ed else naapurit[nyk][0]
    else:
        if len(naapurit[alku]) != 1 or len(naapurit[loppu]) != 1 or any(
                len(v) != 2 for k, v in naapurit.items() if k not in (alku, loppu)):
            return None
        polku, ed, nyk = [alku], None, alku
        while nyk != loppu:
            ed, nyk = nyk, next(n for n in naapurit[nyk] if n != ed)
            polku.append(nyk)
    return polku if len(polku) == len(naapurit) else None


def _mittausjarjestys(r, karjet, keski, polku, sijoitus, suljettu):
    """Kärkiketju -> mitattujen pisteiden järjestys: mitatut kärjet ja niiden välissä seinän
    100-pisteet seinää pitkin. Piilokulmat jäävät pois (muodosta_karjet laskee ne)."""
    def xy(k):
        i = karjet[k]
        return r[i] if i is not None else (keski[0][k[0]], keski[1][k[1]])

    jarj = []
    for k1, k2 in zip(polku, polku[1:] + ([polku[0]] if suljettu else [])):
        if karjet[k1] is not None:
            jarj.append(karjet[k1])
        p1, p2 = xy(k1), xy(k2)
        akseli = 0 if abs(p1[0] - p2[0]) < abs(p1[1] - p2[1]) else 1
        muu = 1 - akseli
        ala, yla = sorted((p1[muu], p2[muu]))
        tol = _linjatoleranssi(yla - ala)
        seinalla = [i for i, a in sijoitus.items()
                    if a == akseli and abs(r[i][akseli] - (p1[akseli] + p2[akseli]) / 2) <= tol
                    and ala < r[i][muu] < yla]
        jarj.extend(sorted(seinalla, key=lambda i: abs(r[i][muu] - p1[muu])))
    if not suljettu:
        jarj.append(karjet[polku[-1]])
    return jarj


def _suuntavaihtoehdot(r, sata):
    """Jokaisen 100-pisteen mahdolliset seinän suunnat (akseli, jolla on toinen piste samalla
    linjalla, _samalla_linjalla) parhaasta huonoimpaan, tai None jos pisteellä ei ole linjakumppania."""
    tulos = []
    for i in sata:
        poikkeamat = []
        for akseli in (0, 1):
            suhteet = [abs(r[j][akseli] - r[i][akseli]) / _linjatoleranssi(abs(r[j][1 - akseli] - r[i][1 - akseli]))
                       for j in range(len(r)) if j != i]
            if min(suhteet) <= 1:
                poikkeamat.append((min(suhteet), akseli))
        if not poikkeamat:
            return None
        tulos.append([a for _, a in sorted(poikkeamat)])
    return tulos


def _suuntajaot(vaihtoehdot, max_vaihdot=2):
    """Suuntajaot niin, että ensin kaikki parhaat, sitten yksi vaihdettu, sitten kaksi."""
    moniselitteiset = [n for n, v in enumerate(vaihtoehdot) if len(v) > 1]
    for vaihtoja in range(0, min(max_vaihdot, len(moniselitteiset)) + 1):
        for vaihdetut in combinations(moniselitteiset, vaihtoja):
            yield vaihtoja, [v[1] if n in vaihdetut else v[0] for n, v in enumerate(vaihtoehdot)]


def jarjesta_suorakulmaisesti(alku, valit, loppu, lidar=None):
    """Pisteiden järjestys seinälinjoista: suorakulmaisessa talossa jokaisesta kulmasta lähtee
    yksi seinä pääsuunnassa ja yksi sitä vastaan kohtisuoraan, ja jokainen 100-piste on
    pysty- tai vaakaseinällä, jolla on ainakin yksi toinen piste. Piilokulmat ovat pysty- ja
    vaakalinjojen leikkauspisteitä; niitä valitaan niin vähän kuin mahdollista. Järjestys ei
    riipu mittausjärjestyksestä. Avoimen viivan päillä on vain yksi seinä; kummankin pään
    suunta kokeillaan. Tulos tarkistetaan muodosta_karjet:lla (sen laskemien kulmien pitää
    osua päättelyn kulmiin, ei ristiin, ei epäselviä kulmia) ja hyväksytään vain, jos se on
    yksiselitteinen.

    Palauttaa (järjestetyt pisteet, None), (None, syy) jos päättely ei onnistu, tai
    (None, None) jos sitä ei voi käyttää (jaksossa 4-pisteitä tai alle 3 pistettä)."""
    suljettu = alku is loppu
    pisteet = [alku] + list(valit) + ([] if suljettu else [loppu])
    koodit = [koodi_numeroksi(p.get("koodi")) for p in pisteet]
    if len(pisteet) < 3 or any(k not in (KOODI_ALKU_LOPPU, KOODI_KULMA, KOODI_LINJA) for k in koodit):
        return None, None
    xy = [_xy(p) for p in pisteet]
    kulma = _paasuunta(xy)
    r = _kierretty(xy, -kulma)
    kulmat = [i for i, k in enumerate(koodit) if k != KOODI_LINJA]
    sata = [i for i, k in enumerate(koodit) if k == KOODI_LINJA]
    viimeinen = len(pisteet) - 1

    suunnat = _suuntavaihtoehdot(r, sata)
    if suunnat is None:
        return None, "100-piste ei ole samalla seinälinjalla minkään muun pisteen kanssa"
    paa_vaihtoehdot = [{}] if suljettu else [{0: a, viimeinen: b} for a in (0, 1) for b in (0, 1)]

    budjetti = [JARJESTYS_MAX_KOKEILUT]
    erillisia = False
    hyvat = {}   # järjestysavain -> (piilokulmia, järjestetyt pisteet)
    for vaihtoja, jako in _suuntajaot(suunnat):
        if hyvat:
            break   # vähemmillä vaihdoilla löytyi jo ratkaisu
        sijoitus = dict(zip(sata, jako))
        for paat in paa_vaihtoehdot:
            loytyi_taso = None
            ratkaisut = _seinakarjet(r, kulmat, sijoitus, paat, budjetti)
            while True:
                try:
                    karjet, naapurit, keski = next(ratkaisut)
                except StopIteration:
                    break
                except ValueError:
                    return None, "vaihtoehtoja on liikaa"
                piiloja = sum(1 for i in karjet.values() if i is None)
                if loytyi_taso is not None and piiloja > loytyi_taso:
                    break
                mitattu = {i: k for k, i in karjet.items() if i is not None}
                polku = _kierros(naapurit, mitattu[0], None if suljettu else mitattu[viimeinen])
                if polku is None:
                    erillisia = erillisia or (suljettu and all(len(v) == 2 for v in naapurit.values()))
                    continue
                jarj = _mittausjarjestys(r, karjet, keski, polku, sijoitus, suljettu)
                if sorted(jarj) != list(range(len(pisteet))):
                    continue
                jarjestetty = [pisteet[i] for i in jarj]
                kj, varoitukset = muodosta_karjet(jarjestetty, suljettu, lidar)
                # muodosta_karjet laskee kulmat uudelleen pisteistä; niiden pitää osua päättelyyn
                paatellyt = _kierretty([r[karjet[k]] if karjet[k] is not None else (keski[0][k[0]], keski[1][k[1]])
                                        for k in polku], kulma)
                if len(kj) != len(paatellyt) or any(
                        min(math.dist(_xy(k), p) for p in paatellyt) > JARJESTYS_TARKISTUS_M for k in kj):
                    continue
                if menee_ristiin({"karjet": kj, "suljettu": suljettu}) or any(
                        t in v for v in varoitukset for t in EPASELVAT_VAROITUKSET):
                    continue
                avain = tuple(jarj) if not suljettu else min(tuple(jarj), tuple(jarj[:1] + jarj[:0:-1]))
                hyvat.setdefault(avain, (piiloja, jarjestetty))
                loytyi_taso = piiloja
    if not hyvat:
        if erillisia:
            return None, "pisteistä muodostuu useampi erillinen rengas (kaksi taloa tai sisäpiha?)"
        return None, "kulmia ja 100-pisteitä ei saatu seinälinjoiksi"
    vahiten = min(p for p, _ in hyvat.values())
    parhaat = [j for p, j in hyvat.values() if p == vahiten]
    if len(parhaat) > 1:
        return None, "seinälinjoista löytyi useampi mahdollinen järjestys"
    return parhaat[0], None


def _vinot_kulmat(karjet, suljettu, raja_aste=10.0):
    """Kärkien nimet, joissa seinien välinen kulma poikkeaa yli raja_aste suorasta kulmasta
    tai suorasta jatkeesta (vain suorien seinien välillä, kaaret ohitetaan)."""
    vinot = []
    n = len(karjet)
    for i in range(n) if suljettu else range(1, n - 1):
        a, b, c = karjet[i - 1], karjet[i], karjet[(i + 1) % n]
        if a.get("bulge") or b.get("bulge"):
            continue
        poikkeama = _poikkeama_suorasta_kulmasta(_suuntakulma(_xy(a), _xy(b)), _suuntakulma(_xy(b), _xy(c)))
        if poikkeama > raja_aste:
            vinot.append(str(b.get("nimi")))
    return vinot


# ---------------------------------------------------------------------------
# Kantakartta apuna (Helsinki)
# ---------------------------------------------------------------------------
# kantakartta = [[ulkorengas, sisärengas, ...], ...] rakennuksittain; rengas = [(e, n), ...]
# (EPSG:3879). Moduuli ei hae karttaa itse (ks. hae_kiintopisteet.hae_helsinki_rakennukset).

def _renkaan_ala(rengas):
    pts = [tuple(p[:2]) for p in rengas]
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


class _Murtoviiva:
    """Murtoviiva (xy-pisteet) etäisyyttä ja viivaa pitkin mittausta varten -- samat
    toiminnot kuin shapelyn LineStringissä, jotta muodostus ei vaadi lisäkirjastoja."""

    def __init__(self, pisteet):
        self.pisteet = [tuple(p[:2]) for p in pisteet]
        self.janat = list(zip(self.pisteet, self.pisteet[1:]))
        self.pituudet = [math.dist(a, b) for a, b in self.janat]
        self.length = sum(self.pituudet)

    def _lahin(self, p):
        """(etäisyys, matka viivaa pitkin) lähimpään kohtaan."""
        paras, kuljettu = None, 0.0
        for (a, b), pituus in zip(self.janat, self.pituudet):
            t = 0.0
            if pituus:
                t = max(0.0, min(1.0, ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / pituus ** 2))
            d = math.dist(p, (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
            if paras is None or d < paras[0]:
                paras = (d, kuljettu + t * pituus)
            kuljettu += pituus
        return paras or (math.inf, 0.0)

    def distance(self, p):
        return self._lahin(p)[0]

    def project(self, p):
        return self._lahin(p)[1]

    def suunta(self, matka):
        """Yksikkösuunta kohdassa matka (sen janan suunta)."""
        for (a, b), pituus in zip(self.janat, self.pituudet):
            if pituus and (matka <= pituus or (a, b) == self.janat[-1]):
                return (b[0] - a[0]) / pituus, (b[1] - a[1]) / pituus
            matka -= pituus
        return 1.0, 0.0

    def interpolate(self, matka):
        for (a, b), pituus in zip(self.janat, self.pituudet):
            if matka <= pituus and pituus:
                t = matka / pituus
                return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
            matka -= pituus
        return self.pisteet[-1]


def _kantakartan_viivat(kantakartta):
    """[(rakennuksen indeksi, renkaan reunaviiva _Murtoviivana)]. Alle
    KANTAKARTTA_MIN_ALA_M2 kohteet ohitetaan."""
    viivat = []
    for r, renkaat in enumerate(kantakartta or []):
        if not renkaat or _renkaan_ala(renkaat[0]) < KANTAKARTTA_MIN_ALA_M2:
            continue
        for rengas in renkaat:
            pts = [tuple(p[:2]) for p in rengas]
            if len(pts) < 3:
                continue
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            viivat.append((r, _Murtoviiva(pts)))
    return viivat


def _osuu_kantakarttaan(pisteet, kantakartta):
    """Rakennukset, joiden reunaan jokin piste osuu (alle KANTAKARTTA_RAJA_M)."""
    viivat = _kantakartan_viivat(kantakartta)
    return sorted({r for r, viiva in viivat for p in pisteet
                   if viiva.distance(_xy(p)) <= KANTAKARTTA_RAJA_M})


def jarjesta_kantakartan_mukaan(alku, valit, loppu, kantakartta, lidar=None):
    """Jakson pisteet kantakartan talon reunan kiertojärjestyksessä: jokainen piste
    projisoidaan saman renkaan reunalle (enintään KANTAKARTTA_RAJA_M), ja järjestys tulee
    reunaa pitkin kuljetusta matkasta. Toimii myös vinoilla seinillä, kaarilla ja
    100-pisteillä. Avoimessa viivassa valitaan se kiertosuunta alusta loppuun, jonka
    matkalle kaikki pisteet osuvat. Tulos tarkistetaan muodosta_karjet:lla.

    Palauttaa (järjestetyt pisteet, None) tai (None, syy)."""
    viivat = _kantakartan_viivat(kantakartta)
    if not viivat:
        return None, "kantakartalla ei ole rakennuksia"
    suljettu = alku is loppu
    pisteet = [alku] + list(valit) + ([] if suljettu else [loppu])
    pp = [_xy(p) for p in pisteet]
    etaisyydet = [[viiva.distance(p) for p in pp] for _, viiva in viivat]
    paras = min(range(len(viivat)), key=lambda k: max(etaisyydet[k]))
    if max(etaisyydet[paras]) > KANTAKARTTA_RAJA_M:
        kaukana = [(min(e[i] for e in etaisyydet), pisteet[i].get("nimi")) for i in range(len(pisteet))]
        lahin, nimi = max(kaukana)
        if lahin > KANTAKARTTA_RAJA_M:
            return None, f"piste {nimi} ei osu kantakartan taloon (lähin {lahin:.1f} m)"
        return None, "pisteet osuvat kantakartalla eri rakennuksiin tai seiniin"
    viiva = viivat[paras][1]
    pituus = viiva.length
    matkat = [viiva.project(p) for p in pp]

    if suljettu:
        jarj = [0] + sorted(range(1, len(pisteet)), key=lambda i: (matkat[i] - matkat[0]) % pituus)
    else:
        a, b = matkat[0], matkat[-1]
        valista = range(1, len(pisteet) - 1)
        suunnat = []
        for merkki in (1, -1):
            kokonaan = (merkki * (b - a)) % pituus
            if all((merkki * (matkat[i] - a)) % pituus <= kokonaan for i in valista):
                suunnat.append(sorted(valista, key=lambda i: (merkki * (matkat[i] - a)) % pituus))
        if len(suunnat) != 1:
            return None, "pisteet eivät ole kantakartan talon reunalla yhtenäisellä matkalla alusta loppuun"
        jarj = [0] + suunnat[0] + [len(pisteet) - 1]

    jarjestetty = [pisteet[i] for i in jarj]
    karjet, varoitukset = muodosta_karjet(jarjestetty, suljettu, lidar)
    if menee_ristiin({"karjet": karjet, "suljettu": suljettu}):
        return None, "kantakartan mukainen viiva menee ristiin"
    if any(t in v for v in varoitukset for t in EPASELVAT_VAROITUKSET):
        return None, "kantakartan mukainen järjestys jättää kulmia epäselviksi"
    return jarjestetty, None


def _sama_jarjestys(a, b, suljettu):
    """Ovatko kaksi järjestystä samat (suljetussa myös vastakkaiseen suuntaan)."""
    ida, idb = [id(p) for p in a], [id(p) for p in b]
    return ida == idb or (suljettu and ida == idb[:1] + idb[:0:-1])


def _poikkeamat(tulos, reunat, askel_m, peitto_raja_m=None):
    """Seinälinjan etäisyys vertailuviivoista (_Murtoviiva) viivoittain, viivaa pitkin askel_m
    välein. Jos peitto_raja_m on annettu (LiDAR-janat), kohtaa verrataan vain sen suuntaisiin
    janoihin, joiden kohdalla se on (kohtisuora etäisyys), ja kauempana olevalla kohdalla ei
    ole vertailuviivaa (etäisyys None, esim. keilaamaton seinä tai janan pään ohi)."""
    raja_cos = math.cos(math.radians(LIDAR_PEITTO_KULMA_ASTE))
    tulokset = []
    for viiva in tulos.get("viivat", []):
        pisteet = viivan_pisteet(viiva)
        if len(pisteet) < 2:
            continue
        janat = _Murtoviiva(pisteet)
        n = max(2, int(janat.length / askel_m) + 1)
        naytteet = []
        for k in range(n):
            matka = janat.length * k / (n - 1)
            p = janat.interpolate(matka)
            if peitto_raja_m is None:
                d = min(r.distance(p) for r in reunat)
            else:
                ux, uy = janat.suunta(matka)
                d = math.inf
                for r in reunat:
                    (rx, ry), a = r.suunta(0), r.pisteet[0]
                    t = (p[0] - a[0]) * rx + (p[1] - a[1]) * ry
                    if abs(ux * rx + uy * ry) >= raja_cos and 0 <= t <= r.length:
                        d = min(d, abs((p[0] - a[0]) * ry - (p[1] - a[1]) * rx))
            naytteet.append((p[0], p[1], None if peitto_raja_m is not None and d > peitto_raja_m else d))
        etaisyydet = [d for _, _, d in naytteet if d is not None]
        tulokset.append({"nimi": viiva.get("nimi"), "naytteet": naytteet,
                         "keskiarvo_m": sum(etaisyydet) / len(etaisyydet) if etaisyydet else None,
                         "suurin_m": max(etaisyydet) if etaisyydet else None,
                         "peitto": len(etaisyydet) / len(naytteet)})
    return tulokset


def poikkeamat_kantakartasta(tulos, kantakartta, askel_m=0.25):
    """Seinälinjan etäisyys kantakartan rakennusten reunoista viivoittain, viivaa pitkin
    askel_m välein: [{"nimi", "naytteet": [(e, n, etäisyys_m)], "keskiarvo_m", "suurin_m",
    "peitto"}]. Tyhjä lista, jos viivoja tai karttaa ei ole."""
    reunat = [v for _, v in _kantakartan_viivat(kantakartta)]
    return _poikkeamat(tulos, reunat, askel_m) if reunat else []


def poikkeamaluokka(etaisyys_m):
    """(luokka, väri) poikkeamalle, ks. POIKKEAMALUOKAT."""
    return next((luokka, vari) for raja, luokka, vari in POIKKEAMALUOKAT if etaisyys_m < raja)


def lue_lidar_dxf(polku):
    """LiDAR-seinät DXF:stä (Lidar-repon lidarpipe: <nimi>_seinat.dxf) tasoittain:
    {"SEINA": [((e0, n0), (e1, n1)), ...], "EPAVARMA": [...], "PAATELTY": [...]}. PAATELTY = lidarpipen
    ääriviivan päätellyt osat (aukkojen liitokset, katvenurkat), vain järjestyksen apuna (lidar_aariviivat);
    vertailu ja piilokulmat käyttävät mitattua SEINA-tasoa. LINE ja (LW)POLYLINE pilkotaan
    janoiksi; muut tasot (esim. TAHYKSET) ohitetaan. Vaatii ezdxf:n (sovellus; QGIS-lisäosa
    lukee DXF:n QGIS:n omalla lukijalla)."""
    import ezdxf

    janat = {"SEINA": [], "EPAVARMA": [], "PAATELTY": []}
    for e in ezdxf.readfile(polku).modelspace():
        taso = e.dxf.layer.upper()
        if taso not in janat:
            continue
        if e.dxftype() == "LINE":
            janat[taso].append(((e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)))
        elif e.dxftype() in ("LWPOLYLINE", "POLYLINE"):
            pisteet = [(p[0], p[1]) for p in (e.get_points("xy") if e.dxftype() == "LWPOLYLINE" else e.points())]
            if e.is_closed and pisteet:
                pisteet.append(pisteet[0])
            janat[taso].extend(zip(pisteet, pisteet[1:]))
    return janat


def poikkeamat_lidarista(tulos, lidar, askel_m=0.25):
    """Seinälinjan etäisyys LiDAR-seinistä (ks. muodosta_seinalinjat) kuten
    poikkeamat_kantakartasta. Kohdalla, jonka lähellä (LIDAR_PEITTO_RAJA_M) ei ole
    LiDAR-seinää, etäisyys on None; "peitto" = LiDAR-seinän kattama osuus viivasta."""
    reunat = [_Murtoviiva([a, b]) for a, b, _, _ in _lidar_janat(lidar)]
    return _poikkeamat(tulos, reunat, askel_m, LIDAR_PEITTO_RAJA_M) if reunat else []


def poikkeama_kantakartasta(tulos, kantakartta, askel_m=0.25):
    """Kuinka kaukana seinälinja on kantakartan rakennusten reunoista: {"keskiarvo_m",
    "suurin_m"} kaikista viivoista askel_m välein mitattuna, tai None (ei viivaa tai karttaa)."""
    etaisyydet = [d for v in poikkeamat_kantakartasta(tulos, kantakartta, askel_m) for _, _, d in v["naytteet"]]
    if not etaisyydet:
        return None
    return {"keskiarvo_m": sum(etaisyydet) / len(etaisyydet), "suurin_m": max(etaisyydet)}


def _renkaan_karjet(rengas, suoraraja_m=0.01):
    """Renkaan kärjet ilman sulkevaa toistoa ja suoralla olevia välipisteitä."""
    pts = [tuple(p[:2]) for p in rengas]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    karjet = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        pituus = math.dist(a, b)
        if not pituus or abs((p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])) / pituus >= suoraraja_m:
            karjet.append(p)
    return karjet


def kantakartan_riskit(kantakartta, pisteet):
    """Kohdat kantakartan talossa, joissa järjestyksen päättely seinälinjoista voi
    luovuttaa tai viiva mennä väärin. Vain rakennukset, joiden reunaan seinälinjan pisteet
    osuvat. Palauttaa listan tekstejä."""
    pisteet = _seinalinjapisteet(pisteet)
    osuvat = _osuu_kantakarttaan(pisteet, kantakartta)
    riskit = []
    if len(osuvat) > 1 and len({viivan_avain(p) for p in pisteet}) < len(osuvat):
        riskit.append(f"Pisteet osuvat {len(osuvat)} rakennukseen. Anna jokaiselle talolle oma viivanumero "
                      "koodin perään (esim. 8 2, 5 2, 100 2); muuten talot yhdistyvät samaksi viivaksi.")
    for r in osuvat:
        renkaat = kantakartta[r]
        if len(renkaat) > 1:
            riskit.append("Kantakartan talossa on sisäpiha. Sisäpihan seinät eivät kuulu "
                          "ulkoseinän viivaan.")
        karjet = _renkaan_karjet(renkaat[0])
        n = len(karjet)
        if n < 3:
            continue
        seinat = [math.dist(karjet[i], karjet[(i + 1) % n]) for i in range(n)]
        vinoja = lyhyita = kaaria = 0
        lyhyiden_putki = 0
        for i in range(n):
            ed, nyk = seinat[i - 1], seinat[i]
            if ed >= 1.0 and nyk >= 1.0:
                poikkeama = _poikkeama_suorasta_kulmasta(_suuntakulma(karjet[i - 1], karjet[i]),
                                                         _suuntakulma(karjet[i], karjet[(i + 1) % n]))
                vinoja += poikkeama > KANTAKARTTA_VINO_ASTE
            lyhyiden_putki = lyhyiden_putki + 1 if nyk < 1.0 else 0
            if lyhyiden_putki == 3:
                kaaria += 1
            if nyk < 0.3 and lyhyiden_putki < 3:
                lyhyita += 1
        if kaaria:
            riskit.append("Kantakartan talossa on kaareva seinä. Kaari mitataan 4-pisteillä; "
                          "järjestys otetaan silloin kantakartasta tai lyhimmästä reitistä.")
        if vinoja:
            riskit.append(f"Kantakartan talossa on {vinoja} vinoa kulmaa (ei 90°), esim. viisto "
                          "erkkeri. Niissä seinälinjapäättely luovuttaa ja järjestys otetaan "
                          "kantakartasta. Jos talo on muuttunut, mittaa kiertäen ja valitse "
                          "Mittausjärjestys.")
        if lyhyita:
            riskit.append(f"Kantakartan talossa on {lyhyita} alle 30 cm seinää. Alle 5 cm portaat "
                          "eivät erotu seinälinjapäättelyssä.")
    return riskit


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------

def _xy(p):
    return (p["e"], p["n"])


def _sovita_suora(pisteet):
    """Pienimmän neliösumman suora (kohtisuorat etäisyydet): (keskipiste, yksikkösuunta)."""
    xs = [p[0] for p in pisteet]
    ys = [p[1] for p in pisteet]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - cx) ** 2 for x in xs)
    syy = sum((y - cy) ** 2 for y in ys)
    sxy = sum((x - cx) * (y - cy) for x, y in zip(xs, ys))
    kulma = 0.5 * math.atan2(2 * sxy, sxx - syy)
    return (cx, cy), (math.cos(kulma), math.sin(kulma))


def _etaisyys_suorasta(piste, suora):
    (cx, cy), (dx, dy) = suora
    return abs((piste[0] - cx) * dy - (piste[1] - cy) * dx)


def _suurin_poikkeama(pisteet):
    suora = _sovita_suora(pisteet)
    return max(_etaisyys_suorasta(p, suora) for p in pisteet), suora


def _leikkaus(suora1, suora2):
    """Kahden suoran leikkauspiste, tai None jos lähes yhdensuuntaiset."""
    (px, py), (dx, dy) = suora1
    (qx, qy), (fx, fy) = suora2
    risti = dx * fy - dy * fx
    if abs(risti) < math.sin(math.radians(YHDENSUUNTAISUUS_RAJA_ASTE)):
        return None
    t = ((qx - px) * fy - (qy - py) * fx) / risti
    return (px + t * dx, py + t * dy)


def _projektio(piste, a, b):
    """Pisteen projektio suoralle a-b ja parametri t (0 = a, 1 = b)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    pituus2 = dx * dx + dy * dy
    t = ((piste[0] - a[0]) * dx + (piste[1] - a[1]) * dy) / pituus2
    return (a[0] + t * dx, a[1] + t * dy), t


def _suuntakulma(p, q):
    return math.atan2(q[1] - p[1], q[0] - p[0])


def _poikkeama_suorasta_kulmasta(kulma1, kulma2):
    """Kuinka paljon (asteina) kahden suunnan välinen kulma poikkeaa 90:n monikerrasta."""
    ero = math.degrees(abs(kulma1 - kulma2)) % 90.0
    return min(ero, 90.0 - ero)


def _korkeus_keskiarvo(*pisteet):
    arvot = [p.get("korkeus") for p in pisteet if p.get("korkeus") is not None]
    return sum(arvot) / len(arvot) if arvot else None


# ---------------------------------------------------------------------------
# Kärjet
# ---------------------------------------------------------------------------

def _karki(p, laji="mitattu"):
    return {"e": p["e"], "n": p["n"], "z": p.get("korkeus"), "laji": laji, "nimi": p.get("nimi"),
            "bulge": 0.0}


def _laskettu_karki(xy, a, b, nimi):
    return {"e": xy[0], "n": xy[1], "z": _korkeus_keskiarvo(a, b), "laji": "laskettu", "nimi": nimi,
            "bulge": 0.0}


def _tarkista_jatke(karki, lahella, varoitukset):
    lahin = min(math.hypot(karki["e"] - p["e"], karki["n"] - p["n"]) for p in lahella)
    if lahin > MAX_JATKE_M:
        varoitukset.append(
            f"Laskettu kulma '{karki['nimi']}' on {lahin:.1f} m päässä lähimmästä mitatusta "
            "pisteestä -- tarkista pisteiden koodit ja järjestys."
        )


# ---------------------------------------------------------------------------
# Seinälinjat 100-pisteistä
# ---------------------------------------------------------------------------

def _suora_kahdesta(p, q):
    dx, dy = q[0] - p[0], q[1] - p[1]
    pituus = math.hypot(dx, dy)
    return p, (dx / pituus, dy / pituus)


def _suuntien_poikkeama(d1, d2):
    return _poikkeama_suorasta_kulmasta(math.atan2(d1[1], d1[0]), math.atan2(d2[1], d2[0]))


def _seinapatkalla(pisteet, alku, loppu, suora):
    """Ovatko pisteet seinäpätkällä alku-loppu (kulmapisteet). Avoimessa päässä
    (None) riittää, etteivät pisteet ole toisen pään kulman takana."""
    _, (dx, dy) = suora
    if alku is not None and loppu is not None:
        pituus = math.hypot(loppu[0] - alku[0], loppu[1] - alku[1])
        if pituus < 1e-9:
            return False
        for p in pisteet:
            _, t = _projektio(p, alku, loppu)
            if t < -LINJA_TOLERANSSI_M / pituus or t > 1 + LINJA_TOLERANSSI_M / pituus:
                return False
        return True
    raja = alku if alku is not None else loppu
    if raja is None:
        return True
    sijainnit = [(p[0] - raja[0]) * dx + (p[1] - raja[1]) * dy for p in pisteet]
    return max(sijainnit) <= LINJA_TOLERANSSI_M or min(sijainnit) >= -LINJA_TOLERANSSI_M


def _lidar_janat(lidar):
    """LiDAR-seinät [((e0, n0), (e1, n1)), ...] -> [(alku, loppu, yksikkösuunta, pituus)]."""
    janat = []
    for a, b in lidar or []:
        a, b = tuple(a[:2]), tuple(b[:2])
        pituus = math.dist(a, b)
        if pituus >= LIDAR_MIN_PITUUS_M:
            janat.append((a, b, ((b[0] - a[0]) / pituus, (b[1] - a[1]) / pituus), pituus))
    return janat


def _lidar_seina(piste, suunta, janat):
    """Pisteen kautta suunnassa kulkevan LiDAR-seinän janat: saman suoran pätkät (seinä voi
    katketa oviaukon, kasvillisuuden tai katveen kohdalta). Pätkän kumpikin pää on alle
    LIDAR_PISTE_RAJA_M suorasta."""
    ux, uy = suunta
    return [j for j in janat
            if all(abs((p[0] - piste[0]) * uy - (p[1] - piste[1]) * ux) <= LIDAR_PISTE_RAJA_M for p in j[:2])]


def _samaa_seinaa(seina, pisteet, suunta, raja_cos):
    """Kuuluvatko pisteet (pätkä tai toinen seinä, suunta yksikkövektorina) seinään [suora,
    päätepisteet]: lähes sama suunta, kaikki pisteet yhteisellä suoralla (pitkän pätkän suoran
    jatke kallistuisi kohinasta) ja aukko enintään LIDAR_YHDISTA_VALI_M."""
    (cx, cy), (ux, uy) = seina[0]
    if abs(suunta[0] * ux + suunta[1] * uy) < raja_cos or \
            _suurin_poikkeama(seina[1] + pisteet)[0] > LIDAR_PISTE_RAJA_M:
        return False
    tt = sorted((p[0] - cx) * ux + (p[1] - cy) * uy for p in seina[1])
    uu = sorted((p[0] - cx) * ux + (p[1] - cy) * uy for p in pisteet)
    return uu[0] - tt[-1] <= LIDAR_YHDISTA_VALI_M and tt[0] - uu[-1] <= LIDAR_YHDISTA_VALI_M


def _valmiit_renkaat(janat, tol=0.002):
    """Suljetut kierrokset janoista, jotka yhtyvät päistään (lidarpipen ääriviiva: SEINA + PAATELTY):
    komponentit, joiden jokaisessa solmussa on tasan kaksi janaa. [[rengas]] kuten lidar_aariviivat."""
    solmut, naapurit = {}, {}

    def solmu(p):
        avain = (round(p[0] / tol), round(p[1] / tol))
        solmut.setdefault(avain, (p[0], p[1]))
        return avain

    for a, b in janat:
        ka, kb = solmu(a[:2]), solmu(b[:2])
        if ka != kb:
            naapurit.setdefault(ka, []).append(kb)
            naapurit.setdefault(kb, []).append(ka)
    renkaat, kaytetyt = [], set()
    for alku in naapurit:
        if alku in kaytetyt or len(naapurit[alku]) != 2:
            continue
        rengas, edellinen, nyky = [alku], None, alku
        while True:
            kaytetyt.add(nyky)
            seuraavat = [k for k in naapurit[nyky] if k != edellinen] if edellinen else naapurit[nyky][:1]
            if len(naapurit[nyky]) != 2 or not seuraavat:
                rengas = None
                break
            edellinen, nyky = nyky, seuraavat[0]
            if nyky == alku:
                break
            if nyky in kaytetyt:
                rengas = None
                break
            rengas.append(nyky)
        if rengas and len(rengas) >= 3:
            pisteet = [solmut[k] for k in rengas]
            if _renkaan_ala(pisteet) >= KANTAKARTTA_MIN_ALA_M2:
                renkaat.append([pisteet + [pisteet[0]]])
    return renkaat


def lidar_aariviivat(lidar, paatelty=None):
    """Suljetut ääriviivat LiDAR-seinistä kantakartan muodossa ([[rengas]] rakennuksittain;
    ks. jarjesta_kantakartan_mukaan). paatelty = lidarpipen PAATELTY-taso: jos SEINA- ja PAATELTY-
    janat muodostavat päistään yhtyvän suljetun kierroksen (lidarpipen ääriviiva), se kelpaa
    sellaisenaan. Muuten ääriviiva päätellään SEINA-janoista: saman suoran pätkät yhdistetään seiniksi (aukko enintään
    LIDAR_YHDISTA_VALI_M), ja seinän pää liitetään toiseen seinään, kun niiden suorien
    leikkauspiste on molempien päiden lähellä (LIDAR_PIILO_RAJA_M; katveessa oleva nurkka).
    Ääriviivaksi kelpaa vain kierros, jossa jokaisen seinän molemmat päät liittyvät
    yksiselitteisesti (epäselvä nurkka muualla keilauksessa ei haittaa). Tyhjä lista, jos
    suljettua kierrosta ei synny (esim. osittainen keilaus)."""
    valmiit = _valmiit_renkaat(list(lidar or []) + list(paatelty or []))
    if valmiit:
        return valmiit
    janat = sorted(_lidar_janat(lidar), key=lambda j: -j[3])
    raja_cos = math.cos(math.radians(LIDAR_YHDISTA_ASTE))
    seinat = []   # [[suora, päätepisteet]]; pisimmät pätkät ensin
    for a, b, d, _ in janat:
        seina = next((s for s in seinat if _samaa_seinaa(s, [a, b], d, raja_cos)), None)
        if seina is None:
            seinat.append([_sovita_suora([a, b]), [a, b]])
        else:
            seina[1].extend([a, b])
            seina[0] = _sovita_suora(seina[1])
    # Lyhyt pätkä voi yhdistää kaksi jo erillistä seinää (aukko kummastakin alle LIDAR_YHDISTA_VALI_M,
    # mutta seinien välillä suurempi): yhdistetään seiniä, kunnes mikään ei muutu
    yhdistyi = True
    while yhdistyi:
        yhdistyi = False
        for i, j in combinations(range(len(seinat)), 2):
            if _samaa_seinaa(seinat[i], seinat[j][1], seinat[j][0][1], raja_cos):
                seinat[i][1].extend(seinat.pop(j)[1])
                seinat[i][0] = _sovita_suora(seinat[i][1])
                yhdistyi = True
                break
    # seinän päät suoralla: (alkupiste, loppupiste)
    paat = []
    for suora, pisteet in seinat:
        (cx, cy), (ux, uy) = suora
        tt = [(p[0] - cx) * ux + (p[1] - cy) * uy for p in pisteet]
        paat.append([(cx + ux * min(tt), cy + uy * min(tt)), (cx + ux * max(tt), cy + uy * max(tt))])
    # liitokset: (seinä, pää) <-> (seinä, pää) suorien leikkauspisteessä
    liitokset = {}
    for i in range(len(seinat)):
        for j in range(i + 1, len(seinat)):
            (_, (ux, uy)), (_, (vx, vy)) = seinat[i][0], seinat[j][0]
            if math.degrees(math.acos(min(1.0, abs(ux * vx + uy * vy)))) < LIDAR_MIN_KULMA_ASTE:
                continue
            x = _leikkaus(seinat[i][0], seinat[j][0])
            if x is None:
                continue
            ki = min(range(2), key=lambda k: math.dist(paat[i][k], x))
            kj = min(range(2), key=lambda k: math.dist(paat[j][k], x))
            if math.dist(paat[i][ki], x) <= LIDAR_PIILO_RAJA_M and math.dist(paat[j][kj], x) <= LIDAR_PIILO_RAJA_M:
                liitokset.setdefault((i, ki), []).append(((j, kj), x))
                liitokset.setdefault((j, kj), []).append(((i, ki), x))
    renkaat, kaytetyt = [], set()
    for alku in range(len(seinat)):
        if alku in kaytetyt:
            continue
        rengas, seina, paa = [], alku, 1
        while True:
            kaytetyt.add(seina)
            liitos = liitokset.get((seina, paa))
            # Epäselvä nurkka (pää liittyy moneen seinään) katkaisee vain tämän kierroksen; muualla
            # keilauksessa (aita, naapuritalo) oleva ei estä talon ääriviivaa
            if liitos is None or len(liitos) != 1 or len(liitokset[liitos[0][0]]) != 1:
                break
            (seina, toinen), x = liitos[0]
            rengas.append(x)
            paa = 1 - toinen
            if seina == alku:
                break
        if seina == alku and len(rengas) >= 3 and _renkaan_ala(rengas) >= KANTAKARTTA_MIN_ALA_M2:
            renkaat.append([rengas + [rengas[0]]])
    return renkaat


def _lidar_etaisyys(piste, janat):
    """Pisteen etäisyys lähimpään LiDAR-janaan."""
    paras = math.inf
    for a, _, (ux, uy), pituus in janat:
        t = max(0.0, min(pituus, (piste[0] - a[0]) * ux + (piste[1] - a[1]) * uy))
        paras = min(paras, math.dist(piste, (a[0] + ux * t, a[1] + uy * t)))
    return paras


def _lidar_ristiriita(pisteet, suunta, janat):
    """Onko seinä (pisteet ja sovitettu suunta) ristiriidassa LiDARin kanssa: jonkin pisteen
    kautta kulkee LiDAR-seiniä, mutta mikään niistä ei ole seinän suuntainen."""
    ux, uy = suunta
    raja = math.cos(math.radians(LIDAR_SUUNTAINEN_ASTE))
    for p in pisteet:
        kautta = [d for a, _, d, pituus in janat
                  if -LIDAR_PAA_RAJA_M <= (p[0] - a[0]) * d[0] + (p[1] - a[1]) * d[1] <= pituus + LIDAR_PAA_RAJA_M
                  and abs((p[0] - a[0]) * d[1] - (p[1] - a[1]) * d[0]) <= LIDAR_PISTE_RAJA_M]
        if kautta and all(abs(ux * dx + uy * dy) < raja for dx, dy in kautta):
            return True
    return False


def _lidar_suunta(piste, tunnettu, janat):
    """Piilokulman toisen seinän suunta LiDARista. piste = mitattu kulmapiste, tunnettu =
    100-pisteistä sovitettu seinä (suora), jolle piilokulma tulee.

    Kelpaava LiDAR-seinä kulkee kulmapisteen kautta (jana alle LIDAR_PISTE_RAJA_M päässä,
    pisteen kohdalla tai lähellä janan päätä), ei ole tunnetun seinän suuntainen, ja saman
    suoran pätkistä jokin päättyy lähelle kohtaa, jossa suora leikkaa tunnetun seinän: seinä
    johtaa kulmapisteestä piilokulmaan, kun taas kulmapisteen toinen seinä johtaa muualle.
    Suunta sovitetaan kaikkien saman suoran pätkien päihin. Pieni poikkeama suorasta kulmasta
    (alle LIDAR_SUORA_RAJA_ASTE) on mittauskohinaa: silloin palautetaan tarkka kohtisuora.
    Palauttaa (suunta, poikkeama suorasta kulmasta asteina) tai None."""
    (px, py), (tx, ty) = tunnettu
    tp = math.hypot(tx, ty)
    paras = None
    for a, b, (ux, uy), pituus in janat or []:
        t = (piste[0] - a[0]) * ux + (piste[1] - a[1]) * uy
        if t < -LIDAR_PAA_RAJA_M or t > pituus + LIDAR_PAA_RAJA_M:
            continue
        etaisyys = abs((piste[0] - a[0]) * uy - (piste[1] - a[1]) * ux)
        if etaisyys > LIDAR_PISTE_RAJA_M:
            continue
        if math.degrees(math.acos(min(1.0, abs(ux * tx + uy * ty) / tp))) < LIDAR_MIN_KULMA_ASTE:
            continue
        seina = _lidar_seina(piste, (ux, uy), janat)
        _, (sx, sy) = _sovita_suora([p for j in seina for p in j[:2]])
        leikkaus = _leikkaus((piste, (sx, sy)), ((px, py), (tx, ty)))
        if leikkaus is None or min(math.dist(leikkaus, p) for j in seina for p in j[:2]) > LIDAR_PIILO_RAJA_M:
            continue
        if paras is None or etaisyys < paras[0]:
            kulma = math.degrees(math.acos(min(1.0, abs(sx * tx + sy * ty) / tp)))
            paras = (etaisyys, (sx, sy), 90.0 - kulma)
    if paras is None:
        return None
    (sx, sy), poikkeama = paras[1:]
    if poikkeama < LIDAR_SUORA_RAJA_ASTE:
        return (-ty / tp, tx / tp), poikkeama
    return (sx, sy), poikkeama


def _arvioi_jako(pts, ryhmat, alku_kiintea, loppu_kiintea, edellinen_xy, seuraava_xy, lidar=None):
    viimeinen = len(ryhmat) - 1
    for j, g in enumerate(ryhmat):
        if len(g) == 1:
            if not ((j == 0 and alku_kiintea) or (j == viimeinen and loppu_kiintea)):
                return None
        elif _suurin_poikkeama([pts[i] for i in g])[0] > LINJA_TOLERANSSI_M:
            return None

    suorat = [_sovita_suora([pts[i] for i in g]) if len(g) >= 2 else None for g in ryhmat]
    yksin_alku, yksin_loppu = len(ryhmat[0]) == 1, len(ryhmat[-1]) == 1
    oletus_90 = False
    lidar_poikkeamat = []
    if len(ryhmat) == 1:
        if yksin_alku:
            return None
    elif yksin_alku and yksin_loppu:
        # Seinä jatkuu samana ulokkeen (parveke, syvennys) molemmin puolin
        if len(ryhmat) < 3 or pts[0] == pts[-1]:
            return None
        suorat[0] = suorat[-1] = _suora_kahdesta(pts[0], pts[-1])
    elif yksin_alku or yksin_loppu:
        # Piilokulman toiselta seinältä on vain kulmapiste: suunta LiDARista tai suora kulma
        k, tunnettu = (0, suorat[1]) if yksin_alku else (-1, suorat[-2])
        _, (dx, dy) = tunnettu
        lidarista = _lidar_suunta(pts[k], tunnettu, lidar)
        if lidarista:
            suorat[k] = (pts[k], lidarista[0])
            lidar_poikkeamat.append(lidarista[1])
        else:
            suorat[k] = (pts[k], (-dy, dx))
            oletus_90 = True

    kulmat = []
    for s1, s2 in zip(suorat, suorat[1:]):
        x = _leikkaus(s1, s2)
        if x is None:
            return None
        kulmat.append(x)

    for j, g in enumerate(ryhmat):
        alku = kulmat[j - 1] if j > 0 else (pts[0] if alku_kiintea else None)
        loppu = kulmat[j] if j < viimeinen else (pts[-1] if loppu_kiintea else None)
        if not _seinapatkalla([pts[i] for i in g], alku, loppu, suorat[j]):
            return None

    suunnat = [s[1] for s in suorat]
    # Kulma LiDAR-seinään on mitattu, ei arvattu: sen vinoutta ei rangaista (muuten jako, jonka
    # kulma vain sattuu olemaan lähempänä suoraa, voittaisi mitatun vinon kulman)
    mitattu = ({0} if lidar_poikkeamat and yksin_alku else set()) | \
        ({len(suunnat) - 2} if lidar_poikkeamat and yksin_loppu else set())
    pisteet = sum(_suuntien_poikkeama(d1, d2) for i, (d1, d2) in enumerate(zip(suunnat, suunnat[1:]))
                  if i not in mitattu)
    if edellinen_xy is not None and alku_kiintea and edellinen_xy != pts[0]:
        pisteet += _suuntien_poikkeama(_suora_kahdesta(edellinen_xy, pts[0])[1], suunnat[0])
    if seuraava_xy is not None and loppu_kiintea and seuraava_xy != pts[-1]:
        pisteet += _suuntien_poikkeama(suunnat[-1], _suora_kahdesta(pts[-1], seuraava_xy)[1])
    pisteet += 5.0 * oletus_90 + 0.5 * len(kulmat)
    if lidar:
        # LiDARin kanssa ristiriitainen seinä (esim. kulmapiste ja toisen seinän piste samalla
        # suoralla) rangaistaan kuten suoran kulman oletus
        pisteet += 5.0 * sum(_lidar_ristiriita([pts[i] for i in g], suorat[j][1], lidar)
                             for j, g in enumerate(ryhmat) if len(g) >= 2)
        # Laskettu kulma, jonka lähellä ei ole LiDAR-seinää (esim. ulkona talosta), on epäuskottava
        pisteet += LIDAR_TUKEMATON_KULMA * sum(_lidar_etaisyys(x, lidar) > LIDAR_PIILO_RAJA_M for x in kulmat)
    return pisteet, {"suorat": suorat, "kulmat": kulmat, "oletus_90": oletus_90, "lidar": lidar_poikkeamat}


def _ketjun_suorat(pts, alku_kiintea, loppu_kiintea, edellinen_xy=None, seuraava_xy=None, lidar=None):
    """Jakaa pisteketjun peräkkäisiin seinälinjoihin ja laskee niiden väliset kulmat.

    pts: (e, n)-parit järjestyksessä. alku_kiintea / loppu_kiintea: onko ketjun
    ensimmäinen / viimeinen piste kulmapiste (5/8). Muuten pää on avoin (kaari jatkuu).
    Käy läpi jaot peräkkäisiin ryhmiin; kelvollisessa jaossa jokainen ryhmä on suoralla
    ja sen pisteet ovat oman seinäpätkänsä sisällä. Jaot muodostetaan vain suorista
    ryhmistä, joten mahdottomat jaot karsiutuvat heti. Paras jako on se, jonka kulmat
    ovat lähimpänä suoraa kulmaa ja jossa on vähiten kulmia. lidar = _lidar_janat()-janat
    piilokulman seinän suunnalle (ks. _lidar_suunta).
    Palauttaa {"suorat", "kulmat", "oletus_90", "lidar": [LiDAR-suunnan poikkeama 90°:sta]} tai None."""
    n = len(pts)
    if n > JAKO_MAX_PISTEET:
        return None

    def kelpaa(i, j):
        if i == j:
            return (i == 0 and alku_kiintea) or (j == n - 1 and loppu_kiintea)
        return _suurin_poikkeama(pts[i:j + 1])[0] <= LINJA_TOLERANSSI_M

    # loput[i] = loppuindeksit, joilla pisteet i..j muodostavat kelvollisen ryhmän
    loput = [[j for j in range(i, n) if kelpaa(i, j)] for i in range(n)]
    paras = None
    kokeiltu = 0
    pino = [(0, [])]
    while pino and kokeiltu < JAKO_MAX_KOKEILUT:
        alku, ryhmat = pino.pop()
        if alku == n:
            kokeiltu += 1
            tulos = _arvioi_jako(pts, ryhmat, alku_kiintea, loppu_kiintea, edellinen_xy, seuraava_xy, lidar)
            if tulos is not None and (paras is None or tulos[0] < paras[0]):
                paras = tulos
            continue
        for j in loput[alku]:
            pino.append((j + 1, ryhmat + [list(range(alku, j + 1))]))
    return None if paras is None else paras[1]


# ---------------------------------------------------------------------------
# Kaaret 4-pisteistä
# ---------------------------------------------------------------------------

def _ympyra_pisteista(pisteet):
    """Pienimmän neliösumman ympyrä (Kåsa); kolmella pisteellä tarkka. (keskipiste, säde) tai None."""
    cx0 = sum(p[0] for p in pisteet) / len(pisteet)
    cy0 = sum(p[1] for p in pisteet) / len(pisteet)
    rivit = [(p[0] - cx0, p[1] - cy0) for p in pisteet]
    # x^2 + y^2 + D x + E y + F = 0 -> normaaliyhtälöt
    m = [[0.0] * 3 for _ in range(3)]
    v = [0.0] * 3
    for x, y in rivit:
        r = (x, y, 1.0)
        oikea = -(x * x + y * y)
        for i in range(3):
            v[i] += r[i] * oikea
            for j in range(3):
                m[i][j] += r[i] * r[j]

    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))

    d = det(m)
    if abs(d) < 1e-12:
        return None
    ratkaisu = []
    for k in range(3):
        mk = [[v[i] if j == k else m[i][j] for j in range(3)] for i in range(3)]
        ratkaisu.append(det(mk) / d)
    D, E, F = ratkaisu
    cx, cy = -D / 2, -E / 2
    r2 = cx * cx + cy * cy - F
    if r2 <= 0:
        return None
    return (cx + cx0, cy + cy0), math.sqrt(r2)


def _suoran_ja_ympyran_leikkaus(suora, keski, sade, lahella):
    """Suoran ja ympyrän leikkauspisteistä se, joka on lähimpänä pistettä 'lahella'."""
    (px, py), (dx, dy) = suora
    fx, fy = px - keski[0], py - keski[1]
    b = 2 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - sade * sade
    disk = b * b - 4 * c
    if disk < 0:
        return None
    s = math.sqrt(disk)
    ehdokkaat = [(px + dx * t, py + dy * t) for t in ((-b - s) / 2, (-b + s) / 2)]
    return min(ehdokkaat, key=lambda q: math.hypot(q[0] - lahella[0], q[1] - lahella[1]))


def _pyoristys(s1, s2, piste, seina1, seina2):
    """Ympyrä, joka sivuaa molempia seinälinjoja ja kulkee kaaripisteen kautta
    (pyöristetty kulma). Palauttaa (keskipiste, säde, sivuamispiste1, sivuamispiste2) tai None."""
    v = _leikkaus(s1, s2)
    if v is None:
        return None

    def yksikko(p):
        pituus = math.hypot(p[0] - v[0], p[1] - v[1])
        return ((p[0] - v[0]) / pituus, (p[1] - v[1]) / pituus), pituus

    (u1, et1), (u2, et2) = yksikko(seina1), yksikko(seina2)
    puolikulma = math.acos(max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))) / 2
    wx, wy = u1[0] + u2[0], u1[1] + u2[1]
    wl = math.hypot(wx, wy)
    if wl < 1e-9:
        return None
    w = (wx / wl, wy / wl)
    # |v + t*w - piste| = t*sin(puolikulma)
    gx, gy = v[0] - piste[0], v[1] - piste[1]
    a = math.cos(puolikulma) ** 2
    b = 2 * (gx * w[0] + gy * w[1])
    c = gx * gx + gy * gy
    disk = b * b - 4 * a * c
    if disk < 0 or a < 1e-12:
        return None
    ratkaisut = []
    for t in ((-b - math.sqrt(disk)) / (2 * a), (-b + math.sqrt(disk)) / (2 * a)):
        if t <= 0:
            continue
        keski = (v[0] + t * w[0], v[1] + t * w[1])
        etaisyys = t * math.cos(puolikulma)
        t1 = (v[0] + u1[0] * etaisyys, v[1] + u1[1] * etaisyys)
        t2 = (v[0] + u2[0] * etaisyys, v[1] + u2[1] * etaisyys)
        kelpaa = etaisyys <= et1 + LINJA_TOLERANSSI_M and etaisyys <= et2 + LINJA_TOLERANSSI_M
        ratkaisut.append((kelpaa, t * math.sin(puolikulma), keski, t1, t2))
    if not ratkaisut:
        return None
    _, sade, keski, t1, t2 = max(ratkaisut, key=lambda r: (r[0], r[1]))
    return keski, sade, t1, t2


def _bulge(keski, alku, kautta, loppu):
    """DXF:n bulge (tan(kaarikulma/4)) kaarelle alku -> kautta -> loppu, positiivinen vastapäivään."""
    def kulma(p):
        return math.atan2(p[1] - keski[1], p[0] - keski[0])

    def vastapaivaan(a, b):
        return (b - a) % (2 * math.pi)

    a0, am, a1 = kulma(alku), kulma(kautta), kulma(loppu)
    if vastapaivaan(a0, am) <= vastapaivaan(a0, a1):
        kaarikulma = vastapaivaan(a0, a1)
    else:
        kaarikulma = -vastapaivaan(a1, a0)
    return math.tan(kaarikulma / 4)


def _ratkaise_kaari(kaaripisteet, vasen, oikea, nimi, varoitukset):
    """Kaari kaaripisteiden kautta. vasen/oikea = ("piste", xy) kun kaaren pää on mitattu
    kulmapiste, tai ("suora", suora, lähin_seinäpiste) kun pää on piilossa seinälinjalla.
    Palauttaa (alku_xy, loppu_xy, bulge) tai None."""
    kp = kaaripisteet
    kiinteat = [v[1] for v in (vasen, oikea) if v[0] == "piste"]
    alku = vasen[1] if vasen[0] == "piste" else None
    loppu = oikea[1] if oikea[0] == "piste" else None
    ympyra = None

    if len(kiinteat) == 2:
        ympyra = _ympyra_pisteista([alku] + kp + [loppu])
    elif len(kiinteat) == 1:
        if len(kp) < 2:
            varoitukset.append(f"Kaari {nimi}: toinen pää ei näy, tarvitaan vähintään 2 kaaripistettä.")
            return None
        ympyra = _ympyra_pisteista(kiinteat + kp)
    else:
        s1, s2 = vasen[1], oikea[1]
        if len(kp) >= 3:
            ympyra = _ympyra_pisteista(kp)
        elif _leikkaus(s1, s2) is not None:
            tulos = _pyoristys(s1, s2, kp[len(kp) // 2], vasen[2], oikea[2])
            if tulos is None:
                return None
            keski, sade, alku, loppu = tulos
            ympyra = (keski, sade)
            varoitukset.append(f"Kaari {nimi}: päät eivät näy, oletettu että kaari sivuaa molempia seiniä.")
        elif len(kp) == 2:
            # Sama seinälinja, kaksi kaaripistettä: keskipiste seinälinjalla (puoliympyrä)
            mx, my = (kp[0][0] + kp[1][0]) / 2, (kp[0][1] + kp[1][1]) / 2
            dx, dy = kp[1][0] - kp[0][0], kp[1][1] - kp[0][1]
            pituus = math.hypot(dx, dy)
            keski = _leikkaus(s1, ((mx, my), (-dy / pituus, dx / pituus)))
            if keski is None:
                return None
            ympyra = (keski, math.hypot(kp[0][0] - keski[0], kp[0][1] - keski[1]))
            varoitukset.append(
                f"Kaari {nimi}: päät eivät näy ja kaaripisteitä on vain 2 -- oletettu "
                "keskipiste seinälinjalle (puoliympyrä). Mittaa 3 kaaripistettä varmemman tuloksen saamiseksi."
            )
        else:
            varoitukset.append(
                f"Kaari {nimi}: päät eivät näy samalla seinälinjalla, tarvitaan vähintään 3 kaaripistettä."
            )
            return None

    if ympyra is None:
        return None
    keski, sade = ympyra
    if alku is None:
        alku = _suoran_ja_ympyran_leikkaus(vasen[1], keski, sade, vasen[2])
    if loppu is None:
        loppu = _suoran_ja_ympyran_leikkaus(oikea[1], keski, sade, oikea[2])
    if alku is None or loppu is None:
        varoitukset.append(f"Kaari {nimi}: kaari ei leikkaa seinälinjaa.")
        return None

    poikkeama = max(abs(math.hypot(p[0] - keski[0], p[1] - keski[1]) - sade) for p in kp + kiinteat)
    if poikkeama > LINJA_TOLERANSSI_M:
        varoitukset.append(
            f"Kaari {nimi}: kaaripisteet poikkeavat ympyrästä enimmillään {poikkeama:.3f} m."
        )
    return alku, loppu, _bulge(keski, alku, kp[len(kp) // 2], loppu)


# ---------------------------------------------------------------------------
# Kulmapisteiden välinen osuus
# ---------------------------------------------------------------------------

def _valin_karjet(a, valit, b, karki_a, edellinen_xy, seuraava_xy, varoitukset, lidar=None):
    """Kärjet kulmapisteiden A ja B välille (ei A:ta eikä B:tä). valit = 100- ja
    4-pisteet järjestyksessä. Kaaren bulge asetetaan kaaren alkukärjelle, joka voi
    olla karki_a. Palauttaa listan kärkiä tai None, jos väliä ei saada ratkaistua."""
    osat = []
    for p in valit:
        laji = "kaari" if koodi_numeroksi(p.get("koodi")) == KOODI_KAARI else "linja"
        if osat and osat[-1][0] == laji:
            osat[-1][1].append(p)
        else:
            osat.append((laji, [p]))

    linjat = {}
    for i, (laji, ps) in enumerate(osat):
        if laji != "linja":
            continue
        alku_k, loppu_k = i == 0, i == len(osat) - 1
        pts = ([_xy(a)] if alku_k else []) + [_xy(p) for p in ps] + ([_xy(b)] if loppu_k else [])
        tulos = _ketjun_suorat(pts, alku_k, loppu_k,
                               edellinen_xy if alku_k else None, seuraava_xy if loppu_k else None, lidar)
        if tulos is None:
            return None
        if tulos["oletus_90"]:
            varoitukset.append(
                f"Piilokulma pisteiden {a.get('nimi')} ja {b.get('nimi')} välissä: toiselta seinältä "
                f"ei ole linjapistettä ({', '.join(str(p.get('nimi')) for p in ps)}), "
                "oletettu suora kulma (90°)."
            )
        for poikkeama in tulos["lidar"]:
            if poikkeama < LIDAR_SUORA_RAJA_ASTE:
                varoitukset.append(
                    f"Piilokulma pisteiden {a.get('nimi')} ja {b.get('nimi')} välissä: LiDAR vahvistaa "
                    f"suoran kulman (poikkeama {poikkeama:.1f}°).")
            else:
                varoitukset.append(
                    f"Piilokulma pisteiden {a.get('nimi')} ja {b.get('nimi')} välissä: toisen seinän suunta "
                    f"otettiin LiDARista (poikkeaa suorasta kulmasta {poikkeama:.1f}°).")
        linjat[i] = tulos

    if len(osat) == 1 and osat[0][0] == "linja":
        nimet = f"{osat[0][1][0].get('nimi')}-{osat[0][1][-1].get('nimi')}"
        return [_laskettu_karki(x, a, b, f"kulma ({nimet})") for x in linjat[0]["kulmat"]]

    uudet = []
    viimeisin = karki_a
    for i, (laji, ps) in enumerate(osat):
        if laji == "linja":
            for x in linjat[i]["kulmat"]:
                viimeisin = _laskettu_karki(x, a, b, f"kulma ({ps[0].get('nimi')}...)")
                uudet.append(viimeisin)
            continue
        nimi = f"{ps[0].get('nimi')}-{ps[-1].get('nimi')}" if len(ps) > 1 else str(ps[0].get("nimi"))
        if i == 0:
            vasen = ("piste", _xy(a))
        else:
            vasen = ("suora", linjat[i - 1]["suorat"][-1], _xy(osat[i - 1][1][-1]))
        if i == len(osat) - 1:
            oikea = ("piste", _xy(b))
        else:
            oikea = ("suora", linjat[i + 1]["suorat"][0], _xy(osat[i + 1][1][0]))
        kaari = _ratkaise_kaari([_xy(p) for p in ps], vasen, oikea, nimi, varoitukset)
        if kaari is None:
            return None
        alku_xy, loppu_xy, bulge = kaari
        if vasen[0] == "suora":
            viimeisin = _laskettu_karki(alku_xy, a, b, f"kaaren alku ({nimi})")
            uudet.append(viimeisin)
        viimeisin["bulge"] = bulge
        if oikea[0] == "suora":
            viimeisin = _laskettu_karki(loppu_xy, a, b, f"kaaren loppu ({nimi})")
            uudet.append(viimeisin)
    return uudet


def muodosta_karjet(jarjestetty, suljettu, lidar=None):
    """Muuttaa järjestetyn pistelistan viivan kärjiksi. Palauttaa (kärjet, varoitukset).

    Kahden kulman välin piilokulmat ratkaistaan viereisten seinien suunnista: edellinen seinä
    tulee jo lasketuista kärjistä, seuraava seinä B-kulman jälkeisestä kärjestä. Seuraavaa
    kärkeä ei vielä tunneta, kun väliä ratkaistaan, joten viiva lasketaan kahdesti: ensin
    seuraavana suuntana vain kulmapiste (5/8), sitten ensimmäisen kierroksen B:n jälkeinen
    kärki (voi olla laskettu piilokulma). Pelkkä B:n jälkeinen 100-piste voisi olla seuraavan
    piilokulman takana, jolloin suunta olisi vino (Osuuskunnantie 60). lidar = _lidar_janat()-janat
    piilokulmille."""
    ankkurit = [i for i, p in enumerate(jarjestetty)
                if koodi_numeroksi(p.get("koodi")) in (KOODI_ALKU_LOPPU, KOODI_KULMA)]
    if not ankkurit:
        return [], ["Jaksossa ei ole yhtään kulmapistettä (5 tai 8)."]
    karjet, _, b_kohdat = _muodosta_karjet(jarjestetty, suljettu, ankkurit, None, lidar=lidar)
    seuraavat = []
    for kohta in b_kohdat:
        if kohta + 1 < len(karjet):
            seuraavat.append((karjet[kohta + 1]["e"], karjet[kohta + 1]["n"]))
        elif suljettu and len(karjet) > 1:
            seuraavat.append((karjet[1]["e"], karjet[1]["n"]) if kohta == 0 else (karjet[0]["e"], karjet[0]["n"]))
        else:
            seuraavat.append(None)
    # Suljetun viivan ensimmäisen välin edellinen seinä: ensimmäisen kierroksen viimeinen kärki
    edellinen_alku = (karjet[-1]["e"], karjet[-1]["n"]) if suljettu and len(karjet) > 1 else None
    karjet, varoitukset, _ = _muodosta_karjet(jarjestetty, suljettu, ankkurit, seuraavat, edellinen_alku, lidar)
    return karjet, varoitukset


def _muodosta_karjet(jarjestetty, suljettu, ankkurit, seuraavat, edellinen_alku=None, lidar=None):
    """muodosta_karjet:n yksi kierros. seuraavat = välikohtainen seuraavan seinän suuntapiste
    (B:n jälkeinen kärki edelliseltä kierrokselta) tai None: silloin käytetään B:n jälkeistä
    pistettä vain, jos se on kulmapiste. edellinen_alku = suljetun viivan ensimmäisen välin
    edellisen seinän suuntapiste (muuten viimeinen kulmapiste). Palauttaa (kärjet, varoitukset,
    B-kärkien kohdat)."""
    varoitukset = []
    n = len(jarjestetty)
    karjet = []
    b_kohdat = []
    valit = list(zip(ankkurit, ankkurit[1:]))
    if suljettu:
        valit.append((ankkurit[-1], ankkurit[0] + n))

    karjet.append(_karki(jarjestetty[ankkurit[0]]))
    for vali, (ia, ib) in enumerate(valit):
        a = jarjestetty[ia % n]
        b = jarjestetty[ib % n]
        hs = [jarjestetty[i % n] for i in range(ia + 1, ib)]
        uudet = []

        if hs:
            karki_a = karjet[-1]
            if a is b:
                # Ainoa kulmapiste: talo kierretään 8-pisteestä takaisin siihen, joten
                # ketjun molemmat päät ovat sama kiinteä piste.
                uudet = _valin_karjet(a, hs, b, karki_a, None, None, varoitukset, lidar)
                if uudet is None:
                    karki_a["bulge"] = 0.0
                    varoitukset.append(
                        "Viivassa on vain yksi kulmapiste, eikä linjapisteistä saatu selviä "
                        "seinälinjoja -- viiva piirretty pisteiden kautta."
                    )
                    uudet = [_karki(h) for h in hs]
            else:
                if len(karjet) >= 2:
                    edellinen = (karjet[-2]["e"], karjet[-2]["n"])
                elif suljettu:
                    edellinen = edellinen_alku or _xy(jarjestetty[ankkurit[-1]])
                else:
                    edellinen = None
                if seuraavat is not None:
                    seuraava = seuraavat[vali]
                else:
                    seuraava_i = ib + 1
                    seuraava = (_xy(jarjestetty[seuraava_i % n])
                                if (seuraava_i < n or suljettu) and (seuraava_i % n) in ankkurit else None)
                uudet = _valin_karjet(a, hs, b, karki_a, edellinen, seuraava, varoitukset, lidar)
                if uudet is None:
                    karki_a["bulge"] = 0.0
                    varoitukset.append(
                        f"Pisteistä {', '.join(str(h.get('nimi')) for h in hs)} ei saatu selviä "
                        f"seinälinjoja kulmien {a.get('nimi')} ja {b.get('nimi')} välille -- "
                        "viiva piirretty pisteiden kautta."
                    )
                    uudet = [_karki(h) for h in hs]

            for karki in uudet:
                if karki["laji"] == "laskettu":
                    _tarkista_jatke(karki, [a, b] + hs, varoitukset)

        karjet.extend(uudet)
        if not (suljettu and ib == ankkurit[0] + n):
            karjet.append(_karki(b))
            b_kohdat.append(len(karjet) - 1)
        else:
            b_kohdat.append(0)

    return karjet, varoitukset, b_kohdat


def _kaaren_pisteet(p1, p2, bulge, askel_aste=3.0):
    """Bulge-kaaren pisteet p1 -> p2 (p1 ja p2 mukana)."""
    kaarikulma = 4 * math.atan(bulge)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    janne = math.hypot(dx, dy)
    if janne < 1e-9:
        return [p1, p2]
    h = janne / 2 / math.tan(kaarikulma / 2)
    keski = ((p1[0] + p2[0]) / 2 - dy / janne * h, (p1[1] + p2[1]) / 2 + dx / janne * h)
    sade = math.hypot(p1[0] - keski[0], p1[1] - keski[1])
    a0 = math.atan2(p1[1] - keski[1], p1[0] - keski[0])
    maara = max(2, int(abs(math.degrees(kaarikulma)) / askel_aste) + 1)
    pisteet = [(keski[0] + sade * math.cos(a0 + kaarikulma * i / maara),
                keski[1] + sade * math.sin(a0 + kaarikulma * i / maara)) for i in range(maara + 1)]
    pisteet[0], pisteet[-1] = p1, p2
    return pisteet


def viivan_pisteet(viiva):
    """Viivan (e, n)-pisteet piirtämistä varten: kaaret tihennetään pisteiksi ja
    suljettu viiva palaa alkupisteeseen."""
    return [(e, n) for e, n, _ in viivan_pisteet_z(viiva)]


def viivan_pisteet_z(viiva):
    """Kuten viivan_pisteet, mutta (e, n, korkeus): kärjen korkeus on sen mitattu (laskettu
    kulma: viereisten pisteiden keskiarvo) korkeus, ja kaaren pisteiden korkeus
    interpoloidaan kärkien välillä. Kärjelle, jolta korkeus puuttuu, käytetään kärkien
    keskiarvoa; jos korkeuksia ei ole lainkaan, korkeus on None."""
    karjet = viiva["karjet"]
    if not karjet:
        return []
    tunnetut = [k["z"] for k in karjet if k.get("z") is not None]
    oletus = sum(tunnetut) / len(tunnetut) if tunnetut else None

    def z(k):
        return k["z"] if k.get("z") is not None else oletus

    parit = list(zip(karjet, karjet[1:]))
    if viiva["suljettu"]:
        parit.append((karjet[-1], karjet[0]))
    tulos = [(karjet[0]["e"], karjet[0]["n"], z(karjet[0]))]
    for k1, k2 in parit:
        p1, p2 = (k1["e"], k1["n"]), (k2["e"], k2["n"])
        z1, z2 = z(k1), z(k2)
        if abs(k1.get("bulge") or 0.0) > 1e-12:
            kaari = _kaaren_pisteet(p1, p2, k1["bulge"])
            n = len(kaari) - 1
            tulos.extend((x, y, None if z1 is None else z1 + (z2 - z1) * i / n)
                         for i, (x, y) in enumerate(kaari) if i > 0)
        else:
            tulos.append((p2[0], p2[1], z2))
    return tulos


# ---------------------------------------------------------------------------
# Tuloksen tarkistus: risteäminen ja epäselvät kohdat
# ---------------------------------------------------------------------------

EPASELVAT_VAROITUKSET = ("oletettu suora kulma", "ei saatu selviä", "päässä lähimmästä")


def _janat_leikkaavat(p1, p2, q1, q2):
    def puoli(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = puoli(q1, q2, p1), puoli(q1, q2, p2)
    d3, d4 = puoli(p1, p2, q1), puoli(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def menee_ristiin(viiva):
    """Leikkaako viiva (kaaret tihennettyinä) itsensä."""
    pisteet = viivan_pisteet(viiva)
    janat = list(zip(pisteet, pisteet[1:]))
    for i in range(len(janat)):
        for k in range(i + 2, len(janat)):
            if viiva["suljettu"] and i == 0 and k == len(janat) - 1:
                continue  # suljetun viivan ensimmäinen ja viimeinen jana ovat naapurit
            if _janat_leikkaavat(*janat[i], *janat[k]):
                return True
    return False


def _jakson_tulos(jakso, tapa, lidar=None):
    jarjestetty = jarjesta_jakso(jakso["alku"], jakso["valit"], jakso["loppu"], tapa)
    karjet, varoitukset = muodosta_karjet(jarjestetty, suljettu=jakso["suljettu"], lidar=lidar)
    ristissa = menee_ristiin({"karjet": karjet, "suljettu": jakso["suljettu"]})
    epaselvia = sum(1 for v in varoitukset if any(t in v for t in EPASELVAT_VAROITUKSET))
    return karjet, varoitukset, (ristissa, epaselvia)


def _jarjesta_lidarin_mukaan(alku, valit, loppu, lidar_kartta, lidar):
    """Järjestys LiDAR-ääriviivasta (lidar_aariviivat) kuten kantakartasta."""
    jarjestetty, syy = jarjesta_kantakartan_mukaan(alku, valit, loppu, lidar_kartta, lidar)
    if syy:
        syy = syy.replace("kantakartan", "LiDAR-ääriviivan").replace("kantakartalla", "LiDAR-ääriviivalla")
    return jarjestetty, syy


def _jakson_karjet(jakso, tapa, kantakartta=None, lidar=None, lidar_kartta=None):
    """Jakson kärjet. Automaattisessa järjestyksessä ("lyhin") järjestys päätellään ensin
    seinälinjoista; jos LiDAR-ääriviiva tai kantakartta on annettu, tulosta verrataan niihin
    ja erosta varoitetaan. Jos päättely ei onnistu, järjestys otetaan LiDAR-ääriviivasta,
    sitten kantakartasta ja viimeisenä lyhimmästä reitistä (varoituksen kanssa). Lyhin reitti tarkistetaan: jos viiva menee
    ristiin tai siinä on epäselviä kohtia, verrataan mittausjärjestykseen ja valitaan parempi."""
    if tapa == "lyhin_vanha":   # vertailua varten: lyhin reitti ilman päättelyä seinälinjoista
        return _lyhin_tarkistettuna(jakso, lidar)
    if tapa == "lyhin":
        valin = f"{jakso['alku'].get('nimi')}-{jakso['loppu'].get('nimi')}"
        jarjestetty, syy = jarjesta_suorakulmaisesti(jakso["alku"], jakso["valit"], jakso["loppu"], lidar)
        kartan, kartan_syy = (jarjesta_kantakartan_mukaan(jakso["alku"], jakso["valit"], jakso["loppu"], kantakartta,
                                                          lidar)
                              if kantakartta else (None, None))
        lidarin, lidarin_syy = (_jarjesta_lidarin_mukaan(jakso["alku"], jakso["valit"], jakso["loppu"], lidar_kartta,
                                                         lidar)
                                if lidar_kartta else (None, None))
        if jarjestetty is not None:
            karjet, varoitukset = muodosta_karjet(jarjestetty, suljettu=jakso["suljettu"], lidar=lidar)
            if lidarin is not None and not _sama_jarjestys(jarjestetty, lidarin, jakso["suljettu"]):
                varoitukset = varoitukset + [
                    f"Järjestys poikkeaa LiDAR-ääriviivasta jaksolla {valin}. Tarkista viiva."]
            if kartan is not None and not _sama_jarjestys(jarjestetty, kartan, jakso["suljettu"]):
                varoitukset = varoitukset + [
                    f"Järjestys poikkeaa kantakartasta jaksolla {valin}. Tarkista viiva "
                    "(talo voi olla muuttunut kartan jälkeen)."]
            elif kantakartta and kartan is None and kartan_syy and "ei osu" in kartan_syy:
                varoitukset = varoitukset + [
                    f"Pisteet eivät vastaa kantakartan taloa jaksolla {valin} ({kartan_syy}). "
                    "Talo voi olla muuttunut kartan jälkeen; tarkista viiva."]
            return karjet, varoitukset
        if lidarin is not None:
            karjet, varoitukset = muodosta_karjet(lidarin, suljettu=jakso["suljettu"], lidar=lidar)
            return karjet, varoitukset + [
                f"Järjestys otettiin LiDAR-ääriviivasta jaksolla {valin}, koska sitä ei voitu päätellä "
                f"seinälinjoista ({syy})."]
        if kartan is not None:
            karjet, varoitukset = muodosta_karjet(kartan, suljettu=jakso["suljettu"], lidar=lidar)
            return karjet, varoitukset + [
                f"Järjestys otettiin kantakartasta jaksolla {valin}, koska sitä ei voitu päätellä "
                f"seinälinjoista ({syy}). Tarkista viiva."]
        karjet, varoitukset = _lyhin_tarkistettuna(jakso, lidar)
        if syy and len(jakso["valit"]) >= 2:
            lisa = (f" eikä LiDAR-ääriviivasta ({lidarin_syy})" if lidarin_syy else "") + \
                (f" eikä kantakartasta ({kartan_syy})" if kartan_syy else "")
            varoitukset = varoitukset + [
                f"Kulmien järjestystä ei voitu päätellä seinälinjoista jaksolla {valin} ({syy}){lisa}, "
                "joten käytettiin lyhintä reittiä. Tarkista viiva."]
        vinot = _vinot_kulmat(karjet, jakso["suljettu"])
        if vinot and len(jakso["valit"]) >= 2:
            varoitukset = varoitukset + [
                f"Viivassa on vinoja kulmia jaksolla {valin} (pisteet {', '.join(vinot)}) -- "
                "tarkista, että pisteet on yhdistetty oikein."]
        return karjet, varoitukset
    return _jakson_tulos(jakso, tapa, lidar)[:2]


def _lyhin_tarkistettuna(jakso, lidar=None):
    """Lyhin reitti. (Koveralla talolla se voi oikaista pitkän seinän, jolla ei ole
    välipisteitä, joten ristiin menevää tai epäselvää tulosta verrataan mittausjärjestykseen.)"""
    karjet, varoitukset, arvo = _jakson_tulos(jakso, "lyhin", lidar)
    if arvo == (False, 0):
        return karjet, varoitukset
    m_karjet, m_varoitukset, m_arvo = _jakson_tulos(jakso, "mittaus", lidar)
    if m_arvo < arvo:
        syy = "menee ristiin" if arvo[0] else "jättää kulmia epäselviksi"
        return m_karjet, m_varoitukset + [
            f"Lyhin reitti {syy} jaksolla {jakso['alku'].get('nimi')}-{jakso['loppu'].get('nimi')}, "
            "joten käytettiin mittausjärjestystä."]
    if arvo[0]:
        varoitukset = varoitukset + [
            f"Seinälinja menee ristiin jaksolla {jakso['alku'].get('nimi')}-{jakso['loppu'].get('nimi')} "
            "-- tarkista pisteiden järjestys (kokeile mittausjärjestystä)."]
    return karjet, varoitukset


# ---------------------------------------------------------------------------
# Pääfunktio
# ---------------------------------------------------------------------------

def muodosta_seinalinjat(pisteet, tapa="lyhin", kantakartta=None, lidar=None, lidar_paatelty=None):
    """pisteet = jobxml_tuonti.jasenna_tyo():n toinen paluuarvo (mittausjärjestyksessä).
    tapa = "lyhin" (automaattinen), "lyhin_vanha" (lyhin reitti ilman päättelyä
    seinälinjoista) tai "mittaus". kantakartta = rakennusten renkaat (ks. "Kantakartta
    apuna"); käytetään vain automaattisessa järjestyksessä.

    Useampi talo samaan tiedostoon: viivan numero koodin perään ("8 2", "5 2"), ks.
    viivan_numero. Ilman numeroa piste kuuluu viivaan 1. Kohdekoodit (RAK 8, KATOS 8) ja
    niiden valikkotiedot (Sokkeli) erottavat viivat ilman numeroa, ks. viivan_avain.
    lidar = LiDAR-seinät [((e0, n0), (e1, n1)), ...] (EPSG:3879, esim. lidarpipen seinälinja-DXF:n
    SEINA-taso): piilokulman seinän suunta otetaan niistä suoran kulman oletuksen sijaan, ja jos
    seinistä syntyy suljettu ääriviiva (lidar_aariviivat), automaattinen järjestys otetaan siitä,
    kun sitä ei voi päätellä seinälinjoista (ennen kantakarttaa). lidar_paatelty = DXF:n PAATELTY-taso
    (lidarpipen ääriviivan päätellyt osat): vain ääriviivaan, ei piilokulmiin.

    Palauttaa {"viivat": [{"karjet": [...], "suljettu": bool, "numero": viivan numero,
                           "avain": viivan_avain, "nimi": viivan_nimi}],
               "pisteet": [kaikki seinälinjan mitatut pisteet],
               "pois_jatetyt": [...], "varoitukset": [...]}"""
    jaksot, pois_jatetyt = jaa_jaksoihin(pisteet)
    lidar_kartta = lidar_aariviivat(lidar, lidar_paatelty) if lidar else []
    lidar = _lidar_janat(lidar)
    avaimet = sorted({viivan_avain(p) for p in _seinalinjapisteet(pisteet)})
    monta = len(avaimet) > 1
    varoitukset = []
    viivat = []
    for avain in avaimet:
        nimi = viivan_nimi(avain)
        numero = avain[2]
        etuliite = f"{nimi}: " if monta else ""
        viivan_jaksot = [j for j in jaksot if j["viiva"] == avain]
        pois = [p for p in pois_jatetyt if viivan_avain(p) == avain]
        if not viivan_jaksot:
            varoitukset.append(f"Viivalla {nimi.removeprefix('Viiva ')} ei ole 8-pistettä, joten sen pisteitä "
                               "ei otettu viivaan: " + ", ".join(str(p.get("nimi")) for p in pois))
            continue
        if pois:
            varoitukset.append(
                etuliite + "Ensimmäistä 8-pistettä ennen tai viimeisen 8-pisteen jälkeen mitattuja pisteitä "
                "ei otettu viivaan: " + ", ".join(str(p.get("nimi")) for p in pois)
            )
        if viivan_jaksot[0]["suljettu"]:
            karjet, v = _jakson_karjet(viivan_jaksot[0], tapa, kantakartta, lidar, lidar_kartta)
            varoitukset.extend(etuliite + x for x in v)
            viivat.append({"karjet": karjet, "suljettu": True, "numero": numero, "avain": avain, "nimi": nimi})
            continue
        # Jaksot 8a-8b, 8b-8c ... yhdistetään yhdeksi jatkuvaksi viivaksi.
        yhdistetyt = []
        for j in viivan_jaksot:
            karjet, v = _jakson_karjet(j, tapa, kantakartta, lidar, lidar_kartta)
            varoitukset.extend(etuliite + x for x in v)
            if yhdistetyt and karjet:
                # Jakson alkukärki (8) korvaa edellisen jakson loppukärjen, koska
                # siinä on mahdollisen kaaren bulge.
                yhdistetyt[-1] = karjet[0]
                karjet = karjet[1:]
            yhdistetyt.extend(karjet)
        viivat.append({"karjet": yhdistetyt, "suljettu": False, "numero": numero, "avain": avain, "nimi": nimi})

    kaytetyt = []
    for j in jaksot:
        for p in [j["alku"]] + j["valit"] + [j["loppu"]]:
            if not any(p is k for k in kaytetyt):
                kaytetyt.append(p)

    return {"viivat": viivat, "pisteet": kaytetyt, "pois_jatetyt": pois_jatetyt, "varoitukset": varoitukset}


# ---------------------------------------------------------------------------
# Esikatselukuva ja DXF-vienti
# ---------------------------------------------------------------------------

def rajaa_viivaan(tulos, nimi):
    """muodosta_seinalinjat()-tulos, jossa on vain viiva nimi (viivan_nimi) ja sen pisteet."""
    viivat = [v for v in tulos["viivat"] if v["nimi"] == nimi]
    avaimet = {v["avain"] for v in viivat}
    return {**tulos, "viivat": viivat, "pisteet": [p for p in tulos["pisteet"] if viivan_avain(p) in avaimet]}


_KOODIVARIT = {KOODI_ALKU_LOPPU: "tab:green", KOODI_KULMA: "tab:blue", KOODI_LINJA: "tab:orange",
               KOODI_KAARI: "tab:purple"}


def piirra_seinalinja_kartta(tulos, out_path, hae_tausta=None, marginaali_m=5.0):
    """Esikatselukuva. hae_tausta(bbox_3879) -> kuvataulukko on valinnainen
    taustakartan hakufunktio (esim. Helsingin kantakartta); jos haku epäonnistuu,
    kuva piirretään ilman taustaa."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8))

    viivojen_pisteet = [viivan_pisteet(v) for v in tulos["viivat"]]
    xs = [p["e"] for p in tulos["pisteet"]] + [q[0] for vp in viivojen_pisteet for q in vp]
    ys = [p["n"] for p in tulos["pisteet"]] + [q[1] for vp in viivojen_pisteet for q in vp]
    bbox = None
    if xs:
        keski_x, keski_y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        puolisivu = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + marginaali_m
        bbox = [keski_x - puolisivu, keski_y - puolisivu, keski_x + puolisivu, keski_y + puolisivu]
        if hae_tausta is not None:
            try:
                kuva = hae_tausta(bbox)
                ax.imshow(kuva, extent=(bbox[0], bbox[2], bbox[1], bbox[3]), zorder=0)
            except Exception as e:
                print(f"Huom: seinälinjan taustakartan haku epäonnistui ({e}) -- jatketaan ilman taustaa.")
    for viiva, vp in zip(tulos["viivat"], viivojen_pisteet):
        karjet = viiva["karjet"]
        if vp:
            ax.plot([q[0] for q in vp], [q[1] for q in vp], "-", color="black", linewidth=1.5, zorder=1)
        lasketut = [k for k in karjet if k["laji"] == "laskettu"]
        if lasketut:
            selite_on = "laskettu kulma" in ax.get_legend_handles_labels()[1]
            ax.scatter([k["e"] for k in lasketut], [k["n"] for k in lasketut],
                       marker="x", color="tab:red", s=60, zorder=3, label=None if selite_on else "laskettu kulma")
        if len(tulos["viivat"]) > 1 and karjet:
            ax.annotate(viiva["nimi"], (karjet[0]["e"], karjet[0]["n"]),
                        textcoords="offset points", xytext=(-10, -14), fontsize=9, fontweight="bold")

    for koodi, vari in _KOODIVARIT.items():
        ryhma = [p for p in tulos["pisteet"] if koodi_numeroksi(p.get("koodi")) == koodi]
        if ryhma:
            ax.scatter([p["e"] for p in ryhma], [p["n"] for p in ryhma],
                       color=vari, s=30, zorder=2, label=f"koodi {koodi}")
    for p in tulos["pisteet"]:
        ax.annotate(str(p.get("nimi")), (p["e"], p["n"]), textcoords="offset points",
                    xytext=(4, 4), fontsize=8)

    if bbox:
        ax.set_xlim(bbox[0], bbox[2])
        ax.set_ylim(bbox[1], bbox[3])
    ax.set_aspect("equal")
    ax.ticklabel_format(useOffset=False, style="plain")
    ax.locator_params(nbins=5)
    ax.tick_params(axis="x", labelrotation=30)
    ax.set_xlabel("E (ETRS-GK25)")
    ax.set_ylabel("N (ETRS-GK25)")
    ax.grid(True, linewidth=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def dxf_taso(avain):
    """Viivan DXF-taso: numerokoodit SEINALINJA, kohdekoodit omalle tasolleen kohteen ja
    valikkotietojen mukaan (RAK + Sokkeli -> SEINALINJA_RAK_SOKKELI). Viivan numero ei vaikuta."""
    kohde, valinnat, _ = avain
    if not kohde:
        return "SEINALINJA"
    nimi = "_".join(["SEINALINJA", kohde, *valinnat]).upper()
    # DXF:n tasonimessä eivät käy < > / \ " : ; ? * | = ` eivätkä välilyönnit
    return "".join("_" if m in '<>/\\":;?*|=` ' else m for m in nimi)


def kirjoita_dxf(tulos, out_path):
    """Tasot: SEINALINJA (LWPOLYLINE), MITATUT_PISTEET (POINT), PISTETEKSTIT (TEXT),
    LASKETUT_KULMAT (POINT). Tekstit ovat omalla tasollaan, koska QGIS tuo DXF:n
    tekstit pisteinä -- tason voi piilottaa (MicroStationissa ne näkyvät tekstinä)."""
    import ezdxf

    doc = ezdxf.new("R2010")
    doc.layers.add("SEINALINJA", color=7)
    doc.layers.add("MITATUT_PISTEET", color=3)
    doc.layers.add("PISTETEKSTIT", color=8)
    doc.layers.add("LASKETUT_KULMAT", color=1)
    msp = doc.modelspace()

    for viiva in tulos["viivat"]:
        taso = dxf_taso(viiva["avain"])
        if taso not in doc.layers:
            doc.layers.add(taso, color=7)
        # bulge = kaari kärjestä seuraavaan, joten kaaret ovat aitoja kaaria myös CAD:ssä
        msp.add_lwpolyline([(k["e"], k["n"], k.get("bulge") or 0.0) for k in viiva["karjet"]],
                           format="xyb", close=viiva["suljettu"], dxfattribs={"layer": taso})
        for k in viiva["karjet"]:
            if k["laji"] == "laskettu":
                msp.add_point((k["e"], k["n"], k["z"] or 0.0), dxfattribs={"layer": "LASKETUT_KULMAT"})

    for p in tulos["pisteet"]:
        msp.add_point((p["e"], p["n"], p.get("korkeus") or 0.0), dxfattribs={"layer": "MITATUT_PISTEET"})
        kohde, tyyppi, numero = _koodin_osat(p.get("koodi"))
        koodi = " ".join(([kohde] if kohde else []) + [str(tyyppi)] + ([str(numero)] if numero != 1 else []))
        msp.add_text(f"{p.get('nimi')} ({koodi})",
                     height=0.2, dxfattribs={"layer": "PISTETEKSTIT"}
                     ).set_placement((p["e"] + 0.1, p["n"] + 0.1))

    doc.saveas(out_path)
    return out_path
