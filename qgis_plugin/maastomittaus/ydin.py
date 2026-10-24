"""
ydin.py -- Pluginin QGIS:stä riippumaton osa: JXL-tiedosto -> seinälinja,
kantakartan poikkeama ja riskit. Käyttää samoja moduuleja kuin Streamlit-sovellus
(jobxml_tuonti.py, seinalinja.py); rakenna_zip.py kopioi ne lib-kansioon.
"""

import json
import math
import os
import re
import shutil
import struct
import sys

# Skriptiversiossa (rakenna_zip.py) moduulilla ei ole tiedostoa (__file__ = "<...>") ja jaetut
# moduulit ovat jo sys.modulesissa; lib-kansiota ei silloin etsitä (työkansion lib ei kelpaa).
_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib") if os.path.isfile(__file__) else None
if _LIB and os.path.isdir(_LIB):
    # Jaetut moduulit tuodaan aina tämän lisäosan lib-kansiosta. QGIS:n Python-istunnossa voi
    # olla jo saman niminen vanha versio (lisäosa päivitetty ilman uudelleenkäynnistystä) tai
    # skriptiversion kopio; ne poistetaan, jotta käyttöön tulee tämän version koodi.
    if _LIB in sys.path:
        sys.path.remove(_LIB)
    sys.path.insert(0, _LIB)
    for _nimi in ("seinalinja", "jobxml_tuonti", "seinat_pilvesta"):
        sys.modules.pop(_nimi, None)

import jobxml_tuonti as jx  # noqa: E402
import seinalinja as sl  # noqa: E402

# (näytettävä nimi, seinalinja.muodosta_seinalinjat-tapa) samassa järjestyksessä kuin sovelluksessa
TAVAT = [("Automaattinen", "lyhin"), ("Mittausjärjestys", "mittaus"), ("Lyhin reitti (vanha)", "lyhin_vanha")]

# Poikkeaman luokat (yläraja m, luokka, väri): sovelluksen kartassa 5 ja 15 cm, lisäosassa
# oletuksena 3, 5 ja 15 cm (työkalun kenttä Poikkeaman luokkarajat)
POIKKEAMALUOKAT = sl.POIKKEAMALUOKAT
LUOKKARAJAT_OLETUS = "3 5 15"
# Kaksi ylintä luokkaa keltainen ja punainen kuten sovelluksessa; alemmat vihreän sävyt tummasta vaaleaan
_VIHREAT = ((24, 110, 40), (140, 205, 80))

KANTAKARTTA_MARGINAALI_M = 5.0
# Seinät 3D -tason seinän paksuus: ohut, jotta pistepilven seinäpinnan senttien ero näkyy
SEINAN_LEVEYS_M = 0.02


def lue_jxl(polku):
    """(raportti, pisteet, hylätyt) JobXML-tiedostosta."""
    with open(polku, "rb") as f:
        return jx.jasenna_tyo(f.read(), os.path.basename(polku))


def seinalinjan_alue(pisteet, marginaali_m=KANTAKARTTA_MARGINAALI_M):
    """Seinälinjan pisteiden alue (x0, y0, x1, y1) marginaalilla, tai None."""
    sl_pisteet = sl.seinalinjan_pisteet(pisteet)
    if not sl_pisteet:
        return None
    es, ns = [p["e"] for p in sl_pisteet], [p["n"] for p in sl_pisteet]
    return min(es) - marginaali_m, min(ns) - marginaali_m, max(es) + marginaali_m, max(ns) + marginaali_m


def _cm_teksti(arvo):
    return f"{arvo:g}".replace(".", ",")


def lue_luokkarajat(teksti):
    """Luokkarajat senttimetreinä tekstistä ("3 5 15", "3; 5; 15", "3, 5, 15" tai "2,5 5 15";
    desimaalipilkku käy) -> nouseva lista. Tyhjä = LUOKKARAJAT_OLETUS. ValueError, jos ei kelpaa."""
    teksti = (teksti or "").strip() or LUOKKARAJAT_OLETUS
    osat = []
    for osa in teksti.replace(";", " ").replace(", ", " ").split():
        # "3,5,15" (pilkut erottimina) vs. "2,5" (desimaalipilkku)
        osat.extend(osa.split(",") if osa.count(",") > 1 else [osa.replace(",", ".")])
    try:
        rajat = sorted({float(o) for o in osat if o})
    except ValueError:
        raise ValueError(f"Luokkarajat pitää antaa senttimetreinä välilyönnein erotettuna, esim. "
                         f"{LUOKKARAJAT_OLETUS} (annettu: {teksti})")
    if not rajat or rajat[0] <= 0:
        raise ValueError(f"Luokkarajojen pitää olla positiivisia senttimetrejä, esim. {LUOKKARAJAT_OLETUS}")
    return rajat


def poikkeamaluokat(rajat_cm=None):
    """Luokat [(yläraja m, luokka, väri)] rajoista (cm): alle 3 cm, 3–5 cm, ..., yli 15 cm. Värit
    liukuvat vihreästä keltaisen kautta punaiseen (kolmella luokalla samat kuin sovelluksessa)."""
    rajat = lue_luokkarajat(LUOKKARAJAT_OLETUS) if rajat_cm is None else list(rajat_cm)
    nimet = ([f"alle {_cm_teksti(rajat[0])} cm"]
             + [f"{_cm_teksti(a)}–{_cm_teksti(b)} cm" for a, b in zip(rajat, rajat[1:])]
             + [f"yli {_cm_teksti(rajat[-1])} cm"])
    vihreat = len(nimet) - 2
    varit = (["#2ca02c"] if vihreat == 1 else
             ["#" + "".join(f"{round(a + (b - a) * i / (vihreat - 1)):02x}" for a, b in zip(*_VIHREAT))
              for i in range(vihreat)]) + ["#ffbf00", "#d62728"]
    if len(nimet) == 2:
        varit = ["#2ca02c", "#d62728"]
    return [(rajat[i] / 100 if i < len(rajat) else math.inf, nimi, vari) for i, (nimi, vari) in
            enumerate(zip(nimet, varit[-len(nimet):]))]


