-- schema.sql (päivitetty)
-- Koordinaatisto: ETRS-GK25 (EPSG:3879)

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS kiintopisteet (
    id SERIAL PRIMARY KEY,
    pistetunnus TEXT,
    luokka TEXT,
    tyyppi TEXT,
    korkeus NUMERIC(7,3),
    geom geometry(Point, 3879)
);
CREATE INDEX IF NOT EXISTS idx_kiintopisteet_geom ON kiintopisteet USING GIST (geom);

CREATE TABLE IF NOT EXISTS kiinteistot (
    kiinteistotunnus TEXT PRIMARY KEY,
    geom geometry(Point, 3879)
);
CREATE INDEX IF NOT EXISTS idx_kiinteistot_geom ON kiinteistot USING GIST (geom);

-- Rajamerkit tallennetaan myös kantaan (aiemmin vain txt/png)
CREATE TABLE IF NOT EXISTS rajamerkit (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    numero TEXT,
    geom geometry(Point, 3879)
);
CREATE INDEX IF NOT EXISTS idx_rajamerkit_geom ON rajamerkit USING GIST (geom);

-- Viimeisimmän haun tulokset (vain säteen sisällä olevat pisteet),
-- jotta QGIS voi näyttää PELKÄSTÄÄN nämä eikä koko Helsingin kiintopisteet.
-- Tyhjennetään ja täytetään uudelleen joka haulla (yksi aktiivinen haku kerrallaan).
CREATE TABLE IF NOT EXISTS haku_tulokset (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    pistetunnus TEXT,
    koodi INT,
    korkeus NUMERIC,
    luokka TEXT,
    etaisyys_m NUMERIC,
    geom geometry(Point, 3879)
);
CREATE INDEX IF NOT EXISTS idx_haku_tulokset_geom ON haku_tulokset USING GIST (geom);

-- Haetun kiinteistön omat rajaviivat (KiinteistorajanSijaintitiedot-haun
-- tulos), jotta ne näkyvät myös QGIS:ssä eikä vain PNG-kartassa.
-- pituus_m: rajaviivan pituus metreinä (QGIS-attribuuttina käytettäväksi).
-- Tyhjennetään ja täytetään uudelleen joka haulla.
CREATE TABLE IF NOT EXISTS kiinteistorajat (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    pituus_m NUMERIC,
    geom geometry(LineString, 3879)
);
CREATE INDEX IF NOT EXISTS idx_kiinteistorajat_geom ON kiinteistorajat USING GIST (geom);

-- Sovelluksesta tallennetut JobXML-mittaukset. Kertyvät tallennuksista; poisto
-- sovelluksen poisto-osiosta (kiinteistö, lähdetiedosto tai koko taulu).
-- kuvaus = pisteen kategoria, tarkkuusluokka = pistekoodi,
-- vinoetaisyys = takymetrin vinoetäisyys (GNSS-pisteillä tyhjä).
CREATE TABLE IF NOT EXISTS kentalla_mitatut_pisteet (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    pistetunnus TEXT,
    kuvaus TEXT,
    mittaustapa TEXT,
    tarkkuusluokka TEXT,
    vinoetaisyys NUMERIC,
    satelliitteja INT,
    pdop NUMERIC,
    korkeus NUMERIC,
    lahdetiedosto TEXT,
    geom geometry(Point, 3879)
);
CREATE INDEX IF NOT EXISTS idx_kentalla_mitatut_pisteet_geom ON kentalla_mitatut_pisteet USING GIST (geom);
-- Lisätty myöhemmin: mittausaika, asema, jolta piste mitattiin (asema_nro kuten asemapisteet-taulussa),
-- ja jarjestys = mittauksen eteneminen tasaisena järjestyksenä (asema, sen pisteet, seuraava asema ...)
-- QGIS-animaatiota varten; sama numerointi asemapisteet- ja asemien_liitokset-tauluissa.
ALTER TABLE kentalla_mitatut_pisteet ADD COLUMN IF NOT EXISTS mitattu TIMESTAMP;
ALTER TABLE kentalla_mitatut_pisteet ADD COLUMN IF NOT EXISTS asema TEXT;
ALTER TABLE kentalla_mitatut_pisteet ADD COLUMN IF NOT EXISTS asema_nro INT;
ALTER TABLE kentalla_mitatut_pisteet ADD COLUMN IF NOT EXISTS jarjestys INT;

