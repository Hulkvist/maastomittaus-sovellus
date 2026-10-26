"""
jobxml_tuonti.py -- Trimble JobXML (.jxl/.xml) -tiedostojen jäsennys, analyysi ja tuonti
------------------------------------------------------------------------------------------
Jäsentää työn pisteet, asemapisteet, residuaalit ja kulmavirheet, luokittelee
pisteet (asema-, liitos-, korkeusliitos-, kartoitus- ym. pisteet), laskee
asemapisteiden laadun ja MML:n 2x-säännön ylitykset (PDF-raportti: mittausraportti.py).

Kahden kojeasennon mittauksesta Trimble kirjoittaa samasta pisteestä useita
PointRecordeja (Face1 -> Face2 -> MTA -> [Averaged]). Raa'at havainnot
suodatetaan pois, ja jäljelle jää yksi piste perityllä luokituksella
(ks. _merkitse_kojeasento_suppressoinnit).

Vaatimukset: pip install psycopg2-binary
"""

import re
import html
import math
from collections import defaultdict, Counter
from datetime import datetime, timedelta

import seinalinja as sl

DB_SRID = 3879
GEOMETRIA_K_VAKIO = 8.0
TYOJAKSO_KYNNYS_H = 2
SUURI_SE_VAROITUSRAJA_M = 0.02
PIENI_TYOJAKSO_VAROITUSRAJA_S = 120
REAALILUOKAT = {'Normal', 'BackSight', 'Stakeout', 'Construction'}
KOJEASENTO_LOOKBACK = 15  # kuinka monta tietuetta taaksepäin etsitään raakahavaintoja


# ---------------------------------------------------------------------------
# Apufunktiot: XML-tekstin poiminta
# ---------------------------------------------------------------------------

def _poimi(tag, block):
    m = re.search(fr'<{tag}>([^<]*)</{tag}>', block)
    if m:
        return m.group(1)
    if re.search(fr'<{tag}\s*/>', block):
        return ""
    return None


def _poimi_float(tag, block):
    v = _poimi(tag, block)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _poimi_int(tag, block):
    v = _poimi_float(tag, block)
    return int(v) if v is not None else None


def _job_ja_kirjasto(content):
    idx = content.find('<JOBFile')
    end = content.find('>', idx)
    header = content[idx:end + 1] if idx != -1 else ""
    job_m = re.search(r'jobName="([^"]+)"', header)
    # Työhön voi ladata useamman koodikirjaston; kukin on oma FeatureCodingRecordinsa
    kirjastot = [f"{nimi} ({aika[11:16]})" for aika, nimi in re.findall(
        r'<FeatureCodingRecord[^>]*TimeStamp="([^"]*)"[^>]*>.*?<SourceFilename>([^<]*)</SourceFilename>',
        content, re.S)]
    if not kirjastot:
        kirjasto_m = re.search(r'<SourceFilename>([^<]*)</SourceFilename>', content)
        kirjastot = [kirjasto_m.group(1)] if kirjasto_m else []
    return (
        job_m.group(1) if job_m else "Tuntematon",
        ", ".join(kirjastot) or "(ei nimettyä kirjastoa)",
    )


def _ominaisuudet(block):
    """Pisteen ominaisuustiedot (koodikirjaston attribuutit): lista
    {"kohde": "RAK", "nimi": "Rakennetyyppi", "arvo": "Sokkeli", "tyyppi": "Menu"}."""
    tiedot = []
    for kohde, sisalto in re.findall(r'<Feature Name="([^"]*)">(.*?)</Feature>', block, re.S):
        for attribuutti in re.findall(r'<Attribute>(.*?)</Attribute>', sisalto, re.S):
            tiedot.append({"kohde": html.unescape(kohde),
                           "nimi": html.unescape(_poimi('Name', attribuutti) or ""),
                           "arvo": html.unescape(_poimi('Value', attribuutti) or ""),
                           "tyyppi": _poimi('Type', attribuutti)})
    return tiedot


def _hylkaysperuste(block):
    if _poimi('Deleted', block) == 'true':
        note = re.search(r'<Note>([^<]*)</Note>', block)
        lisatieto = f" ({note.group(1)})" if note else ""
        return f"Poistettu Trimblessa (Deleted=true){lisatieto}"

    method = _poimi('Method', block)
    survey_method = _poimi('SurveyMethod', block)
    classification = _poimi('Classification', block)

    # "Averaged"-tietue (Trimblen LASKEMA kahden kojeasennon
    # keskiarvo) käyttää samaa Method=Coordinates+SurveyMethod=KeyedIn
    # -yhdistelmää kuin oikeasti käsin syötetyt roskapisteet. Averaged EI OLE
    # käsin syötetty -- sen tunnistaa GridStandardDeviations/AverageResiduals
    # -lohkoista, joita käsin syötetyllä pisteellä ei koskaan ole. Tämä ehto
    # päästää Averaged-tietueet KeyedIn-hylkäyssäännön ohi.
    if method == 'Coordinates' and survey_method == 'KeyedIn' and classification != 'Averaged':
        return "Käsin syötetty (Method=Coordinates, SurveyMethod=KeyedIn)"

    grid = re.search(
        r'<(?:Grid|ComputedGrid)>\s*<North>([^<]*)</North>\s*<East>([^<]*)</East>',
        block,
    )
    if not grid:
        return "Koordinaattitietoa ei löytynyt (ei Grid/ComputedGrid-elementtiä)"
    n_raw, e_raw = grid.group(1), grid.group(2)
    if n_raw == '' or e_raw == '':
        return "Tyhjä koordinaatti (N tai E puuttuu kokonaan -- keskeneräinen asemointi)"
    try:
        if float(n_raw) == 0.0 and float(e_raw) == 0.0:
            return "Nollakoordinaatti (N=0 ja E=0)"
    except ValueError:
        return "Koordinaatti ei ole numeerinen"
    return None


def _grid_koordinaatit(block):
    grid = re.search(
        r'<(?:Grid|ComputedGrid)>\s*<North>([^<]*)</North>\s*<East>([^<]*)</East>(?:\s*<Elevation>([^<]*)</Elevation>)?',
        block,
    )
    if not grid:
        return None, None, None
    try:
        n = float(grid.group(1)) if grid.group(1) else None
        e = float(grid.group(2)) if grid.group(2) else None
        el = float(grid.group(3)) if grid.group(3) else None
        return n, e, el
    except ValueError:
        return None, None, None


def _luokittele(method, classification):
    if method == 'Resection':
        return 'Asemapiste'
    if classification == 'BackSight':
        return 'Liitospiste'
    if classification == 'Stakeout':
        return 'Merkintäpiste'
    if classification == 'Construction':
        return 'Suunnittelupiste (Construction)'
    return 'Kartoituspiste'


def on_gnss_mittaus(method):
    """GNSS-mittaus: tavallinen (GpsStaticObservation) tai jatkuva topo
    (GpsContinuousTimePoint, GpsContinuousDistancePoint ...)."""
    return bool(method) and method.startswith('Gps')


def nayta_mittaustapa(kategoria, method, survey_method):
    if kategoria == 'Asemapiste':
        return 'Yhteiskäyttö'
    if kategoria in ('Liitospiste', 'Korkeusliitos'):
        if on_gnss_mittaus(method):
            return 'RTK'
        return 'Yhteiskäyttö'
    if kategoria == 'Liitospiste (alkuperäinen RTK-mittaus)':
        return 'RTK'
    if kategoria in ('Merkintäpiste', 'Kartoituspiste', 'Suunnittelupiste (Construction)'):
        if method and method.startswith('GpsContinuous'):
            return 'RTK (jatkuva)'
        if on_gnss_mittaus(method):
            return 'RTK'
        return 'Takymetri'
    return survey_method or method or '-'


# ---------------------------------------------------------------------------
# Kahden kojeasennon (Face1+Face2 -> MTA -> [Averaged]) tunnistus ja siivous
# ---------------------------------------------------------------------------

def _merkitse_kojeasento_suppressoinnit(recs):
    """recs: lista (id, timestamp, block)-tupleja PointRecord-tietueista
    tiedostojärjestyksessä. Palauttaa (suppress_idx, final_class, kojeasento_idx,
    gps_laatu_map):
    suppress_idx: set indeksejä jotka jätetään kokonaan pois pisteet_validit-
      listasta (raa'at Face1/Face2-havainnot + MTA jota seuraa Averaged).
    final_class: dict {idx: peritty_todellinen_luokka} niille MTA/Averaged-
      indekseille jotka JÄÄVÄT jäljelle lopullisena pisteenä.
    kojeasento_idx: set niistä final_class-indekseistä joissa oli aidosti
      havaittu Face1+Face2-pari (eikä vain toistomittaus ilman Face-kenttää).
    gps_laatu_map: dict {idx: [pdop_tiedot-dict, ...]} niille
      Averaged-indekseille, joiden ALLE SUPPRESSOIDUT raakahavainnot olivat
      GpsStaticObservation-mittauksia. Tarvitaan, koska Averaged-tietueen
      omassa lohkossa Method on aina "Coordinates" (ei "GpsStaticObservation"),
      jolloin pdop/hdop/satelliittitiedot katoaisivat kokonaan, jos piste
      mitattiin kahdesti RTK:lla ja Trimble laski niistä keskiarvon.
    """
    n = len(recs)
    suppress = set()
    final_class = {}
    kojeasento_idx = set()
    gps_laatu_map = {}

    for i, (_, _, block) in enumerate(recs):
        classification = _poimi('Classification', block)
        if classification not in ('MTA', 'Averaged'):
            continue
        name = _poimi('Name', block)

        if classification == 'MTA' and i + 1 < n:
            next_name = _poimi('Name', recs[i + 1][2])
            next_class = _poimi('Classification', recs[i + 1][2])
            if next_name == name and next_class == 'Averaged':
                suppress.add(i)
                continue

        real_class = None
        faces_seen = set()
        gps_laatu_lista = []
        j = i - 1
        askeleet = 0
        while j >= 0 and askeleet < KOJEASENTO_LOOKBACK:
            j_name = _poimi('Name', recs[j][2])
            j_class = _poimi('Classification', recs[j][2])
            if j_name == name and j_class in REAALILUOKAT:
                suppress.add(j)
                real_class = j_class
                face = _poimi('Face', recs[j][2])
                if face:
                    faces_seen.add(face)
                j_method = _poimi('Method', recs[j][2])
                if j_method == 'GpsStaticObservation':
                    gps_laatu_lista.append(_pdop_tiedot(recs[j][2]))
            askeleet += 1
            j -= 1

        final_class[i] = real_class or 'Normal'
        if {'Face1', 'Face2'} <= faces_seen:
            kojeasento_idx.add(i)
        if gps_laatu_lista:
            gps_laatu_map[i] = gps_laatu_lista

    return suppress, final_class, kojeasento_idx, gps_laatu_map


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------

