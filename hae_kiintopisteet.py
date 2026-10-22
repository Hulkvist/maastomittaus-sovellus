"""
hae_kiintopisteet.py
--------------------
Koordinaatisto: ETRS-GK25 (EPSG:3879) kaikkialla.

MML:n avoimet rajapinnat: kiinteistön sijainti, rajamerkit ja rajaviivat,
osoitehaku, kiintopisteiden lataus, kiinteistön tunnistus mitatuista pisteistä.
Tulokset PostGIS-kantaan, txt-tiedostoon ja kartoille (PNG ja zoomattava folium).

Vaatimukset:
pip install requests psycopg2-binary shapely matplotlib contextily pyproj pillow
GDAL/ogr2ogr asennettuna
PostgreSQL + PostGIS, jossa schema.sql on ajettu

Käyttö:
export MML_API_KEY="oma-api-avaimesi"
python3 hae_kiintopisteet.py --kiinteistotunnus 091-25-840-8 \\
    --sade 1000 --kiinteistorajat \\
    --tulostiedosto kiintopisteet.krd --kartta-tiedosto kartta.png
"""

import os
import re
import sys
import time
import json
import math
import argparse
import subprocess
import io
import shutil
from collections import Counter
from contextlib import contextmanager
from functools import lru_cache
import requests
import psycopg2
from shapely.geometry import shape

MML_API_KEY = os.environ.get("MML_API_KEY")
BASE_TIEDOSTOPALVELU = "https://avoin-paikkatieto.maanmittauslaitos.fi/tiedostopalvelu/ogcproc/v1"
BASE_KIINTEISTO_API = "https://avoin-paikkatieto.maanmittauslaitos.fi/kiinteisto-avoin/simple-features/v3"
BASE_KARTTAKUVA_WMTS = "https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wmts/1.0.0"
BASE_GEOCODING = "https://avoin-paikkatieto.maanmittauslaitos.fi/geocoding"

# Helsingin kaupungin avoin WMS-rajapinta (kantakartta taustaksi Helsingin alueella)
HELSINKI_WMS_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wms"
HELSINKI_KANTAKARTTA_LAYER = "avoindata:Kantakartta"
HELSINKI_KANTAKARTTA_HARMAA_LAYER = "avoindata:Kantakartta_harmaa"
HELSINKI_WFS_URL = "https://kartta.hel.fi/ws/geoserver/avoindata/wfs"
HELSINKI_RAKENNUKSET_LAYER = "avoindata:Rakennukset_alue"
HELSINKI_KUNTANUMERO = "091"

COORDINATE_SYSTEMS = {
    "ETRS-GK25 / EPSG:3879": 3879,
    "ETRS-TM35FIN / EPSG:3067": 3067,
    "WGS84 / EPSG:4326": 4326,
}

DB_SRID = 3879
FILESERVICE_SRID = 3067
KIINTOPISTE_KOODI = 11
RAJAMERKKI_KOODI = 12
RAKENNUKSEN_KULMA_KOODI = 4
OMA_KIINTOPISTE_LUOKKA = "Helsinki (oma tiedosto)"
SUURI_PINTA_ALA_VAROITUSRAJA = 50000

KIINTEISTO_TUNNISTUS_KATEGORIAT = {"Kartoituspiste", "Merkintäpiste", "Suunnittelupiste (Construction)"}

HELSINKI_BBOX_3067 = [370000, 6660000, 410000, 6690000]

RAJAMERKKI_TUNNUS_KENTAT = [
    "numero", "rajamerkkitunnus", "rajamerkin_tunnus", "tunnus", "pistetunnus", "id",
]

DB_CONN = {
    "dbname": os.environ.get("PGDATABASE", "kiintopisteet_db"),
    "user": os.environ.get("PGUSER", "postgres"),
    "password": os.environ.get("PGPASSWORD", ""),
    "host": os.environ.get("PGHOST", "localhost"),
    "port": os.environ.get("PGPORT", "5432"),
}


def lisaa_api_key(url, api_key):
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}api-key={api_key}"


def normalisoi_kiinteistotunnus(tunnus):
    osat = tunnus.split("-")
    if len(osat) != 4:
        return tunnus.replace("-", "")
    kunta, sijaintialue, ryhma, yksikko = osat
    return kunta.zfill(3) + sijaintialue.zfill(3) + ryhma.zfill(4) + yksikko.zfill(4)


def on_helsinki(kiinteistotunnus_raw):
    tunnus = normalisoi_kiinteistotunnus(kiinteistotunnus_raw)
    return tunnus[:3] == HELSINKI_KUNTANUMERO


def laske_zoom(leveys_m, max_tiles_per_side=5, max_zoom=18, min_zoom=10):
    """Suurin zoom, jolla alue mahtuu max_tiles_per_side tiileen. leveys_m on alueen
    leveys Web Mercator -metreinä (EPSG:3857), ei maastossa: 60. leveyspiirillä
    Mercator-metrejä on noin kaksi kertaa maastometrit."""
    for z in range(max_zoom, min_zoom - 1, -1):
        tile_size_m = 40075016.686 / (2 ** z)
        tiles_per_side = leveys_m / tile_size_m
        if tiles_per_side <= max_tiles_per_side:
            return z
    return min_zoom


def poimi_pistenumero(tunnus):
    if not tunnus:
        return tunnus
    m = re.search(r'[A-Za-z](\d+)', tunnus)
    return m.group(1) if m else tunnus


def kiintopisteen_nimi(pistetunnus, luokka):
    """Näytettävä nimi: MML:n tunnuksesta numero-osa, omista kiintopisteistä koko tunnus."""
    return pistetunnus if luokka == OMA_KIINTOPISTE_LUOKKA else poimi_pistenumero(pistetunnus)


def on_paamerkki(tunnus):
    if not tunnus:
        return True
    m = re.search(r'[A-Za-z](\d+)', tunnus)
    if not m:
        return True
    return m.end() == len(tunnus)


def jarjesta_e_n(a, b):
    return (a, b) if a > b else (b, a)


def lataa_kiintopisteet_gpkg(bbox, api_key, out_path, max_odotus_s=300):
    """Lataa kiintopisteet bboxilta (EPSG:3067, [x0, y0, x1, y1]) GPKG-tiedostoon
    MML:n tiedostopalvelun asynkronisena työnä."""
    exec_url = lisaa_api_key(
        f"{BASE_TIEDOSTOPALVELU}/processes/kiintopisteet_bbox/execution", api_key
    )
    payload = {
        "id": "kiintopisteet_bbox",
        "inputs": {"boundingBoxInput": bbox, "fileFormatInput": "GPKG"},
    }
    headers = {"Content-Type": "application/json"}
    resp = requests.post(exec_url, headers=headers, data=json.dumps(payload), timeout=60)
    resp.raise_for_status()
    job = resp.json()
    job_id = job["jobID"]
    print(f"Työ käynnistetty (jobID={job_id}), odotetaan valmistumista...")

    status_url = lisaa_api_key(f"{BASE_TIEDOSTOPALVELU}/jobs/{job_id}", api_key)
    alku = time.monotonic()
    while True:
        if time.monotonic() - alku > max_odotus_s:
            raise RuntimeError(f"MML:n kiintopistelataus ei valmistunut {max_odotus_s} sekunnissa.")
        time.sleep(5)
        status_resp = requests.get(status_url, timeout=30)
        status_resp.raise_for_status()
        status_data = status_resp.json()
        status = status_data["status"]
        print(f"  tila: {status} ({status_data.get('progress', 0)}%)")
        if status == "successful":
            break
        if status in ("failed", "dismissed"):
            raise RuntimeError(f"Työ epäonnistui: {status_data}")

    results_url = lisaa_api_key(f"{BASE_TIEDOSTOPALVELU}/jobs/{job_id}/results/", api_key)
    results_resp = requests.get(results_url, timeout=30)
    results_resp.raise_for_status()
    results_data = results_resp.json()

    download_url = None
    for r in results_data.get("results", []):
        path = r.get("path", "")
        if path.endswith(".gpkg"):
            download_url = path
            break
    if not download_url:
        for r in results_data.get("results", []):
            if r.get("zipPath"):
                download_url = r["zipPath"]
                break
    if not download_url:
        raise RuntimeError(f"Ladattavaa tiedostoa ei löytynyt: {results_data}")

    file_resp = requests.get(lisaa_api_key(download_url, api_key), timeout=180)
    file_resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(file_resp.content)
    print(f"Ladattu (pysyvästi tallennettu): {out_path}")


@contextmanager
def kanta(db_conn):
    """Kursori, jonka muutokset vahvistetaan lopuksi; virheessä perutaan ja yhteys suljetaan."""
    conn = psycopg2.connect(**db_conn)
    try:
        with conn, conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def tyhjenna_taulu(db_conn, taulu):
    with kanta(db_conn) as cur:
        cur.execute(f"TRUNCATE TABLE {taulu};")


def aja_ogr2ogr(argumentit):
    """Ajaa ogr2ogr:n posix_spawnilla (täysi polku, close_fds=False). Tavallinen fork
    ajaisi lapsiprosessissa PROJ-kirjaston pthread_atfork-käsittelijän, joka sulkee
    PROJ:n SQLite-yhteydet; macOS:llä tämä kaataa lapsen (os_log forkin jälkeen
    monisäikeisessä prosessissa, esim. Streamlit-palvelimessa)."""
    ohjelma = shutil.which("ogr2ogr")
    if ohjelma is None:
        raise RuntimeError("ogr2ogr ei löydy (GDAL puuttuu, ks. packages.txt).")
    subprocess.run([ohjelma] + argumentit, check=True, close_fds=False)