def poikkeamaluokka(etaisyys_m, luokat=None):
    """(luokka, väri) poikkeamalle; luokat = poikkeamaluokat(...), oletuksena sovelluksen luokat."""
    if luokat is None:
        return sl.poikkeamaluokka(etaisyys_m)
    return next((luokka, vari) for raja, luokka, vari in luokat if etaisyys_m < raja)


def viivan_tiedot(viiva):
    """Viivan ominaisuudet tasolle: kohdekoodi, rakennetyyppi ja numero viivan avaimesta."""
    kohde, valinnat, numero = viiva["avain"]
    return {"kohde": kohde or None, "rakennetyyppi": ", ".join(valinnat) or None, "numero": numero}


def muodosta(pisteet, tapa="lyhin", kantakartta=None, kantakartta_jarjestykseen=True, lidar=None,
             lidar_paatelty=None):
    """Seinälinja ja vertailut kuten sovelluksessa. kantakartta = rakennusten renkaat
    (seinalinja.py) tai None; lidar = LiDAR-seinät janoina tai None (piilokulmat, järjestys
    ja vertailu, ks. seinalinja.muodosta_seinalinjat); lidar_paatelty = DXF:n PAATELTY-taso (vain
    järjestyksen apuna). Palauttaa {"tulos", "poikkeamat",
    "poikkeamat_lidar", "riskit", "lidar_aariviiva"}: tulos = muodosta_seinalinjat()-tulos,
    poikkeamat(_lidar) = poikkeamat_kantakartasta() / poikkeamat_lidarista() viivan nimen
    mukaan, riskit = kantakartan_riskit(), lidar_aariviiva = syntyikö suljettu ääriviiva."""
    tulos = sl.muodosta_seinalinjat(pisteet, tapa=tapa,
                                    kantakartta=kantakartta if kantakartta_jarjestykseen else None, lidar=lidar,
                                    lidar_paatelty=lidar_paatelty)
    poikkeamat, riskit = {}, []
    if kantakartta:
        poikkeamat = {p["nimi"]: p for p in sl.poikkeamat_kantakartasta(tulos, kantakartta)}
        riskit = sl.kantakartan_riskit(kantakartta, pisteet)
    poikkeamat_lidar = {p["nimi"]: p for p in sl.poikkeamat_lidarista(tulos, lidar)} if lidar else {}
    return {"tulos": tulos, "poikkeamat": poikkeamat, "poikkeamat_lidar": poikkeamat_lidar, "riskit": riskit,
            "lidar_aariviiva": bool(lidar and sl.lidar_aariviivat(lidar, lidar_paatelty))}


def keilausraportti(polku):
    """Lyhyt yhteenveto lidarpipen raportista (_raportti.json) lokiin: lista tekstejä."""
    with open(polku, encoding="utf-8") as f:
        r = json.load(f)
    rivit = []
    if r.get("points"):
        rivit.append(f"{r['points']:,}".replace(",", " ") + f" pistettä, {r.get('frames', '?')} ruutua")
    sulku = r.get("closure") or {}
    if sulku.get("before_m") and sulku.get("after_m"):
        rivit.append(f"sulkuvirhe {max(sulku['before_m'].values()) * 1000:.0f} mm -> "
                     f"{max(sulku['after_m'].values()) * 1000:.1f} mm optimoinnin jälkeen")
    seuranta = r.get("track") or {}
    if seuranta.get("rms_h_m") is not None:
        rivit.append(f"georeferointi seurannasta ({seuranta.get('points')} pistettä): RMS vaaka "
                     f"{seuranta['rms_h_m'] * 100:.1f} cm, pysty {seuranta.get('rms_v_m', 0) * 100:.1f} cm")
    optimointi = r.get("optimization") or {}
    if optimointi.get("max_correction_m") is not None:
        rivit.append(f"suurin korjaus optimoinnissa {optimointi['max_correction_m'] * 100:.0f} cm"
                     + (f", tähyksiä {optimointi['targets']}" if optimointi.get("targets") else ""))
    return rivit



def seinapalat(viiva, leveys_m=SEINAN_LEVEYS_M, naytteet=None, askel_m=0.25):
    """Seinälinja 3D-näkymän seinäksi: jokainen pätkä (kaarilla tihennetty) leveys_m levyisenä
    nelikulmiona ja sen korkeus (päiden korkeuksien keskiarvo, tai None). QGIS:n 3D-näkymä
    nostaa monikulmiot kentän korkeudelta; viivan omat korkeudet se hylkää.
    naytteet = vertailun näytteet [(e, n, ero_m tai None)] (esim. pistepilvestä etumerkillinen ero):
    pätkät pilkotaan noin askel_m paloiksi, ja pala saa lähimmän näytteen eron (None, jos
    näytettä ei ole askel_m sisällä), jotta 3D-seinän voi värittää poikkeaman mukaan.
    Palauttaa [([(e, n) x 4], korkeus, ero_m tai None)]."""
    palat = []
    pisteet = sl.viivan_pisteet_z(viiva)
    for (e1, n1, z1), (e2, n2, z2) in zip(pisteet, pisteet[1:]):
        pituus = math.hypot(e2 - e1, n2 - n1)
        if pituus < 1e-6:
            continue
        nx, ny = -(n2 - n1) / pituus * leveys_m / 2, (e2 - e1) / pituus * leveys_m / 2
        korkeudet = [z for z in (z1, z2) if z is not None]
        korkeus = sum(korkeudet) / len(korkeudet) if korkeudet else None
        osia = 1 if naytteet is None else max(1, round(pituus / askel_m))
        for i in range(osia):
            t0, t1 = i / osia, (i + 1) / osia
            a = (e1 + (e2 - e1) * t0, n1 + (n2 - n1) * t0)
            b = (e1 + (e2 - e1) * t1, n1 + (n2 - n1) * t1)
            ero = None
            if naytteet:
                keski = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                e, n, lahin = min(naytteet, key=lambda x: math.dist(keski, x[:2]))
                ero = lahin if math.dist(keski, (e, n)) <= askel_m else None
            z = korkeus if len(korkeudet) < 2 else z1 + (z2 - z1) * (t0 + t1) / 2
            palat.append(([(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny), (b[0] - nx, b[1] - ny),
                           (a[0] - nx, a[1] - ny)], z, ero))
    return palat