-- Mittauksista muodostetut seinälinjat (koodit 8/5/100), tallennetaan pisteiden
-- kanssa samalla napilla. Saman kiinteistön ja lähdetiedoston viivat korvataan
-- uudelleentallennuksessa. Kaaret tihennetty murtoviivaksi.
-- taso = DXF-taso (SEINALINJA, SEINALINJA_RAK_SOKKELI ...).
-- lidar_*: poikkeama LiDAR-seinistä, jos LiDAR-DXF oli mukana (muuten tyhjä).
CREATE TABLE IF NOT EXISTS seinalinjat (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    viiva TEXT,
    taso TEXT,
    suljettu BOOLEAN,
    pituus_m NUMERIC,
    lasketut_kulmat INT,
    lidar_keskiarvo_cm NUMERIC,
    lidar_suurin_cm NUMERIC,
    lidar_peitto_pros NUMERIC,
    lahdetiedosto TEXT,
    tallennettu TIMESTAMPTZ DEFAULT now(),
    geom geometry(LineString, 3879)
);
CREATE INDEX IF NOT EXISTS idx_seinalinjat_geom ON seinalinjat USING GIST (geom);

-- Mittausraportti tallennetuista mittauksista: yhteenveto ja PDF (ladattavissa
-- sovelluksen kohdasta "Tallennetut mittausraportit"). Piste = mitattujen pisteiden
-- keskipiste, jotta raportin tiedot saa QGIS:ssä kartalta klikkaamalla.
-- Saman kiinteistön ja lähdetiedoston raportti korvataan uudelleentallennuksessa.
CREATE TABLE IF NOT EXISTS mittausraportit (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    lahdetiedosto TEXT,
    tyon_nimi TEXT,
    mittauspaiva TEXT,
    kalusto TEXT,
    mitattuja_pisteita INT,
    asemia INT,
    hylattyja INT,
    huonoin_asema TEXT,
    huonoin_laatuluokka TEXT,
    tarkistukset TEXT,
    pdf BYTEA,
    pdf_kt INT,
    tallennettu TIMESTAMPTZ DEFAULT now(),
    geom geometry(Point, 3879)
);
CREATE INDEX IF NOT EXISTS idx_mittausraportit_geom ON mittausraportit USING GIST (geom);

-- Tallennettujen mittausten kojeasemat laatuluokkineen (QGIS: väritys laatuluokan mukaan).
-- Residuaalit ja keskivirheet millimetreinä.
CREATE TABLE IF NOT EXISTS asemapisteet (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    lahdetiedosto TEXT,
    asema TEXT,
    maarittely TEXT,
    laatuluokka TEXT,
    laatupisteet NUMERIC,
    rms_residuaali_mm NUMERIC,
    suurin_residuaali_mm NUMERIC,
    liitospisteita INT,
    kulmapeitto_deg NUMERIC,
    pdop_keskiarvo NUMERIC,
    keskivirhe_n_mm NUMERIC,
    keskivirhe_e_mm NUMERIC,
    keskivirhe_h_mm NUMERIC,
    korkeus NUMERIC,
    kojekorkeus NUMERIC,
    mitattu TIMESTAMP,
    varoitukset TEXT,
    geom geometry(Point, 3879)
);
CREATE INDEX IF NOT EXISTS idx_asemapisteet_geom ON asemapisteet USING GIST (geom);
-- Lisätty myöhemmin: orientoinnin liitospisteet tekstinä (nimi ja vaakaresiduaali) ja
-- aseman järjestysnumero tiedostossa (QGIS-tyyli laskee siitä aseman värin)
ALTER TABLE asemapisteet ADD COLUMN IF NOT EXISTS liitospisteet TEXT;
ALTER TABLE asemapisteet ADD COLUMN IF NOT EXISTS asema_nro INT;
ALTER TABLE asemapisteet ADD COLUMN IF NOT EXISTS jarjestys INT;