def tuo_gpkg_postgis(gpkg_path, db_conn, lahdelayer="kiintopisteet"):
    """Tuo GPKG:n kiintopisteet kantaan. Samannimiset pisteet korvataan, muiden
    alueiden pisteet säilyvät. Palauttaa tuotujen pisteiden määrän."""
    pg_conn_str = (
        f"PG:dbname={db_conn['dbname']} user={db_conn['user']} "
        f"password={db_conn['password']} host={db_conn['host']} port={db_conn['port']}"
    )
    sql = (
        f"SELECT kiintopistetunnus AS pistetunnus, "
        f"EUREF_FIN_tarkkuusluokka AS luokka, "
        f"keskusmerkki AS tyyppi, "
        f"CAST(N2000_korkeus AS TEXT) AS korkeus, "
        f"geom FROM {lahdelayer}"
    )
    aja_ogr2ogr([
        "-f", "PostgreSQL", pg_conn_str, gpkg_path,
        "-nln", "kiintopisteet_tuonti", "-overwrite", "-lco", "GEOMETRY_NAME=geom",
        "-s_srs", f"EPSG:{FILESERVICE_SRID}", "-t_srs", f"EPSG:{DB_SRID}",
        "-dialect", "SQLite", "-sql", sql,
    ])
    with kanta(db_conn) as cur:
        cur.execute("DELETE FROM kiintopisteet k USING kiintopisteet_tuonti t "
                    "WHERE k.pistetunnus = t.pistetunnus::text;")
        cur.execute(
            f"INSERT INTO kiintopisteet (pistetunnus, luokka, tyyppi, korkeus, geom) "
            # Korkeus tulee välitauluun tekstinä ja muunnetaan vasta tässä: SQLiten CAST tekisi
            # arvoista "12,3" ja "-" hiljaa 12.0 ja 0.0. Tyhjä tai muu kuin luku -> NULL.
            f"SELECT pistetunnus::text, luokka::text, tyyppi::text, "
            f"CASE WHEN replace(trim(korkeus::text), ',', '.') ~ '^-?[0-9]+(\\.[0-9]+)?$' "
            f"THEN replace(trim(korkeus::text), ',', '.')::numeric END, "
            f"ST_SetSRID(ST_Force2D(geom), {DB_SRID}) "
            f"FROM kiintopisteet_tuonti;"
        )
        maara = cur.rowcount
        cur.execute("DROP TABLE kiintopisteet_tuonti;")
    print(f"{maara} kiintopistettä tuotu PostGIS-kantaan (EPSG:{DB_SRID}).")
    return maara


def kiintopiste_bbox_3067(e, n, sade_m, marginaali=0.1):
    """Hakualueen (keskipiste ± säde + marginaali) bbox EPSG:3067:ssä [x0, y0, x1, y1]."""
    r = sade_m * (1 + marginaali)
    muunnin = _muunnin(DB_SRID, FILESERVICE_SRID)
    kulmat = [muunnin.transform(e + de, n + dn) for de in (-r, r) for dn in (-r, r)]
    xs = [k[0] for k in kulmat]
    ys = [k[1] for k in kulmat]
    return [min(xs), min(ys), max(xs), max(ys)]


def paivita_kiintopisteet_alueelle(keskipiste, sade_m, api_key, db_conn):
    """Lataa hakualueen kiintopisteet MML:n tiedostopalvelusta kantaan.
    keskipiste = (e, n) EPSG:3879. Palauttaa tuotujen pisteiden määrän."""
    import tempfile

    bbox = kiintopiste_bbox_3067(keskipiste[0], keskipiste[1], sade_m)
    with tempfile.TemporaryDirectory() as hakemisto:
        gpkg = os.path.join(hakemisto, "kiintopisteet.gpkg")
        lataa_kiintopisteet_gpkg(bbox, api_key, gpkg)
        return tuo_gpkg_postgis(gpkg, db_conn)


def hae_kiinteiston_sijainti(kiinteistotunnus_raw, api_key):
    tunnus = normalisoi_kiinteistotunnus(kiinteistotunnus_raw)
    url = lisaa_api_key(f"{BASE_KIINTEISTO_API}/collections/PalstanSijaintitiedot/items", api_key)
    params = {"kiinteistotunnus": tunnus, "crs": f"http://www.opengis.net/def/crs/EPSG/0/{DB_SRID}"}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    if not features:
        raise ValueError(f"Kiinteistötunnukselle {kiinteistotunnus_raw} ei löytynyt sijaintia.")
    geom = features[0]["geometry"]
    centroid = shape(geom).centroid
    e, n = jarjesta_e_n(centroid.x, centroid.y)
    print(f"Kiinteistön keskipiste: E={e:.3f} N={n:.3f} (EPSG:{DB_SRID})")
    return [e, n]


def hae_kiinteiston_alue(kiinteistotunnus_raw, api_key):
    """Kiinteistön kaikkien palstojen yhdiste (shapely-geometria, EPSG:3879)."""
    from shapely.ops import transform as shapely_transform, unary_union

    tunnus = normalisoi_kiinteistotunnus(kiinteistotunnus_raw)
    url = lisaa_api_key(f"{BASE_KIINTEISTO_API}/collections/PalstanSijaintitiedot/items", api_key)
    params = {"kiinteistotunnus": tunnus, "crs": f"http://www.opengis.net/def/crs/EPSG/0/{DB_SRID}"}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    palstat = [shape(f["geometry"]) for f in resp.json().get("features", []) if f.get("geometry")]
    if not palstat:
        raise ValueError(f"Kiinteistötunnukselle {kiinteistotunnus_raw} ei löytynyt aluetta.")
    alue = unary_union(palstat)
    # Rajapinta voi palauttaa akselit järjestyksessä (N, E); E on GK25:ssä aina suurempi.
    x, y = alue.representative_point().coords[0]
    if x < y:
        alue = shapely_transform(lambda a, b: (b, a), alue)
    return alue


# Helsingin karttapalvelun (kartta.hel.fi: WMS ja WFS) tauko: jos haku aikakatkaistaan tai yhteys ei
# onnistu, seuraavat haut epäonnistuvat heti WMS_TAUKO_S ajan. Streamlit Cloudin palvelin on ulkomailla, ja
# yhteys kartta.hel.fi:hin voi takkuilla: ilman taukoa jokainen asemapistekartta ja jokainen sivun
# uudelleenajo (kantakartan rakennukset seinälinjalle) odottaisi aikarajan verran.
WMS_TAUKO_S = 300
_wms_tauko_asti = [0.0]


def _helsinki_get(url, params, timeout):
    if time.time() < _wms_tauko_asti[0]:
        raise RuntimeError("Helsingin karttapalvelu (kartta.hel.fi) ei vastannut äsken, ohitetaan hetkeksi")
    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except (requests.Timeout, requests.ConnectionError):
        _wms_tauko_asti[0] = time.time() + WMS_TAUKO_S
        raise
    resp.raise_for_status()
    return resp


def hae_helsinki_rakennukset(bbox_3879):
    """Helsingin kantakartan voimassa olevat rakennukset (WFS) alueelta (x0, y0, x1, y1),
    EPSG:3879. Palauttaa [{"tyyppi", "osoite", "polygoni"}]."""
    x0, y0, x1, y1 = bbox_3879
    params = {
        "service": "WFS", "version": "2.0.0", "request": "GetFeature",
        "typeNames": HELSINKI_RAKENNUKSET_LAYER, "outputFormat": "application/json",
        "srsName": f"EPSG:{DB_SRID}",
        "bbox": f"{x0},{y0},{x1},{y1},EPSG:{DB_SRID}",
    }
    resp = _helsinki_get(HELSINKI_WFS_URL, params, 20)

    rakennukset = []
    for f in resp.json().get("features", []):
        props = f.get("properties") or {}
        if f.get("geometry") is None or props.get("tila") not in (None, "voimassa"):
            continue
        poly = shape(f["geometry"])
        if poly.area <= 0:
            continue
        osoite = " ".join(str(props[k]) for k in ("katunimi_suomi", "osoitenumero") if props.get(k))
        rakennukset.append({"tyyppi": props.get("tyyppi"), "osoite": osoite or None, "polygoni": poly})
    return rakennukset


def hae_kiinteiston_rakennukset(alue, min_osuus=0.5):
    """Helsingin kantakartan rakennukset (WFS), joiden pinta-alasta vähintään min_osuus
    on kiinteistön alueella. Palauttaa [{"nro", "tyyppi", "osoite", "polygoni"}],
    nro 1..n pinta-alan mukaan suurimmasta alkaen."""
    x0, y0, x1, y1 = alue.bounds
    rakennukset = [r for r in hae_helsinki_rakennukset((x0 - 2, y0 - 2, x1 + 2, y1 + 2))
                   if r["polygoni"].intersection(alue).area / r["polygoni"].area >= min_osuus]
    rakennukset.sort(key=lambda r: -r["polygoni"].area)
    for i, r in enumerate(rakennukset, start=1):
        r["nro"] = i
    print(f"Löytyi {len(rakennukset)} rakennusta kiinteistöltä.")
    return rakennukset


def rakennusten_renkaat(rakennukset):
    """Rakennusten reunat seinälinjan kantakartaksi (seinalinja.py): rakennuksittain
    [ulkorengas, sisärenkaat...], rengas = [(e, n), ...]. MultiPolygonin osat ovat omia
    rakennuksiaan."""
    tulos = []
    for r in rakennukset:
        poly = r["polygoni"]
        for osa in (poly.geoms if poly.geom_type == "MultiPolygon" else [poly]):
            tulos.append([[(c[0], c[1]) for c in rengas.coords] for rengas in [osa.exterior] + list(osa.interiors)])
    return tulos


