"""Tietokantatestit väliaikaisessa PostGIS-kannassa.

Kanta luodaan testiajon ajaksi ja poistetaan lopuksi. Testit ohitetaan, jos PostgreSQL:ää
tai PostGIS:iä ei ole käytettävissä (yhteys PG*-ympäristömuuttujilla, oletuskäyttäjä =
kirjautunut käyttäjä). GPKG-tuonnin testit vaativat lisäksi ogr2ogr:n."""
import getpass
import json
import math
import os
import shutil
import sys
import uuid
from decimal import Decimal

import pytest

HAKEMISTO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HAKEMISTO))
psycopg2 = pytest.importorskip("psycopg2")
import hae_kiintopisteet as hk
import jobxml_tuonti as jx
import seinalinja as sl

E0, N0 = 25496000.0, 6672000.0


def _yhteys(dbname):
    return {
        "dbname": dbname,
        "user": os.environ.get("PGUSER", getpass.getuser()),
        "password": os.environ.get("PGPASSWORD", ""),
        "host": os.environ.get("PGHOST", "localhost"),
        "port": os.environ.get("PGPORT", "5432"),
    }


@pytest.fixture(scope="module")
def db():
    hallinta = _yhteys("postgres")
    nimi = f"testi_{uuid.uuid4().hex[:10]}"
    try:
        conn = psycopg2.connect(connect_timeout=3, **hallinta)
    except psycopg2.Error as e:
        pytest.skip(f"PostgreSQL ei käytettävissä: {e}")
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f"CREATE DATABASE {nimi};")
    try:
        yhteys = _yhteys(nimi)
        with hk.kanta(yhteys) as cur:
            try:
                with open(os.path.join(os.path.dirname(HAKEMISTO), "schema.sql"), encoding="utf-8") as f:
                    cur.execute(f.read())
            except psycopg2.Error as e:
                pytest.skip(f"PostGIS ei käytettävissä: {e}")
        yield yhteys
    finally:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {nimi} WITH (FORCE);")
        conn.close()


def kysy(db, sql, parametrit=None):
    with hk.kanta(db) as cur:
        cur.execute(sql, parametrit)
        return cur.fetchall()


@pytest.fixture(autouse=True)
def tyhjat_taulut(request):
    if "db" in request.fixturenames:
        db = request.getfixturevalue("db")
        with hk.kanta(db) as cur:
            cur.execute("TRUNCATE kiintopisteet, kiinteistot, rajamerkit, haku_tulokset, kiinteistorajat, "
                        "kentalla_mitatut_pisteet, seinalinjat, mittausraportit, asemapisteet, "
                        "asemien_liitokset;")


# --- kanta()-apufunktio -------------------------------------------------------

def test_virhe_peruu_muutokset(db):
    with pytest.raises(RuntimeError):
        with hk.kanta(db) as cur:
            cur.execute("INSERT INTO rajamerkit (numero) VALUES ('peruttava');")
            raise RuntimeError("testi")
    assert kysy(db, "SELECT count(*) FROM rajamerkit;") == [(0,)]


# --- kiinteistöhaun tallennukset ----------------------------------------------

def test_kiinteiston_tallennukset_ja_haku_saateella(db):
    hk.tallenna_kiinteiston_sijainti("091-1-1-1", [E0, N0], db)
    hk.tallenna_kiinteiston_sijainti("091-1-1-2", [E0 + 5, N0], db)  # korvaa edellisen
    assert kysy(db, "SELECT kiinteistotunnus FROM kiinteistot;") == [("091-1-1-2",)]

    hk.tallenna_rajamerkit_kantaan("091-1-1-2", [("a", E0 + 1, N0 + 1), ("b", E0 + 2, N0 + 2)], db)
    hk.tallenna_rajamerkit_kantaan("091-1-1-2", [("c", E0 + 3, N0 + 3)], db)
    assert kysy(db, "SELECT numero FROM rajamerkit;") == [("c",)]

    hk.tallenna_rajaviivat_kantaan("091-1-1-2", [[(E0, N0), (E0 + 3, N0 + 4)], [(E0, N0)]], db)
    assert kysy(db, "SELECT pituus_m::float, round(ST_Length(geom)::numeric, 3)::float FROM kiinteistorajat;") \
        == [(5.0, 5.0)]  # yksipisteinen viiva ohitetaan

    with hk.kanta(db) as cur:
        cur.execute("INSERT INTO kiintopisteet (pistetunnus, luokka, korkeus, geom) VALUES "
                    "('L', 'E2', 1.5, ST_SetSRID(ST_MakePoint(%s, %s), 3879)), "
                    "('K', 'E2', 2.5, ST_SetSRID(ST_MakePoint(%s, %s), 3879));",
                    (E0 + 5, N0 + 30, E0 + 5, N0 + 900))
    rivit = hk.hae_kiintopisteet_saateella("091-1-1-2", 100, db)
    assert [(r[0], float(r[6])) for r in rivit] == [("L", 30.0)]
    hk.tallenna_haku_tulokset("091-1-1-2", rivit, db)
    assert kysy(db, "SELECT pistetunnus FROM haku_tulokset;") == [("L",)]