def pilven_seinaviivat(vertailu):
    """Pistepilvestä löytynyt seinäpinta viivoina (poikkeamat_pistepilvesta-tulos): peräkkäiset
    saman seinäpätkän näytteet yhdistetään, keilaamaton kohta katkaisee. [[(e, n), ...]]."""
    viivat, nykyinen, edellinen = [], [], None
    for piste, jana in zip(vertailu["seinapinta"], vertailu["jana"]):
        if piste is None or jana != edellinen:
            if len(nykyinen) > 1:
                viivat.append(nykyinen)
            nykyinen = []
        if piste is not None:
            nykyinen.append(piste)
        edellinen = jana
    if len(nykyinen) > 1:
        viivat.append(nykyinen)
    return viivat


def viivat_pisteista(viivat):
    """Mikä tahansa seinälinja (esim. DXF QGIS:ssä) samaan muotoon kuin muodosta_seinalinjat:
    viivat = [(nimi, [(e, n, korkeus tai None), ...])]. Suljettu, jos ensimmäinen ja viimeinen
    piste ovat samat (viimeinen jätetään pois). Palauttaa {"viivat": [...]} vertailuja ja
    seinapalat()-funktiota varten. Vertailut kootaan nimen mukaan, joten samannimiset viivat
    (esim. DXF:n Layer nimikenttänä) erotetaan: SEINALINJA, SEINALINJA (2), ..."""
    tulos, kaytetyt = [], set()
    for nimi, pisteet in viivat:
        pisteet = list(pisteet)
        suljettu = len(pisteet) > 3 and math.dist(pisteet[0][:2], pisteet[-1][:2]) < 1e-6
        if suljettu:
            pisteet = pisteet[:-1]
        if len(pisteet) < 2:
            continue
        alku, i = nimi, 1
        while nimi in kaytetyt:
            i += 1
            nimi = f"{alku} ({i})"
        kaytetyt.add(nimi)
        karjet = [{"e": e, "n": n, "z": z, "laji": "mitattu", "nimi": f"{nimi}/{i + 1}", "bulge": 0.0}
                  for i, (e, n, z) in enumerate(pisteet)]
        tulos.append({"nimi": nimi, "karjet": karjet, "suljettu": suljettu, "avain": ("", (), 1)})
    return {"viivat": tulos}


def las_pistemaara(polku):
    """LAS/LAZ-tiedoston pistemäärä otsikosta (LAS 1.4: 64-bittinen kenttä), tai None."""
    try:
        with open(polku, "rb") as f:
            otsikko = f.read(255)
        if otsikko[:4] != b"LASF" or len(otsikko) < 227:
            return None
        maara, = struct.unpack("<I", otsikko[107:111])
        if otsikko[25] >= 4 and len(otsikko) >= 255:
            maara = struct.unpack("<Q", otsikko[247:255])[0] or maara
        return maara
    except OSError:
        return None


def las_on_rgb(polku):
    """Onko LAS/LAZ-tiedoston pisteillä värit (pistemuodot 2, 3, 5, 7, 8 ja 10)."""
    try:
        with open(polku, "rb") as f:
            otsikko = f.read(105)
        return otsikko[:4] == b"LASF" and len(otsikko) == 105 and (otsikko[104] & 0x3F) in (2, 3, 5, 7, 8, 10)
    except OSError:
        return False


def las_korkeusalue(polku):
    """LAS-tiedoston pisteiden korkeusalue (min z, max z) otsikosta, tai None."""
    try:
        with open(polku, "rb") as f:
            otsikko = f.read(227)
        if otsikko[:4] != b"LASF" or len(otsikko) < 227:
            return None
        max_z, min_z = struct.unpack("<2d", otsikko[211:227])
        return min_z, max_z
    except OSError:
        return None


def kirjoita_dxf_r12(viivat, polku, taso="SEINALINJA"):
    """Seinälinjat DXF R12:ksi ilman lisäkirjastoja (MicroStation, QGIS ja AutoCAD lukevat):
    viivat = [(nimi, [(e, n), ...], suljettu)], yksi POLYLINE viivaa kohden tasolla taso."""
    rivit = ["0", "SECTION", "2", "ENTITIES"]
    for _, pisteet, suljettu in viivat:
        rivit += ["0", "POLYLINE", "8", taso, "66", "1", "70", "1" if suljettu else "0"]
        for e, n in pisteet:
            rivit += ["0", "VERTEX", "8", taso, "10", f"{e:.4f}", "20", f"{n:.4f}", "30", "0.0"]
        rivit += ["0", "SEQEND", "8", taso]
    rivit += ["0", "ENDSEC", "0", "EOF"]
    with open(polku, "w", encoding="ascii", newline="\r\n") as f:
        f.write("\n".join(rivit) + "\n")
    return polku


# Seinälinjan vertailu suoraan pistepilveen (ilman lidarpipen seinä-DXF:ää)
PILVI_KAISTA_M = 0.6         # seinäpintaa etsitään näin kaukaa seinälinjasta
PILVI_SIVU_M = 0.15          # kohdan ympäriltä seinän suunnassa
PILVI_PAADYT_M = 0.2         # seinäpätkän päistä ei arvioida (viereisen seinän pisteet)
PILVI_KORKEUS_M = (0.4, 2.5)  # seinäpinnan pisteet maanpinnasta (yli kasvillisuuden, alle räystään)
PILVI_MIN_PISTEET = 8        # vähemmällä kohdassa ei ole seinäpintaa (ei keilattu)
PILVI_MIN_KERROKSET = 5      # seinäpinnalla pisteitä vähintään näin monella 10 cm korkeuskerroksella