def _renkaan_nurkat(koordinaatit, suoraraja_m):
    """Renkaan kärjet ilman sulkevaa toistopistettä ja suoralla olevia välipisteitä."""
    pts = [(c[0], c[1]) for c in koordinaatit]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    nurkat = []
    for i, p in enumerate(pts):
        a, b = pts[i - 1], pts[(i + 1) % len(pts)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        pituus = math.hypot(dx, dy)
        etaisyys = abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / pituus if pituus else math.inf
        if etaisyys >= suoraraja_m:
            nurkat.append(p)
    return nurkat


def rakennusten_nurkat(rakennukset, suoraraja_m=0.01):
    """Rakennusten nurkkapisteet [(numero, e, n, rakennus_nro)], numero juoksevasti
    "1", "2", ... kaikkien rakennusten yli (rakennus 1 ensin). Mukana myös
    sisäpihojen nurkat. Kärki, joka on alle suoraraja_m päässä naapurikärkien välisestä
    suorasta, ei ole nurkka (aineistossa on suorilla seinillä välipisteitä)."""
    tulos = []
    for r in rakennukset:
        poly = r["polygoni"]
        osat = list(poly.geoms) if poly.geom_type == "MultiPolygon" else [poly]
        for osa in osat:
            for rengas in [osa.exterior] + list(osa.interiors):
                for e, n in _renkaan_nurkat(rengas.coords, suoraraja_m):
                    tulos.append((str(len(tulos) + 1), e, n, r["nro"]))
    return tulos


def tallenna_kiinteiston_sijainti(kiinteistotunnus, coords, db_conn):
    x, y = coords[0], coords[1]
    with kanta(db_conn) as cur:
        cur.execute("TRUNCATE TABLE kiinteistot;")
        cur.execute(
            f"INSERT INTO kiinteistot (kiinteistotunnus, geom) "
            f"VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), {DB_SRID}));",
            (kiinteistotunnus, x, y),
        )
    print(f"Kiinteistön {kiinteistotunnus} sijainti tallennettu (vanhat kiinteistöt poistettu).")


def hae_kiinteiston_rajamerkit(kiinteistotunnus_raw, api_key):
    tunnus = normalisoi_kiinteistotunnus(kiinteistotunnus_raw)
    url = lisaa_api_key(f"{BASE_KIINTEISTO_API}/collections/RajamerkinSijaintitiedot/items", api_key)
    params = {"kiinteistotunnus": tunnus, "crs": f"http://www.opengis.net/def/crs/EPSG/0/{DB_SRID}"}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    if not features:
        print(f"Kiinteistölle {kiinteistotunnus_raw} ei löytynyt rajamerkkejä (0 kpl).")
        return []

    tulokset = []
    for i, f in enumerate(features, start=1):
        props = f.get("properties", {}) or {}
        tunniste = None
        for kentta in RAJAMERKKI_TUNNUS_KENTAT:
            if props.get(kentta) not in (None, ""):
                tunniste = str(props[kentta])
                break
        if not tunniste:
            tunniste = f"rm{i}"
        geom = f.get("geometry")
        if geom is None:
            continue
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            continue
        e, n = jarjesta_e_n(coords[0], coords[1])
        tulokset.append((tunniste, e, n))

    print(f"Löytyi {len(tulokset)} rajamerkkiä kiinteistölle {kiinteistotunnus_raw}.")
    return tulokset


def hae_kiinteiston_rajaviivat(kiinteistotunnus_raw, api_key):
    tunnus = normalisoi_kiinteistotunnus(kiinteistotunnus_raw)
    url = lisaa_api_key(f"{BASE_KIINTEISTO_API}/collections/KiinteistorajanSijaintitiedot/items", api_key)
    params = {"kiinteistotunnus": tunnus, "crs": f"http://www.opengis.net/def/crs/EPSG/0/{DB_SRID}"}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])
    if not features:
        print(f"Kiinteistölle {kiinteistotunnus_raw} ei löytynyt rajaviivoja (0 kpl).")
        return []

    viivat = []
    for f in features:
        geom = f.get("geometry")
        if geom is None:
            continue
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not coords:
            continue
        if gtype == "LineString":
            viivat.append([jarjesta_e_n(pt[0], pt[1]) for pt in coords])
        elif gtype == "MultiLineString":
            for line in coords:
                viivat.append([jarjesta_e_n(pt[0], pt[1]) for pt in line])

    print(f"Löytyi {len(viivat)} rajaviivaa kiinteistölle {kiinteistotunnus_raw}.")
    return viivat


def tallenna_rajamerkit_kantaan(kiinteistotunnus, rajamerkit, db_conn):
    with kanta(db_conn) as cur:
        cur.execute("TRUNCATE TABLE rajamerkit;")
        for numero, e, n in rajamerkit:
            cur.execute(
                f"INSERT INTO rajamerkit (kiinteistotunnus, numero, geom) "
                f"VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), {DB_SRID}));",
                (kiinteistotunnus, numero, e, n),
            )
    if rajamerkit:
        print(f"{len(rajamerkit)} rajamerkkiä tallennettu kantaan (rajamerkit-taulu).")


def tallenna_rajaviivat_kantaan(kiinteistotunnus, rajaviivat, db_conn):
    with kanta(db_conn) as cur:
        cur.execute("TRUNCATE TABLE kiinteistorajat;")
        for viiva in rajaviivat:
            if len(viiva) < 2:
                continue
            wkt = "LINESTRING(" + ", ".join(f"{e} {n}" for e, n in viiva) + ")"
            cur.execute(
                "INSERT INTO kiinteistorajat (kiinteistotunnus, pituus_m, geom) "
                "VALUES (%s, %s, ST_GeomFromText(%s, %s));",
                (kiinteistotunnus, round(viivan_pituus(viiva), 3), wkt, DB_SRID),
            )
    if rajaviivat:
        print(f"{len(rajaviivat)} rajaviivaa tallennettu kantaan (kiinteistorajat-taulu).")


def hae_kiintopisteet_saateella(kiinteistotunnus, sade_m, db_conn, luokka=None):
    with kanta(db_conn) as cur:
        cur.execute("SELECT * FROM kiintopisteet_saateella(%s, %s, %s);", (kiinteistotunnus, sade_m, luokka))
        return cur.fetchall()


def hae_kiinteiston_kiintopisteet(kiinteistotunnus, sade_m, db_conn, luokka=None):
    """Kiinteistön kiintopisteet säteeltä. Helsingissä käytetään vain tuotuja kaupungin
    kiintopisteitä (OMA_KIINTOPISTE_LUOKKA), ei MML:n pisteitä; muualla annettua luokkaa."""
    if on_helsinki(kiinteistotunnus):
        luokka = OMA_KIINTOPISTE_LUOKKA
    return hae_kiintopisteet_saateella(kiinteistotunnus, sade_m, db_conn, luokka)


def suodata_paamerkit(tulokset, sisallyta_varamerkit):
    """Varamerkkisääntö koskee MML:n tunnuksia; omat kiintopisteet ovat aina mukana."""
    if sisallyta_varamerkit:
        return tulokset
    return [r for r in tulokset if r[5] == OMA_KIINTOPISTE_LUOKKA or on_paamerkki(r[0])]


def _luku(teksti):
    try:
        return float(teksti.replace(",", "."))
    except ValueError:
        return None


def jasenna_kiintopiste_txt(teksti):
    """Kiintopisteet tekstitiedostosta (ETRS-GK25). E (25-26 milj.) ja N (6,6-7,8 milj.)
    tunnistetaan suuruusluokasta, joten sarakejärjestys ei haittaa. Tunnus on ensimmäinen
    kenttä (nimi N E Z, nimi koodi N E Z), paitsi jos ennen koordinaatteja on vähintään
    kolme kenttää: silloin tunnus on koordinaatteja edeltävä kenttä ja koodi sitä edeltävä
    (krd: 1 0 koodi numero E N Z). Korkeus on koordinaattien jälkeinen ensimmäinen luku,
    jonka itseisarvo on alle 1000. Erottimena puolipiste, sarkain tai välilyönti, tai pilkku,
    jos desimaalierottimena on piste. Muuten pilkku on desimaalipilkku.
    Palauttaa (pisteet, ohitetut): [{"tunnus", "koodi", "n", "e", "korkeus"}], [(rivinumero, rivi)]."""
    pisteet, ohitetut = [], []
    for nro, rivi in enumerate(teksti.splitlines(), start=1):
        if not rivi.strip():
            continue
        if ";" in rivi:
            kentat = rivi.split(";")
        elif "\t" in rivi:
            kentat = rivi.split("\t")
        elif rivi.count(",") >= 2 and "." in rivi:
            kentat = rivi.split(",")
        else:
            kentat = rivi.split()
        kentat = [k.strip() for k in kentat if k.strip()]

        e = n = korkeus = ensimmainen = None
        if len(kentat) >= 3:
            for i, k in enumerate(kentat[1:], start=1):
                arvo = _luku(k)
                if arvo is None:
                    continue
                if e is None and 25_000_000 <= arvo <= 26_000_000:
                    e = arvo
                elif n is None and 6_600_000 <= arvo <= 7_800_000:
                    n = arvo
                elif e is not None and n is not None and abs(arvo) < 1000:
                    korkeus = arvo
                    break
                else:
                    continue
                if ensimmainen is None:
                    ensimmainen = i
        if e is None or n is None:
            ohitetut.append((nro, rivi.strip()))
            continue
        if ensimmainen >= 3:
            tunnus, koodi = kentat[ensimmainen - 1], kentat[ensimmainen - 2]
        else:
            tunnus, koodi = kentat[0], kentat[1] if ensimmainen == 2 else None
        pisteet.append({"tunnus": tunnus, "koodi": koodi, "n": n, "e": e, "korkeus": korkeus})
    return pisteet, ohitetut


def tallenna_omat_kiintopisteet(pisteet, db_conn):
    """Tallentaa omat kiintopisteet kiintopisteet-tauluun (luokka OMA_KIINTOPISTE_LUOKKA).
    Sama tunnus voi esiintyä useassa paikassa, joten piste korvataan vain, jos samalla
    tunnuksella on oma piste jo samassa sijainnissa (alle 1 cm päässä). MML:n pisteisiin
    ei kosketa. Palauttaa tallennettujen määrän."""
    with kanta(db_conn) as cur:
        for p in pisteet:
            cur.execute(
                f"DELETE FROM kiintopisteet WHERE luokka = %s AND pistetunnus = %s "
                f"AND ST_DWithin(geom, ST_SetSRID(ST_MakePoint(%s, %s), {DB_SRID}), 0.01);",
                (OMA_KIINTOPISTE_LUOKKA, p["tunnus"], p["e"], p["n"]),
            )
            cur.execute(
                f"INSERT INTO kiintopisteet (pistetunnus, luokka, korkeus, geom) "
                f"VALUES (%s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), {DB_SRID}));",
                (p["tunnus"], OMA_KIINTOPISTE_LUOKKA, p["korkeus"], p["e"], p["n"]),
            )
    return len(pisteet)


def lahin_oma_kiintopiste(kiinteistotunnus, db_conn):
    """Omien kiintopisteiden määrä kannassa ja lähimmän etäisyys (m) kiinteistöstä
    (None, jos omia pisteitä ei ole) -- vianetsintään, kun säteeltä ei löydy mitään."""
    with kanta(db_conn) as cur:
        cur.execute(
            "SELECT COUNT(*), MIN(ST_Distance(k.geom, kt.geom)) FROM kiintopisteet k, kiinteistot kt "
            "WHERE k.luokka = %s AND kt.kiinteistotunnus = %s;",
            (OMA_KIINTOPISTE_LUOKKA, kiinteistotunnus),
        )
        maara, etaisyys = cur.fetchone()
    return maara, etaisyys