# --- MML:n kiintopisteiden tuonti (GPKG) ----------------------------------------

def _gpkg(polku, pisteet):
    if not shutil.which("ogr2ogr"):
        pytest.skip("ogr2ogr ei käytettävissä")
    geojson = polku.with_suffix(".geojson")
    geojson.write_text(json.dumps({
        "type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3067"}},
        "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [x, y]},
                      "properties": {"kiintopistetunnus": t, "EUREF_FIN_tarkkuusluokka": luokka,
                                     "keskusmerkki": "pultti", "N2000_korkeus": h}}
                     for t, x, y, luokka, h in pisteet]}))
    hk.aja_ogr2ogr(["-f", "GPKG", str(polku), str(geojson), "-nln", "kiintopisteet"])
    return str(polku)


def test_gpkg_tuonti_korkeudet_ja_yhdistaminen(db, tmp_path):
    # ensimmäisen pisteen tyhjä korkeus teki ennen sarakkeesta tekstin ja kaatoi tuonnin
    eka = _gpkg(tmp_path / "eka.gpkg", [("A1", 385000, 6671000, "E4", ""), ("A2", 385100, 6671100, "E4", "12,3"),
                                        ("A3", 385200, 6671200, "E4", "-"), ("A4", 385300, 6671300, "E4", "7.25")])
    assert hk.tuo_gpkg_postgis(eka, db) == 4
    toka = _gpkg(tmp_path / "toka.gpkg", [("A1", 385000, 6671000, 4, 99.5), ("B1", 327500, 6822500, "E2", 110.0)])
    assert hk.tuo_gpkg_postgis(toka, db) == 2
    rivit = {t: (luokka, None if k is None else float(k))
             for t, luokka, k in kysy(db, "SELECT pistetunnus, luokka, korkeus FROM kiintopisteet;")}
    assert rivit == {"A1": ("4", 99.5), "A2": ("E4", 12.3), "A3": ("E4", None), "A4": ("E4", 7.25),
                     "B1": ("E2", 110.0)}
    assert kysy(db, "SELECT to_regclass('kiintopisteet_tuonti');") == [(None,)]


# --- omat kiintopisteet -------------------------------------------------------

def test_omat_kiintopisteet(db):
    with hk.kanta(db) as cur:
        cur.execute("INSERT INTO kiintopisteet (pistetunnus, luokka, geom) "
                    "VALUES ('MML1', 'E2', ST_SetSRID(ST_MakePoint(%s, %s), 3879));", (E0, N0))
    pisteet, _ = hk.jasenna_kiintopiste_txt(f"K1;{N0 + 10};{E0 + 10};1,5\nK2 {N0 + 20} {E0 + 20}\n")
    assert hk.tallenna_omat_kiintopisteet(pisteet, db) == 2
    assert hk.tallenna_omat_kiintopisteet(pisteet, db) == 2  # uudelleentuonti ei tuplaa
    assert sorted(kysy(db, "SELECT pistetunnus, luokka FROM kiintopisteet;")) == [
        ("K1", hk.OMA_KIINTOPISTE_LUOKKA), ("K2", hk.OMA_KIINTOPISTE_LUOKKA), ("MML1", "E2")]
    assert hk.poista_omat_kiintopisteet(db) == 2
    assert kysy(db, "SELECT pistetunnus FROM kiintopisteet;") == [("MML1",)]