def lue_las_xyz(polku):
    """Pakkaamattoman LAS-tiedoston pisteet (n x 3 -numpy-taulukko e, n, z). LAZ/COPC pitää ensin
    purkaa (lisäosa rajaa pistepilven QGIS:n pdal:clip-työkalulla LAS-muotoon)."""
    import numpy as np

    with open(polku, "rb") as f:
        otsikko = f.read(375)
        if otsikko[:4] != b"LASF":
            raise ValueError(f"Ei LAS-tiedosto: {polku}")
        if otsikko[104] & 0x80 or otsikko[104] & 0x40:
            raise ValueError("Pakattu LAS (LAZ) -- pura ensin LAS-muotoon")
        alku, = struct.unpack("<I", otsikko[96:100])
        pituus, = struct.unpack("<H", otsikko[105:107])
        maara, = struct.unpack("<I", otsikko[107:111])
        if maara == 0 and otsikko[25] >= 4:      # LAS 1.4: 64-bittinen pistemäärä
            maara, = struct.unpack("<Q", otsikko[247:255])
        skaala = struct.unpack("<3d", otsikko[131:155])
        siirto = struct.unpack("<3d", otsikko[155:179])
        f.seek(alku)
        data = np.frombuffer(f.read(maara * pituus), dtype=np.uint8).reshape(maara, pituus)
    xyz_int = data[:, :12].copy().view("<i4").reshape(maara, 3)
    return xyz_int * np.array(skaala) + np.array(siirto)


def lue_las_paikallinen(polku, osa=5_000_000, luokat=False):
    """Pakkaamattoman LAS-tiedoston pisteet paikallisina float32-koordinaatteina (n x 3) ja siirto
    (e0, n0, 0): kartan koordinaatti = paikallinen + siirto. Puolet vähemmän muistia kuin lue_las_xyz,
    ja luku paloittain, joten iso pilvi (Stonex, kymmeniä miljoonia pisteitä) mahtuu muistiin.
    luokat=True: lisäksi pisteiden luokat (uint8; ilmakeilauksen katot erottavat seinät aidoista)."""
    import numpy as np

    with open(polku, "rb") as f:
        otsikko = f.read(375)
    if otsikko[:4] != b"LASF":
        raise ValueError(f"Ei LAS-tiedosto: {polku}")
    if otsikko[104] & 0x80 or otsikko[104] & 0x40:
        raise ValueError("Pakattu LAS (LAZ) -- pura ensin LAS-muotoon")
    alku, = struct.unpack("<I", otsikko[96:100])
    pituus, = struct.unpack("<H", otsikko[105:107])
    maara, = struct.unpack("<I", otsikko[107:111])
    if maara == 0 and otsikko[25] >= 4:      # LAS 1.4: 64-bittinen pistemäärä
        maara, = struct.unpack("<Q", otsikko[247:255])
    skaala = np.array(struct.unpack("<3d", otsikko[131:155]))
    siirto = np.array(struct.unpack("<3d", otsikko[155:179]))
    _, min_x, _, min_y = struct.unpack("<4d", otsikko[179:211])
    origo = np.array([math.floor(min_x), math.floor(min_y), 0.0])
    # Luokka: pistemuodoissa 0–5 tavussa 15 (5 alinta bittiä), muodoissa 6–10 tavussa 16
    muoto = otsikko[104] & 0x3F
    luokan_kohta, maski = (16, 0xFF) if muoto >= 6 else (15, 0x1F)
    tietue = np.dtype({"names": ["xyz", "luokka"], "formats": [("<i4", (3,)), "u1"],
                       "offsets": [0, luokan_kohta], "itemsize": pituus})
    data = np.memmap(polku, dtype=tietue, mode="r", offset=alku, shape=(maara,))
    xyz = np.empty((maara, 3), dtype=np.float32)
    luokka = np.empty(maara, dtype=np.uint8) if luokat else None
    for i in range(0, maara, osa):
        xyz[i:i + osa] = data["xyz"][i:i + osa] * skaala + (siirto - origo)
        if luokat:
            luokka[i:i + osa] = data["luokka"][i:i + osa] & maski
    del data
    return (xyz, origo, luokka) if luokat else (xyz, origo)


def taysi_vauhti():
    """Laskentasäie täydelle nopeudelle. QGIS ajaa Processing-työkalut taustasäikeessä: macOS siirtää sen
    tehokkuusytimille (mitattu Apple M: sama pistepilven ruutu 67 s -> 310 s) ja Windows 11 voi hidastaa
    taustasäiettä (EcoQoS). Palauttaa, onnistuiko; virheet ohitetaan (työkalu toimii silti)."""
    import ctypes
    import sys

    try:
        if sys.platform == "darwin":
            libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
            return libc.pthread_set_qos_class_self_np(0x19, 0) == 0          # QOS_CLASS_USER_INITIATED
        if sys.platform == "win32":
            from ctypes import wintypes

            class Tila(ctypes.Structure):     # THREAD_POWER_THROTTLING_STATE
                _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG),
                            ("StateMask", wintypes.ULONG)]

            k32 = ctypes.windll.kernel32
            saie = k32.GetCurrentThread()
            k32.SetThreadPriority(saie, 0)                                   # THREAD_PRIORITY_NORMAL
            tila = Tila(1, 1, 0)        # EXECUTION_SPEED-hidastus pois päältä
            return bool(k32.SetThreadInformation(saie, 3, ctypes.byref(tila), ctypes.sizeof(tila)))
    except Exception:
        pass
    return False