def poista_omat_kiintopisteet(db_conn):
    """Poistaa tekstitiedostosta tuodut kiintopisteet (MML:n pisteet jäävät)."""
    with kanta(db_conn) as cur:
        cur.execute("DELETE FROM kiintopisteet WHERE luokka = %s;", (OMA_KIINTOPISTE_LUOKKA,))
        return cur.rowcount


def tallenna_haku_tulokset(kiinteistotunnus, tulokset, db_conn):
    with kanta(db_conn) as cur:
        cur.execute("TRUNCATE TABLE haku_tulokset;")
        for pistetunnus, koodi, n, e, korkeus, luokka, etaisyys in tulokset:
            cur.execute(
                f"""INSERT INTO haku_tulokset
                    (kiinteistotunnus, pistetunnus, koodi, korkeus, luokka, etaisyys_m, geom)
                    VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), {DB_SRID}));""",
                (kiinteistotunnus, pistetunnus, koodi, korkeus, luokka, etaisyys, e, n),
            )
    if tulokset:
        print(f"{len(tulokset)} hakutulosta tallennettu kantaan (haku_tulokset-taulu) -- lisää TÄMÄ taso QGIS:ään.")


KRD_MERKISTO = "cp1252"


def krd_koodi(koodi):
    """Koodikentän ensimmäinen osa krd:hen ("9 1" -> "9"; toinen osa on esim. viivan numero,
    jota krd ei ymmärrä). Puuttuva koodi -> "0"."""
    osat = str(koodi).split() if koodi is not None else []
    return osat[0] if osat else "0"


def _krd_kentta(arvo, leveys):
    """Oikealle tasattu kenttä; liian pitkän arvon eteen yksi välilyönti, jotta kentät erottuvat."""
    return arvo.rjust(leveys) if len(arvo) < leveys else " " + arvo


def krd_rivi(numero, koodi, e, n, z, desimaalit=3):
    """Yksi krd-rivi: 1 0 koodi numero E N Z, kentät 8+8+8+8+14+14+14 merkkiä oikealle
    tasattuina, CRLF. Puuttuva korkeus -> 0.000, nimen välilyönnit -> _."""
    nimi = "_".join(str(numero).split()) or "0"
    return (f"{1:>8}{0:>8}{_krd_kentta(krd_koodi(koodi), 8)}{_krd_kentta(nimi, 8)}"
            f"{_krd_kentta(f'{e:.{desimaalit}f}', 14)}{_krd_kentta(f'{n:.{desimaalit}f}', 14)}"
            f"{_krd_kentta(f'{z if z is not None else 0.0:.3f}', 14)}\r\n")


def kirjoita_yhdistetty_krd(kiintopisteet, rajamerkit, out_path, kohde_epsg=None, nurkat=None, desimaalit=3):
    """Kiintopisteet, rajamerkit ja rakennusten nurkat krd-tiedostoon (ks. krd_rivi)."""
    rivit = []
    for pistetunnus, koodi, n, e, korkeus, luokka, etaisyys in kiintopisteet:
        n_out, e_out = muunna_piste(e, n, kohde_epsg) if kohde_epsg else (n, e)
        rivit.append(krd_rivi(kiintopisteen_nimi(pistetunnus, luokka), koodi, e_out, n_out, korkeus, desimaalit))
    for tunniste, e, n in rajamerkit:
        n_out, e_out = muunna_piste(e, n, kohde_epsg) if kohde_epsg else (n, e)
        rivit.append(krd_rivi(tunniste, RAJAMERKKI_KOODI, e_out, n_out, None, desimaalit))
    for tunniste, e, n, *_ in nurkat or []:
        n_out, e_out = muunna_piste(e, n, kohde_epsg) if kohde_epsg else (n, e)
        rivit.append(krd_rivi(tunniste, RAKENNUKSEN_KULMA_KOODI, e_out, n_out, None, desimaalit))
    with open(out_path, "wb") as f:
        f.write("".join(rivit).encode(KRD_MERKISTO, errors="replace"))
    print(f"Tulostiedosto kirjoitettu: {out_path} ({len(kiintopisteet)} kiintopistettä + {len(rajamerkit)} rajamerkkiä"
          f" + {len(nurkat or [])} rakennuksen nurkkaa)")


@lru_cache(maxsize=None)
def _muunnin(lahde_epsg, kohde_epsg):
    from pyproj import Transformer
    return Transformer.from_crs(f"EPSG:{lahde_epsg}", f"EPSG:{kohde_epsg}", always_xy=True)


def muunna_piste(e, n, kohde_epsg):
    if kohde_epsg == DB_SRID:
        return n, e
    x_out, y_out = _muunnin(DB_SRID, kohde_epsg).transform(e, n)
    if kohde_epsg == 4326:
        return x_out, y_out
    return y_out, x_out


def _hae_pinta_ala_kiinteistotunnuksella(tunnus, api_key):
    try:
        url = lisaa_api_key(f"{BASE_KIINTEISTO_API}/collections/PalstanSijaintitiedot/items", api_key)
        params = {"kiinteistotunnus": normalisoi_kiinteistotunnus(tunnus)}
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if not features:
            return None
        props = features[0].get("properties", {}) or {}
        for kentta in ("pinta_ala", "pintaala", "rekisteriala", "ala"):
            if props.get(kentta) not in (None, ""):
                return float(props[kentta])
        return None
    except Exception:
        return None


def hae_kiinteistotunnus_osoitteella(osoite, kaupunki, api_key):
    """Geokoodaa osoitteen MML:n GEOKOODAUSPALVELUN kautta (Pelias-pohjainen
    /geocoding/v2/pelias/search, sources=addresses).
    Palauttaa (valittu_tunnus, ehdokkaat, tasmasiko_kunta)."""
    text = f"{osoite.strip()} {kaupunki.strip()}".strip() if kaupunki else osoite.strip()

    url = f"{BASE_GEOCODING}/v2/pelias/search"
    params = {
        "text": text,
        "sources": "addresses",
        "crs": "EPSG:3067",
        "lang": "fi",
        "api-key": api_key,
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])

    if not features:
        raise ValueError(
            f"Osoitteelle '{osoite}'" + (f", {kaupunki}" if kaupunki else "") +
            " ei löytynyt rakennuksen osoitetta MML:n geokoodauspalvelusta."
        )

    ehdokkaat = []
    nahdyt_tunnukset = set()
    for f in features:
        props = f.get("properties", {}) or {}
        tunnus = props.get("kiinteistotunnus")
        if not tunnus or tunnus in nahdyt_tunnukset:
            continue
        nahdyt_tunnukset.add(tunnus)

        kunta_label = (
            props.get("label:municipality") or props.get("municipality")
            or props.get("localadmin") or props.get("locality") or ""
        )
        tasmasiko_kunta = (kaupunki.lower() in str(kunta_label).lower()) if kaupunki else True

        pinta_ala = _hae_pinta_ala_kiinteistotunnuksella(tunnus, api_key)

        ehdokkaat.append({
            "lahde": "Geokoodauspalvelu (RYHTI-rakennusosoitteet)",
            "tunnus": tunnus,
            "pinta_ala": pinta_ala,
            "tasmasiko_kunta": tasmasiko_kunta,
        })

    if not ehdokkaat:
        raise ValueError(
            f"Osoitteelle '{osoite}' löytyi rakennus geokoodauspalvelusta, mutta vastauksessa "
            "ei ollut kiinteistotunnus-kenttää."
        )

    ehdokkaat_sopivat = [e for e in ehdokkaat if not kaupunki or e["tasmasiko_kunta"]]
    kohde_lista = ehdokkaat_sopivat if ehdokkaat_sopivat else ehdokkaat
    valittu = min(kohde_lista, key=lambda e: e["pinta_ala"] if e["pinta_ala"] is not None else float("inf"))

    return valittu["tunnus"], ehdokkaat, valittu["tasmasiko_kunta"]


def _ensimmainen_koordinaatti(coords):
    """Palauttaa geometrian ensimmäisen (x, y) -koordinaattiparin riippumatta
    siitä onko geometria Polygon, MultiPolygon jne (kuinka syvästi sisäkkäin
    tahansa listoja)."""
    c = coords
    while isinstance(c, list) and c and isinstance(c[0], list):
        c = c[0]
    return c


def _normalisoi_polygoni_epsg3879(geom_dict):
    """Muuntaa GeoJSON-geometrian EPSG:3879:ään TARKISTAMALLA itse ensimmäisen
    koordinaattiparin suuruusluokan -- EI luoteta palvelimen ilmoittamaan
    koordinaatistoon. EPSG:3879:n arvot ovat aina miljoonia (esim. N~6.68
    miljoonaa, E~25.5 miljoonaa); WGS84-asteet Suomessa ovat aina alle 100.
    Jos molemmat ensimmäisen pisteen arvot ovat itseisarvoltaan alle 1000,
    geometria tulkitaan WGS84:ksi (lon, lat -- GeoJSON-järjestys) ja
    muunnetaan EPSG:3879:ään pyprojilla. Muussa tapauksessa oletetaan
    geometrian olevan jo EPSG:3879:ssä sellaisenaan."""
    from shapely.ops import transform as shapely_transform
    from pyproj import Transformer

    coords = geom_dict.get("coordinates")
    piste = _ensimmainen_koordinaatti(coords)
    poly = shape(geom_dict)
    if not piste or len(piste) < 2:
        return poly
    x, y = piste[0], piste[1]
    if abs(x) < 1000 and abs(y) < 1000:
        transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{DB_SRID}", always_xy=True)
        return shapely_transform(transformer.transform, poly)
    return poly