def test_omat_kiintopisteet_sama_tunnus_eri_paikoissa(db):
    with hk.kanta(db) as cur:
        cur.execute("INSERT INTO kiintopisteet (pistetunnus, luokka, geom) "
                    "VALUES ('100', 'E2', ST_SetSRID(ST_MakePoint(%s, %s), 3879));", (E0, N0))
    pisteet, _ = hk.jasenna_kiintopiste_txt(f"100 {N0 + 10} {E0 + 10}\n100 {N0 + 500} {E0 + 500}\n")
    hk.tallenna_omat_kiintopisteet(pisteet, db)
    hk.tallenna_omat_kiintopisteet(pisteet, db)  # uudelleentuonti ei tuplaa
    assert sorted(r[0] for r in kysy(db, "SELECT luokka FROM kiintopisteet WHERE pistetunnus = '100';")) == sorted(
        ["E2", hk.OMA_KIINTOPISTE_LUOKKA, hk.OMA_KIINTOPISTE_LUOKKA])

    hk.tallenna_kiinteiston_sijainti("091-1-1-1", [E0, N0], db)
    assert len(hk.hae_kiinteiston_kiintopisteet("091-1-1-1", 100, db)) == 1
    maara, lahin = hk.lahin_oma_kiintopiste("091-1-1-1", db)
    assert maara == 2 and abs(lahin - 14.1) < 0.1


# --- JobXML-mittausten tallennus ja poistot -----------------------------------

@pytest.mark.oikeat_aineistot
def test_mittausten_tallennus_ja_poistot(db):
    with open(os.path.join(HAKEMISTO, "data", "jobxml", "testi2.jxl"), "rb") as f:
        _, pisteet, _ = jx.jasenna_tyo(f.read(), "testi2.jxl")
    tallennettavat = jx.pisteet_tallennettavaksi(pisteet)
    assert len(tallennettavat) == len(pisteet) - 3  # RTK-alkuperäismittaukset pois
    assert jx.tallenna_mittaukset_kantaan("091-1-1-1", tallennettavat, db) == len(tallennettavat)
    assert jx.tallenna_mittaukset_kantaan("091-1-1-2", tallennettavat[:2], db) == 2

    rivi = kysy(db, "SELECT kuvaus, tarkkuusluokka, mittaustapa, vinoetaisyys > 0 FROM kentalla_mitatut_pisteet "
                    "WHERE pistetunnus = '1' AND kiinteistotunnus = '091-1-1-1';")
    assert rivi == [("Kartoituspiste", "8", "Takymetri", True)]

    assert jx.poista_mittaukset_kannasta("091-1-1-2", db) == (2, 0, 0)
    assert jx.poista_mittaukset_lahdetiedostolla("muu.jxl", db) == (0, 0, 0)
    assert jx.poista_mittaukset_lahdetiedostolla("testi2.jxl", db) == (len(tallennettavat), 0, 0)
    jx.tallenna_mittaukset_kantaan("091-1-1-1", tallennettavat[:3], db)
    assert jx.poista_kaikki_mittaukset(db) == (3, 0, 0)