def ruudut(x0, y0, x1, y1, koko):
    """Ruutuverkko alueelle (x0, y0, x1, y1): [(i, j, e0, n0)], ruudun vasen alakulma (e0, n0) koon
    monikerroilla, joten samassa paikassa olevat ruudut ovat samat alueesta riippumatta."""
    i0, j0 = math.floor(x0 / koko), math.floor(y0 / koko)
    i1, j1 = math.floor(x1 / koko), math.floor(y1 / koko)
    return [(i, j, i * koko, j * koko) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


class Kattorasteri:
    """Ilmakeilauksen kattopisteet (rakennusluokka) rasterina alueelle (x0, y0, x1, y1) solulla solu [m].
    Ruuduittain lisätyt pisteet (lisaa) kootaan koko alueelle; seinat_pilvesta.roof_share mittaa linjoille
    katon läheisyyden (aidat ja muurit pois)."""

    def __init__(self, alue, solu=0.5):
        import numpy as np

        self.e0, self.n0 = float(alue[0]), float(alue[1])
        self.solu = solu
        self.rasteri = np.zeros((int((alue[2] - alue[0]) / solu) + 1, int((alue[3] - alue[1]) / solu) + 1), bool)

    def lisaa(self, xy):
        """xy (n x 2) kartan koordinaatteina (ETRS-GK25)."""
        import numpy as np

        q = np.floor((np.asarray(xy, float) - (self.e0, self.n0)) / self.solu).astype(np.int64)
        ok = (q[:, 0] >= 0) & (q[:, 0] < self.rasteri.shape[0]) & (q[:, 1] >= 0) & (q[:, 1] < self.rasteri.shape[1])
        self.rasteri[q[ok, 0], q[ok, 1]] = True


def _ulkonormaali(viiva, a, b):
    """Seinäpätkän a->b yksikkönormaali talosta ulospäin (suljettu viiva; avoimella vasen puoli)."""
    ux, uy = (b[0] - a[0]), (b[1] - a[1])
    pituus = math.hypot(ux, uy)
    vasen = (-uy / pituus, ux / pituus)
    if not viiva["suljettu"]:
        return vasen
    pts = [(k["e"], k["n"]) for k in viiva["karjet"]]
    ala = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))
    return (-vasen[0], -vasen[1]) if ala > 0 else vasen   # vastapäivään kiertävällä ulkopuoli oikealla


def _lahella(xyz, pisteet, vara_m):
    """Pistepilven pisteet viivan pisteiden ympäröivästä suorakaiteesta (vara_m reunoilla)."""
    import numpy as np

    es, ns = [p[0] for p in pisteet], [p[1] for p in pisteet]
    valinta = ((xyz[:, 0] > min(es) - vara_m) & (xyz[:, 0] < max(es) + vara_m)
               & (xyz[:, 1] > min(ns) - vara_m) & (xyz[:, 1] < max(ns) + vara_m))
    return xyz[valinta] if len(xyz) else np.zeros((0, 3))


def maanpinnat(viivat, xyz, sade_m=1.5):
    """Maanpinnan korkeus viivojen pisteissä pistepilvestä: alimpien pisteiden (2. persentiili)
    korkeus sade_m säteellä, tai None, jos pisteitä on alle PILVI_MIN_PISTEET.
    viivat = [(nimi, [(e, n, ...)])] -> [[korkeus tai None, ...] viivoittain]."""
    import numpy as np

    xyz = np.asarray(xyz)
    tulos = []
    for _, pisteet in viivat:
        lahella = _lahella(xyz, pisteet, sade_m)
        korkeudet = []
        for p in pisteet:
            z = lahella[(lahella[:, 0] - p[0]) ** 2 + (lahella[:, 1] - p[1]) ** 2 < sade_m ** 2, 2]
            korkeudet.append(float(np.percentile(z, 2)) if len(z) >= PILVI_MIN_PISTEET else None)
        tulos.append(korkeudet)
    return tulos