-- Asemien orientoinnit: viiva asemalta jokaiseen liitospisteeseen ja korkeusliitokseen
-- residuaaleineen (mm). QGIS: aseman värillä (asema_nro), kuten asemapisteen reunus.
CREATE TABLE IF NOT EXISTS asemien_liitokset (
    id SERIAL PRIMARY KEY,
    kiinteistotunnus TEXT,
    lahdetiedosto TEXT,
    asema TEXT,
    asema_nro INT,
    liitospiste TEXT,
    tyyppi TEXT,
    delta_n_mm NUMERIC,
    delta_e_mm NUMERIC,
    dhz_mm NUMERIC,
    dh_mm NUMERIC,
    kaytto TEXT,
    pituus_m NUMERIC,
    geom geometry(LineString, 3879)
);
CREATE INDEX IF NOT EXISTS idx_asemien_liitokset_geom ON asemien_liitokset USING GIST (geom);
ALTER TABLE asemien_liitokset ADD COLUMN IF NOT EXISTS asema_nro INT;
ALTER TABLE asemien_liitokset ADD COLUMN IF NOT EXISTS jarjestys INT;

-- animaatioaika (kentalla_mitatut_pisteet, asemapisteet, asemien_liitokset): jarjestys sekunteina
-- 1.1.2000 00:00 UTC alkaen; QGIS:n aikasäädin lukee ajan tästä. Aikavyöhykkeellinen, koska
-- aikasäädin toimii UTC-ajassa: aikavyöhykkeetön sarake siirtyi siinä 2-3 h, eikä mitään näkynyt.
-- Ensimmäinen versio oli aikavyöhykkeetön, joten se vaihdetaan (laskennallinen, ei tietoa häviä).
DO $$
DECLARE
    taulu TEXT;
BEGIN
    FOREACH taulu IN ARRAY ARRAY['kentalla_mitatut_pisteet', 'asemapisteet', 'asemien_liitokset'] LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = taulu AND column_name = 'animaatioaika'
                     AND data_type = 'timestamp without time zone') THEN
            EXECUTE format('ALTER TABLE %I DROP COLUMN animaatioaika', taulu);
        END IF;
        EXECUTE format('ALTER TABLE %I ADD COLUMN IF NOT EXISTS animaatioaika TIMESTAMPTZ '
                       'GENERATED ALWAYS AS (to_timestamp(946684800 + jarjestys)) STORED', taulu);
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION kiintopisteet_saateella(
    p_kiinteistotunnus TEXT,
    p_sade_m NUMERIC DEFAULT 1000,
    p_luokka TEXT DEFAULT NULL
)
RETURNS TABLE (
    pistetunnus TEXT,
    koodi INT,
    n_koordinaatti NUMERIC,
    e_koordinaatti NUMERIC,
    korkeus NUMERIC,
    luokka TEXT,
    etaisyys_m NUMERIC
) AS $$
    SELECT
        k.pistetunnus,
        11 AS koodi,
        ROUND(ST_Y(k.geom)::numeric, 3) AS n_koordinaatti,
        ROUND(ST_X(k.geom)::numeric, 3) AS e_koordinaatti,
        COALESCE(ROUND(k.korkeus, 3), 0.000) AS korkeus,
        k.luokka,
        ROUND(ST_Distance(k.geom, kt.geom)::numeric, 1) AS etaisyys_m
    FROM kiintopisteet k, kiinteistot kt
    WHERE kt.kiinteistotunnus = p_kiinteistotunnus
      AND ST_DWithin(k.geom, kt.geom, p_sade_m)
      AND (p_luokka IS NULL OR k.luokka ILIKE p_luokka)
    ORDER BY etaisyys_m;
$$ LANGUAGE sql STABLE;