@pytest.mark.oikeat_aineistot
def test_seinalinjojen_tallennus_ja_poistot(db):
    with open(os.path.join(HAKEMISTO, "data", "jobxml", "testi2.jxl"), "rb") as f:
        _, pisteet, _ = jx.jasenna_tyo(f.read(), "testi2.jxl")
    tulos = jx.muodosta_seinalinja(pisteet)
    viivoja = len(tulos["viivat"])
    assert viivoja >= 1
    poikkeamat = [{"nimi": tulos["viivat"][0]["nimi"], "keskiarvo_m": 0.012, "suurin_m": 0.034, "peitto": 0.8}]
    assert jx.tallenna_seinalinjat_kantaan("091-1-1-1", tulos, "testi2.jxl", db, poikkeamat) == viivoja
    # uudelleentallennus korvaa saman kiinteistön ja tiedoston viivat
    assert jx.tallenna_seinalinjat_kantaan("091-1-1-1", tulos, "testi2.jxl", db) == viivoja
    jx.tallenna_seinalinjat_kantaan("091-1-1-2", tulos, "testi2.jxl", db)

    viiva = tulos["viivat"][0]
    rivi = kysy(db, "SELECT viiva, taso, suljettu, pituus_m, lidar_keskiarvo_cm, ST_SRID(geom), ST_IsValid(geom) "
                    "FROM seinalinjat WHERE kiinteistotunnus = '091-1-1-1' AND viiva = %s;", (viiva["nimi"],))
    assert len(rivi) == 1
    nimi, taso, suljettu, pituus, lidar_cm, srid, kelpaa = rivi[0]
    assert (nimi, taso, suljettu, srid, kelpaa) == (viiva["nimi"], "SEINALINJA", viiva["suljettu"], 3879, True)
    assert lidar_cm is None  # toinen tallennus ilman LiDARia korvasi ensimmäisen
    odotettu = sum(math.dist(a, b) for a, b in zip(sl.viivan_pisteet(viiva), sl.viivan_pisteet(viiva)[1:]))
    assert abs(float(pituus) - odotettu) < 0.01
    if viiva["suljettu"]:
        assert kysy(db, "SELECT bool_and(ST_IsClosed(geom)) FROM seinalinjat WHERE viiva = %s;",
                    (viiva["nimi"],)) == [(True,)]

    jx.tallenna_mittaukset_kantaan("091-1-1-1", jx.pisteet_tallennettavaksi(pisteet)[:2], db)
    assert jx.poista_mittaukset_kannasta("091-1-1-1", db) == (2, viivoja, 0)
    assert jx.poista_mittaukset_lahdetiedostolla("testi2.jxl", db) == (0, viivoja, 0)
    jx.tallenna_seinalinjat_kantaan("091-1-1-1", tulos, "testi2.jxl", db, poikkeamat)
    assert kysy(db, "SELECT lidar_keskiarvo_cm, lidar_suurin_cm, lidar_peitto_pros FROM seinalinjat "
                    "WHERE viiva = %s;", (viiva["nimi"],)) == [(Decimal("1.2"), Decimal("3.4"), Decimal("80"))]
    assert jx.poista_kaikki_mittaukset(db) == (0, viivoja, 0)


def test_helsingissa_vain_omat_kiintopisteet(db):
    with hk.kanta(db) as cur:
        cur.execute("INSERT INTO kiintopisteet (pistetunnus, luokka, geom) VALUES "
                    "('MML1', 'E2', ST_SetSRID(ST_MakePoint(%s, %s), 3879)), "
                    "('OMA1', %s, ST_SetSRID(ST_MakePoint(%s, %s), 3879));",
                    (E0 + 10, N0, hk.OMA_KIINTOPISTE_LUOKKA, E0 + 20, N0))
    hk.tallenna_kiinteiston_sijainti("091-1-1-1", [E0, N0], db)
    assert [r[0] for r in hk.hae_kiinteiston_kiintopisteet("091-1-1-1", 100, db)] == ["OMA1"]
    hk.tallenna_kiinteiston_sijainti("049-1-1-1", [E0, N0], db)  # Espoo
    assert sorted(r[0] for r in hk.hae_kiinteiston_kiintopisteet("049-1-1-1", 100, db)) == ["MML1", "OMA1"]