def _konveksi_kuori(pisteet):
    pisteet = sorted(set(pisteet))
    if len(pisteet) <= 2:
        return pisteet

    def risti(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    ala = []
    for p in pisteet:
        while len(ala) >= 2 and risti(ala[-2], ala[-1], p) <= 0:
            ala.pop()
        ala.append(p)
    yla = []
    for p in reversed(pisteet):
        while len(yla) >= 2 and risti(yla[-2], yla[-1], p) <= 0:
            yla.pop()
        yla.append(p)
    return ala[:-1] + yla[:-1]


def _signeerattu_etaisyys_reunasta(piste, monikulmio):
    n = len(monikulmio)
    if n < 3:
        return None
    etaisyydet = []
    for i in range(n):
        x1, y1 = monikulmio[i]
        x2, y2 = monikulmio[(i + 1) % n]
        edge_len = math.hypot(x2 - x1, y2 - y1)
        if edge_len == 0:
            continue
        cross = (x2 - x1) * (piste[1] - y1) - (y2 - y1) * (piste[0] - x1)
        etaisyydet.append(cross / edge_len)
    return min(etaisyydet) if etaisyydet else None


def _keskim_sivun_pituus(monikulmio):
    n = len(monikulmio)
    pituudet = [
        math.hypot(monikulmio[(i + 1) % n][0] - monikulmio[i][0],
                   monikulmio[(i + 1) % n][1] - monikulmio[i][1])
        for i in range(n)
    ]
    return sum(pituudet) / len(pituudet) if pituudet else None


def laske_asemapisteen_sijaintiluokitus(asema_piste, liitospisteet, k=GEOMETRIA_K_VAKIO):
    if len(liitospisteet) < 3:
        return None
    monikulmio = _konveksi_kuori(liitospisteet)
    if len(monikulmio) < 3:
        return None
    etaisyys = _signeerattu_etaisyys_reunasta(asema_piste, monikulmio)
    keskisivu = _keskim_sivun_pituus(monikulmio)
    if etaisyys is None or not keskisivu:
        return None

    d_norm = etaisyys / (keskisivu / 2)
    S = 1 / (1 + math.exp(-k * d_norm))

    if S >= 0.85:
        luokka = "Erinomainen — hyvin keskellä liitospisteitä"
    elif S >= 0.65:
        luokka = "Hyvä — selvästi sisällä"
    elif S >= 0.35:
        luokka = "Tyydyttävä — lähellä reunaa"
    elif S >= 0.15:
        luokka = "Heikko — hieman ulkona (ekstrapolointia)"
    else:
        luokka = "Huono — kaukana ulkona (merkittävä ekstrapolointi)"

    return {
        "etaisyys_m": round(etaisyys, 2),
        "keskisivu_m": round(keskisivu, 1),
        "S": round(S, 3),
        "luokka": luokka,
    }


# ---------------------------------------------------------------------------
# Kartat (Helsingin harmaakantakartta)
# ---------------------------------------------------------------------------

# Piirretyt asemapistekartat (PNG) muistissa: sama asema piirtyy sovelluksen sivulla ja PDF-raportissa,
# joten raportti käyttää sivulla jo piirrettyä kuvaa. Vain kartat, joihin kantakartta saatiin taustalle;
# ilman taustaa jääneet piirretään uudelleen (palvelu voi olla jo toipunut).
_ASEMAKARTAT = {}
_ASEMAKARTAT_MAX = 200


def piirra_asemapiste_kartta(asemapiste, out_path):
    """Pieni kartta yhdelle asemapisteelle ja sen liitospisteille (muistista, jos sama asema on jo
    piirretty taustan kanssa)."""
    import hae_kiintopisteet as hk

    if asemapiste.get("n") is None or asemapiste.get("e") is None:
        return None
    avain = (round(asemapiste["n"], 4), round(asemapiste["e"], 4),
             tuple(asemapiste.get("liitospisteet_koordinaatit") or ()),
             tuple(asemapiste.get("korkeusliitos_koordinaatit") or ()))
    if avain in _ASEMAKARTAT:
        with open(out_path, "wb") as f:
            f.write(_ASEMAKARTAT[avain])
        return out_path

    liitospisteet = [
        {"nimi": nimi, "n": n, "e": e}
        for (nimi, n, e) in asemapiste.get("liitospisteet_koordinaatit", [])
    ]
    korkeusliitokset = [
        {"nimi": nimi, "n": n, "e": e}
        for (nimi, n, e) in asemapiste.get("korkeusliitos_koordinaatit", [])
    ]

    tiedot = {}
    tulos = hk.piirra_asemapisteen_pienikartta(
        asemapiste["n"], asemapiste["e"], liitospisteet, korkeusliitokset, out_path, tiedot=tiedot,
    )
    if tulos and tiedot.get("tausta"):
        if len(_ASEMAKARTAT) >= _ASEMAKARTAT_MAX:
            _ASEMAKARTAT.pop(next(iter(_ASEMAKARTAT)))
        with open(tulos, "rb") as f:
            _ASEMAKARTAT[avain] = f.read()
    return tulos


def piirra_yleiskartta(pisteet, out_path):
    """Kokonaiskartta KAIKISTA tiedoston validoista pisteistä (kaikki
    kategoriat) yhdellä kertaa. pisteet on jasenna_tyo():n toinen paluuarvo."""
    import hae_kiintopisteet as hk

    return hk.piirra_jobxml_yleiskartta(pisteet, out_path)


def muodosta_seinalinja(pisteet, tapa="lyhin", kantakartta=None, lidar=None, lidar_paatelty=None, nakyvyys=True):
    """Seinälinja koodien 8/5/100 perusteella (ks. seinalinja.py).
    pisteet on jasenna_tyo():n toinen paluuarvo, tapa "lyhin" (automaattinen),
    "lyhin_vanha" tai "mittaus". kantakartta = hk.rakennusten_renkaat(...) (Helsinki).
    lidar = LiDAR-seinät janoina (seinalinja.lue_lidar_dxf()["SEINA"]) tai None; lidar_paatelty =
    saman DXF:n PAATELTY-taso (vain järjestyksen apuna); nakyvyys = asemapisteiden näkyvyystarkistus."""
    return sl.muodosta_seinalinjat(pisteet, tapa=tapa, kantakartta=kantakartta, lidar=lidar,
                                   lidar_paatelty=lidar_paatelty, nakyvyys=nakyvyys)


# ---------------------------------------------------------------------------
# Asemapisteen laatuluokitus
# ---------------------------------------------------------------------------

def _pisteet_maaran_mukaan(maara):
    """Liitospisteiden määrän laatupisteet asteikolla 0–100."""
    if maara <= 1:
        return 0.0
    if maara == 2:
        return 20.0
    if maara == 3:
        return 70.0
    if maara == 4:
        return 82.0
    if maara == 5:
        return 90.0
    if maara == 6:
        return 96.0
    return 100.0


def _pdop_pisteet(pdop):
    """Paikalliseen RTK-aineistoon sopiva PDOP-asteikko."""
    if pdop is None:
        return None
    if pdop <= 1.20:
        return 100.0
    if pdop <= 1.50:
        return 90.0
    if pdop <= 1.80:
        return 75.0
    if pdop <= 2.00:
        return 55.0
    if pdop <= 2.50:
        return 35.0
    if pdop <= 3.00:
        return 15.0
    return 0.0


def _residuaali_pisteet(residuaali_m):
    """Suurimman residuaalin pisteet. Syöte metreinä."""
    if residuaali_m is None:
        return None
    mm = abs(residuaali_m) * 1000.0
    if mm <= 5:
        return 100.0
    if mm <= 10:
        return 85.0
    if mm <= 20:
        return 65.0
    if mm <= 30:
        return 40.0
    if mm <= 50:
        return 15.0
    return 0.0


def _kulmapeitto_asteina(asemapiste, liitospisteet):
    """Laskee liitospisteiden kulmapeiton asemapisteestä."""
    if asemapiste is None or len(liitospisteet) < 2:
        return None

    an, ae = asemapiste
    kulmat = []

    for n, e in liitospisteet:
        if n is None or e is None:
            continue
        kulma = math.degrees(math.atan2(e - ae, n - an)) % 360.0
        kulmat.append(kulma)

    if len(kulmat) < 2:
        return None

    kulmat.sort()
    aukot = [
        kulmat[i + 1] - kulmat[i]
        for i in range(len(kulmat) - 1)
    ]
    aukot.append(kulmat[0] + 360.0 - kulmat[-1])
    return 360.0 - max(aukot)


def _kulmapeitto_pisteet(kulmapeitto):
    if kulmapeitto is None:
        return None
    if kulmapeitto >= 270:
        return 100.0
    if kulmapeitto >= 210:
        return 85.0
    if kulmapeitto >= 150:
        return 65.0
    if kulmapeitto >= 90:
        return 40.0
    return 15.0


def _sijainti_pisteet(sijainti):
    if not sijainti:
        return None

    arvo = sijainti.get("S")
    if arvo is None:
        return None
    if arvo >= 0.85:
        return 100.0
    if arvo >= 0.65:
        return 80.0
    if arvo >= 0.35:
        return 60.0
    if arvo >= 0.15:
        return 30.0
    return 0.0


def laske_asemapisteen_laatu(
    asemapiste,
    liitospisteet,
    sijainti,
    residuaalit,
):
    """Laskee asemapisteen kokonaislaadun.

    Parametrit:
      asemapiste: (N, E) tai None
      liitospisteet: lista muodossa [(N, E, PDOP), ...]
      sijainti: nykyisen sijaintiluokituksen sanakirja tai None
      residuaalit: lista residuaalisanakirjoja
    """
    koordinaatit = [
        (n, e)
        for n, e, _ in liitospisteet
        if n is not None and e is not None
    ]
    maara = len(koordinaatit)

    pdopit = [
        pdop
        for _, _, pdop in liitospisteet
        if pdop is not None
    ]
    pdop_keskiarvo = (
        sum(pdopit) / len(pdopit)
        if pdopit
        else None
    )
    pdop_huonoin = max(pdopit) if pdopit else None

    # Vaakaresiduaali = sqrt(dN² + dE²); suurimman liitospiste kerrotaan varoituksessa
    residuaalimatkat = []
    suurimman_liitospiste = None
    for residuaali in residuaalit or []:
        delta_n = residuaali.get("delta_n")
        delta_e = residuaali.get("delta_e")
        if delta_n is not None and delta_e is not None:
            residuaalimatkat.append(
                math.hypot(delta_n, delta_e)
            )
            if residuaalimatkat[-1] == max(residuaalimatkat):
                suurimman_liitospiste = residuaali.get("liitospiste")

    rms_residuaali = (
        math.sqrt(
            sum(arvo * arvo for arvo in residuaalimatkat)
            / len(residuaalimatkat)
        )
        if residuaalimatkat
        else None
    )
    suurin_residuaali = (
        max(residuaalimatkat)
        if residuaalimatkat
        else None
    )

    sijaintipisteet = _sijainti_pisteet(sijainti)
    maarapisteet = _pisteet_maaran_mukaan(maara)
    residuaalipisteet = _residuaali_pisteet(
        suurin_residuaali
    )
    pdop_pisteet = _pdop_pisteet(pdop_keskiarvo)

    kulmapeitto = None
    kulmapeittopisteet = None
    if asemapiste is not None:
        kulmapeitto = _kulmapeitto_asteina(
            asemapiste,
            koordinaatit,
        )
        kulmapeittopisteet = _kulmapeitto_pisteet(
            kulmapeitto
        )

    osat = {
        "sijaintipisteet": sijaintipisteet,
        "residuaalipisteet": residuaalipisteet,
        "pdop_pisteet": pdop_pisteet,
        "maarapisteet": maarapisteet,
        "kulmapeittopisteet": kulmapeittopisteet,
    }
    painot = {
        "sijaintipisteet": 0.20,
        "residuaalipisteet": 0.35,
        "pdop_pisteet": 0.20,
        "maarapisteet": 0.10,
        "kulmapeittopisteet": 0.15,
    }

    tunnetut = [
        (nimi, pisteet)
        for nimi, pisteet in osat.items()
        if pisteet is not None
    ]
    painosumma = sum(
        painot[nimi]
        for nimi, _ in tunnetut
    )
    kokonaispiste = (
        sum(
            pisteet * painot[nimi]
            for nimi, pisteet in tunnetut
        ) / painosumma
        if painosumma
        else None
    )

    if kokonaispiste is None:
        luokka = "Ei laskettavissa"
    elif kokonaispiste >= 85:
        luokka = "Erinomainen"
    elif kokonaispiste >= 70:
        luokka = "Hyvä"
    elif kokonaispiste >= 50:
        luokka = "Tyydyttävä"
    elif kokonaispiste >= 30:
        luokka = "Heikko"
    else:
        luokka = "Huono"

    varoitukset = []

    if maara == 2:
        varoitukset.append("Vain 2 liitospistettä")
        if kokonaispiste is not None:
            kokonaispiste = min(kokonaispiste, 69.0)
            if luokka in ("Erinomainen", "Hyvä"):
                luokka = "Tyydyttävä"

    if pdop_huonoin is not None and pdop_huonoin > 2.5:
        varoitukset.append(
            f"Huonoin PDOP {pdop_huonoin:.2f}"
        )

    if pdop_huonoin is not None and pdop_huonoin > 3.0:
        if kokonaispiste is not None:
            kokonaispiste = min(kokonaispiste, 49.0)
            luokka = "Heikko"

    if suurin_residuaali is not None and suurin_residuaali > 0.030:
        varoitukset.append(
            f"Suurin vaakaresiduaali "
            f"{suurin_residuaali * 1000:.1f} mm"
            + (f" (liitospiste {suurimman_liitospiste})" if suurimman_liitospiste else "")
        )

    if kulmapeitto is not None and kulmapeitto < 90:
        varoitukset.append(
            f"Pieni kulmapeitto {kulmapeitto:.0f}°"
        )
        if kokonaispiste is not None:
            kokonaispiste = min(kokonaispiste, 49.0)
            luokka = "Heikko"

    return {
        "kokonaispiste": (
            round(kokonaispiste, 1)
            if kokonaispiste is not None
            else None
        ),
        "luokka": luokka,
        "liitospisteita": maara,
        "maarapisteet": maarapisteet,
        "pdop_keskiarvo": (
            round(pdop_keskiarvo, 2)
            if pdop_keskiarvo is not None
            else None
        ),
        "pdop_huonoimmillaan": (
            round(pdop_huonoin, 2)
            if pdop_huonoin is not None
            else None
        ),
        "pdop_pisteet": pdop_pisteet,
        "rms_residuaali_m": (
            round(rms_residuaali, 4)
            if rms_residuaali is not None
            else None
        ),
        "suurin_residuaali_m": (
            round(suurin_residuaali, 4)
            if suurin_residuaali is not None
            else None
        ),
        "suurin_residuaali_liitospiste": suurimman_liitospiste,
        "residuaalipisteet": residuaalipisteet,
        "kulmapeitto_deg": (
            round(kulmapeitto, 1)
            if kulmapeitto is not None
            else None
        ),
        "kulmapeittopisteet": kulmapeittopisteet,
        "sijaintipisteet": sijaintipisteet,
        "varoitukset": varoitukset,
    }


# ---------------------------------------------------------------------------
# Työn tiedot, koordinaatisto ja kalusto (mittausraporttia varten)
# ---------------------------------------------------------------------------

def _tietueet_idlla(content, tag):
    """{ID: lohko} kaikista annetun tyyppisistä tietueista."""
    return {m.group(1): m.group(2) for m in re.finditer(
        fr'<{tag} ID="([^"]+)"[^>]*>(.*?)</{tag}>', content, re.S)}


def _tyon_tiedot(content):
    idx = content.find('<JOBFile')
    header = content[idx:content.find('>', idx) + 1] if idx != -1 else ""

    def attr(nimi):
        m = re.search(fr'{nimi}="([^"]*)"', header)
        return m.group(1) if m else None
    yksikot = next(iter(_tietueet_idlla(content, "UnitsRecord").values()), "")
    return {
        "ohjelma": attr("product"), "ohjelmaversio": attr("productVersion"),
        "ohjaimen_sarjanumero": attr("controllerSerialNumber"), "luotu": attr("TimeStamp"),
        "kulmayksikko": _poimi("AngleUnits", yksikot), "etaisyysyksikko": _poimi("DistanceUnits", yksikot),
        "paineyksikko": _poimi("PressureUnits", yksikot), "lampotilayksikko": _poimi("TemperatureUnits", yksikot),
    }


def _koordinaatisto(content):
    ks = next(iter(_tietueet_idlla(content, "CoordinateSystemRecord").values()), "")
    geoidi = re.search(r'<GeoidName>([^<]*)</GeoidName>', content)
    return {"jarjestelma": _poimi("SystemName", ks), "kaista": _poimi("ZoneName", ks),
            "datumi": _poimi("DatumName", ks), "geoidi": geoidi.group(1) if geoidi else None}


TAPAHTUMAT = {"StartRoverSurvey": "Roveri käynnistetty", "EndSurvey": "Mittaus lopetettu",
              "RTKInitialised": "RTK alustettu", "RTKNotInitialised": "RTK ei alustettu"}
ASEMATYYPIT = {"StandardResection": "Vapaa asemapiste", "KnownStation": "Tunnettu asemapiste"}


def _asetukset(content):
    """Projektio, ellipsoidi, datumimuunnos, korjaukset ja kartoitusasetukset."""
    def eka(tag):
        return next(iter(_tietueet_idlla(content, tag).values()), "")
    proj, ell, datum, korj = eka("ProjectionRecord"), eka("EllipsoidRecord"), eka("DatumRecord"), eka("CorrectionsRecord")
    litistyneisyys = _poimi_float("Flattening", ell)
    mittakaava = _poimi_float("Scale", datum)
    maskit = []
    for b in _tietueet_idlla(content, "RoverSurveyOptionsRecord").values():
        m = (_poimi_float("ElevationMask", b), _poimi_float("PDOPMask", b))
        if m not in maskit:
            maskit.append(m)
    lahipiste = re.search(r'<NeighbourhoodAdjustment>\s*<Applied>([^<]*)</Applied>', korj)
    return {
        "projektio": {"tyyppi": _poimi("Type", proj), "keskileveys_deg": _poimi_float("CentralLatitude", proj),
                      "keskimeridiaani_deg": _poimi_float("CentralLongitude", proj),
                      "pohjoiskorjaus": _poimi_float("FalseNorthing", proj),
                      "itakorjaus": _poimi_float("FalseEasting", proj), "mittakaava": _poimi_float("Scale", proj)},
        "ellipsoidi": {"isoakseli": _poimi_float("EarthRadius", ell),
                       "litistyneisyys_1_per": 1 / litistyneisyys if litistyneisyys else None},
        "datumimuunnos": {"tyyppi": _poimi("Type", datum),
                          "kierrot_deg": [_poimi_float(f"Rotation{a}", datum) for a in "XYZ"],
                          "siirrot_m": [_poimi_float(f"Translation{a}", datum) for a in "XYZ"],
                          "mittakaava_ppm": (mittakaava - 1) * 1e6 if mittakaava is not None else None,
                          "vertauskehys": _poimi("ReferenceGlobalFrameName", datum),
                          "epookki": _poimi("ReferenceGlobalFrameEpoch", datum)} if datum else None,
        "korjaukset": {"etaisyydet": _poimi("Distances", korj), "karttakoordinaatit": _poimi("GridOrientation", korj),
                       "eteläatsimuutti": _poimi("SouthAzimuth", korj),
                       "magneettinen_deklinaatio": _poimi_float("MagneticDeclination", korj),
                       "merenpintakorjaus": _poimi("ApplySeaLevelCorrection", korj),
                       "lahipistetasoitus": lahipiste.group(1) if lahipiste else None} if korj else None,
        "kartoitusasetukset": [{"korkeusmaski_deg": a, "pdop_maski": b} for a, b in maskit],
    }


def _aikaleima(ts):
    try:
        return datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def _tapahtumat(content):
    """Mittaustapahtumat aikajärjestyksessä: roverin käynnistys ja lopetus, RTK:n alustukset,
    VRS-yhteydet (huomautuksista) ja asemapisteiden määritykset."""
    tapahtumat = []
    for tag, kentta in (("SurveyEventRecord", "Event"), ("InitialisationRecord", "InitialisationEvent")):
        for m in re.finditer(fr'<{tag} ID="[^"]+"[^>]*TimeStamp="([^"]+)">(.*?)</{tag}>', content, re.S):
            tapahtuma = _poimi(kentta, m.group(2))
            lisa = _poimi("InitialisationType", m.group(2)) if tag == "InitialisationRecord" else None
            tapahtumat.append((_aikaleima(m.group(1)), TAPAHTUMAT.get(tapahtuma, tapahtuma),
                               {"OnTheFly": "lennossa"}.get(lisa, lisa) or ""))
    for m in re.finditer(r'<NoteRecord ID="[^"]+"[^>]*TimeStamp="([^"]+)">(.*?)</NoteRecord>', content, re.S):
        for huom in re.findall(r'<Note>([^<]*)</Note>', m.group(2)):
            if huom.startswith("VRSID"):
                tapahtumat.append((_aikaleima(m.group(1)), "VRS-yhteys",
                                   huom.replace("&apos;", "'").replace("&quot;", '"')))
    for m in re.finditer(r'<StationRecord ID="[^"]+"[^>]*TimeStamp="([^"]+)">(.*?)</StationRecord>', content, re.S):
        b = m.group(2)
        tapahtumat.append((_aikaleima(m.group(1)), f"Asemapiste {_poimi('StationName', b)}",
                           f"{ASEMATYYPIT.get(_poimi('StationType', b), _poimi('StationType', b) or '')}, "
                           f"{_poimi('NumberOfBacksightPoints', b) or '?'} liitospistettä"))
    tapahtumat.sort(key=lambda t: (t[0] is None, t[0] or datetime.min))
    return [{"aika": a, "tapahtuma": t, "lisatieto": l} for a, t, l in tapahtumat]


def _gnss_lisatiedot(block, antennit):
    """RTK-pisteen lisätiedot: ECEF, antennikorkeus, kallistusetäisyys (sauvan korkeus x tan kallistus,
    kuten Trimblen raportissa), GDOP, tukiaseman tietojen ikä, käytetyt sijainnit ja VCV (m²)."""
    ecef = re.search(r'<ECEF>(.*?)</ECEF>', block, re.S)
    if not ecef:
        return {}
    antenni = antennit.get(_poimi("AntennaID", block), "")
    asento = re.search(r'<Attitude>(.*?)</Attitude>', block, re.S)
    kallistus = None
    korkeus = _poimi_float("ReducedHeight", antenni)
    if asento and korkeus is not None:
        pitch, roll = _poimi_float("Pitch", asento.group(1)), _poimi_float("Roll", asento.group(1))
        if pitch is not None and roll is not None:
            kulma = math.atan(math.hypot(math.tan(math.radians(pitch)), math.tan(math.radians(roll))))
            kallistus = korkeus * math.tan(kulma)
    qc2 = re.search(r'<QualityControl2>(.*?)</QualityControl2>', block, re.S)
    return {
        "ecef": tuple(_poimi_float(a, ecef.group(1)) for a in "XYZ"),
        "antennikorkeus": _poimi_float("MeasuredHeight", antenni),
        "kallistusetaisyys": kallistus,
        "gdop": _poimi_float("GDOP", block),
        "tukiaseman_ika_s": _poimi_float("RTCMAge", block),
        "sijainteja": _poimi_int("NumberOfPositionsUsed", block),
        "vcv": {k: _poimi_float(f"VCV{k}", qc2.group(1)) for k in ("xx", "xy", "xz", "yy", "yz", "zz")} if qc2 else None,
    }


def _kalusto(content, instrumentit, tahykset):
    """Takymetrit, GNSS-vastaanottimet ja tähykset kukin kerran (sama laite toistuu
    jokaisella asemalla)."""
    takymetrit, nahdyt = [], set()
    for b in instrumentit.values():
        tieto = {"malli": _poimi("Model", b), "tyyppi": _poimi("Type", b), "sarjanumero": _poimi("Serial", b),
                 "firmware": _poimi("FirmwareVersion", b),
                 "ha_tarkkuus_deg": _poimi_float("HorizontalAnglePrecision", b),
                 "va_tarkkuus_deg": _poimi_float("VerticalAnglePrecision", b),
                 "edm_tarkkuus_m": _poimi_float("EDMPrecision", b), "edm_ppm": _poimi_float("EDMppm", b),
                 "taitekerroin": _poimi_float("RefractiveIndex", b), "aallonpituus": _poimi_float("CarrierWavelength", b),
                 "orientointitapa": _poimi("SetHorizontalCircleMode", b),
                 "vaakakollimaatio": _poimi_float("InstrumentAppliedHorizontalCollimation", b),
                 "pystykollimaatio": _poimi_float("InstrumentAppliedVerticalCollimation", b),
                 "tappikaltevuus": _poimi_float("TrunionAxisTiltCorrection", b),
                 "edm_vakio": _poimi_float("InstrumentAppliedEDMConstant", b)}
        avain = tuple(tieto.values())
        if avain not in nahdyt:
            nahdyt.add(avain)
            takymetrit.append(tieto)
    antennit = _tietueet_idlla(content, "AntennaRecord")
    gnss, nahdyt = [], set()
    for gid, b in _tietueet_idlla(content, "GPSEquipmentRecord").items():
        korkeudet = sorted({_poimi_float("MeasuredHeight", a) for a in antennit.values()
                            if _poimi("GPSEquipmentID", a) == gid and _poimi_float("MeasuredHeight", a) is not None})
        tieto = {"vastaanotin": _poimi("ReceiverType", b), "sarjanumero": _poimi("ReceiverSerialNumber", b),
                 "firmware": _poimi("ReceiverFirmwareVersion", b), "antenni": _poimi("AntennaType", b),
                 "mittaustapa": _poimi("AntennaMeasurementMethod", b), "antennikorkeudet": korkeudet}
        avain = (tieto["vastaanotin"], tieto["sarjanumero"], tieto["antenni"], tieto["mittaustapa"])
        if avain in nahdyt:
            vanha = next(g for g in gnss if (g["vastaanotin"], g["sarjanumero"], g["antenni"], g["mittaustapa"]) == avain)
            vanha["antennikorkeudet"] = sorted(set(vanha["antennikorkeudet"]) | set(korkeudet))
        else:
            nahdyt.add(avain)
            gnss.append(tieto)
    tahys_lista, nahdyt = [], set()
    for t in tahykset.values():
        avain = (t["nimi"], t["prismatyyppi"], t["prismavakio_m"], t["korkeus_m"])
        if avain not in nahdyt:
            nahdyt.add(avain)
            tahys_lista.append(t)
    ilmastokorjaukset = []
    for b in _tietueet_idlla(content, "AtmosphereRecord").values():
        k = {"kaarevuus": _poimi("ApplyEarthCurvatureCorrection", b), "refraktio": _poimi("ApplyRefractionCorrection", b),
             "refraktiovakio": _poimi_float("RefractionCoefficient", b)}
        if k not in ilmastokorjaukset:
            ilmastokorjaukset.append(k)
    return {"takymetrit": takymetrit, "gnss": gnss, "tahykset": tahys_lista, "ilmastokorjaukset": ilmastokorjaukset}


def _tahykset(content):
    return {tid: {"nimi": _poimi("Name", b), "prismatyyppi": _poimi("PrismType", b),
                  "prismavakio_m": _poimi_float("PrismConstant", b), "korkeus_m": _poimi_float("TargetHeight", b)}
            for tid, b in _tietueet_idlla(content, "TargetRecord").items()}


def _havainto(block, tahykset):
    """Takymetrihavainto (kulmat asteina kuten JobXML:ssä) tai None."""
    c = re.search(r'<Circle>(.*?)</Circle>', block, re.S)
    if not c:
        return None
    cb = c.group(1)
    tahys = tahykset.get(_poimi("TargetID", block)) or {}
    return {"ha_deg": _poimi_float("HorizontalCircle", cb), "va_deg": _poimi_float("VerticalCircle", cb),
            "sd_m": _poimi_float("EDMDistance", cb), "kojeasento": _poimi("Face", cb),
            "tahyskorkeus_m": tahys.get("korkeus_m"), "prismavakio_m": tahys.get("prismavakio_m"),
            "tahys": tahys.get("nimi"), "prismatyyppi": tahys.get("prismatyyppi"),
            "lukittu": _poimi("TargetLocked", block), "lukitustyyppi": _poimi("LockType", block)}


# ---------------------------------------------------------------------------
# Pääjäsennys
# ---------------------------------------------------------------------------

_RECORD_PATTERNS = {
    'StationRecord': re.compile(r'<StationRecord ID="([^"]+)"[^>]*TimeStamp="([^"]+)">(.*?)</StationRecord>', re.S),
    'PointRecord': re.compile(r'<PointRecord ID="([^"]+)"[^>]*TimeStamp="([^"]+)">(.*?)</PointRecord>', re.S),
    'StationResiduals': re.compile(r'<StationResiduals ID="([^"]+)"[^>]*TimeStamp="([^"]+)">(.*?)</StationResiduals>', re.S),
    'BackBearingRecord': re.compile(r'<BackBearingRecord ID="([^"]+)"[^>]*TimeStamp="([^"]+)">(.*?)</BackBearingRecord>', re.S),
}


def _kaikki_tietueet_jarjestyksessa(content):
    tietueet = []
    for tag, pattern in _RECORD_PATTERNS.items():
        for m in pattern.finditer(content):
            tietueet.append((m.start(), tag, m.group(1), m.group(2), m.group(3)))
    tietueet.sort(key=lambda x: x[0])
    return tietueet


def _residuaalit_lohkosta(block):
    tulokset = []
    for rec in re.finditer(r'<ResidualsRecord>(.*?)</ResidualsRecord>', block, re.S):
        rb = rec.group(1)
        tulokset.append({
            "liitospiste": _poimi('PointName', rb),
            "delta_n": _poimi_float('DeltaNorth', rb),
            "delta_e": _poimi_float('DeltaEast', rb),
            "delta_h": _poimi_float('DeltaElevation', rb),
            "d_ha_deg": _poimi_float('HorizontalCircle', rb),
            "d_va_deg": _poimi_float('VerticalCircle', rb),
            "d_sd_m": _poimi_float('SlopeDistance', rb),
            "kaytto": _poimi('ObservationUsedInSolutionFor', rb),
        })
    return tulokset


def _pdop_tiedot(block):
    qc = re.search(r'<QualityControl1>(.*?)</QualityControl1>', block, re.S)
    if not qc:
        return {}
    qb = qc.group(1)
    return {
        "pdop": _poimi_float('PDOP', qb),
        "hdop": _poimi_float('HDOP', qb),
        "vdop": _poimi_float('VDOP', qb),
        "satelliitteja": _poimi_int('NumberOfSatellites', qb),
    }


def jasenna_tyo(tiedosto_bytes, lahdetiedosto="tuntematon.xml"):
    content = tiedosto_bytes.decode('utf-8', errors='ignore') if isinstance(tiedosto_bytes, bytes) else tiedosto_bytes

    job_nimi, kirjasto = _job_ja_kirjasto(content)
    tietueet = _kaikki_tietueet_jarjestyksessa(content)
    instrumentit = _tietueet_idlla(content, "InstrumentRecord")
    ilmastot = _tietueet_idlla(content, "AtmosphereRecord")
    tahykset = _tahykset(content)
    antennit = _tietueet_idlla(content, "AntennaRecord")
    station_tiedot = {}
    station_orientoinnit = defaultdict(list)

    # Kahden kojeasennon suppressointi lasketaan VAIN PointRecord-tietueille,
    # omassa järjestyksessään (ei sekaisin StationRecord/BackBearing-tietueiden kanssa).
    point_recs_only = [(rid, ts, block) for (pos, tag, rid, ts, block) in tietueet if tag == 'PointRecord']
    suppress_idx, final_class_map, kojeasento_idx, gps_laatu_map = _merkitse_kojeasento_suppressoinnit(point_recs_only)

    station_lista = []
    station_kulmavirheet = defaultdict(list)
    pisteet_validit = []
    hylatyt = []
    asemapisteet_raaka = []
    residuaalit_raaka = []       # [(pos, [residual dicts])]
    resection_positions = []     # [(pos, station_record_id)] KAIKISTA resektioista (myös poistetut)

    point_record_counter = -1

    for pos, tag, rid, ts, block in tietueet:
        aikaleima = None
        try:
            aikaleima = datetime.fromisoformat(ts)
        except ValueError:
            pass

        if tag == 'StationRecord':
            nimi = _poimi('StationName', block)
            station_lista.append((pos, rid, nimi))
            ilmasto = ilmastot.get(_poimi('AtmosphereID', block), "")
            station_tiedot[rid] = {
                "kojekorkeus": _poimi_float('TheodoliteHeight', block),
                "maarittely": ASEMATYYPIT.get(_poimi('StationType', block), _poimi('StationType', block)),
                "mittakaava": _poimi_float('ScaleFactor', block),
                "mittakaava_tyyppi": _poimi('ScaleType', block),
                "ilmasto": {"paine": _poimi_float('Pressure', ilmasto), "lampotila": _poimi_float('Temperature', ilmasto),
                            "ppm": _poimi_float('PPM', ilmasto)} if ilmasto else None,
            }
            continue

        if tag == 'StationResiduals':
            residuaalit_raaka.append((pos, _residuaalit_lohkosta(block)))
            continue

        if tag == 'BackBearingRecord':
            srid = _poimi('StationRecordID', block)
            backsight_nimi = _poimi('BackSight', block)
            kulmavirhe = _poimi_float('OrientationCorrectionStandardError', block)
            if srid and kulmavirhe is not None:
                station_kulmavirheet[srid].append({"liitospiste": backsight_nimi, "kulmavirhe_rad": kulmavirhe})
            if srid:
                station_orientoinnit[srid].append({
                    "liitospiste": backsight_nimi,
                    "korjaus_deg": _poimi_float('OrientationCorrection', block),
                    "keskivirhe_deg": kulmavirhe,
                })
            continue

        if tag == 'PointRecord':
            point_record_counter += 1
            idx = point_record_counter

            if idx in suppress_idx:
                continue  # raaka Face1/Face2/välivaihe-MTA -- ei kirjata mihinkään

            nimi = _poimi('Name', block)
            koodi = _poimi('Code', block)
            method = _poimi('Method', block)
            survey_method = _poimi('SurveyMethod', block)
            classification = _poimi('Classification', block)
            station_id = _poimi('StationID', block)
            on_kojeasento = idx in kojeasento_idx

            # HUOM: hylkäysperuste lasketaan RAA'ALLA classification-arvolla
            # (block sisältää sen vielä alkuperäisenä, esim. "Averaged"),
            # koska juuri se laukaisee KeyedIn-poikkeuksen. Tämä on tehtävä
            # ENNEN classification-arvon korvaamista perityllä todellisella
            # luokalla alla.
            syy = _hylkaysperuste(block)

            # Jos tämä on MTA/Averaged-lopputulos, käytetään sen perittyä
            # TODELLISTA luokkaa (Normal/BackSight/Stakeout/Construction)
            # varsinaisen luokittelun pohjana.
            if idx in final_class_map:
                classification = final_class_map[idx]

            # KAIKKI resektiot (myös Deleted=true) kirjataan sijaintipohjaista
            # residuaalikohdistusta varten.
            matching_station_id = None
            if method == 'Resection':
                for spos, sid, sname in reversed(station_lista):
                    if spos < pos and sname == nimi:
                        matching_station_id = sid
                        break
                resection_positions.append((pos, matching_station_id))

            if syy:
                hylatyt.append({
                    "nimi": nimi, "koodi": koodi, "syy": syy,
                    "aikaleima": aikaleima, "lahdetiedosto": lahdetiedosto,
                })
                continue

            n, e, korkeus = _grid_koordinaatit(block)
            kategoria = _luokittele(method, classification)

            if method == 'Resection':
                se = re.search(r'<ResectionStandardErrors>(.*?)</ResectionStandardErrors>', block, re.S)
                se_n = _poimi_float('NorthStandardError', se.group(1)) if se else None
                se_e = _poimi_float('EastStandardError', se.group(1)) if se else None
                se_h = _poimi_float('ElevationStandardError', se.group(1)) if se else None
                asemapisteet_raaka.append({
                    "pos": pos, "nimi": nimi, "koodi": koodi, "n": n, "e": e, "korkeus": korkeus,
                    "se_n": se_n, "se_e": se_e, "se_h": se_h, "aikaleima": aikaleima,
                    "station_record_id": matching_station_id,
                })

            if on_gnss_mittaus(method):
                pdop_info = _pdop_tiedot(block)
            elif idx in gps_laatu_map:
                lahteet = gps_laatu_map[idx]
                pdop_info = {}
                for kentta in ("pdop", "hdop", "vdop"):
                    arvot = [l.get(kentta) for l in lahteet if l.get(kentta) is not None]
                    if arvot:
                        pdop_info[kentta] = round(sum(arvot) / len(arvot), 2)
                satelliitit = [l.get("satelliitteja") for l in lahteet if l.get("satelliitteja") is not None]
                if satelliitit:
                    pdop_info["satelliitteja"] = min(satelliitit)
                    method = 'GpsStaticObservation'
            else:
                pdop_info = {}

            pisteet_validit.append({
                "nimi": nimi, "koodi": koodi, "kategoria": kategoria,
                "mittaustapa_raaka": survey_method, "method": method,
                "n": n, "e": e, "korkeus": korkeus,
                "station_record_id": station_id,
                "aikaleima": aikaleima, "lahdetiedosto": lahdetiedosto,
                "_classification": classification,
                "kahdesta_kojeasennosta": on_kojeasento,
                "havainto": _havainto(block, tahykset),
                "tarkkuus_h": _poimi_float('Horizontal', block) if '<Precision>' in block else None,
                "tarkkuus_v": _poimi_float('Vertical', block) if '<Precision>' in block else None,
                "gnss": _gnss_lisatiedot(block, antennit),
                "ominaisuudet": _ominaisuudet(block),
                **pdop_info,
            })

    # --- Residuaalien kohdistus SIJAINNIN perusteella ---
    resection_positions.sort(key=lambda x: x[0])

    def _srid_residuaalilohkolle(pos_sr):
        parhain = None
        for pos_r, srid in resection_positions:
            if pos_r < pos_sr:
                parhain = srid
            else:
                break
        return parhain

    residuaalit_per_asema = defaultdict(list)
    for pos_sr, lohkon_residuaalit in residuaalit_raaka:
        srid = _srid_residuaalilohkolle(pos_sr)
        if srid:
            residuaalit_per_asema[srid].extend(lohkon_residuaalit)

    # --- Korkeusliitosten tunnistus ---
    kaytto_per_srid_nimi = defaultdict(set)
    for srid, reslist in residuaalit_per_asema.items():
        for r in reslist:
            if r["liitospiste"]:
                kaytto_per_srid_nimi[(srid, r["liitospiste"])].add(r["kaytto"])

    korkeusliitos_nimet_per_asema = set()
    for (srid, nimi), kaytot in kaytto_per_srid_nimi.items():
        if kaytot and kaytot <= {"VerticalOnly"}:
            korkeusliitos_nimet_per_asema.add((srid, nimi))

    for p in pisteet_validit:
        if (p["_classification"] == "BackSight"
                and (p["station_record_id"], p["nimi"]) in korkeusliitos_nimet_per_asema):
            p["kategoria"] = "Korkeusliitos"

    # --- Liitospisteiden ja korkeusliitosten koordinaattilistat asemittain ---
    station_backsights = defaultdict(list)
    for p in pisteet_validit:
        if p["kategoria"] == "Liitospiste" and p["station_record_id"]:
            station_backsights[p["station_record_id"]].append((p["nimi"], p["n"], p["e"]))

    station_korkeusliitokset = defaultdict(list)
    for p in pisteet_validit:
        if p["kategoria"] == "Korkeusliitos" and p["station_record_id"]:
            station_korkeusliitokset[p["station_record_id"]].append((p["nimi"], p["n"], p["e"]))

    # --- Liitospisteen kaksoiskirjautuman merkintä (RTK-alkuperäismittaus) ---
    backsight_nimet = {p["nimi"] for p in pisteet_validit if p["kategoria"] == "Liitospiste"}
    for p in pisteet_validit:
        if (on_gnss_mittaus(p["method"]) and p["kategoria"] == "Kartoituspiste"
                and p["nimi"] in backsight_nimet):
            p["kategoria"] = "Liitospiste (alkuperäinen RTK-mittaus)"
    rtk_laatu_per_nimi = defaultdict(list)
    for p in pisteet_validit:
        if p["kategoria"] == "Liitospiste (alkuperäinen RTK-mittaus)":
            rtk_laatu_per_nimi[p["nimi"]].append(p)

    for p in pisteet_validit:
        if p["kategoria"] == "Liitospiste" and p["nimi"] in rtk_laatu_per_nimi:
            lahteet = rtk_laatu_per_nimi[p["nimi"]]
            for kentta in ("pdop", "hdop", "vdop"):
                arvot = [l.get(kentta) for l in lahteet if l.get(kentta) is not None]
                if arvot:
                    p[kentta] = round(sum(arvot) / len(arvot), 2)
            satelliitit = [l.get("satelliitteja") for l in lahteet if l.get("satelliitteja") is not None]
            if satelliitit:
                p["satelliitteja"] = min(satelliitit)

    # --- Näytettävä mittaustapa ---
    for p in pisteet_validit:
        p["mittaustapa"] = nayta_mittaustapa(p["kategoria"], p["method"], p["mittaustapa_raaka"])

    # --- Työaika ---
    aikaleimat = sorted({p["aikaleima"] for p in pisteet_validit if p["aikaleima"]})
    tyojaksot = []
    if aikaleimat:
        kynnys = timedelta(hours=TYOJAKSO_KYNNYS_H)
        alku = aikaleimat[0]
        edellinen = aikaleimat[0]
        for t in aikaleimat[1:]:
            if t - edellinen > kynnys:
                tyojaksot.append({"alku": alku, "loppu": edellinen, "kesto_s": int((edellinen - alku).total_seconds())})
                alku = t
            edellinen = t
        tyojaksot.append({"alku": alku, "loppu": edellinen, "kesto_s": int((edellinen - alku).total_seconds())})

    tyoaika_yhteensa_s = sum(j["kesto_s"] for j in tyojaksot)

    # --- Asemapisteiden täydentäminen ---
    asemapisteet = []
    for a in asemapisteet_raaka:
        liitospisteet_koord = []
        if a["station_record_id"] and a["station_record_id"] in station_backsights:
            liitospisteet_koord = [
                (n, e) for (_, n, e) in station_backsights[a["station_record_id"]]
                if n is not None and e is not None
            ]
        sijainti = None
        if a["n"] is not None and a["e"] is not None and len(liitospisteet_koord) >= 3:
            sijainti = laske_asemapisteen_sijaintiluokitus((a["n"], a["e"]), liitospisteet_koord)

        liitospiste_nimet = [nimi for (nimi, _, _) in station_backsights.get(a["station_record_id"], [])]
        liitospiste_koordinaatit = station_backsights.get(a["station_record_id"], [])
        korkeusliitos_nimet = [nimi for (srid, nimi) in korkeusliitos_nimet_per_asema if srid == a["station_record_id"]]
        korkeusliitos_koordinaatit = station_korkeusliitokset.get(a["station_record_id"], [])
        kulmavirheet = station_kulmavirheet.get(a["station_record_id"], [])
        residuaalit = residuaalit_per_asema.get(a["station_record_id"], [])
        liitospisteet_laatua_varten = []

        for nimi, n, e in station_backsights.get(
            a["station_record_id"],
            [],
        ):
            pdop = next(
                (
                    p.get("pdop")
                    for p in pisteet_validit
                    if (
                        p.get("nimi") == nimi
                        and p.get("station_record_id")
                        == a["station_record_id"]
                        and p.get("pdop") is not None
                    )
                ),
                None,
            )

            if n is not None and e is not None:
                liitospisteet_laatua_varten.append(
                    (n, e, pdop)
                )

        asemapisteen_laatu = laske_asemapisteen_laatu(
            (
                (a["n"], a["e"])
                if a["n"] is not None and a["e"] is not None
                else None
            ),
            liitospisteet_laatua_varten,
            sijainti,
            residuaalit,
        )

        kojeasento_liitospisteet = [
            p["nimi"] for p in pisteet_validit
            if p["kategoria"] == "Liitospiste" and p["station_record_id"] == a["station_record_id"]
            and p.get("kahdesta_kojeasennosta")
        ]

        tiedot = station_tiedot.get(a["station_record_id"], {})
        asemapisteet.append({
            "nimi": a["nimi"],
            "station_record_id": a["station_record_id"],
            "koodi": a["koodi"],
            "n": a["n"],
            "e": a["e"],
            "korkeus": a["korkeus"],
            "se_n_m": a["se_n"],
            "se_e_m": a["se_e"],
            "se_korkeus_m": a["se_h"],
            "kojekorkeus": tiedot.get("kojekorkeus"),
            "maarittely": tiedot.get("maarittely"),
            "mittakaava": tiedot.get("mittakaava"),
            "mittakaava_tyyppi": tiedot.get("mittakaava_tyyppi"),
            "ilmasto": tiedot.get("ilmasto"),
            "orientointi": station_orientoinnit.get(a["station_record_id"], []),
            "liitospisteet": liitospiste_nimet,
            "liitospisteet_koordinaatit": liitospiste_koordinaatit,
            "kojeasento_liitospisteet": kojeasento_liitospisteet,
            "korkeusliitokset": korkeusliitos_nimet,
            "korkeusliitos_koordinaatit": korkeusliitos_koordinaatit,
            "residuaalit": residuaalit,
            "kulmavirheet": kulmavirheet,
            "sijainti": sijainti,
            "laatu": asemapisteen_laatu,
            "aikaleima": a["aikaleima"],
        })

    # --- Asema, jolta piste on mitattu (seinälinjan näkyvyystarkistus) ---
    asemat_xy = {a["station_record_id"]: a for a in asemapisteet_raaka
                 if a["station_record_id"] and a["n"] is not None}
    for p in pisteet_validit:
        a = asemat_xy.get(p["station_record_id"])
        if a and p["kategoria"] != "Asemapiste":
            p["asema"] = {"nimi": a["nimi"], "e": a["e"], "n": a["n"]}

    # --- MML:n 2x-sääntö ---
    varoitukset_2x = []
    for a in asemapisteet_raaka:
        srid = a["station_record_id"]
        if not srid or srid not in station_backsights or a["n"] is None:
            continue
        etaisyydet_liitoksiin = [
            math.hypot(a["n"] - n, a["e"] - e)
            for (_, n, e) in station_backsights[srid] if n is not None and e is not None
        ]
        if not etaisyydet_liitoksiin:
            continue
        max_liitos = max(etaisyydet_liitoksiin)
        raja = 2 * max_liitos
        for p in pisteet_validit:
            if p["station_record_id"] == srid and p["kategoria"] == "Kartoituspiste" and p["n"] is not None:
                etaisyys = math.hypot(p["n"] - a["n"], p["e"] - a["e"])
                if etaisyys > raja:
                    varoitukset_2x.append({
                        "piste": p["nimi"], "asema": a["nimi"],
                        "etaisyys_m": round(etaisyys, 1), "raja_m": round(raja, 1),
                    })

    maara = Counter(p["kategoria"] for p in pisteet_validit)
    kahdesta_kojeasennosta_maara = sum(1 for p in pisteet_validit if p.get("kahdesta_kojeasennosta"))

    raportti = {
        "lahdetiedosto": lahdetiedosto,
        "job_nimi": job_nimi,
        "koodikirjasto": kirjasto,
        "tyon_tiedot": _tyon_tiedot(content),
        "koordinaatisto": _koordinaatisto(content),
        "kalusto": _kalusto(content, instrumentit, tahykset),
        "asetukset": _asetukset(content),
        "tapahtumat": _tapahtumat(content),
        "tyojaksot": tyojaksot,
        "tyoaika_yhteensa_s": tyoaika_yhteensa_s,
        "maara": dict(maara),
        "kahdesta_kojeasennosta_maara": kahdesta_kojeasennosta_maara,
        "hylatyt_maara": len(hylatyt),
        "hylatyt_pisteet": hylatyt,
        "asemapisteet": asemapisteet,
        "varoitukset_2x": varoitukset_2x,
        "seinalinja_kaytettavissa": sl.on_seinalinjapisteita(pisteet_validit),
    }
    return raportti, pisteet_validit, hylatyt


def pisteet_tallennettavaksi(pisteet):
    return [p for p in pisteet if p["kategoria"] != "Liitospiste (alkuperäinen RTK-mittaus)"]


KRD_MITATUT = {"Kartoituspiste", "Merkintäpiste"}
KRD_LIITOKSET = {"Liitospiste", "Korkeusliitos"}
KRD_RTK = "Liitospiste (alkuperäinen RTK-mittaus)"


# Kirjainkoodien (esim. työpaikan koodikirjasto) oletusmuunnos krd:hen: krd ymmärtää vain
# numerokoodeja. Sovelluksessa taulukkoa voi muokata istunnon ajan.
KRD_KOODIMUUNNOS = {"RAK": "100", "KATOS": "100", "LIP": "100", "ASP": "9",
                    "SK": "9", "JV": "9", "AV": "9", "SV": "9", "AITA": "9"}
KRD_KOODISELITTEET = {"RAK": "rakennus", "KATOS": "katos", "LIP": "liitospiste", "ASP": "asemapiste",
                      "SK": "suorakulmio (ohjauskoodi)", "JV": "jatka viivaa (ohjauskoodi)",
                      "AV": "aloita viiva (ohjauskoodi)", "SV": "sulje viiva (ohjauskoodi)", "AITA": "aita"}
KRD_TUNTEMATON_KOODI = "9"


def _krd_kirjainkoodi(koodi):
    """Kirjainkoodi, joka tarvitsee muunnostaulukon ("RAK", "RAK AV" -> "RAK"), tai None, jos
    koodista saa numeron suoraan ("9 1", "RAK 5") tai koodi puuttuu."""
    osat = str(koodi).split() if koodi is not None else []
    if not osat or osat[0].isdigit() or (len(osat) > 1 and osat[1].isdigit()):
        return None
    return osat[0].upper()


def krd_koodi(koodi, muunnos=None):
    """Numerokoodi krd:hen. Numerokoodista ensimmäinen osa ("9 1" -> "9"), kirjainkoodista
    tyyppinumero ("RAK 5" -> "5", "RAK 8 2" -> "8"), pelkästä kirjainkoodista muunnostaulukon
    numero ("RAK" -> "100"); tuntematon kirjainkoodi -> KRD_TUNTEMATON_KOODI."""
    osat = str(koodi).split() if koodi is not None else []
    if not osat:
        return "0"
    if osat[0].isdigit():
        return osat[0]
    if len(osat) > 1 and osat[1].isdigit():
        return osat[1]
    return (KRD_KOODIMUUNNOS if muunnos is None else muunnos).get(osat[0].upper(), KRD_TUNTEMATON_KOODI)


def _krd_valitut(pisteet, asemapisteet, apupisteet):
    """krd:hen tulevat pisteet [(indeksi, piste)] ja nimet, joilla on useampi mittaus eri paikoissa."""
    ryhmat = defaultdict(list)
    for i, p in enumerate(pisteet):
        if p.get("e") is not None and p.get("n") is not None:
            ryhmat[p["nimi"]].append((i, p))

    valitut = []
    useassa_paikassa = []
    for nimi, tietueet in ryhmat.items():
        kategoriat = {p["kategoria"] for _, p in tietueet}
        if "Asemapiste" in kategoriat:
            if asemapisteet:
                valitut.append(next((i, p) for i, p in tietueet if p["kategoria"] == "Asemapiste"))
            continue
        rtk = [(i, p) for i, p in tietueet if p["kategoria"] == KRD_RTK]
        mitatut = [(i, p) for i, p in tietueet if p["kategoria"] in KRD_MITATUT]
        liitokset = [(i, p) for i, p in tietueet if p["kategoria"] in KRD_LIITOKSET]
        if rtk:
            valitut.append(rtk[0])
        elif liitokset and mitatut:
            if apupisteet:
                valitut.append(mitatut[0])
        elif liitokset:
            valitut.append(liitokset[0])
        elif mitatut:
            valitut.append(mitatut[0])
            if any(math.hypot(p["e"] - mitatut[0][1]["e"], p["n"] - mitatut[0][1]["n"]) > 0.05 for _, p in mitatut):
                useassa_paikassa.append(nimi)
    valitut.sort(key=lambda t: t[0])
    return valitut, useassa_paikassa


def krd_kirjainkoodit(pisteet, asemapisteet=False, apupisteet=False):
    """krd:hen tulevien pisteiden kirjainkoodit, jotka tarvitsevat muunnoksen: {koodi: pisteiden määrä}."""
    valitut, _ = _krd_valitut(pisteet, asemapisteet, apupisteet)
    return dict(Counter(k for k in (_krd_kirjainkoodi(p.get("koodi")) for _, p in valitut) if k))


def krd_pisteet(pisteet, asemapisteet=False, apupisteet=False, koodimuunnos=None):
    """Pisteet krd-tiedostoon, yksi rivi nimeä kohden: liitospisteet ja mitatut pisteet,
    valittaessa myös asemapisteet ja apupisteet (kartoituspisteenä mitattu ja myöhemmin
    liitospisteenä käytetty). Koordinaatti: RTK-alkuperäinen > ensimmäinen kartoitusmittaus >
    ensimmäinen liitoshavainto. Rivit valitun tietueen tiedostojärjestyksessä. Koodit
    muunnetaan numeroiksi (krd_koodi); koodimuunnos = kirjainkoodien taulukko (oletus
    KRD_KOODIMUUNNOS). Palauttaa ([(numero, koodi, e, n, z)], varoitukset)."""
    muunnos = KRD_KOODIMUUNNOS if koodimuunnos is None else koodimuunnos
    valitut, useassa_paikassa = _krd_valitut(pisteet, asemapisteet, apupisteet)
    rivit = [(p["nimi"], krd_koodi(p.get("koodi"), muunnos), p["e"], p["n"], p.get("korkeus")) for _, p in valitut]
    varoitukset = []
    kaksiosaiset = [p["nimi"] for _, p in valitut
                    if len(str(p.get("koodi") or "").split()) > 1 and not _krd_kirjainkoodi(p.get("koodi"))]
    if kaksiosaiset:
        varoitukset.append("Koodista otettiin vain pistetyyppi (muut osat poistettu): " + ", ".join(kaksiosaiset))
    tuntemattomat = sorted({k for k in (_krd_kirjainkoodi(p.get("koodi")) for _, p in valitut)
                            if k and k not in muunnos})
    if tuntemattomat:
        varoitukset.append(f"Kirjainkoodeille ei ole muunnosta, kirjoitettu {KRD_TUNTEMATON_KOODI}: "
                           + ", ".join(tuntemattomat))
    ilman_korkeutta = [r[0] for r in rivit if r[4] is None]
    if ilman_korkeutta:
        varoitukset.append(f"{len(ilman_korkeutta)} pisteeltä puuttuu korkeus, kirjoitettu 0.000: "
                           + ", ".join(ilman_korkeutta[:20]) + (" ..." if len(ilman_korkeutta) > 20 else ""))
    pitkat = [r[0] for r in rivit if len(r[0]) > 8]
    if pitkat:
        varoitukset.append("Yli 8 merkin nimet eivät mahdu numerosarakkeeseen (sarakkeet siirtyvät): "
                           + ", ".join(pitkat))
    if useassa_paikassa:
        varoitukset.append("Samalla nimellä useampi mittaus yli 5 cm eri paikoissa, mukaan otettiin ensimmäinen: "
                           + ", ".join(useassa_paikassa))
    return rivit, varoitukset


def kirjoita_krd(rivit):
    """krd-tiedoston sisältö (bytes) riveistä [(numero, koodi, e, n, z)]."""
    import hae_kiintopisteet as hk

    return "".join(hk.krd_rivi(*r) for r in rivit).encode(hk.KRD_MERKISTO, errors="replace")


# ---------------------------------------------------------------------------
# Kannan tallennus JA poisto
# ---------------------------------------------------------------------------

def _tallennettavat_asemat(raportti):
    """Asemapisteet, joilla on koordinaatit; asema_nro = järjestysnumero tässä listassa (1, 2, ...)."""
    return [a for a in (raportti or {}).get("asemapisteet") or [] if a.get("e") is not None and a.get("n") is not None]


def mittausjarjestys(raportti, pisteet):
    """Mittauksen eteneminen tasaisena järjestyksenä (QGIS-animaatio): asema, sitten siltä mitatut
    pisteet aikajärjestyksessä, sitten seuraava asema jne. Asema alkaa sen ensimmäisestä havainnosta,
    joten liitospisteet tulevat aseman jälkeen. Asemattomat pisteet (GNSS) omalla ajallaan; Asemapiste-
    kategorian piste saa asemansa järjestyksen. Liitospisteiden RTK-alkuperäismittaukset eivät ole mukana.

    Palauttaa (asemat, pisteiden_tiedot): asemat = {asema_nro: jarjestys} (asema_nro kuten
    _tallennettavat_asemat()), pisteiden_tiedot = [(aseman nimi, asema_nro, jarjestys)] samassa
    järjestyksessä kuin pisteet (Nonet, jos piste ei kuulu järjestykseen)."""
    asemat = _tallennettavat_asemat(raportti)
    srid_nro = {a.get("station_record_id"): nro for nro, a in enumerate(asemat, 1)}
    nimi_nro = {}
    for nro, a in enumerate(asemat, 1):
        nimi_nro.setdefault(a["nimi"], nro)

    def pisteen_asema(p):
        if p.get("station_record_id") in srid_nro:
            return srid_nro[p["station_record_id"]]
        if p.get("kategoria") == "Asemapiste":
            return nimi_nro.get(p.get("nimi"))
        return None

    viimeinen = datetime.max
    alku = {nro: a.get("aikaleima") or viimeinen for nro, a in enumerate(asemat, 1)}
    for p in pisteet:
        nro = pisteen_asema(p)
        if nro and p.get("aikaleima"):
            alku[nro] = min(alku[nro], p["aikaleima"])
    # (aika, 0 = asema ennen saman hetken pisteitä, alkuperäinen järjestys, avain)
    tapahtumat = [(alku[nro], 0, nro, ("asema", nro)) for nro in alku]
    for i, p in enumerate(pisteet):
        if p.get("kategoria") == "Liitospiste (alkuperäinen RTK-mittaus)":
            continue
        if p.get("kategoria") == "Asemapiste" and pisteen_asema(p):
            continue
        tapahtumat.append((p.get("aikaleima") or viimeinen, 1, i, ("piste", i)))
    jarjestys = {avain: n for n, (_, _, _, avain) in enumerate(sorted(tapahtumat), 1)}

    asemien = {nro: jarjestys[("asema", nro)] for nro in alku}
    tiedot = []
    for i, p in enumerate(pisteet):
        nro = pisteen_asema(p)
        nimi = asemat[nro - 1]["nimi"] if nro else None
        if ("piste", i) in jarjestys:
            tiedot.append((nimi, nro, jarjestys[("piste", i)]))
        elif nro and p.get("kategoria") == "Asemapiste":
            tiedot.append((nimi, nro, asemien[nro]))
        else:
            tiedot.append((None, None, None))
    return asemien, tiedot


# Mittauksen lisätiedot kentalla_mitatut_pisteet-tauluun (sarake: arvo pisteestä). Kulmat gooneina
# (JobXML: asteet), kojeasento I/II. Takymetrin sarakkeet ovat RTK-pisteillä tyhjiä ja päinvastoin.
MITTAUSTIETOSARAKKEET = ("prisma", "prismatyyppi", "prismavakio_mm", "tahyskorkeus_m", "vaakakulma_gon",
                         "pystykulma_gon", "kojeasento", "kahdesta_kojeasennosta", "antennikorkeus_m",
                         "tarkkuus_vaaka_m", "tarkkuus_korkeus_m", "hdop", "vdop", "kallistusetaisyys_m",
                         "korjauksen_ika_s", "ominaisuudet")


def _mittaustiedot(p):
    """Pisteen lisätiedot MITTAUSTIETOSARAKKEET-järjestyksessä."""
    h = p.get("havainto") or {}
    g = p.get("gnss") or {}

    def gon(aste):
        return None if aste is None else round(aste * 400.0 / 360.0, 6)

    vakio = h.get("prismavakio_m")
    asento = {"Face1": "I", "Face2": "II"}.get(h.get("kojeasento"), h.get("kojeasento"))
    ominaisuudet = "; ".join(f"{o['nimi']}: {o['arvo']}" for o in p.get("ominaisuudet") or [] if o.get("arvo"))
    return (h.get("tahys"), h.get("prismatyyppi"), None if vakio is None else round(vakio * 1000, 1),
            h.get("tahyskorkeus_m"), gon(h.get("ha_deg")), gon(h.get("va_deg")), asento,
            bool(p.get("kahdesta_kojeasennosta")) if h else None, g.get("antennikorkeus"),
            p.get("tarkkuus_h"), p.get("tarkkuus_v"), p.get("hdop"), p.get("vdop"), g.get("kallistusetaisyys"),
            g.get("tukiaseman_ika_s"), ominaisuudet or None)


def tallenna_mittaukset_kantaan(kiinteistotunnus, pisteet, db_conn, raportti=None):
    """Pisteet kentalla_mitatut_pisteet-tauluun. Saman kiinteistön ja lähdetiedoston aiemmat pisteet
    korvataan (sama JXL uudelleen ei tuplaa, kuten raportti, asemat ja seinälinja). raportti
    (jasenna_tyo()-tulos) antaa pisteille aseman ja mittausjärjestyksen (QGIS-animaatio); ilman sitä
    ne jäävät tyhjiksi."""
    import hae_kiintopisteet as hk

    if not pisteet:
        return 0
    _, jarjestys = mittausjarjestys(raportti, pisteet) if raportti else (None, [(None, None, None)] * len(pisteet))
    lisatty = 0
    with hk.kanta(db_conn) as cur:
        for lahde in sorted({p.get("lahdetiedosto") for p in pisteet if p.get("lahdetiedosto")}):
            cur.execute("DELETE FROM kentalla_mitatut_pisteet WHERE kiinteistotunnus = %s AND lahdetiedosto = %s;",
                        (kiinteistotunnus, lahde))
        for p, (asema, asema_nro, nro) in zip(pisteet, jarjestys):
            if p.get("e") is None or p.get("n") is None:
                continue
            # kuvaus = pisteen kategoria, tarkkuusluokka = pistekoodi
            cur.execute(
                f"""INSERT INTO kentalla_mitatut_pisteet
                    (kiinteistotunnus, pistetunnus, kuvaus, mittaustapa, tarkkuusluokka,
                     vinoetaisyys, satelliitteja, pdop, korkeus, lahdetiedosto, mitattu, asema, asema_nro,
                     jarjestys, {", ".join(MITTAUSTIETOSARAKKEET)}, geom)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            {", ".join(["%s"] * len(MITTAUSTIETOSARAKKEET))},
                            ST_SetSRID(ST_MakePoint(%s, %s), {DB_SRID}));""",
                (kiinteistotunnus, p["nimi"], p.get("kategoria"), p.get("mittaustapa"), p.get("koodi"),
                 (p.get("havainto") or {}).get("sd_m"), p.get("satelliitteja"), p.get("pdop"),
                 p.get("korkeus"), p.get("lahdetiedosto"), p.get("aikaleima"), asema, asema_nro, nro,
                 *_mittaustiedot(p), p["e"], p["n"]),
            )
            lisatty += 1
    return lisatty


def tallenna_seinalinjat_kantaan(kiinteistotunnus, tulos, lahdetiedosto, db_conn, poikkeamat_lidar=None):
    """Seinälinjat (muodosta_seinalinja()-tulos) seinalinjat-tauluun. Saman kiinteistön ja
    lähdetiedoston aiemmat viivat korvataan, joten uudelleentallennus ei tuplaa.
    poikkeamat_lidar = seinalinja.poikkeamat_lidarista()-tulos tai None. Palauttaa
    tallennettujen viivojen määrän."""
    import hae_kiintopisteet as hk

    lidar = {p["nimi"]: p for p in poikkeamat_lidar or [] if p.get("keskiarvo_m") is not None}
    lisatty = 0
    with hk.kanta(db_conn) as cur:
        cur.execute("DELETE FROM seinalinjat WHERE kiinteistotunnus = %s AND lahdetiedosto = %s;",
                    (kiinteistotunnus, lahdetiedosto))
        for viiva in (tulos or {}).get("viivat", []):
            pisteet = sl.viivan_pisteet(viiva)
            if len(pisteet) < 2:
                continue
            p = lidar.get(viiva["nimi"])
            wkt = "LINESTRING(" + ", ".join(f"{e:.4f} {n:.4f}" for e, n in pisteet) + ")"
            cur.execute(
                f"""INSERT INTO seinalinjat
                    (kiinteistotunnus, viiva, taso, suljettu, pituus_m, lasketut_kulmat,
                     lidar_keskiarvo_cm, lidar_suurin_cm, lidar_peitto_pros, lahdetiedosto, geom)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, ST_GeomFromText(%s, {DB_SRID}));""",
                (kiinteistotunnus, viiva["nimi"], sl.dxf_taso(viiva["avain"]), viiva["suljettu"],
                 round(sum(math.dist(a, b) for a, b in zip(pisteet, pisteet[1:])), 3),
                 sum(1 for k in viiva["karjet"] if k["laji"] == "laskettu"),
                 round(p["keskiarvo_m"] * 100, 1) if p else None,
                 round(p["suurin_m"] * 100, 1) if p else None,
                 round(p["peitto"] * 100) if p else None,
                 lahdetiedosto, wkt),
            )
            lisatty += 1
    return lisatty


LAATULUOKAT = ("Erinomainen", "Hyvä", "Tyydyttävä", "Heikko", "Huono", "Ei laskettavissa")  # paras ensin


def _huonoin_asema(asemat):
    """Asema, jonka laatuluokka on huonoin (saman luokan sisällä pienin kokonaispiste), tai None."""
    def jarjestys(a):
        laatu = a.get("laatu") or {}
        luokka = laatu.get("luokka")
        return (LAATULUOKAT.index(luokka) if luokka in LAATULUOKAT else len(LAATULUOKAT),
                -(laatu.get("kokonaispiste") or 0))
    return max(asemat, key=jarjestys) if asemat else None


def _mm_tai_none(arvo_m):
    return round(arvo_m * 1000, 1) if arvo_m is not None else None


def tallenna_raportti_kantaan(kiinteistotunnus, raportti, pisteet, hylatyt, pdf, db_conn):
    """Mittausraportin yhteenveto ja PDF mittausraportit-tauluun sekä asemapisteet
    asemapisteet-tauluun. Saman kiinteistön ja lähdetiedoston aiempi raportti ja asemat
    korvataan. pdf = mittausraportti.tee_pdf()-tulos tai None. Palauttaa tallennettujen
    asemapisteiden määrän."""
    import hae_kiintopisteet as hk
    import mittausraportti as mr

    lahdetiedosto = raportti.get("lahdetiedosto")
    sisalto = mr.raportin_sisalto(raportti, pisteet, hylatyt)
    perustiedot = dict(sisalto["perustiedot"])
    kalusto = raportti.get("kalusto") or {}
    kalusto_teksti = "; ".join(
        [" ".join(x for x in (t.get("malli") or t.get("tyyppi"), t.get("sarjanumero")) if x)
         for t in kalusto.get("takymetrit", [])]
        + [" ".join(x for x in (g.get("vastaanotin"), g.get("sarjanumero")) if x) for g in kalusto.get("gnss", [])])
    asemat = _tallennettavat_asemat(raportti)
    asemien_jarjestys, pisteiden_jarjestys = mittausjarjestys(raportti, pisteet)   # sama kuin pisteillä
    # liitosviiva ilmestyy, kun asema mittaa liitospisteen (muuten aseman kanssa)
    liitoksen_jarjestys = {(nro, p["nimi"]): j for p, (_, nro, j) in zip(pisteet, pisteiden_jarjestys)
                           if nro and p.get("kategoria") in ("Liitospiste", "Korkeusliitos")}
    huonoin = _huonoin_asema(asemat)
    huonoin_laatu = (huonoin or {}).get("laatu") or {}
    mitatut = [p for p in pisteet if p["kategoria"] in mr.MITATUT_KATEGORIAT and p.get("e") is not None]
    keskipiste = ((sum(p["e"] for p in mitatut) / len(mitatut), sum(p["n"] for p in mitatut) / len(mitatut))
                  if mitatut else (asemat[0]["e"], asemat[0]["n"]) if asemat else None)

    with hk.kanta(db_conn) as cur:
        cur.execute("DELETE FROM mittausraportit WHERE kiinteistotunnus = %s AND lahdetiedosto = %s;",
                    (kiinteistotunnus, lahdetiedosto))
        for taulu in ("asemapisteet", "asemien_liitokset"):
            cur.execute(f"DELETE FROM {taulu} WHERE kiinteistotunnus = %s AND lahdetiedosto = %s;",
                        (kiinteistotunnus, lahdetiedosto))
        cur.execute(
            f"""INSERT INTO mittausraportit
                (kiinteistotunnus, lahdetiedosto, tyon_nimi, mittauspaiva, kalusto, mitattuja_pisteita,
                 asemia, hylattyja, huonoin_asema, huonoin_laatuluokka, tarkistukset, pdf, pdf_kt, geom)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        {"ST_SetSRID(ST_MakePoint(%s, %s), " + str(DB_SRID) + ")" if keskipiste else "NULL"});""",
            (kiinteistotunnus, lahdetiedosto, raportti.get("job_nimi"), perustiedot.get("Mittauspäivä"),
             kalusto_teksti or None, len(mitatut), len(raportti.get("asemapisteet") or []), len(hylatyt),
             huonoin["nimi"] if huonoin else None,
             (f"{huonoin_laatu.get('luokka')} ({huonoin_laatu['kokonaispiste']:.0f}/100)"
              if huonoin_laatu.get("kokonaispiste") is not None else huonoin_laatu.get("luokka")),
             "\n".join(sisalto["tarkistukset"]) or None,
             hk.psycopg2.Binary(pdf) if pdf else None, round(len(pdf) / 1024) if pdf else None,
             *(keskipiste or ())),
        )
        # asema_nro: järjestysnumero tiedoston sisällä; QGIS-tyyli laskee siitä aseman värin
        for asema_nro, a in enumerate(asemat, 1):
            laatu = a.get("laatu") or {}
            varoitukset = (laatu.get("varoitukset") or []) + [v for v in [mr._korkeusvaroitus(a)] if v]
            liitokset = _aseman_liitokset(a)
            for l in liitokset:
                cur.execute(
                    f"""INSERT INTO asemien_liitokset
                        (kiinteistotunnus, lahdetiedosto, asema, asema_nro, jarjestys, liitospiste, tyyppi,
                         delta_n_mm, delta_e_mm, dhz_mm, dh_mm, kaytto, pituus_m, geom)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                ST_SetSRID(ST_MakeLine(ST_MakePoint(%s, %s), ST_MakePoint(%s, %s)), {DB_SRID}));""",
                    (kiinteistotunnus, lahdetiedosto, a["nimi"], asema_nro,
                     liitoksen_jarjestys.get((asema_nro, l["liitospiste"]), asemien_jarjestys[asema_nro]),
                     l["liitospiste"], l["tyyppi"],
                     _mm_tai_none(l["delta_n"]), _mm_tai_none(l["delta_e"]), _mm_tai_none(l["dhz"]),
                     _mm_tai_none(l["delta_h"]), l["kaytto"], round(math.dist((a["e"], a["n"]), (l["e"], l["n"])), 3),
                     a["e"], a["n"], l["e"], l["n"]),
                )
            cur.execute(
                f"""INSERT INTO asemapisteet
                    (kiinteistotunnus, lahdetiedosto, asema, asema_nro, jarjestys, maarittely, laatuluokka,
                     laatupisteet,
                     rms_residuaali_mm, suurin_residuaali_mm, liitospisteita, kulmapeitto_deg, pdop_keskiarvo,
                     keskivirhe_n_mm, keskivirhe_e_mm, keskivirhe_h_mm, korkeus, kojekorkeus, mitattu,
                     varoitukset, liitospisteet, geom)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), {DB_SRID}));""",
                (kiinteistotunnus, lahdetiedosto, a["nimi"], asema_nro, asemien_jarjestys[asema_nro],
                 a.get("maarittely"), laatu.get("luokka"),
                 round(laatu["kokonaispiste"], 1) if laatu.get("kokonaispiste") is not None else None,
                 _mm_tai_none(laatu.get("rms_residuaali_m")), _mm_tai_none(laatu.get("suurin_residuaali_m")),
                 laatu.get("liitospisteita"),
                 round(laatu["kulmapeitto_deg"], 1) if laatu.get("kulmapeitto_deg") is not None else None,
                 laatu.get("pdop_keskiarvo"), _mm_tai_none(a.get("se_n_m")), _mm_tai_none(a.get("se_e_m")),
                 _mm_tai_none(a.get("se_korkeus_m")), a.get("korkeus"), a.get("kojekorkeus"), a.get("aikaleima"),
                 "; ".join(varoitukset) or None,
                 ", ".join(l["liitospiste"] + ("" if l["dhz"] is None else f" (dHz {l['dhz'] * 1000:.1f} mm)")
                           + (" korkeus" if l["tyyppi"] == "korkeusliitos" else "") for l in liitokset) or None,
                 a["e"], a["n"]),
            )
    return len(asemat)


def _aseman_liitokset(asema):
    """Aseman liitospisteet ja korkeusliitokset koordinaatteineen ja residuaaleineen (metreinä):
    [{"liitospiste", "tyyppi", "e", "n", "delta_n", "delta_e", "dhz", "delta_h", "kaytto"}]."""
    import mittausraportti as mr

    residuaalit = {r.get("liitospiste"): r for r in asema.get("residuaalit") or []}
    tulos = []
    for tyyppi, avain in (("liitospiste", "liitospisteet_koordinaatit"), ("korkeusliitos", "korkeusliitos_koordinaatit")):
        for nimi, n, e in asema.get(avain) or []:
            if n is None or e is None:
                continue
            r = residuaalit.get(nimi) or {}
            tulos.append({"liitospiste": nimi, "tyyppi": tyyppi, "e": e, "n": n,
                          "delta_n": r.get("delta_n"), "delta_e": r.get("delta_e"), "dhz": mr._vaaka(r),
                          "delta_h": r.get("delta_h"), "kaytto": mr.KAYTTO.get(r.get("kaytto"), r.get("kaytto"))})
    return tulos


def hae_raportit(db_conn, kiinteistotunnus=None, maara=50):
    """Tallennetut mittausraportit uusin ensin (ilman PDF:ää): lista sanakirjoja."""
    import hae_kiintopisteet as hk

    with hk.kanta(db_conn) as cur:
        cur.execute(
            """SELECT id, kiinteistotunnus, lahdetiedosto, tyon_nimi, mittauspaiva, asemia, mitattuja_pisteita,
                      huonoin_laatuluokka, tarkistukset, pdf_kt, tallennettu
               FROM mittausraportit WHERE %(tunnus)s::text IS NULL OR kiinteistotunnus = %(tunnus)s
               ORDER BY tallennettu DESC LIMIT %(maara)s;""",
            {"tunnus": kiinteistotunnus, "maara": maara})
        sarakkeet = [d[0] for d in cur.description]
        return [dict(zip(sarakkeet, rivi)) for rivi in cur.fetchall()]


def hae_raportin_pdf(kiinteistotunnus, lahdetiedosto, db_conn):
    """Tallennetun raportin PDF tavuina tai None. Haku kiinteistöllä ja lähdetiedostolla eikä
    id:llä, koska uudelleentallennus korvaa rivin uudella."""
    import hae_kiintopisteet as hk

    with hk.kanta(db_conn) as cur:
        cur.execute("SELECT pdf FROM mittausraportit WHERE kiinteistotunnus = %s AND lahdetiedosto = %s "
                    "ORDER BY tallennettu DESC LIMIT 1;", (kiinteistotunnus, lahdetiedosto))
        rivi = cur.fetchone()
    return bytes(rivi[0]) if rivi and rivi[0] is not None else None


def tiedoston_muut_kiinteistot(lahdetiedosto, kiinteistotunnus, db_conn):
    """Kiinteistötunnukset, joille sama lähdetiedosto on tallennettu kantaan tämän lisäksi (esim. ensin
    väärällä tunnuksella). Tallennus korvaa vain saman kiinteistön ja tiedoston rivit."""
    import hae_kiintopisteet as hk

    with hk.kanta(db_conn) as cur:
        cur.execute("SELECT DISTINCT kiinteistotunnus FROM kentalla_mitatut_pisteet "
                    "WHERE lahdetiedosto = %s AND kiinteistotunnus <> %s ORDER BY 1;",
                    (lahdetiedosto, kiinteistotunnus))
        return [rivi[0] for rivi in cur.fetchall()]


def poista_mittaukset_kannasta(kiinteistotunnus, db_conn):
    """Poistaa KAIKKI annetulle kiinteistötunnukselle tallennetut pisteet, seinälinjat,
    mittausraportit ja asemapisteet. Palauttaa (pisteet, viivat, raportit)."""
    return _poista_mittaukset("kiinteistotunnus = %s", (kiinteistotunnus,), db_conn)


def poista_mittaukset_lahdetiedostolla(lahdetiedosto, db_conn):
    """Poistaa vain yhden JobXML-tiedoston tuomat pisteet, seinälinjat, mittausraportin ja
    asemapisteet (lahdetiedosto-sarake). Palauttaa (pisteet, viivat, raportit)."""
    return _poista_mittaukset("lahdetiedosto = %s", (lahdetiedosto,), db_conn)


def poista_kaikki_mittaukset(db_conn):
    """Tyhjentää KOKO mittaustaulut (MITTAUSTAULUT, kaikki kiinteistöt).
    Palauttaa (pisteet, viivat, raportit)."""
    return _poista_mittaukset("TRUE", (), db_conn)


# Tallennetun mittauksen taulut; poistot koskevat kaikkia. Kolme ensimmäistä lasketaan.
MITTAUSTAULUT = ("kentalla_mitatut_pisteet", "seinalinjat", "mittausraportit", "asemapisteet", "asemien_liitokset")


def _poista_mittaukset(ehto, parametrit, db_conn):
    import hae_kiintopisteet as hk

    maarat = []
    with hk.kanta(db_conn) as cur:
        for taulu in MITTAUSTAULUT:
            cur.execute(f"DELETE FROM {taulu} WHERE {ehto};", parametrit)
            maarat.append(cur.rowcount)
    return tuple(maarat[:3])


# ---------------------------------------------------------------------------
# Apufunktiot
# ---------------------------------------------------------------------------

def _muotoile_kesto(sekuntia):
    h = sekuntia // 3600
    m = (sekuntia % 3600) // 60
    s = sekuntia % 60
    return f"{h}h {m}min {s}s" if h else f"{m}min {s}s"