def tunnista_kiinteisto_pisteparvesta(pisteet, api_key, marginaali_m=5):
    """Ehdottaa kiinteistötunnusta JobXML-tiedoston mitattujen pisteiden
    perusteella. Käyttää VAIN kartoitus-/merkintä-/suunnittelupisteitä
    (KIINTEISTO_TUNNISTUS_KATEGORIAT).

    Palauttaa (ehdotettu_tunnus, osumat_per_tunnus_dict, pisteita_mukana_yhteensa).
    ehdotettu_tunnus on None jos sopivia pisteitä ei ollut tai osumia ei löytynyt."""
    from shapely.geometry import Point
    from pyproj import Transformer

    pisteet_mukana = [
        p for p in pisteet
        if p.get("kategoria") in KIINTEISTO_TUNNISTUS_KATEGORIAT
        and p.get("n") is not None and p.get("e") is not None
    ]
    if not pisteet_mukana:
        return None, {}, 0

    xs = [p["e"] for p in pisteet_mukana]
    ys = [p["n"] for p in pisteet_mukana]
    min_e, max_e = min(xs) - marginaali_m, max(xs) + marginaali_m
    min_n, max_n = min(ys) - marginaali_m, max(ys) + marginaali_m

    to_wgs84 = Transformer.from_crs(f"EPSG:{DB_SRID}", "EPSG:4326", always_xy=True)
    lon1, lat1 = to_wgs84.transform(min_e, min_n)
    lon2, lat2 = to_wgs84.transform(max_e, max_n)
    min_lon, max_lon = sorted([lon1, lon2])
    min_lat, max_lat = sorted([lat1, lat2])

    url = lisaa_api_key(f"{BASE_KIINTEISTO_API}/collections/PalstanSijaintitiedot/items", api_key)
    params = {
        "bbox": f"{min_lon},{min_lat},{max_lon},{max_lat}",
        "limit": 200,
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", [])

    polygonit = {}
    for f in features:
        props = f.get("properties", {}) or {}
        tunnus = props.get("kiinteistotunnus")
        geom = f.get("geometry")
        if not tunnus or not geom:
            continue
        try:
            # KORJAUS: normalisoidaan EPSG:3879:ään ITSE koordinaattien
            # suuruusluokan perusteella -- ei luoteta palvelimen crs-vastaukseen.
            polygonit[tunnus] = _normalisoi_polygoni_epsg3879(geom)
        except Exception:
            continue

    if not polygonit:
        return None, {}, len(pisteet_mukana)

    osumat = Counter()
    for p in pisteet_mukana:
        piste_geom = Point(p["e"], p["n"])
        for tunnus, poly in polygonit.items():
            if poly.contains(piste_geom):
                osumat[tunnus] += 1
                break

    if not osumat:
        return None, {}, len(pisteet_mukana)

    ehdotettu_tunnus, _ = osumat.most_common(1)[0]
    return ehdotettu_tunnus, dict(osumat), len(pisteet_mukana)


@lru_cache(maxsize=64)
def _hae_wms_kuva(bbox_3879, leveys_px, korkeus_px, layer, timeout):
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "SRS": f"EPSG:{DB_SRID}",
        "BBOX": f"{bbox_3879[0]},{bbox_3879[1]},{bbox_3879[2]},{bbox_3879[3]}",
        "WIDTH": leveys_px,
        "HEIGHT": korkeus_px,
        "FORMAT": "image/png",
    }
    resp = _helsinki_get(HELSINKI_WMS_URL, params, timeout)
    if "image" not in resp.headers.get("Content-Type", ""):
        raise RuntimeError(f"Helsingin WMS ei palauttanut kuvaa: {resp.text[:300]}")
    return resp.content


def hae_helsinki_kantakartta(bbox_3879, leveys_px=1200, korkeus_px=1200, layer=HELSINKI_KANTAKARTTA_LAYER,
                             timeout=60):
    """Helsingin kantakartta kuvana alueelta (WMS). Onnistuneet haut muistetaan (sama alue ei hae
    uudelleen). Jos palvelu ei vastannut äsken (WMS_TAUKO_S), virhe tulee heti."""
    from PIL import Image

    sisalto = _hae_wms_kuva(tuple(round(float(v), 3) for v in bbox_3879), leveys_px, korkeus_px, layer, timeout)
    return Image.open(io.BytesIO(sisalto))


