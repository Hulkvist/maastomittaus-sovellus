"""
rakenna_zip.py -- Tekee QGIS:iin asennettavan lisäosan Lännen nopein seinälinja
(qgis_plugin/dist/lannen_nopein_seinalinja.zip) ja saman työkalun yhtenä Processing-skriptinä
(qgis_plugin/dist/lannen_nopein_seinalinja_skripti.py).

Kopioi sovelluksen jobxml_tuonti.py:n, seinalinja.py:n ja seinat_pilvesta.py:n lisäosan
lib-kansioon, jotta lisäosa käyttää samaa koodia kuin sovellus (ja lidarscanin lidarpipe). Kopioista karsitaan osat, joita seinälinja ei
tarvitse (kantaan tallennus ja poistot, krd-vienti, kuvat, DXF), ks. KARSITTAVAT.
Aja aina, kun niitä on muutettu:

    python3 qgis_plugin/rakenna_zip.py

Asennus QGIS:ssä: Lisäosat -> Hallitse ja asenna lisäosia -> Asenna zip-tiedostosta.
Skripti (jos lisäosia ei saa asentaa): Prosessointi-työkalulaatikko -> Python-kuvake ->
Lisää skripti työkalulaatikkoon.
"""

import ast
import os
import re
import zipfile

KANSIO = os.path.dirname(os.path.abspath(__file__))
SOVELLUS = os.path.dirname(KANSIO)
LISAOSA = os.path.join(KANSIO, "maastomittaus")   # kansion nimi pysyy, jotta päivitys korvaa vanhan
JAETUT = ["jobxml_tuonti.py", "seinalinja.py", "seinat_pilvesta.py"]
# Ylimmän tason funktiot ja vakiot, joita lisäosa ei tarvitse: ne jätetään pois lisäosasta ja
# skriptistä (mm. kannan taulut ja SQL eivät päädy jaettavaan tiedostoon).
KARSITTAVAT = {
    "jobxml_tuonti.py": [
        "_ASEMAKARTAT", "_ASEMAKARTAT_MAX", "piirra_asemapiste_kartta", "piirra_yleiskartta", "muodosta_seinalinja", "pisteet_tallennettavaksi",
        "KRD_MITATUT", "KRD_LIITOKSET", "KRD_RTK", "KRD_KOODIMUUNNOS", "KRD_KOODISELITTEET", "KRD_TUNTEMATON_KOODI",
        "_krd_kirjainkoodi", "krd_koodi", "_krd_valitut", "krd_kirjainkoodit", "krd_pisteet", "kirjoita_krd",
        "_tallennettavat_asemat", "mittausjarjestys", "tallenna_mittaukset_kantaan", "tallenna_seinalinjat_kantaan", "poista_mittaukset_kannasta", "poista_mittaukset_lahdetiedostolla",
        "poista_kaikki_mittaukset", "MITTAUSTAULUT", "_poista_mittaukset", "LAATULUOKAT", "_huonoin_asema",
        "_mm_tai_none", "MITTAUSTIETOSARAKKEET", "_mittaustiedot", "tallenna_raportti_kantaan", "_aseman_liitokset", "hae_raportit", "hae_raportin_pdf",
    ],
    "seinalinja.py": ["rajaa_viivaan", "_KOODIVARIT", "piirra_seinalinja_kartta", "dxf_taso", "kirjoita_dxf",
                      "lue_lidar_dxf"],
    # lidarpipen DXF-vienti tarvitsee ezdxf:n; lisäosa kirjoittaa DXF:n write_dxf_r12:lla
    "seinat_pilvesta.py": ["write_dxf"],
}
ZIP_NIMI = "lannen_nopein_seinalinja.zip"
SKRIPTIN_NIMI = "lannen_nopein_seinalinja_skripti.py"

# Skriptiin pakattavat moduulit: (moduulin nimi, tiedosto). Jaetut moduulit ovat ylimpänä
# tasolla, koska jobxml_tuonti tuo seinalinjan nimellä; lisäosan omat paketin sisällä.
SKRIPTIN_MODUULIT = [("seinalinja", os.path.join(SOVELLUS, "seinalinja.py")),
                     ("jobxml_tuonti", os.path.join(SOVELLUS, "jobxml_tuonti.py")),
                     ("maastomittaus_skripti.ydin", os.path.join(LISAOSA, "ydin.py")),
                     ("maastomittaus_skripti.tyylit", os.path.join(LISAOSA, "tyylit.py")),
                     ("maastomittaus_skripti.kantakartta", os.path.join(LISAOSA, "kantakartta.py")),
                     ("maastomittaus_skripti.lidar", os.path.join(LISAOSA, "lidar.py")),
                     ("maastomittaus_skripti.seinalinja_algoritmi", os.path.join(LISAOSA, "seinalinja_algoritmi.py"))]

SKRIPTIN_RUNKO = '''# Lännen nopein seinälinja -- QGIS:n Processing-skripti (seinälinja JXL-tiedostosta).
# Generoitu: qgis_plugin/rakenna_zip.py (älä muokkaa käsin). Sama työkalu kuin lisäosassa.
# Lisää: Prosessointi-työkalulaatikko -> Python-kuvake -> Lisää skripti työkalulaatikkoon.
# Merkkijonot ovat ASCII-koodattuja, jotta tiedosto toimii millä tahansa merkistöllä.


def _lataa_algoritmi():
    import sys
    import types

    lahteet = %s
    paketti = types.ModuleType("maastomittaus_skripti")
    paketti.__path__ = []
    sys.modules["maastomittaus_skripti"] = paketti
    for nimi, lahde in lahteet:
        moduuli = types.ModuleType(nimi)
        moduuli.__file__ = "<" + nimi + ">"
        if "." in nimi:
            moduuli.__package__ = "maastomittaus_skripti"
        sys.modules[nimi] = moduuli
        exec(compile(lahde, moduuli.__file__, "exec"), moduuli.__dict__)
    return sys.modules["maastomittaus_skripti.seinalinja_algoritmi"].SeinalinjaJxlAlgoritmi


class SeinalinjaJxl(_lataa_algoritmi()):
    def createInstance(self):
        return SeinalinjaJxl()
'''