def poikkeamat_pistepilvesta(tulos, xyz, askel_m=0.25):
    """Seinälinjan etäisyys pistepilven seinäpinnasta viivoittain (kuten poikkeamat_lidarista):
    jokaisessa kohdassa seinäpinta on se etäisyys seinälinjan normaalin suunnassa (PILVI_KAISTA_M),
    jolla pisteitä on eniten eri korkeuksilla (pystysuora pinta), mukana maanpinnan ja räystään
    väliset pisteet (PILVI_KORKEUS_M paikallisesta maanpinnasta). Kohta ilman riittävästi pisteitä (keilaamaton) = None. Palauttaa
    [{"nimi", "naytteet": [(e, n, etäisyys_m)], "etumerkki": [+ = seinä ulompana], "seinapinta":
    [(e, n) löydetty seinäpinta tai None], "jana": [seinäpätkän indeksi], "maanpinnat":
    [(e, n, korkeus)], "keskiarvo_m", "suurin_m", "peitto"}]."""
    import numpy as np

    xyz = np.asarray(xyz)
    tulokset = []
    for viiva in tulos.get("viivat", []):
        pisteet = sl.viivan_pisteet(viiva)
        naytteet, etumerkit, maanpinnat, paikat = [], [], [], []   # paikat: (seinäpätkä, ulkonormaali)
        viivan_xyz = _lahella(xyz, pisteet, PILVI_KAISTA_M + 1.5)
        for j, (a, b) in enumerate(zip(pisteet, pisteet[1:])):
            pituus = math.dist(a, b)
            if pituus < 2 * PILVI_PAADYT_M:
                continue
            ux, uy = (b[0] - a[0]) / pituus, (b[1] - a[1]) / pituus
            nx, ny = _ulkonormaali(viiva, a, b)
            n = max(1, int((pituus - 2 * PILVI_PAADYT_M) / askel_m))
            kohdat = [PILVI_PAADYT_M + (pituus - 2 * PILVI_PAADYT_M) * k / n for k in range(n + 1)]
            paikat.extend([(j, (nx, ny))] * len(kohdat))
            dx, dy = viivan_xyz[:, 0] - a[0], viivan_xyz[:, 1] - a[1]
            s, t = dx * ux + dy * uy, dx * nx + dy * ny
            kaista = (s > -0.5) & (s < pituus + 0.5) & (np.abs(t) < PILVI_KAISTA_M + 1.0)
            if kaista.sum() < PILVI_MIN_PISTEET:
                # Keilaamaton seinä kuuluu peittoon (None-näytteet) kuten poikkeamat_lidarista
                naytteet.extend((a[0] + ux * sk, a[1] + uy * sk, None) for sk in kohdat)
                etumerkit.extend([None] * len(kohdat))
                continue
            s, t, z = s[kaista], t[kaista], viivan_xyz[kaista, 2]
            maa = float(np.percentile(z, 2))
            maanpinnat.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, maa))
            seina = (z > maa + PILVI_KORKEUS_M[0]) & (z < maa + PILVI_KORKEUS_M[1]) & (np.abs(t) < PILVI_KAISTA_M)
            s, t, z_seina = s[seina], t[seina], z[seina]
            for sk in kohdat:
                e, nn = a[0] + ux * sk, a[1] + uy * sk
                valinta = np.abs(s - sk) < PILVI_SIVU_M
                lahella, korkeus = t[valinta], z_seina[valinta]
                if len(lahella) < PILVI_MIN_PISTEET:
                    naytteet.append((e, nn, None))
                    etumerkit.append(None)
                    continue
                # Seinä on pystysuora: valitaan etäisyys, jolla pisteitä on mahdollisimman monella
                # korkeudella (10 cm kerrokset). Räystäs on yhdellä korkeudella, kasvillisuus hajallaan.
                lokerot = np.floor((lahella + PILVI_KAISTA_M) / 0.02).astype(int)
                kerrokset = np.floor((korkeus - maa) / 0.1).astype(int)
                parit = np.unique(lokerot * 1000 + kerrokset)
                peitto = np.bincount(parit // 1000, minlength=int(2 * PILVI_KAISTA_M / 0.02) + 2).astype(float)
                tasoitettu = np.convolve(peitto, np.ones(3), "same")
                paras = int(np.argmax(tasoitettu))
                if peitto[max(0, paras - 1):paras + 2].max() < PILVI_MIN_KERROKSET:
                    naytteet.append((e, nn, None))
                    etumerkit.append(None)
                    continue
                huippu = (paras + 0.5) * 0.02 - PILVI_KAISTA_M
                lahi = lahella[np.abs(lahella - huippu) < 0.03]
                ero = float(np.mean(lahi))
                naytteet.append((e, nn, abs(ero)))
                etumerkit.append(ero)
        # Yksittäinen piikki (kumpikin naapuri yli 10 cm eri suuntaan) on kohinaa, ei seinää;
        # yhtenäinen jakso (esim. porras tai uloke, jota seinälinjassa ei ole) säilyy. Naapurit vain
        # samalta seinäpätkältä (kulman takana on eri seinä).
        for i in range(1, len(etumerkit) - 1):
            ed, nyk, seur = etumerkit[i - 1], etumerkit[i], etumerkit[i + 1]
            if paikat[i - 1][0] != paikat[i][0] or paikat[i + 1][0] != paikat[i][0]:
                continue
            if None not in (ed, nyk, seur) and abs(nyk - ed) > 0.1 and abs(nyk - seur) > 0.1:
                naytteet[i] = (naytteet[i][0], naytteet[i][1], None)
                etumerkit[i] = None
        etaisyydet = [d for _, _, d in naytteet if d is not None]
        seinapinta = [None if ero is None else (e + nx * ero, n + ny * ero)
                      for (e, n, _), ero, (_, (nx, ny)) in zip(naytteet, etumerkit, paikat)]
        tulokset.append({"nimi": viiva.get("nimi"), "naytteet": naytteet, "etumerkki": etumerkit,
                         "seinapinta": seinapinta, "jana": [j for j, _ in paikat], "maanpinnat": maanpinnat,
                         "keskiarvo_m": sum(etaisyydet) / len(etaisyydet) if etaisyydet else None,
                         "suurin_m": max(etaisyydet) if etaisyydet else None,
                         "peitto": len(etaisyydet) / len(naytteet) if naytteet else 0.0})
    return tulokset


def las_alue(polku):
    """LAS/LAZ-tiedoston pisteiden alue (x0, y0, x1, y1) otsikosta (myös pakatussa), tai None."""
    try:
        with open(polku, "rb") as f:
            otsikko = f.read(227)
        if otsikko[:4] != b"LASF" or len(otsikko) < 227:
            return None
        max_x, min_x, max_y, min_y = struct.unpack("<4d", otsikko[179:211])
        return min_x, min_y, max_x, max_y
    except OSError:
        return None


# Pistepilven koordinaatisto. Stonexin GOpost tallentaa ETRS-GK25:n ilman kaistan tunnusta
# (EPSG:3132, itä ~500 000) ja osa ohjelmista merkitsee EPSG:3132:n, vaikka luvuissa 25 on mukana.
GK25_EPSG = 3879
GK25_ILMAN_KAISTAA_EPSG = 3132
GK25_KAISTA_M = 25_000_000.0
_GK25_ITA = (25_400_000.0, 25_600_000.0)   # ETRS-GK25:n itäkoordinaatit Suomessa
_SUOMI_POHJOINEN = (6_550_000.0, 7_850_000.0)
_GEOKEY_PROJEKTIO = 3072   # ProjectedCSTypeGeoKey
_GEOKEY_MAANT = 2048       # GeographicTypeGeoKey


def _las_vlrt(f, otsikko):
    """Otsikon VLR:t [(tiedoston kohta, jossa data alkaa, user_id, record_id, data)]."""
    otsikon_koko, = struct.unpack("<H", otsikko[94:96])
    maara, = struct.unpack("<I", otsikko[100:104])
    kohta, vlrt = otsikon_koko, []
    for _ in range(maara):
        f.seek(kohta)
        paa = f.read(54)
        if len(paa) < 54:
            break
        pituus, = struct.unpack("<H", paa[20:22])
        vlrt.append((kohta + 54, paa[2:18].split(b"\0")[0].decode("ascii", "replace"),
                     struct.unpack("<H", paa[18:20])[0], f.read(pituus)))
        kohta += 54 + pituus
    return vlrt


def _wkt_projcs(wkt):
    """(alku, loppu) WKT:n PROJCS[...]-osalle (myös COMPD_CS:n sisältä), tai None."""
    alku = wkt.find("PROJCS[")
    if alku < 0:
        return None
    syvyys = 0
    for i in range(alku + 6, len(wkt)):
        syvyys += {"[": 1, "]": -1}.get(wkt[i], 0)
        if syvyys == 0:
            return alku, i + 1
    return None


def _wkt_epsg(wkt):
    """PROJCS:n EPSG-koodi WKT:stä (viimeinen AUTHORITY PROJCS:n sisällä), tai None."""
    osa = _wkt_projcs(wkt)
    koodit = re.findall(r'AUTHORITY\["EPSG","(\d+)"\]', wkt[osa[0]:osa[1]] if osa else "")
    return int(koodit[-1]) if koodit else None


def las_otsikko(polku):
    """LAS/LAZ-otsikon tiedot: {"alue": (x0, y0, x1, y1), "epsg": koordinaatisto otsikosta tai None}.
    Koordinaatisto GeoTIFF-avaimista tai WKT:stä (LAS 1.4 WKT-merkintä: WKT ensin). None, jos
    tiedosto ei ole LAS."""
    with open(polku, "rb") as f:
        otsikko = f.read(375)
        if otsikko[:4] != b"LASF" or len(otsikko) < 227:
            return None
        max_x, min_x, max_y, min_y = struct.unpack("<4d", otsikko[179:211])
        geoavain = wkt = None
        for _, kayttaja, tunnus, data in _las_vlrt(f, otsikko):
            if kayttaja == "LASF_Projection" and tunnus == 34735 and len(data) >= 8:
                arvot = struct.unpack(f"<{len(data) // 2}H", data[:len(data) // 2 * 2])
                for i in range(4, 4 + 4 * arvot[3], 4):
                    avain, sijainti, _, arvo = arvot[i:i + 4]
                    if sijainti == 0 and avain in (_GEOKEY_PROJEKTIO, _GEOKEY_MAANT) and 0 < arvo < 32767:
                        geoavain = geoavain if geoavain and avain == _GEOKEY_MAANT else arvo
            elif tunnus == 2112 and wkt is None:
                wkt = _wkt_epsg(data.split(b"\0")[0].decode("ascii", "replace"))
    wkt_ensin = otsikko[6] & 0x10
    epsg = (wkt or geoavain) if wkt_ensin else (geoavain or wkt)
    return {"alue": (min_x, min_y, max_x, max_y), "epsg": epsg}


def luku(x):
    return f"{x:,.0f}".replace(",", " ")


def paattele_las_koordinaatisto(alue, epsg):
    """Pistepilven koordinaatisto otsikon alueesta ja merkinnästä. Palauttaa {"siirto_x": lisättävä
    itäkoordinaattiin, "epsg": koordinaatisto siirron jälkeen, "kerros_epsg": tason koordinaatisto
    QGIS:ssä (luvut sellaisinaan), "otsikko_epsg": otsikon merkintä, "selitys"}. Jos "epsg" ei ole
    GK25_EPSG, pisteet pitää muuntaa siitä. ValueError, jos koordinaatistoa ei voi päätellä (esim.
    paikallinen koordinaatisto)."""
    x0, y0, x1, y1 = alue
    pohjoinen = _SUOMI_POHJOINEN[0] <= y0 and y1 <= _SUOMI_POHJOINEN[1]
    merkinta = f"EPSG:{epsg}" if epsg else "ei koordinaatistoa"
    if pohjoinen and _GK25_ITA[0] <= x0 and x1 <= _GK25_ITA[1]:
        selitys = "ETRS-GK25 (EPSG:3879)"
        if epsg != GK25_EPSG:
            selitys += f"; otsikossa {merkinta}, mutta itäkoordinaateissa on kaistan tunnus 25 (X = {luku(x0)})"
        return {"siirto_x": 0.0, "epsg": GK25_EPSG, "kerros_epsg": GK25_EPSG, "otsikko_epsg": epsg,
                "selitys": selitys}
    ilman_kaistaa = (_GK25_ITA[0] - GK25_KAISTA_M <= x0 and x1 <= _GK25_ITA[1] - GK25_KAISTA_M)
    if pohjoinen and ilman_kaistaa and epsg in (None, GK25_EPSG, GK25_ILMAN_KAISTAA_EPSG):
        selitys = (f"itäkoordinaatista puuttuu kaistan tunnus 25 (X = {luku(x0)}, otsikossa {merkinta}), "
                   f"lisätään {luku(GK25_KAISTA_M)}")
        return {"siirto_x": GK25_KAISTA_M, "epsg": GK25_EPSG, "kerros_epsg": GK25_ILMAN_KAISTAA_EPSG,
                "otsikko_epsg": epsg, "selitys": selitys}
    if epsg and epsg not in (GK25_EPSG, GK25_ILMAN_KAISTAA_EPSG):
        return {"siirto_x": 0.0, "epsg": epsg, "kerros_epsg": epsg, "otsikko_epsg": epsg,
                "selitys": f"otsikossa EPSG:{epsg}, muunnetaan ETRS-GK25:een (EPSG:3879)"}
    raise ValueError(
        f"Pistepilven koordinaatistoa ei voi päätellä (X {luku(x0)}–{luku(x1)}, Y {luku(y0)}–{luku(y1)}, "
        f"otsikossa {merkinta}). Pistepilven pitää olla ETRS-GK25:ssä (EPSG:3879, myös ilman kaistan tunnusta "
        "25) tai sen otsikossa pitää olla koordinaatisto.")


def las_koordinaatisto(polku):
    """paattele_las_koordinaatisto LAS/LAZ-tiedoston otsikosta; ValueError, jos ei voi päätellä."""
    tiedot = las_otsikko(polku)
    if tiedot is None:
        raise ValueError(f"Ei LAS/LAZ-tiedosto: {os.path.basename(polku)}")
    return paattele_las_koordinaatisto(tiedot["alue"], tiedot["epsg"])


def _gk25_wkt(wkt):
    """ETRS-GK25:n (ilman kaistan tunnusta) PROJCS-WKT muutettuna EPSG:3879:ksi: nimi, false_easting
    ja EPSG-koodi. None, jos WKT ei ole GK25 (keskimeridiaani 25, false_easting 500000)."""
    osa = _wkt_projcs(wkt)
    if osa is None:
        return None
    projcs = wkt[osa[0]:osa[1]]
    if not re.search(r'PARAMETER\["central_meridian",25(\.0*)?\]', projcs):
        return None
    uusi = re.sub(r'PARAMETER\["false_easting",500000(\.0*)?\]', 'PARAMETER["false_easting",25500000]', projcs)
    uusi = re.sub(r'^PROJCS\["[^"]*"', 'PROJCS["ETRS89 / GK25FIN"', uusi)
    uusi = re.sub(r'AUTHORITY\["EPSG","\d+"\]\]$', 'AUTHORITY["EPSG","3879"]]', uusi)   # PROJCS:n oma
    if 'PARAMETER["false_easting",25500000]' not in uusi:
        return None
    return wkt[:osa[0]] + uusi + wkt[osa[1]:]


def korjaa_las_gk25(lahde, kohde):
    """Kopio LAS/LAZ-tiedostosta ETRS-GK25:ssä kaistan tunnuksen kanssa (EPSG:3879). Pisteitä ei
    kirjoiteta uudelleen: kaistan tunnus lisätään otsikon X-siirtoon (pisteiden kokonaisluvut
    pysyvät, joten tarkkuus säilyy ja myös pakattu LAZ käy) ja koordinaatistomerkintä vaihdetaan
    samanmittaisena paikallaan (GeoTIFF-avain ja WKT). Korkeusjärjestelmää ei lisätä (ei mahdu).
    Palauttaa (paattele_las_koordinaatisto, [tehdyt muutokset]). ValueError, jos pilvi ei ole
    ETRS-GK25:ssä (muut koordinaatistot: QGIS:n Reproject point cloud)."""
    tiedot = las_koordinaatisto(lahde)
    if tiedot["epsg"] != GK25_EPSG:
        raise ValueError(f"Pistepilvi ei ole ETRS-GK25:ssä ({tiedot['selitys']}). Muunna se QGIS:n työkalulla "
                         "Reproject point cloud (pdal:reproject) koordinaatistoon EPSG:3879.")
    if os.path.abspath(lahde) == os.path.abspath(kohde):
        raise ValueError("Korjattu pistepilvi pitää tallentaa eri tiedostoon.")
    shutil.copyfile(lahde, kohde)
    muutokset = []
    with open(kohde, "r+b") as f:
        otsikko = f.read(375)
        if tiedot["siirto_x"]:
            siirto_x, = struct.unpack("<d", otsikko[155:163])
            max_x, min_x = struct.unpack("<2d", otsikko[179:195])
            f.seek(155)
            f.write(struct.pack("<d", siirto_x + tiedot["siirto_x"]))
            f.seek(179)
            f.write(struct.pack("<2d", max_x + tiedot["siirto_x"], min_x + tiedot["siirto_x"]))
            muutokset.append(f"itäkoordinaatteihin lisätty {luku(tiedot['siirto_x'])}")
        for kohta, kayttaja, tunnus, data in _las_vlrt(f, otsikko):
            if kayttaja == "LASF_Projection" and tunnus == 34735 and len(data) >= 8:
                arvot = list(struct.unpack(f"<{len(data) // 2}H", data[:len(data) // 2 * 2]))
                for i in range(4, 4 + 4 * arvot[3], 4):
                    if arvot[i] == _GEOKEY_PROJEKTIO and arvot[i + 1] == 0 and arvot[i + 3] != GK25_EPSG:
                        f.seek(kohta + 2 * (i + 3))
                        f.write(struct.pack("<H", GK25_EPSG))
                        muutokset.append(f"GeoTIFF-avain EPSG:{arvot[i + 3]} -> EPSG:3879")
            elif tunnus == 2112:
                vanha = data.split(b"\0")[0].decode("ascii", "replace")
                uusi = _gk25_wkt(vanha)
                if uusi is None or uusi == vanha:
                    continue
                tavut = uusi.encode("ascii")
                if len(tavut) > len(data):
                    tavut = uusi.replace("TOWGS84[0,0,0,0,0,0,0],", "").encode("ascii")
                if len(tavut) > len(data):
                    muutokset.append(f"WKT ({kayttaja}) jäi ennalleen: uusi ei mahdu")
                    continue
                f.seek(kohta)
                f.write(tavut + b"\0" * (len(data) - len(tavut)))
                muutokset.append(f"WKT ({kayttaja}) -> EPSG:3879")
    if not any("EPSG:3879" in m for m in muutokset):
        muutokset.append("otsikossa ei ole koordinaatistoa, jonka voisi vaihtaa: aseta tasolle QGIS:ssä EPSG:3879")
    return tiedot, muutokset


def korjaa_paluunumerot(polku):
    """Pakkaamattoman LAS-tiedoston pisteille paluunumero ja paluiden määrä 1, jos jossakin pisteessä
    on 0 (Stonex: ReturnNumber 1, NumberOfReturns 0; PDAL:n maanpinnan luokittelu SMRF hylkää ne).
    Muokkaa tiedostoa paikallaan. Palauttaa korjattujen pisteiden määrän."""
    import numpy as np

    with open(polku, "rb") as f:
        otsikko = f.read(375)
    if otsikko[:4] != b"LASF" or otsikko[104] & 0xC0:
        raise ValueError("Ei pakkaamaton LAS")
    alku, = struct.unpack("<I", otsikko[96:100])
    muoto, pituus = otsikko[104] & 0x3F, struct.unpack("<H", otsikko[105:107])[0]
    maara = las_pistemaara(polku)
    if not maara:
        return 0
    pisteet = np.memmap(polku, dtype=np.uint8, mode="r+", offset=alku, shape=(maara, pituus))
    tavu = pisteet[:, 14]
    if muoto >= 6:   # LAS 1.4: paluunumero bitit 0-3, määrä 4-7
        nolla = ((tavu & 0x0F) == 0) | ((tavu >> 4) == 0)
        korjattu = (tavu & 0xF0) | 0x01
        korjattu = np.where((korjattu >> 4) == 0, korjattu | 0x10, korjattu)
    else:            # paluunumero bitit 0-2, määrä 3-5
        nolla = ((tavu & 0x07) == 0) | (((tavu >> 3) & 0x07) == 0)
        korjattu = (tavu & 0xF8) | 0x01
        korjattu = np.where(((korjattu >> 3) & 0x07) == 0, korjattu | 0x08, korjattu)
    n = int(nolla.sum())
    if n:
        pisteet[nolla, 14] = korjattu[nolla]
        pisteet.flush()
    del pisteet
    return n