def piirra_asemapisteen_pienikartta(asema_n, asema_e, liitospisteet, korkeusliitokset,
                                     out_path, margin_m=15, tiedot=None):
    """Asemapisteen pieni kartta PNG:ksi. tiedot (dict, valinnainen) saa avaimen "tausta": saatiinko
    kantakartta taustalle."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon

    kaikki_pisteet = [(asema_e, asema_n)]
    for p in list(liitospisteet) + list(korkeusliitokset):
        if p.get("n") is not None and p.get("e") is not None:
            kaikki_pisteet.append((p["e"], p["n"]))

    xs = [p[0] for p in kaikki_pisteet]
    ys = [p[1] for p in kaikki_pisteet]
    keski_x = (min(xs) + max(xs)) / 2
    keski_y = (min(ys) + max(ys)) / 2
    puolisivu = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + margin_m
    puolisivu = max(puolisivu, margin_m)

    bbox = [keski_x - puolisivu, keski_y - puolisivu, keski_x + puolisivu, keski_y + puolisivu]

    fig, ax = plt.subplots(figsize=(3.6, 3.6))

    try:
        kuva = hae_helsinki_kantakartta(bbox, leveys_px=500, korkeus_px=500,
                                         layer=HELSINKI_KANTAKARTTA_HARMAA_LAYER, timeout=10)
        ax.imshow(kuva, extent=(bbox[0], bbox[2], bbox[1], bbox[3]), zorder=0)
        if tiedot is not None:
            tiedot["tausta"] = True
    except Exception as e:
        ax.set_facecolor("#e8e8e8")
        if tiedot is not None:
            tiedot["tausta"] = False
        print(f"Huom: Helsingin harmaakartan haku epäonnistui pienoiskartalle ({e}) -- jatketaan ilman taustaa.")

    horis_koords = [(p["e"], p["n"]) for p in liitospisteet if p.get("n") is not None and p.get("e") is not None]
    if len(horis_koords) >= 3:
        from jobxml_tuonti import _konveksi_kuori
        monikulmio = _konveksi_kuori(horis_koords)
        if len(monikulmio) >= 3:
            ax.add_patch(Polygon(monikulmio, closed=True, fill=False,
                                  edgecolor="dodgerblue", linewidth=1.2, linestyle="--", zorder=2))

    for p in liitospisteet:
        if p.get("n") is not None and p.get("e") is not None:
            ax.scatter([p["e"]], [p["n"]], marker="o", s=55, c="blue", zorder=4,
                       edgecolors="white", linewidths=0.5)
            ax.annotate(str(p["nimi"]), (p["e"], p["n"]), textcoords="offset points",
                       xytext=(4, 4), fontsize=7, color="blue", fontweight="bold")

    for p in korkeusliitokset:
        if p.get("n") is not None and p.get("e") is not None:
            ax.scatter([p["e"]], [p["n"]], marker="s", s=45, c="gray", zorder=4,
                       edgecolors="white", linewidths=0.5)
            ax.annotate(str(p["nimi"]), (p["e"], p["n"]), textcoords="offset points",
                       xytext=(4, -9), fontsize=7, color="dimgray")

    ax.scatter([asema_e], [asema_n], marker="*", s=260, c="darkorange", zorder=6,
               edgecolors="black", linewidths=0.6)
    ax.annotate("Asema", (asema_e, asema_n), textcoords="offset points",
               xytext=(6, 6), fontsize=8, fontweight="bold", color="black")

    ax.set_xlim(bbox[0], bbox[2])
    ax.set_ylim(bbox[1], bbox[3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    plt.tight_layout(pad=0.15)
    plt.savefig(out_path, dpi=140)
    plt.close()
    return out_path


# JobXML-pisteiden kategoriat kartoilla: (väri, matplotlib-merkki, koko)
JOBXML_KATEGORIAVARIT = {
    "Asemapiste": ("#FFD700", "*", 260),
    "Liitospiste": ("blue", "o", 55),
    "Korkeusliitos": ("gray", "^", 45),
    "Kartoituspiste": ("green", "o", 30),
    "Merkintäpiste": ("purple", "^", 40),
    "Suunnittelupiste (Construction)": ("brown", "D", 35),
    "Liitospiste (alkuperäinen RTK-mittaus)": ("lightblue", "o", 22),
}


def _symboli_svg(merkki, vari, koko_px, reuna="white", kartalle=False):
    """Inline-SVG matplotlib-merkkikoodin mukaan (o, *, ^, s, D) -- käytetään
    zoomattavan kartan merkeissä (kartalle=True) ja tasovalitsimen selitteissä.
    Kartalla SVG on block-elementti: inline-SVG asettuisi tekstiriville ja
    valuisi rivikorkeuden verran merkin laatikon keskeltä alaspäin."""
    k = koko_px
    if merkki == "*":
        r_ulko, r_sisa = k / 2 - 1, (k / 2 - 1) * 0.42
        kulmat = []
        for i in range(10):
            r = r_ulko if i % 2 == 0 else r_sisa
            a = math.radians(-90 + i * 36)
            kulmat.append(f"{k / 2 + r * math.cos(a):.1f},{k / 2 + r * math.sin(a) + k * 0.04:.1f}")
        muoto = f'<polygon points="{" ".join(kulmat)}"/>'
    elif merkki == "^":
        muoto = f'<polygon points="{k / 2},1 {k - 1},{k - 1} 1,{k - 1}"/>'
    elif merkki == "s":
        muoto = f'<rect x="1.5" y="1.5" width="{k - 3}" height="{k - 3}"/>'
    elif merkki == "D":
        muoto = f'<polygon points="{k / 2},1 {k - 1},{k / 2} {k / 2},{k - 1} 1,{k / 2}"/>'
    elif merkki == "x":
        muoto = f'<path d="M2,2 L{k - 2},{k - 2} M{k - 2},2 L2,{k - 2}" stroke="{vari}" stroke-width="2.5"/>'
    else:
        muoto = f'<circle cx="{k / 2}" cy="{k / 2}" r="{k / 2 - 1.5}"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{k}" height="{k}" '
            f'viewBox="0 0 {k} {k}" style="{"display:block" if kartalle else "vertical-align:middle"}">'
            f'<g fill="{vari}" stroke="{reuna}" stroke-width="1">{muoto}</g></svg>')


def _karttamerkki(sijainti, merkki, vari, koko, reuna="white", **kwargs):
    """folium.Marker, jonka symbolin keskipiste on täsmälleen pisteen kohdalla."""
    import folium

    svg = _symboli_svg(merkki, vari, koko, reuna, kartalle=True)
    return folium.Marker(
        sijainti,
        icon=folium.DivIcon(html=f'<div style="line-height:0">{svg}</div>', icon_size=(koko, koko),
                            icon_anchor=(koko / 2, koko / 2), class_name="kartta-merkki"),
        **kwargs,
    )


def _viiva_svg(vari, koko_px=14):
    """Inline-SVG viivasymboli tasovalitsimen selitteeseen."""
    k = koko_px
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{k}" height="{k}" '
            f'style="vertical-align:middle"><line x1="1" y1="{k / 2}" x2="{k - 1}" y2="{k / 2}" '
            f'stroke="{vari}" stroke-width="3"/></svg>')


MML_WMTS_TASOT = (("taustakartta", "MML taustakartta"), ("maastokartta", "MML maastokartta"),
                  ("ortokuva", "MML ortokuva (ilmakuva)"))


def on_helsingin_alueella(e, n):
    """Onko EPSG:3879-piste Helsingin kantakartan alueella (HELSINKI_BBOX_3067)."""
    from pyproj import Transformer
    x, y = Transformer.from_crs(f"EPSG:{DB_SRID}", "EPSG:3067", always_xy=True).transform(e, n)
    x0, y0, x1, y1 = HELSINKI_BBOX_3067
    return x0 <= x <= x1 and y0 <= y <= y1


def _latlon_muunnin():
    from pyproj import Transformer
    muunnin = Transformer.from_crs(f"EPSG:{DB_SRID}", "EPSG:4326", always_xy=True)

    def latlon(e, n):
        lon, lat = muunnin.transform(e, n)
        return lat, lon
    return latlon


def _lisaa_taustakartat(kartta, api_key, helsinki):
    """Taustakarttavaihtoehdot zoomattaville kartoille: Helsingin kantakartta (WMS),
    MML:n tausta-/maastokartta ja ortokuva (WMTS, vaatii API-avaimen) sekä
    OpenStreetMap. Oletuksena Helsingissä kantakartta, muualla MML taustakartta.
    HUOM: MML-tiilet haetaan selaimessa, joten API-avain näkyy sivun lähdekoodissa."""
    import folium

    oletus = "helsinki" if helsinki else ("taustakartta" if api_key else "osm")
    for nimi, layer, tunnus in (
        ("Helsingin kantakartta", HELSINKI_KANTAKARTTA_LAYER, "helsinki"),
        ("Kantakartta (harmaa)", HELSINKI_KANTAKARTTA_HARMAA_LAYER, "helsinki_harmaa"),
    ):
        folium.WmsTileLayer(
            url=HELSINKI_WMS_URL, layers=layer, name=nimi, fmt="image/png",
            transparent=False, version="1.3.0", overlay=False, show=tunnus == oletus,
            max_zoom=22, attr="© Helsingin kaupunki, kantakartta",
        ).add_to(kartta)
    if api_key:
        for taso, nimi in MML_WMTS_TASOT:
            folium.TileLayer(
                tiles=f"{BASE_KARTTAKUVA_WMTS}/{taso}/default/WGS84_Pseudo-Mercator/{{z}}/{{y}}/{{x}}.png"
                      f"?api-key={api_key}",
                name=nimi, attr="© Maanmittauslaitos", overlay=False, show=taso == oletus,
                max_zoom=22, max_native_zoom=16,
            ).add_to(kartta)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False, show=oletus == "osm",
                     max_zoom=22, max_native_zoom=19).add_to(kartta)


def luo_kiinteisto_interaktiivinen_kartta(kiinteiston_piste, kiintopisteet, rajamerkit, rajaviivat=None,
                                          sade_m=None, helsinki=False, api_key=None,
                                          rakennukset=None, nurkat=None):
    """Zoomattava kartta kiintopiste-/rajamerkkihausta (samat tiedot kuin piirra_kartta).
    kiinteiston_piste = (e, n) EPSG:3879; kiintopisteet = hae_kiintopisteet_saateella-rivit;
    rajamerkit = [(tunniste, e, n)]; rajaviivat = [[(e, n), ...]];
    rakennukset = hae_kiinteiston_rakennukset-tulos; nurkat = [(tunniste, e, n)]."""
    import folium

    latlon = _latlon_muunnin()
    ke, kn = kiinteiston_piste
    kartta = folium.Map(tiles=None, max_zoom=22, control_scale=True)
    _lisaa_taustakartat(kartta, api_key, helsinki)

    def merkki(sijainti, symboli, koko, tooltip, popup=None, pysyva=False):
        """symboli = (merkki, väri) tai (merkki, väri, reunaväri)."""
        return _karttamerkki(
            sijainti, symboli[0], symboli[1], koko, *symboli[2:],
            tooltip=folium.Tooltip(tooltip, permanent=pysyva),
            popup=folium.Popup(popup, max_width=250) if popup else None,
        )

    if sade_m:
        ryhma = folium.FeatureGroup(name=f"Hakusäde {sade_m:.0f} m")
        folium.Circle(latlon(ke, kn), radius=float(sade_m), color="darkorange", weight=1.5,
                      dash_array="6 6", fill=False).add_to(ryhma)
        ryhma.add_to(kartta)

    if rajaviivat:
        ryhma = folium.FeatureGroup(name=f"{_viiva_svg('red')} Kiinteistön rajat")
        for viiva in rajaviivat:
            folium.PolyLine([latlon(pt[0], pt[1]) for pt in viiva], color="red", weight=2.5,
                            tooltip=f"{viivan_pituus(viiva):.2f} m").add_to(ryhma)
        ryhma.add_to(kartta)

    if kiintopisteet:
        ryhma = folium.FeatureGroup(name=f"{_symboli_svg('o', 'blue', 14)} Kiintopisteet")
        for pistetunnus, koodi, n, e, korkeus, luokka, etaisyys in kiintopisteet:
            numero = kiintopisteen_nimi(pistetunnus, luokka)
            merkki(latlon(e, n), ("o", "blue"), 14, str(numero),
                   f"<b>{numero}</b><br>{luokka or '-'}<br>N {n:.3f}<br>E {e:.3f}<br>"
                   f"Korkeus {korkeus}<br>Etäisyys {etaisyys} m", pysyva=True).add_to(ryhma)
        ryhma.add_to(kartta)

    if rajamerkit:
        ryhma = folium.FeatureGroup(name=f"{_symboli_svg('o', 'black', 10)} Rajamerkit")
        for tunniste, e, n in rajamerkit:
            merkki(latlon(e, n), ("o", "black"), 10, str(tunniste),
                   f"<b>{tunniste}</b><br>N {n:.3f}<br>E {e:.3f}").add_to(ryhma)
        ryhma.add_to(kartta)

    if nurkat:
        ryhma = folium.FeatureGroup(name=f"{_symboli_svg('s', 'crimson', 12)} Rakennusten nurkat")
        for r in rakennukset or []:
            osat = list(r["polygoni"].geoms) if r["polygoni"].geom_type == "MultiPolygon" else [r["polygoni"]]
            for osa in osat:
                for rengas in [osa.exterior] + list(osa.interiors):
                    folium.PolyLine([latlon(e, n) for e, n in rengas.coords], color="crimson", weight=1.5,
                                    tooltip=f"Rakennus {r['nro']}" + (f", {r['osoite']}" if r.get("osoite") else "")
                                    ).add_to(ryhma)
        for tunniste, e, n, *_ in nurkat:
            merkki(latlon(e, n), ("s", "crimson"), 9, tunniste,
                   f"<b>{tunniste}</b><br>N {n:.3f}<br>E {e:.3f}").add_to(ryhma)
        ryhma.add_to(kartta)

    ryhma = folium.FeatureGroup(name=f"{_symboli_svg('*', 'darkorange', 16, 'black')} Kiinteistön keskipiste")
    merkki(latlon(ke, kn), ("*", "darkorange", "black"), 26,
           "Kiinteistön keskipiste").add_to(ryhma)
    ryhma.add_to(kartta)

    if sade_m:
        r = float(sade_m)
        kulmat = [latlon(ke - r, kn - r), latlon(ke + r, kn + r)]
    else:
        kaikki = [(ke, kn)] + [(e, n) for _, e, n in (rajamerkit or [])]
        kulmat = [latlon(min(p[0] for p in kaikki) - 20, min(p[1] for p in kaikki) - 20),
                  latlon(max(p[0] for p in kaikki) + 20, max(p[1] for p in kaikki) + 20)]
    kartta.fit_bounds(kulmat)
    folium.LayerControl(collapsed=False).add_to(kartta)
    return kartta


def luo_jobxml_interaktiivinen_kartta(pisteet, seinalinja=None, api_key=None):
    """Zoomattava Leaflet-kartta (folium) JobXML-pisteistä. Taustana Helsingin
    kantakartta WMS-tiilinä (pyydetään EPSG:3857:ssä), MML:n kartat (api_key) tai
    OpenStreetMap; oletustausta valitaan pisteiden sijainnin mukaan.
    seinalinja = seinalinja.muodosta_seinalinjat()-tulos tai None.
    Palauttaa folium.Map-olion, tai None jos pisteillä ei ole koordinaatteja."""
    import folium
    import seinalinja as sl

    kelvolliset = [p for p in pisteet if p.get("n") is not None and p.get("e") is not None]
    if not kelvolliset:
        return None

    latlon = _latlon_muunnin()
    keski_e = sum(p["e"] for p in kelvolliset) / len(kelvolliset)
    keski_n = sum(p["n"] for p in kelvolliset) / len(kelvolliset)

    kartta = folium.Map(tiles=None, max_zoom=22, control_scale=True)
    _lisaa_taustakartat(kartta, api_key, on_helsingin_alueella(keski_e, keski_n))

    for kategoria, (vari, merkki, _) in JOBXML_KATEGORIAVARIT.items():
        kohteet = [p for p in kelvolliset if p.get("kategoria") == kategoria]
        if not kohteet:
            continue
        asemapiste = kategoria == "Asemapiste"
        reuna = "black" if asemapiste else "white"
        koko = 26 if asemapiste else 14
        # Tasovalitsin näyttää nimen HTML:nä -> symboli nimen viereen
        ryhma = folium.FeatureGroup(name=f"{_symboli_svg(merkki, vari, 14, reuna)} {kategoria}")
        for p in kohteet:
            korkeus = f"{p['korkeus']:.3f}" if p.get("korkeus") is not None else "-"
            popup = (f"<b>{p.get('nimi')}</b><br>Koodi: {p.get('koodi') or '-'}<br>{_ominaisuusrivit(p)}"
                     f"{kategoria}<br>N {p['n']:.3f}<br>E {p['e']:.3f}<br>Korkeus {korkeus}")
            _karttamerkki(
                latlon(p["e"], p["n"]), merkki, vari, koko, reuna,
                popup=folium.Popup(popup, max_width=250),
                tooltip=folium.Tooltip(str(p.get("nimi")), permanent=asemapiste),
            ).add_to(ryhma)
        ryhma.add_to(kartta)

    if seinalinja and seinalinja.get("viivat"):
        ryhma = folium.FeatureGroup(name=f"{_viiva_svg('red')} Seinälinja")
        for viiva in seinalinja["viivat"]:
            # viivan_pisteet tihentää kaaret ja sulkee suljetun viivan
            koordinaatit = [latlon(e, n) for e, n in sl.viivan_pisteet(viiva)]
            folium.PolyLine(koordinaatit, color="red", weight=3).add_to(ryhma)
            for k in viiva["karjet"]:
                if k["laji"] == "laskettu":
                    folium.CircleMarker(latlon(k["e"], k["n"]), radius=4, color="red",
                                        fill=True, fill_opacity=1,
                                        tooltip=f"Laskettu kulma: {k['nimi']}").add_to(ryhma)
        ryhma.add_to(kartta)

    kulmat = [latlon(p["e"], p["n"]) for p in kelvolliset]
    kartta.fit_bounds([[min(k[0] for k in kulmat), min(k[1] for k in kulmat)],
                       [max(k[0] for k in kulmat), max(k[1] for k in kulmat)]], padding=(30, 30))
    folium.LayerControl(collapsed=False).add_to(kartta)
    return kartta


# Seinälinjan koodien värit zoomattavalla kartalla (samat kuin esikatselukuvassa)
SEINALINJA_KOODIVARIT = {8: ("#2ca02c", "koodi 8"), 5: ("#1f77b4", "koodi 5"), 100: ("#ff7f0e", "koodi 100"),
                         4: ("#9467bd", "koodi 4")}


def _ominaisuusrivit(p):
    """Pisteen ominaisuustiedot popupin riveinä ("Rakennetyyppi: Sokkeli<br>"), tai ""."""
    import html

    return "".join(f"{html.escape(o['nimi'])}: {html.escape(o['arvo'])}<br>"
                   for o in p.get("ominaisuudet") or [] if o.get("arvo"))


def _karttateksti(sijainti, teksti, koko_px=11, lihavoitu=False, siirto=(6, -6)):
    """Pysyvä tekstinimiö kartalle (valkoinen reunus, ei laatikkoa)."""
    import folium

    tyyli = (f"font-size:{koko_px}px;font-weight:{'bold' if lihavoitu else 'normal'};white-space:nowrap;"
             "color:black;text-shadow:0 0 2px white,0 0 2px white,0 0 3px white")
    return folium.Marker(sijainti, icon=folium.DivIcon(
        html=f'<div style="{tyyli}">{teksti}</div>', icon_size=(0, 0),
        icon_anchor=(-siirto[0], -siirto[1]), class_name="kartta-teksti"))


def luo_seinalinja_interaktiivinen_kartta(tulos, api_key=None, viiva=None, lidar=None, poikkeamat_lidar=None):
    """Zoomattava kartta seinälinjasta samoilla merkinnöillä kuin esikatselukuvassa:
    viivat, pisteet koodeittain, pistenimet, lasketut kulmat ja viivojen numerot.
    tulos = seinalinja.muodosta_seinalinjat()-tulos. viiva = viivan nimi (esim. "Viiva 2" tai
    "RAK Sokkeli"), johon kartta rajataan aluksi (None = kaikki viivat). lidar =
    seinalinja.lue_lidar_dxf()-tulos ({"SEINA": janat, "EPAVARMA": janat}) ja poikkeamat_lidar =
    seinalinja.poikkeamat_lidarista()-tulos omiksi tasoikseen. Palauttaa folium.Map-olion, tai
    None jos piirrettävää ei ole."""
    import folium
    import seinalinja as sl

    viivojen_pisteet = {v["nimi"]: sl.viivan_pisteet(v) for v in tulos["viivat"]}
    kaikki_xy = [(p["e"], p["n"]) for p in tulos["pisteet"]] + [q for vp in viivojen_pisteet.values() for q in vp]
    if not kaikki_xy:
        return None

    latlon = _latlon_muunnin()
    keski_e = sum(x for x, _ in kaikki_xy) / len(kaikki_xy)
    keski_n = sum(y for _, y in kaikki_xy) / len(kaikki_xy)
    kartta = folium.Map(tiles=None, max_zoom=22, control_scale=True)
    _lisaa_taustakartat(kartta, api_key, on_helsingin_alueella(keski_e, keski_n))

    monta = len(tulos["viivat"]) > 1
    viivaryhma = folium.FeatureGroup(name=f"{_viiva_svg('black')} Seinälinja")
    for v in tulos["viivat"]:
        vp = viivojen_pisteet[v["nimi"]]
        if vp:
            folium.PolyLine([latlon(e, n) for e, n in vp], color="black", weight=2.5,
                            tooltip=v["nimi"]).add_to(viivaryhma)
        if monta and v["karjet"]:
            k = v["karjet"][0]
            _karttateksti(latlon(k["e"], k["n"]), v["nimi"], koko_px=13, lihavoitu=True,
                          siirto=(-10, 14)).add_to(viivaryhma)
    viivaryhma.add_to(kartta)

    lasketut = [k for v in tulos["viivat"] for k in v["karjet"] if k["laji"] == "laskettu"]
    if lasketut:
        ryhma = folium.FeatureGroup(name=f"{_symboli_svg('x', 'red', 14)} laskettu kulma")
        for k in lasketut:
            korkeus = f"{k['z']:.3f}" if k.get("z") is not None else "-"
            _karttamerkki(latlon(k["e"], k["n"]), "x", "red", 14,
                          popup=folium.Popup(f"<b>Laskettu kulma</b><br>{k['nimi']}<br>N {k['n']:.3f}<br>"
                                             f"E {k['e']:.3f}<br>Korkeus {korkeus}", max_width=250),
                          tooltip=f"Laskettu kulma: {k['nimi']}").add_to(ryhma)
        ryhma.add_to(kartta)

    for koodi, (vari, nimi) in SEINALINJA_KOODIVARIT.items():
        kohteet = [p for p in tulos["pisteet"] if sl.koodi_numeroksi(p.get("koodi")) == koodi]
        if not kohteet:
            continue
        ryhma = folium.FeatureGroup(name=f"{_symboli_svg('o', vari, 14)} {nimi}")
        for p in kohteet:
            korkeus = f"{p['korkeus']:.3f}" if p.get("korkeus") is not None else "-"
            _karttamerkki(latlon(p["e"], p["n"]), "o", vari, 12,
                          popup=folium.Popup(f"<b>{p.get('nimi')}</b><br>Koodi: {p.get('koodi') or '-'}<br>"
                                             f"{_ominaisuusrivit(p)}N {p['n']:.3f}<br>E {p['e']:.3f}<br>Korkeus {korkeus}",
                                             max_width=250)).add_to(ryhma)
        ryhma.add_to(kartta)

    nimet = folium.FeatureGroup(name="Pistenimet")
    for p in tulos["pisteet"]:
        _karttateksti(latlon(p["e"], p["n"]), str(p.get("nimi"))).add_to(nimet)
    nimet.add_to(kartta)

    # LiDAR-keilauksen seinät ja seinälinjan poikkeama niistä (kuten QGIS-lisäosassa)
    if lidar and any(lidar.values()):
        ryhma = folium.FeatureGroup(name=f"{_viiva_svg('#9467bd')} LiDAR-seinät")
        for taso, janat in lidar.items():
            for a, b in janat:
                folium.PolyLine([latlon(*a), latlon(*b)], color="#9467bd", weight=4 if taso == "SEINA" else 2,
                                opacity=0.8, dash_array=None if taso == "SEINA" else "6 4",
                                tooltip=f"LiDAR: {'seinä' if taso == 'SEINA' else 'epävarma'}").add_to(ryhma)
        ryhma.add_to(kartta)
    if poikkeamat_lidar:
        ryhma = folium.FeatureGroup(name=f"{_symboli_svg('o', '#ffbf00', 14)} Poikkeama LiDARista")
        for p in poikkeamat_lidar:
            for e, n, d in p["naytteet"]:
                if d is None:
                    continue
                vari = sl.poikkeamaluokka(d)[1]
                folium.CircleMarker(latlon(e, n), radius=3, color=vari, fill=True, fill_color=vari, fill_opacity=1,
                                    weight=0, tooltip=f"{p['nimi']}: {d * 100:.1f} cm").add_to(ryhma)
        ryhma.add_to(kartta)

    rajattavat = kaikki_xy
    if viiva is not None:
        valitut = viivojen_pisteet.get(viiva, []) + [
            (p["e"], p["n"]) for p in sl.rajaa_viivaan(tulos, viiva)["pisteet"]]
        rajattavat = valitut or kaikki_xy
    kulmat = [latlon(e, n) for e, n in rajattavat]
    kartta.fit_bounds([[min(k[0] for k in kulmat), min(k[1] for k in kulmat)],
                       [max(k[0] for k in kulmat), max(k[1] for k in kulmat)]], padding=(30, 30))
    folium.LayerControl(collapsed=False).add_to(kartta)
    return kartta


def piirra_jobxml_yleiskartta(pisteet, out_path, margin_m=20):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    kelvolliset = [p for p in pisteet if p.get("n") is not None and p.get("e") is not None]
    if not kelvolliset:
        return None

    xs = [p["e"] for p in kelvolliset]
    ys = [p["n"] for p in kelvolliset]
    keski_x = (min(xs) + max(xs)) / 2
    keski_y = (min(ys) + max(ys)) / 2
    puolisivu = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + margin_m
    puolisivu = max(puolisivu, margin_m)
    bbox = [keski_x - puolisivu, keski_y - puolisivu, keski_x + puolisivu, keski_y + puolisivu]

    fig, ax = plt.subplots(figsize=(8, 8))

    try:
        kuva = hae_helsinki_kantakartta(bbox, leveys_px=1000, korkeus_px=1000,
                                         layer=HELSINKI_KANTAKARTTA_LAYER)
        ax.imshow(kuva, extent=(bbox[0], bbox[2], bbox[1], bbox[3]), zorder=0)
    except Exception as e:
        ax.set_facecolor("#e8e8e8")
        print(f"Huom: kantakartan haku epäonnistui yleiskartalle ({e}) -- jatketaan ilman taustaa.")

    for kategoria, (vari, marker, koko) in JOBXML_KATEGORIAVARIT.items():
        kohteet = [p for p in kelvolliset if p.get("kategoria") == kategoria]
        if not kohteet:
            continue
        xs_k = [p["e"] for p in kohteet]
        ys_k = [p["n"] for p in kohteet]
        ax.scatter(xs_k, ys_k, c=vari, marker=marker, s=koko, zorder=4, label=kategoria,
                   edgecolors="black" if marker == "*" else "white", linewidths=0.5)

    for p in kelvolliset:
        if p.get("kategoria") == "Asemapiste":
            ax.annotate(str(p["nimi"]), (p["e"], p["n"]), textcoords="offset points",
                       xytext=(6, 6), fontsize=9, fontweight="bold")

    ax.set_xlim(bbox[0], bbox[2])
    ax.set_ylim(bbox[1], bbox[3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    plt.tight_layout(pad=0.3)
    plt.savefig(out_path, dpi=140)
    plt.close()
    return out_path


def piirra_kartta(kiinteiston_piste, kiintopisteet, rajamerkit, out_path, api_key,
                   sade_m=1000, nayta_kiinteistorajat=False, kiinteistotunnus=None,
                   rajaviivat=None, nurkat=None):
    """PNG-kartta haun tuloksista. Helsingissä taustana kantakartta (WMS, EPSG:3879),
    muualla MML:n taustakartta (WMTS, EPSG:3857)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    helsinki = kiinteistotunnus is not None and on_helsinki(kiinteistotunnus)
    ke, kn = kiinteiston_piste
    margin = (sade_m or 500) * 1.15
    bbox_3879 = [ke - margin, kn - margin, ke + margin, kn + margin]
    fig, ax = plt.subplots(figsize=(10, 10))

    if helsinki:
        def muunna(e, n):
            return e, n
        try:
            kuva = hae_helsinki_kantakartta(bbox_3879)
            ax.imshow(kuva, extent=(bbox_3879[0], bbox_3879[2], bbox_3879[1], bbox_3879[3]), zorder=0)
            print("Taustakartta: Helsingin kaupungin Kantakartta (WMS).")
        except Exception as e:
            print(f"Huom: Helsingin kantakartan haku epäonnistui ({e}) -- jatketaan ilman taustakarttaa.")
    else:
        muunna = _muunnin(DB_SRID, 3857).transform

    if nayta_kiinteistorajat and rajaviivat:
        for i, viiva in enumerate(rajaviivat):
            pts = [muunna(pt[0], pt[1]) for pt in viiva]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color="red", linewidth=1.6, zorder=3,
                    label="Kiinteistön raja" if i == 0 else None)

    kx, ky = muunna(ke, kn)
    ax.scatter([kx], [ky], marker="*", s=300, c="darkorange", zorder=6,
               edgecolors="black", linewidths=0.5, label="Kiinteistön keskipiste")

    if kiintopisteet:
        pts = [muunna(e, n) for _, _, n, e, *_ in kiintopisteet]
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], marker="o", s=60, c="blue", zorder=4,
                   label="Kiintopisteet")
        for (x, y), r in zip(pts, kiintopisteet):
            ax.annotate(kiintopisteen_nimi(r[0], r[5]), (x, y), textcoords="offset points", xytext=(5, 5), fontsize=8)

    if rajamerkit:
        pts = [muunna(e, n) for _, e, n in rajamerkit]
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], marker="o", s=18, c="black", zorder=5,
                   label="Rajamerkit")
        for (x, y), (tunniste, _, _) in zip(pts, rajamerkit):
            ax.annotate(tunniste, (x, y), textcoords="offset points", xytext=(4, 4), fontsize=7, color="black")

    if nurkat:
        pts = [muunna(e, n) for _, e, n, *_ in nurkat]
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], marker="s", s=10, c="crimson", zorder=5,
                   label="Rakennusten nurkat")
        for (x, y), (tunniste, *_) in zip(pts, nurkat):
            ax.annotate(tunniste, (x, y), textcoords="offset points", xytext=(3, 3), fontsize=6, color="crimson")

    bx0, by0 = muunna(bbox_3879[0], bbox_3879[1])
    bx1, by1 = muunna(bbox_3879[2], bbox_3879[3])
    ax.set_xlim(bx0, bx1)
    ax.set_ylim(by0, by1)

    if helsinki:
        ax.set_aspect("equal")
    else:
        import contextily as cx

        zoom = laske_zoom(max(bx1 - bx0, by1 - by0), max_tiles_per_side=5, max_zoom=16)
        print(f"MML-taustakartan zoomitaso: {zoom} (säteen {sade_m} m perusteella)")
        taustakartta_url = (
            f"{BASE_KARTTAKUVA_WMTS}/taustakartta/default/WGS84_Pseudo-Mercator/{{z}}/{{y}}/{{x}}.png?api-key={api_key}"
        )
        # Tiilet ladataan rinnakkain (add_basemap lataisi ne yksi kerrallaan)
        kuva, laajuus = cx.bounds2img(bx0, by0, bx1, by1, zoom=zoom, source=taustakartta_url,
                                      n_connections=4)
        ax.imshow(kuva, extent=laajuus, interpolation="bilinear", zorder=0)
        ax.text(0.005, 0.005, "© Maanmittauslaitos", transform=ax.transAxes, fontsize=8)
        print("Taustakartta: MML taustakartta (WMTS).")
        ax.set_xlim(bx0, bx1)
        ax.set_ylim(by0, by1)

    ax.set_axis_off()
    ax.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"Kartta tallennettu: {out_path}")