def _nimi(solmu):
    if isinstance(solmu, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return solmu.name
    if isinstance(solmu, ast.Assign) and len(solmu.targets) == 1 and isinstance(solmu.targets[0], ast.Name):
        return solmu.targets[0].id
    return None


def karsi(lahde, karsittavat, tiedosto="?"):
    """Poistaa lähdekoodista ylimmän tason funktiot ja vakiot nimiltä karsittavat (myös niitä
    suoraan edeltävät kommentit). Virhe, jos jotain nimeä ei löydy tai jäljelle jäänyt koodi
    viittaa poistettuun nimeen."""
    rivit = lahde.splitlines(keepends=True)
    poistot, loydetyt = [], set()
    for solmu in ast.parse(lahde).body:
        if _nimi(solmu) not in karsittavat:
            continue
        loydetyt.add(_nimi(solmu))
        alku = min([solmu.lineno] + [d.lineno for d in getattr(solmu, "decorator_list", [])]) - 1
        while alku > 0 and rivit[alku - 1].lstrip().startswith("#"):
            alku -= 1
        poistot.append((alku, solmu.end_lineno))
    puuttuvat = set(karsittavat) - loydetyt
    if puuttuvat:
        raise ValueError(f"{tiedosto}: karsittavia ei löytynyt: {sorted(puuttuvat)}")
    for alku, loppu in sorted(poistot, reverse=True):
        del rivit[alku:loppu]
    tulos = "".join(rivit)
    # väliotsikot (# ---- / # Otsikko / # ----), joiden alta kaikki poistettiin
    tulos = re.sub(r"(?m)^# -{10,}\n# .*\n# -{10,}\n(?=\s*(?:# -{10,}|\Z))", "", tulos)
    # moduulin kuvauksen Vaatimukset-kappale koskee sovellusta (kanta, kuvat), ei lisäosaa
    tulos = re.sub(r'(?m)^Vaatimukset:.*(?:\n(?!\n|""").*)*\n?', "", tulos, count=1)
    tulos = re.sub(r"\n{3,}", "\n\n\n", tulos).rstrip("\n") + "\n"
    viittaukset = {n.id for n in ast.walk(ast.parse(tulos)) if isinstance(n, ast.Name)}
    viittaukset |= {n.attr for n in ast.walk(ast.parse(tulos)) if isinstance(n, ast.Attribute)}
    jaljella = viittaukset & set(karsittavat)
    if jaljella:
        raise ValueError(f"{tiedosto}: karsittuihin viitataan yhä: {sorted(jaljella)}")
    return tulos


def jaettu_lahde(tiedosto):
    """Sovelluksen tiedoston sisältö lisäosaa varten karsittuna (ks. KARSITTAVAT)."""
    nimi = os.path.basename(tiedosto)
    with open(tiedosto, encoding="utf-8") as f:
        lahde = f.read()
    if nimi not in KARSITTAVAT:
        return lahde
    return (f"# Karsittu kopio sovelluksen tiedostosta {nimi} (qgis_plugin/rakenna_zip.py): mukana vain\n"
            "# seinälinjan muodostukseen tarvittavat osat. Älä muokkaa tätä vaan alkuperäistä.\n"
            + karsi(lahde, KARSITTAVAT[nimi], nimi))


def kopioi_jaetut():
    lib = os.path.join(LISAOSA, "lib")
    os.makedirs(lib, exist_ok=True)
    for nimi in JAETUT:
        with open(os.path.join(lib, nimi), "w", encoding="utf-8", newline="\n") as f:
            f.write(jaettu_lahde(os.path.join(SOVELLUS, nimi)))


def rakenna_skripti(polku):
    lahteet = [(nimi, jaettu_lahde(tiedosto)) for nimi, tiedosto in SKRIPTIN_MODUULIT]
    luettelo = "[\n" + "".join(f"        ({ascii(n)}, {ascii(l)}),\n" for n, l in lahteet) + "    ]"
    with open(polku, "w", encoding="utf-8", newline="\n") as f:
        f.write(SKRIPTIN_RUNKO % luettelo)
    return polku


def rakenna():
    kopioi_jaetut()
    dist = os.path.join(KANSIO, "dist")
    os.makedirs(dist, exist_ok=True)
    zip_polku = os.path.join(dist, ZIP_NIMI)
    with zipfile.ZipFile(zip_polku, "w", zipfile.ZIP_DEFLATED) as z:
        for juuri, kansiot, tiedostot in os.walk(LISAOSA):
            kansiot[:] = [k for k in kansiot if k != "__pycache__"]
            for nimi in sorted(tiedostot):
                polku = os.path.join(juuri, nimi)
                # zipin juuressa on kansio maastomittaus/, kuten QGIS odottaa
                z.write(polku, os.path.relpath(polku, KANSIO))
    return zip_polku, rakenna_skripti(os.path.join(dist, SKRIPTIN_NIMI))


if __name__ == "__main__":
    print(*rakenna(), sep="\n")