@pytest.mark.oikeat_aineistot
def test_mittausraportin_tallennus_haku_ja_poistot(db):
    with open(os.path.join(HAKEMISTO, "data", "jobxml", "testi2.jxl"), "rb") as f:
        raportti, pisteet, hylatyt = jx.jasenna_tyo(f.read(), "testi2.jxl")
    asemia = len(raportti["asemapisteet"])
    assert asemia >= 1
    pdf = b"%PDF-1.4 testi"
    assert jx.tallenna_raportti_kantaan("091-1-1-1", raportti, pisteet, hylatyt, pdf, db) == asemia
    # uudelleentallennus korvaa saman kiinteistön ja tiedoston raportin ja asemat
    assert jx.tallenna_raportti_kantaan("091-1-1-1", raportti, pisteet, hylatyt, pdf, db) == asemia
    jx.tallenna_raportti_kantaan("091-1-1-2", raportti, pisteet, hylatyt, None, db)
    assert kysy(db, "SELECT count(*) FROM mittausraportit;") == [(2,)]
    assert kysy(db, "SELECT count(*) FROM asemapisteet;") == [(2 * asemia,)]

    raportit = jx.hae_raportit(db, "091-1-1-1")
    assert len(raportit) == 1
    r = raportit[0]
    assert (r["lahdetiedosto"], r["asemia"], r["pdf_kt"]) == ("testi2.jxl", asemia, 0)
    assert r["huonoin_laatuluokka"].startswith(raportti["asemapisteet"][0]["laatu"]["luokka"])
    assert r["mittauspaiva"] == "21.09.2026"
    assert jx.hae_raportin_pdf("091-1-1-1", "testi2.jxl", db) == pdf
    assert len(jx.hae_raportit(db)) == 2
    uusin = jx.hae_raportit(db)[0]
    assert uusin["kiinteistotunnus"] == "091-1-1-2" and jx.hae_raportin_pdf("091-1-1-2", "testi2.jxl", db) is None
    # uudelleentallennus vaihtaa rivin id:n, mutta PDF löytyy edelleen
    jx.tallenna_raportti_kantaan("091-1-1-1", raportti, pisteet, hylatyt, pdf + b"2", db)
    assert jx.hae_raportit(db, "091-1-1-1")[0]["id"] != r["id"]
    assert jx.hae_raportin_pdf("091-1-1-1", "testi2.jxl", db) == pdf + b"2"
    assert jx.hae_raportin_pdf("091-1-1-1", "muu.jxl", db) is None

    a = raportti["asemapisteet"][0]
    rivi = kysy(db, "SELECT asema, laatuluokka, rms_residuaali_mm, ST_X(geom), ST_Y(geom), ST_SRID(geom) "
                    "FROM asemapisteet WHERE kiinteistotunnus = '091-1-1-1' AND asema = %s;", (a["nimi"],))
    assert len(rivi) == 1
    nimi, luokka, rms, e, n, srid = rivi[0]
    assert (nimi, luokka, srid) == (a["nimi"], a["laatu"]["luokka"], 3879)
    assert abs(float(rms) - a["laatu"]["rms_residuaali_m"] * 1000) < 0.1
    assert abs(e - a["e"]) < 1e-6 and abs(n - a["n"]) < 1e-6
    # orientoinnin liitospisteet: tekstinä asemalle ja viivoina asemalta liitospisteisiin
    liitospisteet = kysy(db, "SELECT liitospisteet FROM asemapisteet WHERE kiinteistotunnus = '091-1-1-1' "
                             "AND asema = %s;", (a["nimi"],))[0][0]
    assert all(nimi in liitospisteet for nimi in a["liitospisteet"]) and "dHz" in liitospisteet
    asema_nro = kysy(db, "SELECT asema_nro FROM asemapisteet WHERE kiinteistotunnus = '091-1-1-1' AND asema = %s;",
                     (a["nimi"],))[0][0]
    assert asema_nro == 1
    assert kysy(db, "SELECT DISTINCT asema_nro FROM asemien_liitokset WHERE kiinteistotunnus = '091-1-1-1' "
                    "AND asema = %s;", (a["nimi"],)) == [(asema_nro,)]
    viivat = kysy(db, "SELECT liitospiste, dhz_mm, ST_X(ST_StartPoint(geom)), ST_Y(ST_EndPoint(geom)) "
                      "FROM asemien_liitokset WHERE kiinteistotunnus = '091-1-1-1' AND asema = %s "
                      "ORDER BY liitospiste;", (a["nimi"],))
    assert [v[0] for v in viivat] == sorted(a["liitospisteet"])
    koordinaatit = {nimi: n for nimi, n, _ in a["liitospisteet_koordinaatit"]}
    for nimi, dhz, alku_e, loppu_n in viivat:
        assert abs(alku_e - a["e"]) < 1e-6 and abs(loppu_n - koordinaatit[nimi]) < 1e-6
        assert dhz is not None
    # raportin piste on mitattujen pisteiden keskellä
    assert kysy(db, "SELECT bool_and(geom IS NOT NULL) FROM mittausraportit;") == [(True,)]

    assert jx.poista_mittaukset_kannasta("091-1-1-2", db) == (0, 0, 1)
    assert kysy(db, "SELECT count(*) FROM asemapisteet;") == [(asemia,)]
    assert kysy(db, "SELECT count(DISTINCT kiinteistotunnus) FROM asemien_liitokset;") == [(1,)]
    assert jx.poista_mittaukset_lahdetiedostolla("testi2.jxl", db) == (0, 0, 1)
    assert kysy(db, "SELECT count(*) FROM asemapisteet;") == [(0,)]
    jx.tallenna_raportti_kantaan("091-1-1-1", raportti, pisteet, hylatyt, pdf, db)
    assert jx.poista_kaikki_mittaukset(db) == (0, 0, 1)
    assert kysy(db, "SELECT count(*) FROM asemapisteet;") == [(0,)]
    assert kysy(db, "SELECT count(*) FROM asemien_liitokset;") == [(0,)]