def tunnista_rajan_paatepisteet(viiva, rajamerkit, toleranssi_m=0.5):
    if not viiva or not rajamerkit:
        return None, None

    def lahin(piste):
        parhain = None
        parhain_etaisyys = toleranssi_m
        for tunniste, e, n in rajamerkit:
            d = math.hypot(piste[0] - e, piste[1] - n)
            if d <= parhain_etaisyys:
                parhain = tunniste
                parhain_etaisyys = d
        return parhain

    alku = lahin(viiva[0])
    loppu = lahin(viiva[-1])
    return alku, loppu


def viivan_pituus(viiva):
    return sum(
        math.hypot(viiva[i + 1][0] - viiva[i][0], viiva[i + 1][1] - viiva[i][1])
        for i in range(len(viiva) - 1)
    )


def kirjoita_kiinteistotiedot_txt(kiinteistotunnus, api_key, out_path):
    tunnus = normalisoi_kiinteistotunnus(kiinteistotunnus)
    url = lisaa_api_key(f"{BASE_KIINTEISTO_API}/collections/PalstanSijaintitiedot/items", api_key)
    params = {"kiinteistotunnus": tunnus, "crs": f"http://www.opengis.net/def/crs/EPSG/0/{DB_SRID}"}
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"Kiinteistötiedot kirjoitettu: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kiinteistotunnus", required=True)
    parser.add_argument("--sade", type=float, default=1000)
    parser.add_argument("--lataa-kiintopisteet", action="store_true")
    parser.add_argument("--tulostiedosto", default="kiintopisteet.krd")
    parser.add_argument("--gpkg-tiedosto", default="kiintopisteet_raw.gpkg")
    parser.add_argument("--luokka", default=None)
    parser.add_argument("--sisallyta-varamerkit", action="store_true")
    parser.add_argument("--ei-rajamerkkeja", action="store_true")
    parser.add_argument("--kartta-tiedosto", default="kartta.png")
    parser.add_argument("--ei-karttaa", action="store_true")
    parser.add_argument("--kiinteistorajat", action="store_true",
                         help="Piirtää kartalle vain haetun kiinteistön omat rajaviivat (punainen viiva).")
    args = parser.parse_args()

    if not MML_API_KEY:
        sys.exit("Aseta ympäristömuuttuja MML_API_KEY ennen ajoa.")

    if args.lataa_kiintopisteet:
        lataa_kiintopisteet_gpkg(HELSINKI_BBOX_3067, MML_API_KEY, args.gpkg_tiedosto)
        tuo_gpkg_postgis(args.gpkg_tiedosto, DB_CONN)

    coords = hae_kiinteiston_sijainti(args.kiinteistotunnus, MML_API_KEY)
    tallenna_kiinteiston_sijainti(args.kiinteistotunnus, coords, DB_CONN)

    tulokset_kaikki = hae_kiinteiston_kiintopisteet(args.kiinteistotunnus, args.sade, DB_CONN, args.luokka)
    tulokset = suodata_paamerkit(tulokset_kaikki, args.sisallyta_varamerkit)
    tallenna_haku_tulokset(args.kiinteistotunnus, tulokset, DB_CONN)

    print(f"\nKiintopisteet {args.sade} m säteellä ({len(tulokset)} päämerkkiä):")
    for pistetunnus, koodi, n, e, korkeus, luokka, etaisyys in tulokset:
        print(f"  {kiintopisteen_nimi(pistetunnus, luokka)}\t{koodi}\t{n}\t{e}\t{korkeus}\t{luokka}\t{etaisyys} m")

    rajamerkit = []
    if not args.ei_rajamerkkeja:
        rajamerkit = hae_kiinteiston_rajamerkit(args.kiinteistotunnus, MML_API_KEY)
        tallenna_rajamerkit_kantaan(args.kiinteistotunnus, rajamerkit, DB_CONN)

    rajaviivat = []
    if args.kiinteistorajat:
        rajaviivat = hae_kiinteiston_rajaviivat(args.kiinteistotunnus, MML_API_KEY)
        tallenna_rajaviivat_kantaan(args.kiinteistotunnus, rajaviivat, DB_CONN)

    kirjoita_yhdistetty_krd(tulokset, rajamerkit, args.tulostiedosto)

    if not args.ei_karttaa:
        piirra_kartta(coords, tulokset, rajamerkit, args.kartta_tiedosto, MML_API_KEY,
                      sade_m=args.sade, nayta_kiinteistorajat=args.kiinteistorajat,
                      kiinteistotunnus=args.kiinteistotunnus, rajaviivat=rajaviivat)


if __name__ == "__main__":
    main()
