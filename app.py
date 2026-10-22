"""
app.py -- Streamlit-käyttöliittymä
----------------------------------
Kiintopiste- ja rajamerkkihaku (hae_kiintopisteet.py), JobXML-tuonti ja
-raportti (jobxml_tuonti.py), seinälinja (seinalinja.py) sekä tallennettujen
mittausten poisto kannasta.

Käyttö:
    streamlit run app.py
"""

import collections
import hashlib
import math
import os
import tempfile
import time
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium
for _avain in ("MML_API_KEY", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER",
               "PGPASSWORD", "SOVELLUKSEN_SALASANA"):
    if _avain in st.secrets:
        os.environ[_avain] = str(st.secrets[_avain])


# Yksinkertainen salasanasuoja koko sovellukselle
def _tarkista_salasana():
    def _salasana_syotetty():
        if st.session_state.get("_syotetty_salasana") == st.secrets.get("SOVELLUKSEN_SALASANA"):
            st.session_state["_kirjautunut"] = True
            del st.session_state["_syotetty_salasana"]
        else:
            st.session_state["_kirjautunut"] = False

    if st.session_state.get("_kirjautunut", False):
        return True

    st.text_input(
        "Salasana",
        type="password",
        key="_syotetty_salasana",
        on_change=_salasana_syotetty,
    )

    if st.session_state.get("_kirjautunut") is False:
        st.error("Väärä salasana, yritä uudelleen.")

    return False


if not _tarkista_salasana():
    st.stop()
import hae_kiintopisteet as hk
import jobxml_tuonti as jx
import mittausraportti as mr
import seinalinja as sl
import seinalinjan_muokkain as slm


_AJON_ALKU = time.time()


def _ajastettu(nimi, funktio, *args, **kwargs):
    """Ajaa funktion ja kirjoittaa Streamlitin lokiin keston, jos yli 1 s (hitauden syyn etsintään:
    palvelin hakee osan tiedoista ulkoisista palveluista)."""
    alku = time.time()
    try:
        return funktio(*args, **kwargs)
    finally:
        kesto = time.time() - alku
        if kesto > 1.0:
            print(f"Aika: {nimi} {kesto:.1f} s", flush=True)

st.set_page_config(page_title="Kiintopisteiden, rajamerkkien ja rakennusten nurkkien haku", layout="wide")
st.image("kuvat/koirat_kuplat.jpg", width="stretch")  # alkuperäinen ilman kuplia: kuvat/koirat.jpg
st.title("Kiintopisteiden, rajamerkkien ja rakennusten nurkkien haku")

if not hk.MML_API_KEY:
    st.error(
        "Ympäristömuuttuja MML_API_KEY ei ole asetettu. "
        "Aja terminaalissa `export MML_API_KEY=\"oma-avaimesi\"` ennen "
        "`streamlit run app.py` -komentoa, ja käynnistä sovellus uudelleen."
    )
    st.stop()

with st.form("hakulomake"):
    hakutapa = st.radio("Hakutapa", ["Kiinteistötunnus", "Osoite"], horizontal=True)

    kiinteistotunnus_syote = None
    osoite_syote = None
    kaupunki_syote = None

    if hakutapa == "Kiinteistötunnus":
        kiinteistotunnus_syote = st.text_input(
            "Kiinteistötunnus", placeholder="esim. 091-25-840-8 tai 834-434-1-158"
        )
    else:
        col_o1, col_o2 = st.columns(2)
        with col_o1:
            osoite_syote = st.text_input("Katuosoite", placeholder="esim. Mannerheimintie 1")
        with col_o2:
            kaupunki_syote = st.text_input("Kaupunki", placeholder="esim. Helsinki")

    sade = st.number_input("Kiintopisteiden hakusäde (m)", min_value=10.0, max_value=20000.0,
                            value=1000.0, step=50.0)

    col3, col4 = st.columns(2)
    with col3:
        koordinaatisto = st.selectbox(
            "Koordinaatisto (vaikuttaa sekä näytön taulukoihin että kiintopisteet.krd:hen)",
            options=list(hk.COORDINATE_SYSTEMS.keys()),
            index=0,
            help="Kannan sisäinen tallennus (QGIS) on aina GK25/EPSG:3879 riippumatta tästä valinnasta.",
        )
    with col4:
        st.write("")

    col5, col6, col7 = st.columns(3)
    with col5:
        nayta_rajat = st.checkbox("Näytä kiinteistön rajaviivat kartalla ja tallenna kantaan", value=True)
    with col6:
        sisallyta_varamerkit = st.checkbox("Sisällytä varamerkit", value=False)
    with col7:
        hae_rajamerkit = st.checkbox("Hae rajamerkit", value=True)

    hae_nurkat = st.checkbox(
        "Hae rakennusten nurkkapisteet (vain Helsinki)",
        value=True,
        help="Kiinteistön rakennusten nurkat Helsingin kantakartasta. Mukaan tulevat rakennukset, "
             "joiden pinta-alasta vähintään puolet on kiinteistöllä.",
    )
    hae_kiinteistotiedot = st.checkbox(
        "Luo myös erillinen kiinteistotiedot.txt (kaikki avoimen rajapinnan tieto)",
        value=False,
    )
    paivita_kiintopisteet = st.checkbox(
        "Päivitä kiintopisteet MML:ltä",
        value=False,
        help="Kiintopisteet haetaan MML:ltä automaattisesti, jos kannassa ei ole niitä hakualueella. "
             "Tällä ne haetaan uudelleen, vaikka niitä olisi jo kannassa. Ei Helsingissä: siellä "
             "käytetään vain tuotuja kaupungin kiintopisteitä.",
    )

    haettu = st.form_submit_button("Hae tiedot")

if haettu:
    st.session_state.pop("haku", None)
    kohde_epsg = hk.COORDINATE_SYSTEMS[koordinaatisto]
    desimaalit = 8 if kohde_epsg == 4326 else 3

    try:
        if hakutapa == "Kiinteistötunnus":
            if not kiinteistotunnus_syote or not kiinteistotunnus_syote.strip():
                st.warning("Anna kiinteistötunnus ennen hakua.")
                st.stop()
            tunnus = kiinteistotunnus_syote.strip()
        else:
            if not osoite_syote or not osoite_syote.strip():
                st.warning("Anna katuosoite ennen hakua.")
                st.stop()
            with st.spinner(f"Etsitään kiinteistötunnusta osoitteelle: {osoite_syote}, {kaupunki_syote or ''}..."):
                tunnus, ehdokkaat, tasmasiko_kunta = hk.hae_kiinteistotunnus_osoitteella(
                    osoite_syote.strip(), (kaupunki_syote or "").strip(), hk.MML_API_KEY
                )
            st.success(f"Osoite tunnistettu kiinteistöksi: **{tunnus}**")

            if kaupunki_syote and kaupunki_syote.strip() and not tasmasiko_kunta:
                st.warning(
                    f"Rajapinta ei löytänyt osumaa, joka olisi varmuudella kunnassa "
                    f"'{kaupunki_syote.strip()}' -- tulos saattaa olla väärästä kunnasta. "
                    f"Tarkista alta löydetyt ehdokkaat, ja jos tulos on väärä, kokeile "
                    f"hakea suoraan oikealla kiinteistötunnuksella."
                )

            if len(ehdokkaat) > 1:
                with st.expander("Näytä kaikki löydetyt ehdokkaat (valittu pienimmän pinta-alan perusteella)"):
                    st.dataframe(
                        [
                            {
                                "Lähde": e["lahde"], "Kiinteistötunnus": e["tunnus"],
                                "Pinta-ala (m2)": round(e["pinta_ala"], 0) if e["pinta_ala"] is not None else "tuntematon",
                                "Kunta täsmäsi": "kyllä" if e.get("tasmasiko_kunta") else "ei varmaa",
                                "Valittu": "✔" if e["tunnus"] == tunnus else "",
                            }
                            for e in ehdokkaat
                        ],
                        width="stretch",
                    )

            valitun_pinta_ala = next((e["pinta_ala"] for e in ehdokkaat if e["tunnus"] == tunnus), None)
            if valitun_pinta_ala is not None and valitun_pinta_ala > hk.SUURI_PINTA_ALA_VAROITUSRAJA:
                st.warning(
                    f"Valitun kiinteistön pinta-ala on poikkeuksellisen suuri "
                    f"({valitun_pinta_ala:.0f} m2) -- tämä voi olla katu-, rautatie- tai "
                    f"muu yleinen alue eikä rakennuksen oma tontti. Jos kartta näyttää "
                    f"epäilyttävän suurelta määrältä rajamerkkejä, kokeile hakea suoraan "
                    f"oikealla kiinteistötunnuksella."
                )

        with st.spinner("Haetaan kiinteistön sijaintia..."):
            coords = hk.hae_kiinteiston_sijainti(tunnus, hk.MML_API_KEY)
            hk.tallenna_kiinteiston_sijainti(tunnus, coords, hk.DB_CONN)
        n_disp, e_disp = hk.muunna_piste(coords[0], coords[1], kohde_epsg)
        st.success(f"Kiinteistön keskipiste ({koordinaatisto}): N={n_disp:.{desimaalit}f}, E={e_disp:.{desimaalit}f}")

        with st.spinner("Haetaan kiintopisteitä säteeltä..."):
            tulokset_kaikki = hk.hae_kiinteiston_kiintopisteet(tunnus, sade, hk.DB_CONN)
        if hk.on_helsinki(tunnus):
            # Helsingissä vain tuodut kaupungin kiintopisteet, ei MML:n pisteitä
            if not tulokset_kaikki:
                omia, lahin = hk.lahin_oma_kiintopiste(tunnus, hk.DB_CONN)
                if omia:
                    st.warning(f"Säteeltä {sade:.0f} m ei löytynyt kaupungin kiintopisteitä. Kannassa on "
                               f"{omia} tuotua kiintopistettä, lähin {lahin:.0f} m päässä kiinteistöstä. "
                               f"Kasvata sädettä tai tarkista tuodun tiedoston koordinaatit.")
                else:
                    st.warning("Helsingin kaupungin kiintopisteitä ei ole kannassa -- tuo ne "
                               "kohdassa Tuo omat kiintopisteet (txt/krd).")
        elif not tulokset_kaikki or paivita_kiintopisteet:
            try:
                with st.spinner("Haetaan kiintopisteitä MML:n tiedostopalvelusta (voi kestää noin minuutin)..."):
                    tuotu = hk.paivita_kiintopisteet_alueelle(coords, sade, hk.MML_API_KEY, hk.DB_CONN)
                st.info(f"Kantaan tuotiin {tuotu} kiintopistettä MML:ltä.")
                tulokset_kaikki = hk.hae_kiinteiston_kiintopisteet(tunnus, sade, hk.DB_CONN)
            except Exception as latausvirhe:
                st.warning(f"Kiintopisteiden haku MML:ltä epäonnistui ({latausvirhe}) -- jatketaan ilman niitä.")
        with st.spinner("Tallennetaan hakutulokset..."):
            tulokset = hk.suodata_paamerkit(tulokset_kaikki, sisallyta_varamerkit)
            hk.tallenna_haku_tulokset(tunnus, tulokset, hk.DB_CONN)
        st.write(f"Löytyi **{len(tulokset)}** kiintopistettä {sade:.0f} m säteellä.")

        rajamerkit = []
        if hae_rajamerkit:
            with st.spinner("Haetaan rajamerkkejä..."):
                rajamerkit = hk.hae_kiinteiston_rajamerkit(tunnus, hk.MML_API_KEY)
        hk.tallenna_rajamerkit_kantaan(tunnus, rajamerkit, hk.DB_CONN)
        if hae_rajamerkit:
            st.write(f"Löytyi **{len(rajamerkit)}** rajamerkkiä.")
            if len(rajamerkit) > 100:
                st.warning(
                    f"Rajamerkkejä löytyi poikkeuksellisen paljon ({len(rajamerkit)} kpl) -- "
                    "tämä on tyypillistä yleisille alueille (kadut, radat) eikä tavallisille "
                    "tonteille. Tarkista yllä ehdokaslista, jos käytit osoitehakua, tai hae "
                    "suoraan oikealla kiinteistötunnuksella."
                )

        rajaviivat = []
        if nayta_rajat:
            with st.spinner("Haetaan kiinteistön rajaviivoja..."):
                rajaviivat = hk.hae_kiinteiston_rajaviivat(tunnus, hk.MML_API_KEY)
        hk.tallenna_rajaviivat_kantaan(tunnus, rajaviivat, hk.DB_CONN)
        if nayta_rajat:
            st.write(f"Löytyi **{len(rajaviivat)}** rajaviivaa.")

        rakennukset, nurkat = [], []
        if hae_nurkat and hk.on_helsinki(tunnus):
            try:
                with st.spinner("Haetaan rakennusten nurkkapisteitä Helsingin kantakartasta..."):
                    alue = hk.hae_kiinteiston_alue(tunnus, hk.MML_API_KEY)
                    rakennukset = hk.hae_kiinteiston_rakennukset(alue)
                    nurkat = hk.rakennusten_nurkat(rakennukset)
                st.write(f"Löytyi **{len(rakennukset)}** rakennusta, **{len(nurkat)}** nurkkapistettä.")
            except Exception as nurkkavirhe:
                st.warning(f"Rakennusten nurkkapisteiden haku epäonnistui ({nurkkavirhe}) -- jatketaan ilman niitä.")
        elif hae_nurkat:
            st.caption("Rakennusten nurkkapisteet ovat saatavilla vain Helsingistä (Helsingin kantakartta).")

        tmp_dir = tempfile.mkdtemp()
        krd_path = os.path.join(tmp_dir, "kiintopisteet.krd")
        hk.kirjoita_yhdistetty_krd(tulokset, rajamerkit, krd_path, kohde_epsg=kohde_epsg, nurkat=nurkat,
                                   desimaalit=desimaalit)
        with open(krd_path, "rb") as f:
            krd_sisalto = f.read()

        kiinteistotiedot = None
        if hae_kiinteistotiedot:
            kiinteistotiedot_path = os.path.join(tmp_dir, "kiinteistotiedot.txt")
            with st.spinner("Kootaan kiinteistötietoja avoimesta rajapinnasta..."):
                hk.kirjoita_kiinteistotiedot_txt(tunnus, hk.MML_API_KEY, kiinteistotiedot_path)
            with open(kiinteistotiedot_path, "rb") as f:
                kiinteistotiedot = f.read()

        st.session_state["viimeisin_kiinteistotunnus"] = tunnus
        # Tulokset talteen: kartta, taulukot ja latausnapit pysyvät näkyvissä, kun
        # sivu ajetaan uudelleen (esim. PNG-napista tai tiedoston latauksesta).
        st.session_state["haku"] = {
            "tunnus": tunnus, "coords": coords, "tulokset": tulokset, "rajamerkit": rajamerkit,
            "rajaviivat": rajaviivat, "rakennukset": rakennukset, "nurkat": nurkat, "sade": sade,
            "nayta_rajat": nayta_rajat, "koordinaatisto": koordinaatisto, "kohde_epsg": kohde_epsg,
            "desimaalit": desimaalit, "krd": krd_sisalto, "kiinteistotiedot": kiinteistotiedot, "png": None,
        }

    except Exception as e:
        st.error(f"Haku epäonnistui: {e}")


# ---------------------------------------------------------------------------
# Viimeisimmän haun tulokset
# ---------------------------------------------------------------------------
haku = st.session_state.get("haku")
if haku:
    tunnus, coords, tulokset = haku["tunnus"], haku["coords"], haku["tulokset"]
    rajamerkit, rajaviivat = haku["rajamerkit"], haku["rajaviivat"]
    rakennukset, nurkat, sade, nayta_rajat = haku["rakennukset"], haku["nurkat"], haku["sade"], haku["nayta_rajat"]
    koordinaatisto, kohde_epsg, desimaalit = haku["koordinaatisto"], haku["kohde_epsg"], haku["desimaalit"]

    st.subheader(f"Kartta ({tunnus})")
    st.caption("Zoomaa hiirellä tai +/- napeista. Taustakartan ja tasot voi vaihtaa oikeasta yläkulmasta.")
    try:
        hakukartta = hk.luo_kiinteisto_interaktiivinen_kartta(
            coords, tulokset, rajamerkit, rajaviivat if nayta_rajat else None,
            sade_m=sade, helsinki=hk.on_helsinki(tunnus), api_key=hk.MML_API_KEY,
            rakennukset=rakennukset, nurkat=nurkat,
        )
        # returned_objects=[] -> zoomaus ei aja sovellusta uudelleen
        st_folium(hakukartta, height=650, use_container_width=True, returned_objects=[],
                  key="kiinteisto_kartta")
    except Exception as karttavirhe:
        st.caption(f"Zoomattavaa karttaa ei voitu piirtää ({karttavirhe}).")

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        # PNG tehdään vain pyydettäessä: taustakartan tiilet haetaan joka kerta verkosta.
        if st.button("Luo kartta PNG-kuvana", key="hakukartta_png"):
            png_path = os.path.join(tempfile.mkdtemp(), "kartta.png")
            try:
                with st.spinner("Piirretään karttaa..."):
                    hk.piirra_kartta(
                        coords, tulokset, rajamerkit, png_path, hk.MML_API_KEY,
                        sade_m=sade, nayta_kiinteistorajat=nayta_rajat,
                        kiinteistotunnus=tunnus, rajaviivat=rajaviivat, nurkat=nurkat,
                    )
                with open(png_path, "rb") as f:
                    haku["png"] = f.read()
            except Exception as karttavirhe:
                st.error(f"PNG-karttaa ei voitu piirtää: {karttavirhe}")
        if haku["png"]:
            st.download_button("Lataa kartta (PNG)", haku["png"], file_name="kartta.png", mime="image/png")
    with col_b:
        st.download_button(
            f"Lataa kiintopisteet.krd ({koordinaatisto})", haku["krd"],
            file_name="kiintopisteet.krd", mime="text/plain",
        )
    with col_c:
        if haku["kiinteistotiedot"]:
            st.download_button(
                "Lataa kiinteistotiedot.txt", haku["kiinteistotiedot"],
                file_name="kiinteistotiedot.txt", mime="text/plain",
            )

    if tulokset:
        st.subheader(f"Kiintopisteet ({koordinaatisto})")
        rivit = []
        for r in tulokset:
            pistetunnus, koodi, n, e, korkeus, luokka, etaisyys = r
            n_out, e_out = hk.muunna_piste(e, n, kohde_epsg)
            rivit.append({
                "Pistetunnus": hk.kiintopisteen_nimi(pistetunnus, luokka),
                "Koodi": koodi,
                "N": round(n_out, desimaalit),
                "E": round(e_out, desimaalit),
                "Korkeus": korkeus, "Luokka": luokka, "Etäisyys (m)": etaisyys,
            })
        st.dataframe(rivit, width="stretch")

    if rajamerkit:
        st.subheader(f"Rajamerkit ({koordinaatisto})")
        rivit = []
        for tunniste, e, n in rajamerkit:
            n_out, e_out = hk.muunna_piste(e, n, kohde_epsg)
            rivit.append({
                "Tunniste": tunniste,
                "N": round(n_out, desimaalit),
                "E": round(e_out, desimaalit),
            })
        st.dataframe(rivit, width="stretch")

    if nurkat:
        osoitteet = {r["nro"]: r.get("osoite") for r in rakennukset}
        with st.expander(f"Rakennusten nurkat ({koordinaatisto}, {len(nurkat)} kpl)"):
            rivit = []
            for numero, e, n, rakennus_nro in nurkat:
                n_out, e_out = hk.muunna_piste(e, n, kohde_epsg)
                osoite = osoitteet.get(rakennus_nro)
                rivit.append({
                    "Numero": numero,
                    "Rakennus": f"{rakennus_nro}, {osoite}" if osoite else str(rakennus_nro),
                    "N": round(n_out, desimaalit),
                    "E": round(e_out, desimaalit),
                })
            st.dataframe(rivit, width="stretch", hide_index=True)

    if rajaviivat:
        st.subheader("Rajojen pituudet")
        rivit = []
        for i, v in enumerate(rajaviivat):
            alku, loppu = hk.tunnista_rajan_paatepisteet(v, rajamerkit)
            if alku and loppu:
                vali = f"{alku} - {loppu}"
            elif alku or loppu:
                vali = f"{alku or '?'} - {loppu or '?'}"
            else:
                vali = f"Raja #{i + 1} (rajamerkkiä ei tunnistettu)"
            rivit.append({"Väli": vali, "Pituus (m)": round(hk.viivan_pituus(v), 2)})
        st.dataframe(rivit, width="stretch")

    st.info(
        "Tiedot on tallennettu PostGIS-kantaan (kiinteistot, rajamerkit, "
        "haku_tulokset, kiinteistorajat -taulut) AINA GK25/EPSG:3879-muodossa "
        "riippumatta yllä valitusta koordinaatistosta -- QGIS ei siis muutu "
        "tämän valinnan mukaan. Avaa QGIS ja klikkaa jokaista tasoa hiiren "
        "oikealla -> **Reload Layer** nähdäksesi uuden haun tulokset."
    )


# ---------------------------------------------------------------------------
# Omien kiintopisteiden tuonti tekstitiedostosta
# ---------------------------------------------------------------------------
with st.expander("Tuo omat kiintopisteet (txt/krd, ETRS-GK25)"):
    st.caption(
        "Esim. Helsingin kaupungin omat kiintopisteet, joita ei ole avoimissa rajapinnoissa. "
        "N- ja E-koordinaatit tunnistetaan suuruusluokasta, joten sarakkeiden järjestys ei haittaa. "
        "Pistetunnus on ensimmäinen sarake (esim. 'nimi N E Z'), krd-muodossa "
        "('1 0 koodi numero E N Z') koordinaatteja edeltävä numero. Korkeus on "
        "koordinaattien jälkeinen luku. Pisteet tallennetaan kiintopisteiden joukkoon luokalla "
        f"'{hk.OMA_KIINTOPISTE_LUOKKA}', ja haku löytää ne MML:n pisteiden rinnalta."
    )
    oma_tiedosto = st.file_uploader("Kiintopisteet tekstitiedostona", type=["txt", "csv", "krd"],
                                   key="oma_kp_tiedosto")
    if oma_tiedosto is not None:
        raaka = oma_tiedosto.getvalue()
        try:
            teksti = raaka.decode("utf-8")
        except UnicodeDecodeError:
            teksti = raaka.decode("latin-1")
        omat_pisteet, ohitetut = hk.jasenna_kiintopiste_txt(teksti)
        st.write(f"Tunnistettiin **{len(omat_pisteet)}** kiintopistettä, **{len(ohitetut)}** riviä ohitettiin.")
        if omat_pisteet:
            st.dataframe(
                [{"Tunnus": p["tunnus"], "Koodi": p["koodi"], "N": p["n"], "E": p["e"], "Korkeus": p["korkeus"]}
                 for p in omat_pisteet],
                width="stretch", hide_index=True,
            )
            tunnukset = collections.Counter(p["tunnus"] for p in omat_pisteet)
            kahdesti = [t for t, maara in tunnukset.items() if maara > 1]
            if kahdesti:
                st.info(f"{len(kahdesti)} tunnusta esiintyy useammin kuin kerran (esim. "
                        f"{', '.join(kahdesti[:5])}). Kaikki pisteet tallennetaan -- haku tehdään sijainnin mukaan.")
            ulkona = [p["tunnus"] for p in omat_pisteet if not hk.on_helsingin_alueella(p["e"], p["n"])]
            if ulkona:
                st.warning(f"{len(ulkona)} pistettä on Helsingin alueen ulkopuolella "
                           f"(esim. {', '.join(ulkona[:5])}). Tarkista koordinaatisto.")
        if ohitetut:
            with st.expander("Ohitetut rivit (ei tunnistettu N- ja E-koordinaattia)"):
                st.dataframe([{"Rivi": nro, "Sisältö": rivi} for nro, rivi in ohitetut],
                             width="stretch", hide_index=True)
        if omat_pisteet and st.button("Tallenna kiintopisteet kantaan", key="oma_kp_tallenna"):
            try:
                maara = hk.tallenna_omat_kiintopisteet(omat_pisteet, hk.DB_CONN)
                st.success(f"{maara} kiintopistettä tallennettu kantaan.")
            except Exception as e:
                st.error(f"Tallennus epäonnistui: {e}")

    st.markdown("---")
    vahvistus_omat = st.checkbox("Vahvistan: poista kaikki omat (tiedostosta tuodut) kiintopisteet kannasta",
                                 key="oma_kp_poisto_vahvistus")
    if st.button("Poista omat kiintopisteet", key="oma_kp_poista"):
        if not vahvistus_omat:
            st.warning("Rastita vahvistus ennen poistoa.")
        else:
            maara = hk.poista_omat_kiintopisteet(hk.DB_CONN)
            st.success(f"{maara} omaa kiintopistettä poistettu. MML:n kiintopisteet jäivät ennalleen.")


# ---------------------------------------------------------------------------
# JobXML-tiedoston tuonti + raportti
# ---------------------------------------------------------------------------
st.divider()
st.header("Tuo omat mittaukset (JobXML)")
st.caption(
    "Raahaa JobXML (.jxl/.xml) -tiedosto tähän. Ohjelma lukee "
    "koko työn, näyttää kattavan raportin (työaika, asemapisteiden luotettavuus, "
    "MML:n 2x-säännön ylitykset, hylätyt pisteet) ja voit tallentaa mitatut pisteet "
    "kantaan."
)

# HUOM: tiedoston lataus ja jäsennys tehdään ENSIN, jotta kiinteistötunnus
# voidaan ehdottaa automaattisesti mitattujen pisteiden sijainnin perusteella
# ennen kuin käyttäjä valitsee/kirjoittaa tunnuksen.
ladattu_tiedosto = st.file_uploader("Raahaa tai valitse JobXML-tiedosto (.jxl / .xml)", type=["jxl", "xml"],
                                     key="jobxml_tiedosto")

raportti, kaikki_pisteet, hylatyt = None, [], []
ehdotettu_tunnus, ehdotuksen_osumat, ehdotuksen_pisteita_mukana = None, {}, 0
ehdotuksen_virhe = None

if ladattu_tiedosto is not None:
    raaka_bytes = ladattu_tiedosto.getvalue()

    try:
        raportti, kaikki_pisteet, hylatyt = _ajastettu("JobXML:n jäsennys", jx.jasenna_tyo, raaka_bytes,
                                                      lahdetiedosto=ladattu_tiedosto.name)
    except Exception as e:
        st.error(f"Tiedoston jäsennys epäonnistui: {e}")
        raportti, kaikki_pisteet, hylatyt = None, [], []

    if raportti:
        ehdotus_avain = f"kiinteisto_ehdotus_{ladattu_tiedosto.name}_{ladattu_tiedosto.size}"
        if ehdotus_avain not in st.session_state:
            try:
                with st.spinner("Tunnistetaan kiinteistöä automaattisesti mitatuista pisteistä..."):
                    tulos = _ajastettu("kiinteistön tunnistus (MML)", hk.tunnista_kiinteisto_pisteparvesta,
                                    kaikki_pisteet, hk.MML_API_KEY)
                st.session_state[ehdotus_avain] = (tulos[0], tulos[1], tulos[2], None)
                # Ehdotus kirjoitetaan suoraan tekstikentän session_state-avaimeen
                # ennen kuin widget luodaan alempana (text_input:in value= toimii vain
                # widgetin ensimmäisellä luonnilla). Vain tälle tiedostolle ensimmäisen
                # kerran, jottei käyttäjän oma muokkaus ylikirjoitu.
                edellinen_arvo = st.session_state.get("jobxml_tunnus", "")
                edellinen_auto_arvo = st.session_state.get("_jobxml_tunnus_auto", "")
                if tulos[0] and edellinen_arvo == edellinen_auto_arvo:
                    st.session_state["jobxml_tunnus"] = tulos[0]
                    st.session_state["_jobxml_tunnus_auto"] = tulos[0]
            except Exception as e:
                st.session_state[ehdotus_avain] = (None, {}, 0, str(e))
        (ehdotettu_tunnus, ehdotuksen_osumat,
         ehdotuksen_pisteita_mukana, ehdotuksen_virhe) = st.session_state[ehdotus_avain]

def _seinalinjan_kantakartta(pisteet):
    """Helsingin kantakartan rakennukset seinälinjan pisteiden ympäriltä (5 m marginaali).
    Haku tehdään kerran aluetta kohden ja pidetään istunnossa. Palauttaa
    (kantakartta tai None, virheteksti tai None, onko Helsingissä)."""
    sl_pisteet = sl.seinalinjan_pisteet(pisteet)
    if not sl_pisteet:
        return None, None, False
    es, ns = [p["e"] for p in sl_pisteet], [p["n"] for p in sl_pisteet]
    if not hk.on_helsingin_alueella(sum(es) / len(es), sum(ns) / len(ns)):
        return None, None, False
    bbox = (round(min(es) - 5, 1), round(min(ns) - 5, 1), round(max(es) + 5, 1), round(max(ns) + 5, 1))
    valimuisti = st.session_state.setdefault("_kantakartta_valimuisti", {})
    if bbox not in valimuisti:
        try:
            valimuisti[bbox] = hk.rakennusten_renkaat(
                _ajastettu("kantakartan rakennukset (kartta.hel.fi)", hk.hae_helsinki_rakennukset, bbox))
        except Exception as e:
            return None, str(e), True   # epäonnistunutta hakua ei jätetä muistiin
    return valimuisti[bbox] or None, None, True


def _seinalinjan_muokkaukset(raaka_bytes):
    """Tiedoston seinälinjan käsin tehdyt muokkaukset istunnossa: {"pohja": automaattisen viivan
    tunniste, "muokkaukset": [...]} (seinalinja.sovella_muokkaukset)."""
    avain = "_sl_muokkaukset_" + hashlib.sha1(raaka_bytes).hexdigest()
    return st.session_state.setdefault(avain, {"pohja": None, "muokkaukset": []})


def _seinalinjan_muokkaus(sl_tulos, tila, pisteet, valittu, helsinki):
    """Muokkauskartta (seinalinjan_muokkain), Kumoa/Palauta ja suorakulmainen mittaus."""
    kohteet = slm.napsahduspisteet(jx.pisteet_tallennettavaksi(pisteet))
    st.caption("Raahaa kärkeä hiirellä: se napsahtaa mitattuun pisteeseen tai toisen viivan kärkeen, kun se on "
               "lähellä (kärki muuttuu vihreäksi). Klikkaa viivaa = uusi kärki, oikea klikkaus viivaan = poista "
               "jana. Tuplaklikkaa (tai oikea klikkaus) kärkeä = poista kärki. Punainen kärki = laskettu kulma, "
               "oranssi = käsin siirretty. Uuden viivan saa kartan vasemman yläkulman napista ✏ Uusi viiva. "
               "Taustakartan voi vaihtaa oikeasta yläkulmasta.")
    tapahtuma = slm.nayta(sl_tulos, kohteet, api_key=hk.MML_API_KEY, helsinki=helsinki, valittu=valittu)
    if tapahtuma:
        try:
            uusia = sum(1 for m in tila["muokkaukset"] if m["tyyppi"] == "uusi_viiva" and m["nimi"].startswith("Uusi"))
            tila["muokkaukset"].append(slm.muokkaukseksi(tapahtuma, sl_tulos, kohteet, f"Uusi viiva {uusia + 1}"))
        except Exception as e:
            st.error(f"Muokkausta ei voitu tehdä: {e}")
        else:
            st.rerun()
    napit = st.columns([1, 1, 3])
    if napit[0].button("Kumoa viimeisin", disabled=not tila["muokkaukset"], key="sl_kumoa"):
        tila["muokkaukset"].pop()
        st.rerun()
    if napit[1].button("Palauta automaattinen viiva", disabled=not tila["muokkaukset"], key="sl_palauta"):
        tila["muokkaukset"].clear()
        st.rerun()
    if tila["muokkaukset"]:
        st.caption("Muokkaukset: " + "; ".join(slm.kuvaus(m) for m in tila["muokkaukset"]))

    with st.container(border=True):
        st.markdown("**Poista jana**")
        st.caption("Suljettu viiva aukeaa poistetun janan kohdalta, avoin viiva katkeaa kahdeksi viivaksi. "
                   "Kartalla saman saa oikealla klikkauksella viivaan.")
        sarakkeet = st.columns([2, 3, 1])
        viivanimet = [v["nimi"] for v in sl_tulos["viivat"]]
        jv = sarakkeet[0].selectbox("Viiva", viivanimet,
                                    index=viivanimet.index(valittu) if valittu in viivanimet else 0, key="sl_jana_viiva")
        v = next(x for x in sl_tulos["viivat"] if x["nimi"] == jv)
        n = len(v["karjet"])
        janat = [f"kärki {i + 1} ({v['karjet'][i].get('nimi')}) – kärki {(i + 1) % n + 1} "
                 f"({v['karjet'][(i + 1) % n].get('nimi')})" for i in range(n if v["suljettu"] else n - 1)]
        jana = sarakkeet[1].selectbox("Jana", janat, key="sl_jana_jana")
        sarakkeet[2].write("")
        if sarakkeet[2].button("Poista jana", key="sl_jana_poista", disabled=not janat):
            tila["muokkaukset"].append({"tyyppi": "poista_jana", "viiva": jv, "jana": janat.index(jana)})
            st.rerun()

    with st.container(border=True):
        st.markdown("**Suorakulmainen mittaus**")
        st.caption("A ja B = mitattu piste tai viivan kärki. a-mitta pitkin linjaa A→B pisteestä A, b-mitta "
                   "kohtisuoraan: + oikealle (A:sta B:hen katsottuna), − vasemmalle.")
        valinnat = {f"Piste {nimi} ({koodi or '-'})": (e, n, z, str(nimi)) for nimi, koodi, e, n, z in kohteet}
        for v in sl_tulos["viivat"]:
            for j, k in enumerate(v["karjet"]):
                valinnat[f"{v['nimi']}: kärki {j + 1} ({k.get('nimi')})"] = (k["e"], k["n"], k.get("z"), None)
        nimet = list(valinnat)
        if len(nimet) < 2:
            st.caption("Pisteitä on liian vähän.")
            return
        sarakkeet = st.columns(2)
        a_nimi = sarakkeet[0].selectbox("Piste A", nimet, key="sl_suora_a")
        b_nimi = sarakkeet[1].selectbox("Piste B", nimet, index=1, key="sl_suora_b")
        toiminto = st.radio("Toiminto", ["Uusi kärki viivaan", "Uusi viiva A→B siirrettynä b-mitalla"],
                            horizontal=True, key="sl_suora_toiminto")
        sarakkeet = st.columns(2)
        a_mitta = sarakkeet[0].number_input("a-mitta (m)", value=0.0, step=0.01, format="%.3f", key="sl_suora_amitta",
                                            disabled=toiminto != "Uusi kärki viivaan")
        b_mitta = sarakkeet[1].number_input("b-mitta (m)", value=0.0, step=0.01, format="%.3f", key="sl_suora_bmitta")
        A, B = valinnat[a_nimi], valinnat[b_nimi]
        try:
            if toiminto == "Uusi kärki viivaan":
                e, n = sl.suorakulmainen_piste(A[:2], B[:2], a_mitta, b_mitta)
                st.caption(f"Laskettu piste: E {e:.3f}  N {n:.3f}")
                viivanimet = [v["nimi"] for v in sl_tulos["viivat"]]
                sarakkeet = st.columns(2)
                kohde = sarakkeet[0].selectbox("Viiva", viivanimet,
                                               index=viivanimet.index(valittu) if valittu in viivanimet else 0,
                                               key="sl_suora_viiva")
                karjet = next(v for v in sl_tulos["viivat"] if v["nimi"] == kohde)["karjet"]
                kohdat = ["alkuun"] + [f"kärjen {j + 1} ({k.get('nimi')}) jälkeen" for j, k in enumerate(karjet)]
                kohta = sarakkeet[1].selectbox("Kohta", kohdat, index=len(kohdat) - 1, key="sl_suora_kohta")
                if st.button("Lisää kärki", key="sl_suora_lisaa"):
                    tila["muokkaukset"].append({"tyyppi": "lisaa", "viiva": kohde, "jalkeen": kohdat.index(kohta) - 1,
                                                "e": round(e, 3), "n": round(n, 3), "z": None,
                                                "nimi": f"a{a_mitta:g} b{b_mitta:g}", "laji": "laskettu"})
                    st.rerun()
            else:
                alku = sl.suorakulmainen_piste(A[:2], B[:2], 0.0, b_mitta)
                loppu = sl.suorakulmainen_piste(A[:2], B[:2], ((B[0] - A[0]) ** 2 + (B[1] - A[1]) ** 2) ** 0.5, b_mitta)
                st.caption(f"Viiva: E {alku[0]:.3f} N {alku[1]:.3f} → E {loppu[0]:.3f} N {loppu[1]:.3f}")
                if st.button("Lisää viiva", key="sl_suora_viiva_lisaa"):
                    uusia = sum(1 for m in tila["muokkaukset"] if m["tyyppi"] == "uusi_viiva")
                    tila["muokkaukset"].append({
                        "tyyppi": "uusi_viiva", "nimi": f"Lisätty viiva {uusia + 1}",
                        "pohja": valittu or sl_tulos["viivat"][0]["nimi"],
                        "karjet": [{"e": round(x, 3), "n": round(y, 3), "z": None, "nimi": f"b{b_mitta:g}",
                                    "laji": "laskettu"} for x, y in (alku, loppu)]})
                    st.rerun()
        except ValueError as e:
            st.warning(str(e))


def _seinalinjan_lidar():
    """Seinälinja-osioon ladatun LiDAR-seinien DXF:n (lidarpipen _seinat.dxf) janat:
    ({"SEINA": [...], "EPAVARMA": [...]} tai None, virheteksti tai None). Luetaan
    session_statesta, koska kokonaiskartta piirretään ennen osiota; tulos pidetään istunnossa."""
    ladattu = st.session_state.get("seinalinja_lidar")
    if ladattu is None:
        return None, None
    sisalto = ladattu.getvalue()
    avain = hashlib.sha1(sisalto).hexdigest()
    valimuisti = st.session_state.setdefault("_lidar_valimuisti", {})
    if avain not in valimuisti:
        polku = os.path.join(tempfile.mkdtemp(), "lidar_seinat.dxf")
        with open(polku, "wb") as f:
            f.write(sisalto)
        try:
            valimuisti.clear()
            valimuisti[avain] = (sl.lue_lidar_dxf(polku), None)
        except Exception as e:
            return None, f"LiDAR-seinien DXF:ää ei voitu lukea ({e})"
    return valimuisti[avain]


jobxml_hakutapa = st.radio(
    "Kiinteistön tunnistustapa mittauksille", ["Kiinteistötunnus", "Osoite"],
    horizontal=True, key="jobxml_hakutapa",
)

if jobxml_hakutapa == "Kiinteistötunnus":
    # HUOM: EI value=-parametria -- arvo tulee session_statesta (asetettu
    # yllä juuri ennen tätä, jos ehdotus löytyi, tai käyttäjän omasta
    # aiemmasta kirjoituksesta). Jos kumpaakaan ei ole, kenttä on tyhjä.
    if "jobxml_tunnus" not in st.session_state:
        st.session_state["jobxml_tunnus"] = st.session_state.get("viimeisin_kiinteistotunnus", "")
    jobxml_tunnus_syote = st.text_input(
        "Kiinteistötunnus, johon mittaukset liittyvät",
        key="jobxml_tunnus",
    )
    if ladattu_tiedosto is not None and raportti:
        if ehdotettu_tunnus:
            osuma_maara = ehdotuksen_osumat.get(ehdotettu_tunnus, 0)
            st.caption(
                f"🔎 Ehdotettu automaattisesti mitattujen pisteiden sijainnin perusteella "
                f"({osuma_maara}/{ehdotuksen_pisteita_mukana} kartoitus-/merkintäpistettä osui "
                f"tälle kiinteistölle) -- tarkista ja korjaa tarvittaessa."
            )
        elif ehdotuksen_virhe:
            st.warning(f"⚠️ Automaattinen kiinteistön tunnistus epäonnistui: {ehdotuksen_virhe}")
        elif ehdotuksen_pisteita_mukana == 0:
            st.caption(
                "ℹ️ Automaattista ehdotusta ei voitu laskea -- tiedostossa ei ollut yhtään "
                "Kartoituspiste/Merkintäpiste/Suunnittelupiste-kategorian pistettä (vain "
                "asema-, liitos- tai korkeuspisteitä), tai kaikki pisteet olivat samoja."
            )
        else:
            st.caption(
                f"ℹ️ Automaattinen tunnistus tarkisti {ehdotuksen_pisteita_mukana} pistettä, "
                "mutta yksikään ei osunut minkään kiinteistön sisään MML:n rajapinnan mukaan "
                "-- anna kiinteistötunnus itse."
            )
    jobxml_osoite_syote = None
    jobxml_kaupunki_syote = None
else:
    col_jo1, col_jo2 = st.columns(2)
    with col_jo1:
        jobxml_osoite_syote = st.text_input("Katuosoite", key="jobxml_osoite", placeholder="esim. Mannerheimintie 1")
    with col_jo2:
        jobxml_kaupunki_syote = st.text_input("Kaupunki", key="jobxml_kaupunki", placeholder="esim. Helsinki")
    jobxml_tunnus_syote = None

if ladattu_tiedosto is not None and raportti:
    st.success(
        f"**{raportti['job_nimi']}** jäsennetty -- "
        f"{sum(raportti['maara'].values())} mitattua pistettä, {raportti['hylatyt_maara']} hylättyä (lasketut pisteet)."
    )

    with st.expander("Tiedoston perustiedot", expanded=True):
        st.write(f"**Koodikirjasto:** {raportti.get('koodikirjasto', '-')}")

    # Helsingin kantakartan rakennukset seinälinjan apuna (järjestys, tarkistus, riskit)
    sl_kantakartta, sl_kantakartta_virhe, sl_helsingissa = None, None, False
    if raportti.get("seinalinja_kaytettavissa"):
        sl_kantakartta, sl_kantakartta_virhe, sl_helsingissa = _seinalinjan_kantakartta(kaikki_pisteet)
    kaytetty_kantakartta = sl_kantakartta if st.session_state.get("seinalinja_kantakartta", True) else None
    # LiDAR-seinät (Seinälinja-osion latauskenttä) myös kokonaiskartan seinälinjaan, jotta viivat ovat samat
    sl_lidar, sl_lidar_virhe = _seinalinjan_lidar() if raportti.get("seinalinja_kaytettavissa") else (None, None)
    sl_lidar_seinat = sl_lidar["SEINA"] if sl_lidar and sl_lidar["SEINA"] else None
    sl_lidar_paatelty = sl_lidar.get("PAATELTY") if sl_lidar else None   # vain järjestyksen apuna

    with st.expander("Kokonaiskartta (kaikki pisteet)", expanded=True):
        try:
            kartan_seinalinja = (jx.muodosta_seinalinja(kaikki_pisteet, kantakartta=kaytetty_kantakartta,
                                                        lidar=sl_lidar_seinat, lidar_paatelty=sl_lidar_paatelty)
                                 if raportti.get("seinalinja_kaytettavissa") else None)
            if kartan_seinalinja:
                kk_tila = _seinalinjan_muokkaukset(raaka_bytes)
                if kk_tila["muokkaukset"] and kk_tila["pohja"] == sl.viivojen_tunniste(kartan_seinalinja):
                    kartan_seinalinja = sl.sovella_muokkaukset(kartan_seinalinja, kk_tila["muokkaukset"])
            kartta = hk.luo_jobxml_interaktiivinen_kartta(kaikki_pisteet, kartan_seinalinja,
                                                          api_key=hk.MML_API_KEY)
            if kartta is not None:
                st.caption("Zoomaa hiirellä tai +/- napeista. Taustakartan ja tasot voi vaihtaa oikeasta yläkulmasta.")
                # returned_objects=[] -> zoomaus ei aja sovellusta uudelleen
                st_folium(kartta, height=600, use_container_width=True, returned_objects=[],
                          key="jobxml_kokonaiskartta")
            else:
                st.caption("Karttaa ei voitu piirtää (koordinaatit puuttuvat kaikilta pisteiltä).")
        except Exception as karttavirhe:
            st.caption(f"Kokonaiskarttaa ei voitu piirtää: {karttavirhe}")

        # PNG tehdään vain pyydettäessä, koska taustakuva haetaan WMS:stä joka kerta.
        if st.button("Luo kokonaiskartta PNG-kuvana"):
            try:
                yk_path = os.path.join(tempfile.mkdtemp(), "yleiskartta.png")
                tulos_polku = jx.piirra_yleiskartta(kaikki_pisteet, yk_path)
                if tulos_polku and os.path.exists(tulos_polku):
                    with open(tulos_polku, "rb") as f:
                        st.download_button("Lataa kokonaiskartta (PNG)", f,
                                           file_name=f"yleiskartta_{raportti['job_nimi']}.png",
                                           mime="image/png")
            except Exception as karttavirhe:
                st.caption(f"PNG-karttaa ei voitu piirtää: {karttavirhe}")

    # Seinälinja näytetään vain, jos tiedostossa on vähintään yksi 8-koodin piste.
    # Näkyvä seinälinja (ja poikkeama LiDARista) tallennetaan kantaan pisteiden kanssa.
    sl_tallennettava = None
    if raportti.get("seinalinja_kaytettavissa"):
        with st.expander("Seinälinja (koodit 8 / 5 / 100)", expanded=True):
            st.caption(
                "8 = viivan alku/loppu, 5 = talon kulma, 100 = piste seinälinjalla (ei kulma). "
                "Yksi 8-piste = suljettu talo, kaksi tai useampi = avoin viiva 8-pisteiden kautta. "
                "Piilossa olevat kulmat lasketaan 100-pisteiden linjojen leikkauksena. "
                "Useampi talo samaan tiedostoon: viivan numero koodin perään (8 2, 5 2, 100 2); "
                "ilman numeroa viiva 1. Kohdekoodin kanssa tyyppi tulee kohdekoodin perään (RAK 8, RAK 5, "
                "RAK 100, RAK 8 2). Eri kohdekoodit (RAK, KATOS) ja rakennetyypit (esim. Sokkeli) ovat eri "
                "viivoja ilman numeroa; pelkkä RAK on tavallinen piste."
            )
            seinalinja_tapa = st.radio(
                "Pisteiden järjestys 8-pisteiden välillä", ["Automaattinen", "Mittausjärjestys", "Lyhin reitti (vanha)"],
                horizontal=True, key="seinalinja_tapa",
            )
            if sl_helsingissa:
                st.checkbox("Käytä kantakarttaa apuna", value=True, key="seinalinja_kantakartta",
                            help="Automaattisessa järjestyksessä: jos järjestystä ei voi päätellä seinälinjoista, "
                                 "se otetaan Helsingin kantakartan talosta, ja poikkeamasta kartan taloon varoitetaan.")
                if sl_kantakartta_virhe:
                    st.caption(f"Kantakartan rakennuksia ei saatu ({sl_kantakartta_virhe}) -- jatketaan ilman niitä.")
            st.file_uploader(
                "LiDAR-seinät (kokeilu): keilauksen _seinat.dxf", type=["dxf"], key="seinalinja_lidar",
                help="Lidar-repon lidarpipen seinälinja-DXF (SEINA-taso). Piilokulman seinän suunta otetaan "
                     "LiDAR-seinästä suoran kulman oletuksen sijaan, suljetusta LiDAR-ääriviivasta saadaan "
                     "järjestys, ja poikkeama LiDARista näkyy kartalla.")
            if sl_lidar_virhe:
                st.error(sl_lidar_virhe)
            try:
                sl_tulos = jx.muodosta_seinalinja(
                    kaikki_pisteet, tapa={"Automaattinen": "lyhin", "Mittausjärjestys": "mittaus"}.get(seinalinja_tapa, "lyhin_vanha"),
                    kantakartta=kaytetty_kantakartta, lidar=sl_lidar_seinat, lidar_paatelty=sl_lidar_paatelty,
                )
                # Käsin tehdyt muokkaukset (muokkauskartta) automaattisen viivan päälle; jos automaattinen
                # viiva muuttuu (järjestys, kantakartta, LiDAR), muokkaukset eivät enää päde
                sl_tila = _seinalinjan_muokkaukset(raaka_bytes)
                sl_pohja = sl.viivojen_tunniste(sl_tulos)
                if sl_tila["pohja"] != sl_pohja:
                    if sl_tila["muokkaukset"]:
                        st.info("Automaattinen seinälinja muuttui (järjestys, kantakartta tai LiDAR), joten käsin "
                                "tehdyt muokkaukset nollattiin.")
                    sl_tila.update(pohja=sl_pohja, muokkaukset=[])
                sl_tulos = sl.sovella_muokkaukset(sl_tulos, sl_tila["muokkaukset"])
                if kaytetty_kantakartta:
                    riskit = sl.kantakartan_riskit(kaytetty_kantakartta, kaikki_pisteet)
                    if riskit:
                        st.info("**Kantakartan talossa huomioitavaa:**\n\n" + "\n".join(f"- {r}" for r in riskit))
                for varoitus in sl_tulos["varoitukset"]:
                    st.warning(varoitus)
                if kaytetty_kantakartta:
                    poikkeama = sl.poikkeama_kantakartasta(sl_tulos, kaytetty_kantakartta)
                    if poikkeama:
                        st.caption(f"Seinälinja poikkeaa kantakartasta keskimäärin "
                                   f"{poikkeama['keskiarvo_m'] * 100:.0f} cm, enimmillään "
                                   f"{poikkeama['suurin_m'] * 100:.0f} cm.")
                sl_poikkeamat_lidar = sl.poikkeamat_lidarista(sl_tulos, sl_lidar_seinat) if sl_lidar_seinat else []
                sl_tallennettava = (sl_tulos, sl_poikkeamat_lidar)
                if sl_lidar:
                    suljettu = bool(sl_lidar_seinat and sl.lidar_aariviivat(sl_lidar_seinat, sl_lidar_paatelty))
                    st.caption(f"LiDAR: {len(sl_lidar['SEINA'])} seinää, {len(sl_lidar['EPAVARMA'])} epävarmaa. "
                               + ("Seinistä syntyi suljettu ääriviiva (järjestyksen apuna)." if suljettu else
                                  "Suljettua ääriviivaa ei syntynyt, joten järjestystä ei oteta LiDARista; "
                                  "piilokulmat ja vertailu toimivat silti."))
                    for p in sl_poikkeamat_lidar:
                        st.caption(f"{p['nimi']}: LiDAR-seinät eivät kata viivaa." if p["keskiarvo_m"] is None else
                                   f"{p['nimi']}: poikkeaa LiDAR-seinistä keskimäärin {p['keskiarvo_m'] * 100:.1f} cm, "
                                   f"enimmillään {p['suurin_m'] * 100:.1f} cm (LiDAR kattaa {p['peitto'] * 100:.0f} % "
                                   "viivasta).")

                tmp_sl_dir = tempfile.mkdtemp()
                sl_nimet = [v["nimi"] for v in sl_tulos["viivat"]]
                sl_valittu = None
                if len(sl_nimet) > 1:
                    sl_valinta = st.radio("Rajaa kartta", ["Kaikki viivat"] + sl_nimet,
                                          horizontal=True, key="seinalinja_rajaus")
                    if sl_valinta != "Kaikki viivat":
                        sl_valittu = sl_valinta
                if st.toggle("Muokkaa viivaa kartalla", key="seinalinja_muokkaa",
                             help="Kärkien raahaus, napsautus mitattuun pisteeseen, uusi kärki, poisto ja "
                                  "suorakulmainen mittaus. Muokattu viiva menee taulukkoon, DXF:ään, PNG:hen ja "
                                  "kantaan."):
                    _seinalinjan_muokkaus(sl_tulos, sl_tila, kaikki_pisteet, sl_valittu, sl_helsingissa)
                else:
                    try:
                        sl_kartta = hk.luo_seinalinja_interaktiivinen_kartta(sl_tulos, api_key=hk.MML_API_KEY,
                                                                              viiva=sl_valittu, lidar=sl_lidar,
                                                                              poikkeamat_lidar=sl_poikkeamat_lidar)
                        if sl_kartta is not None:
                            st.caption("Zoomaa hiirellä tai +/- napeista. Pisteestä saa koordinaatit klikkaamalla.")
                            # returned_objects=[] -> zoomaus ei aja sovellusta uudelleen; avain rajauksen
                            # mukaan, jotta kartta rajataan uudelleen valinnan vaihtuessa
                            st_folium(sl_kartta, height=650, use_container_width=True, returned_objects=[],
                                      key=f"seinalinja_kartta_{sl_valittu}")
                    except Exception as karttavirhe:
                        st.caption(f"Zoomattavaa seinälinjakarttaa ei voitu piirtää ({karttavirhe}).")

                # PNG tehdään vain pyydettäessä, koska taustakuva haetaan WMS:stä joka kerta.
                if st.button("Luo seinälinja PNG-kuvana", key="seinalinja_png"):
                    sl_png_tulos = sl_tulos if sl_valittu is None else sl.rajaa_viivaan(sl_tulos, sl_valittu)
                    sl_kuva = sl.piirra_seinalinja_kartta(
                        sl_png_tulos, os.path.join(tmp_sl_dir, "seinalinja.png"),
                        hae_tausta=lambda bbox: hk.hae_helsinki_kantakartta(bbox, leveys_px=1000, korkeus_px=1000),
                    )
                    with open(sl_kuva, "rb") as f:
                        st.download_button("Lataa seinälinjakuva (PNG)", f,
                                           file_name=f"seinalinja_{raportti['job_nimi']}"
                                                     f"{'' if sl_valittu is None else '_' + sl_valittu.replace(' ', '_')}.png",
                                           mime="image/png")

                st.dataframe(
                    [{"Viiva": viiva["nimi"], "Nimi": k["nimi"], "Laji": k["laji"],
                      "E": round(k["e"], 3), "N": round(k["n"], 3),
                      "Korkeus": round(k["z"], 3) if k["z"] is not None else None}
                     for viiva in sl_tulos["viivat"] for k in viiva["karjet"]],
                    width="stretch",
                )

                sl_dxf = sl.kirjoita_dxf(sl_tulos, os.path.join(tmp_sl_dir, "seinalinja.dxf"))
                with open(sl_dxf, "rb") as f:
                    st.download_button("Lataa seinälinja (DXF)" + (" (muokattu)" if sl_tulos.get("muokattu") else ""), f,
                                       file_name=f"seinalinja_{raportti['job_nimi']}"
                                                 f"{'_muokattu' if sl_tulos.get('muokattu') else ''}.dxf",
                                       mime="application/dxf")
            except Exception as sl_virhe:
                st.error(f"Seinälinjan muodostus epäonnistui: {sl_virhe}")

    with st.expander("Lataukset", expanded=True):
        # PDF tehdään kerran tiedostoa kohden: asemien kartat haetaan WMS:stä
        pdf_valimuisti = st.session_state.setdefault("_pdf_valimuisti", {})
        pdf_avain = hashlib.sha1(raaka_bytes).hexdigest()
        if pdf_avain not in pdf_valimuisti:
            with st.spinner("Tehdään mittausraporttia..."):
                try:
                    pdf_valimuisti.clear()
                    pdf_valimuisti[pdf_avain] = (_ajastettu("mittausraportti (PDF)", mr.tee_pdf, raportti, kaikki_pisteet,
                                                           hylatyt), None)
                except Exception as pdf_virhe:
                    pdf_valimuisti[pdf_avain] = (None, str(pdf_virhe))
        pdf_bytes, pdf_virhe = pdf_valimuisti[pdf_avain]
        if pdf_bytes:
            st.download_button("Lataa mittausraportti (PDF)", pdf_bytes,
                               file_name=f"mittausraportti_{raportti['job_nimi']}.pdf", mime="application/pdf",
                               key="pdf_lataus")
        else:
            st.error(f"Mittausraportin teko epäonnistui: {pdf_virhe}")

        st.markdown("**Pisteet krd-tiedostona**")
        st.caption("Liitospisteet ja mitatut pisteet, kukin nimi kerran (liitospisteestä RTK-mittaus, jos se on). "
                   "Koodista otetaan vain pistetyyppi (esim. 8 1 -> 8, RAK 5 -> 5).")
        krd_col1, krd_col2 = st.columns(2)
        with krd_col1:
            krd_asemat = st.checkbox("Sisällytä asemapisteet", value=False, key="krd_asemapisteet")
        with krd_col2:
            krd_apupisteet = st.checkbox("Sisällytä apupisteet", value=False, key="krd_apupisteet",
                                         help="Kartoituspisteet, joita käytettiin myöhemmin liitospisteinä.")
        # Kirjainkoodit (esim. RAK, LIP) muunnetaan numeroiksi; muokkaukset säilyvät istunnon ajan
        krd_muunnos = st.session_state.setdefault("_krd_koodimuunnos", dict(jx.KRD_KOODIMUUNNOS))
        krd_kirjaimet = jx.krd_kirjainkoodit(kaikki_pisteet, asemapisteet=krd_asemat, apupisteet=krd_apupisteet)
        if krd_kirjaimet:
            st.markdown("**Kirjainkoodien muunnos krd:hen**")
            st.caption("krd:ssä voi olla vain numerokoodeja. Pelkälle kirjainkoodille (esim. RAK) "
                       "kirjoitetaan tämän taulukon numero; muokkaukset säilyvät istunnon ajan.")
            krd_taulu = st.data_editor(
                pd.DataFrame([{"Koodi": k,
                               "KRD-koodi": int(krd_muunnos.get(k, jx.KRD_TUNTEMATON_KOODI)),
                               "Selite": jx.KRD_KOODISELITTEET.get(k, ""), "Pisteitä": n}
                              for k, n in sorted(krd_kirjaimet.items())]),
                column_config={"KRD-koodi": st.column_config.NumberColumn(min_value=0, step=1, format="%d",
                                                                          required=True)},
                disabled=["Koodi", "Selite", "Pisteitä"], hide_index=True, width="stretch",
                key="krd_muunnos_" + "_".join(sorted(krd_kirjaimet)),
            )
            for rivi in krd_taulu.to_dict("records"):
                if pd.notna(rivi["KRD-koodi"]):
                    krd_muunnos[rivi["Koodi"]] = str(int(rivi["KRD-koodi"]))
        krd_rivit, krd_varoitukset = jx.krd_pisteet(kaikki_pisteet, asemapisteet=krd_asemat, apupisteet=krd_apupisteet,
                                                    koodimuunnos=krd_muunnos)
        for varoitus in krd_varoitukset:
            st.caption(varoitus)
        st.download_button(f"Lataa pisteet (krd, {len(krd_rivit)} pistettä)", jx.kirjoita_krd(krd_rivit),
                           file_name=f"{raportti['job_nimi']}.krd", mime="text/plain", key="krd_lataus")

    with st.expander("Aika työmaalla (ensimmäisen ja viimeisen mitatun pisteen välinen aika)", expanded=True):
        if raportti["tyojaksot"]:
            rivit = []
            for j in raportti["tyojaksot"]:
                kesto_s = j["kesto_s"]
                huomautus = "⚠️ hyvin lyhyt jakso (maalämpö?)" if kesto_s < jx.PIENI_TYOJAKSO_VAROITUSRAJA_S else ""
                rivit.append({
                    "Alku": str(j["alku"]), "Loppu": str(j["loppu"]),
                    "Kesto": jx._muotoile_kesto(kesto_s), "Huomautus": huomautus,
                })
            st.dataframe(rivit, width="stretch")
            st.write(f"**Työaika yhteensä:** {jx._muotoile_kesto(raportti['tyoaika_yhteensa_s'])}")
            if len(raportti["tyojaksot"]) > 1:
                st.info(f"Työ jakautui {len(raportti['tyojaksot'])} eri jaksoon (yli 2 h tauko peräkkäisten mittausten välillä).")
        else:
            st.warning("Ei validia mittausdataa työajan laskemiseksi.")

    with st.expander("Pisteiden yhteenveto", expanded=True):
        rivit = [{"Kategoria": k, "Lukumäärä": v} for k, v in raportti["maara"].items()]
        rivit.append({"Kategoria": "Hylätyt (lasketut pisteet)", "Lukumäärä": raportti["hylatyt_maara"]})
        st.dataframe(rivit, width="stretch")
        if raportti["maara"].get("Korkeusliitos"):
            st.caption(
                "'Korkeusliitos' = tunnettu piste (esim. korkomerkki), jota käytettiin "
                "VAIN asemakorkeuden määrittämiseen -- ei aito horisontaalinen liitospiste, eikä "
                "lasketa mukaan sijaintiluokitukseen tai MML:n 2x-sääntöön."
            )
        if raportti.get("kahdesta_kojeasennosta_maara"):
            st.caption(
                f"📐 **{raportti['kahdesta_kojeasennosta_maara']} pistettä** mitattu kahdesta "
                "kojeasennosta (kollimaatiovirheen "
                "kumoamiseksi) -- näiden koordinaatit ovat kojeen laskema keskiarvo, "
                "tarkempi kuin yhden kojeasennon mittaus."
            )

    if raportti["asemapisteet"]:
        with st.expander(f"Asemapisteet ({len(raportti['asemapisteet'])} kpl)", expanded=True):
            for a in raportti["asemapisteet"]:
                st.markdown(f"**{a['nimi']}**")
                col1, col2, col3, col_kartta = st.columns([1, 1, 1, 1.2])
                with col1:
                    se_n = a.get("se_n_m")
                    se_e = a.get("se_e_m")
                    st.write(f"Trimble SE-N: {se_n:.4f} m" if se_n is not None else "Trimble SE-N: -")
                    st.write(f"Trimble SE-E: {se_e:.4f} m" if se_e is not None else "Trimble SE-E: -")
                    if se_n and se_n > jx.SUURI_SE_VAROITUSRAJA_M:
                        st.warning("Poikkeuksellisen suuri keskivirhe (N)")
                    if se_e and se_e > jx.SUURI_SE_VAROITUSRAJA_M:
                        st.warning("Poikkeuksellisen suuri keskivirhe (E)")
                with col2:
                    liitospisteet = a.get("liitospisteet", [])
                    kojeasento_liitospisteet = set(a.get("kojeasento_liitospisteet", []))
                    st.write(f"Liitospisteitä: {len(liitospisteet)}")
                    if kojeasento_liitospisteet:
                        liitos_nayttolista = [
                            f"{x} 📐" if x in kojeasento_liitospisteet else str(x)
                            for x in liitospisteet
                        ]
                        st.write(f"({', '.join(liitos_nayttolista)})")
                        st.caption(f"📐 = mitattu kahdesta kojeasennosta ({len(kojeasento_liitospisteet)} kpl)")
                    else:
                        st.write(f"({', '.join(str(x) for x in liitospisteet)})")
                    korkeusliitokset = a.get("korkeusliitokset", [])
                    if korkeusliitokset:
                        st.caption(f"Korkeusliitokset (vain korkeus): {', '.join(str(x) for x in korkeusliitokset)}")
                    kulmavirheet = a.get("kulmavirheet", [])
                    if kulmavirheet:
                        st.caption("Kulmavirhe:")
                        for kv in kulmavirheet:
                            st.caption(f"  {kv['liitospiste']}: {kv['kulmavirhe_rad']:.6f}° ({kv['kulmavirhe_rad']*3600:.2f}″)")
                with col3:
                    sijainti = a.get("sijainti")
                    if sijainti:
                        st.write(f"Sijaintiluokka: **{sijainti['S']}**")
                        st.write(sijainti["luokka"])
                        st.caption(
                            f"Etäisyys reunasta: {sijainti['etaisyys_m']} m "
                            f"(+ = sisällä, - = ulkona), keskisivu {sijainti['keskisivu_m']} m"
                        )
                    else:
                        st.write("Sijaintiluokitus ei laskettavissa (alle 3 liitospistettä)")
                laatu = a.get("laatu")

                if laatu:
                    st.markdown("---")
                    st.write(
                        f"Asemapisteen kokonaislaatu: "
                        f"{laatu.get('kokonaispiste')} / 100"
                    )
                    st.write(
                        f"Laatuluokka: {laatu.get('luokka')}"
                    )

                    st.caption(
                        f"Liitospisteitä: "
                        f"{laatu.get('liitospisteita')} | "
                        f"PDOP-keskiarvo: "
                        f"{laatu.get('pdop_keskiarvo')} | "
                        f"Huonoin PDOP: "
                        f"{laatu.get('pdop_huonoimmillaan')} | "
                        f"Kulmapeitto: "
                        f"{laatu.get('kulmapeitto_deg')}°"
                    )

                    st.caption(
                        f"RMS-vaakaresiduaali: "
                        f"{laatu.get('rms_residuaali_m')} m | "
                        f"Suurin vaakaresiduaali: "
                        f"{laatu.get('suurin_residuaali_m')} m"
                    )

                    if laatu.get("varoitukset"):
                        for varoitus in laatu["varoitukset"]:
                            st.warning(varoitus)
                with col_kartta:
                    try:
                        tmp_kartta_dir = tempfile.mkdtemp()
                        kartta_path = os.path.join(tmp_kartta_dir, f"asema_{a['nimi']}.png")
                        tulos_polku = _ajastettu(f"asemapistekartta {a['nimi']}", jx.piirra_asemapiste_kartta, a, kartta_path)
                        if tulos_polku and os.path.exists(tulos_polku):
                            st.image(tulos_polku, caption="tähti = asema, sininen = liitospiste, harmaa = korkeuspiste")
                        else:
                            st.caption("Karttaa ei voitu piirtää (koordinaatit puuttuvat).")
                    except Exception as karttavirhe:
                        st.caption(f"Karttaa ei voitu piirtää: {karttavirhe}")
                if a.get("residuaalit"):
                    st.caption("Residuaalit per liitospiste:")
                    st.dataframe(
                        [{"Liitospiste": r["liitospiste"], "ΔN (m)": r["delta_n"], "ΔE (m)": r["delta_e"],
                          "ΔHz (m)": (math.hypot(r["delta_n"], r["delta_e"])
                                      if r["delta_n"] is not None and r["delta_e"] is not None else None)}
                         for r in a["residuaalit"]],
                        width="stretch",
                    )
                st.markdown("---")

    if raportti["varoitukset_2x"]:
        with st.expander(f"⚠️ MML:n 2x-säännön ylitykset ({len(raportti['varoitukset_2x'])} kpl)", expanded=True):
            st.dataframe(raportti["varoitukset_2x"], width="stretch")

    # --- RTK-/GPS-laatutiedot ---
    rtk_laatupisteet = [
        p for p in kaikki_pisteet
        if (
            p.get("pdop") is not None
            or p.get("hdop") is not None
            or p.get("vdop") is not None
            or p.get("satelliitteja") is not None
        )
    ]

    with st.expander(f"GPS-/RTK-laatutiedot ({len(rtk_laatupisteet)} kpl)", expanded=True):
        if rtk_laatupisteet:
            st.dataframe(
                [
                    {
                        "Nimi": p.get("nimi"),
                        "Kategoria": p.get("kategoria"),
                        "Mittaustapa": p.get("mittaustapa"),
                        "PDOP": p.get("pdop"),
                        "HDOP": p.get("hdop"),
                        "VDOP": p.get("vdop"),
                        "Satelliitteja": p.get("satelliitteja"),
                    }
                    for p in rtk_laatupisteet
                ],
                width="stretch",
            )
        else:
            st.warning(
                "Yhtään PDOP-, HDOP-, VDOP- tai satelliittiarvoa ei löytynyt "
                "jäsennetyistä pisteistä. Tämä kertoo, että tieto katoaa vielä "
                "JobXML-jäsennyksessä eikä pelkästään näkymässä."
            )

    if hylatyt:
        with st.expander(f"Hylätyt (lasketut) pisteet ({len(hylatyt)} kpl)"):
            st.dataframe(
                [{"Nimi": h["nimi"], "Koodi": h["koodi"], "Syy": h["syy"]} for h in hylatyt],
                width="stretch",
            )

    with st.expander("Kaikki mitatut pisteet (taulukko)"):
        st.dataframe(
            [{"Nimi": p["nimi"], "Koodi": p["koodi"], "Ominaisuudet": sl.ominaisuudet_tekstina(p),
              "Kategoria": p["kategoria"],
              "Mittaustapa": p.get("mittaustapa"), "N": p["n"], "E": p["e"], "Korkeus": p["korkeus"],
              "2 kojeasentoa": "📐 kyllä" if p.get("kahdesta_kojeasennosta") else ""}
             for p in kaikki_pisteet],
            width="stretch",
        )
        st.caption(
            "HUOM: 'Liitospiste (alkuperäinen RTK-mittaus)' -rivit näytetään läpinäkyvyyden "
            "vuoksi, mutta niitä EI tallenneta kantaan erikseen. 'Korkeuspiste' = piste jota "
            "käytettiin vain aseman korkeuden määritykseen. '2 kojeasentoa' = piste mitattiin "
            "kahdesta kojeasennosta ja koordinaatti on niiden keskiarvo."
        )

    st.divider()
    with st.container():
        st.caption("Tallennus vie kantaan pisteet, mittausraportin (yhteenveto ja PDF) ja asemapisteet"
                   + (" sekä yllä näkyvän seinälinjan (valittu järjestys, kantakartta- ja LiDAR-valinnat)"
                      if sl_tallennettava else "")
                   + ". Saman kiinteistön ja tiedoston aiemmat pisteet, raportti ja asemat"
                   + (" sekä seinälinja" if sl_tallennettava else "") + " korvataan.")
        if st.button("Tallenna mittaukset kantaan"):
            jobxml_tunnus_lopullinen = jobxml_tunnus_syote

            if jobxml_hakutapa == "Osoite":
                if not jobxml_osoite_syote or not jobxml_osoite_syote.strip():
                    st.warning("Anna katuosoite ennen tallennusta.")
                    st.stop()
                with st.spinner("Etsitään kiinteistötunnusta osoitteelle..."):
                    jobxml_tunnus_lopullinen, _, _ = hk.hae_kiinteistotunnus_osoitteella(
                        jobxml_osoite_syote.strip(), (jobxml_kaupunki_syote or "").strip(), hk.MML_API_KEY
                    )
                st.success(f"Osoite tunnistettu kiinteistöksi: **{jobxml_tunnus_lopullinen}**")

            if not jobxml_tunnus_lopullinen or not jobxml_tunnus_lopullinen.strip():
                st.warning("Anna kiinteistötunnus ennen tallennusta.")
            else:
                tallennettavat = jx.pisteet_tallennettavaksi(kaikki_pisteet)
                maara = jx.tallenna_mittaukset_kantaan(jobxml_tunnus_lopullinen.strip(), tallennettavat, hk.DB_CONN,
                                                       raportti)
                viivoja = (jx.tallenna_seinalinjat_kantaan(jobxml_tunnus_lopullinen.strip(), sl_tallennettava[0],
                                                           ladattu_tiedosto.name, hk.DB_CONN, sl_tallennettava[1])
                           if sl_tallennettava else 0)
                asemia = jx.tallenna_raportti_kantaan(jobxml_tunnus_lopullinen.strip(), raportti, kaikki_pisteet,
                                                      hylatyt, pdf_bytes, hk.DB_CONN)
                st.success(
                    f"{maara} pistettä tallennettu kentalla_mitatut_pisteet-tauluun "
                    f"({len(kaikki_pisteet) - len(tallennettavat)} liitospisteen RTK-alkuperäismittausta "
                    "jätettiin pois tuplapisteiden välttämiseksi)"
                    + (f", {viivoja} seinälinjaa seinalinjat-tauluun" if viivoja else "")
                    + f", mittausraportti{'' if pdf_bytes else ' (ilman PDF:ää)'} mittausraportit-tauluun"
                    + f" ja {asemia} asemapistettä asemapisteet-tauluun."
                )


# ---------------------------------------------------------------------------
# Tallennetut mittausraportit
# ---------------------------------------------------------------------------
st.divider()
st.header("Tallennetut mittausraportit")
st.caption("Kantaan tallennettujen mittausten raportit uusin ensin. Tyhjä kiinteistötunnus = 50 uusinta.")
raportti_tunnus = st.text_input("Kiinteistötunnus", key="raportit_tunnus")
if st.button("Hae raportit", key="raportit_hae"):
    st.session_state["_raportit_haku"] = raportti_tunnus.strip() or None
# Lista haetaan joka ajolla kannasta, jotta uudelleentallennetut ja poistetut raportit näkyvät oikein
tallennetut_raportit = None
if "_raportit_haku" in st.session_state:
    try:
        tallennetut_raportit = jx.hae_raportit(hk.DB_CONN, st.session_state["_raportit_haku"])
    except Exception as e:
        st.error(f"Raporttien haku epäonnistui: {e}")
if tallennetut_raportit is not None:
    if not tallennetut_raportit:
        st.info("Ei tallennettuja raportteja.")
    else:
        st.dataframe(
            [{"Kiinteistö": r["kiinteistotunnus"], "Tiedosto": r["lahdetiedosto"], "Työ": r["tyon_nimi"],
              "Mittauspäivä": r["mittauspaiva"], "Asemia": r["asemia"], "Pisteitä": r["mitattuja_pisteita"],
              "Huonoin asema": r["huonoin_laatuluokka"], "Tarkistettavaa": r["tarkistukset"],
              "Tallennettu": r["tallennettu"].strftime("%d.%m.%Y %H:%M") if r["tallennettu"] else None}
             for r in tallennetut_raportit],
            width="stretch",
        )
        valinta = st.selectbox(
            "Lataa raportti", range(len(tallennetut_raportit)), key="raportit_valinta",
            format_func=lambda i: (f"{tallennetut_raportit[i]['kiinteistotunnus']} -- "
                                   f"{tallennetut_raportit[i]['lahdetiedosto']} ({tallennetut_raportit[i]['mittauspaiva']})"))
        valittu_raportti = tallennetut_raportit[min(valinta or 0, len(tallennetut_raportit) - 1)]
        if valittu_raportti["pdf_kt"] is None:
            st.caption("Raportti tallennettiin ilman PDF:ää.")
        else:
            try:
                pdf = jx.hae_raportin_pdf(valittu_raportti["kiinteistotunnus"], valittu_raportti["lahdetiedosto"],
                                          hk.DB_CONN)
            except Exception as e:
                pdf = None
                st.error(f"PDF:n haku epäonnistui: {e}")
            else:
                if pdf is None:
                    st.warning("Raportin PDF:ää ei löytynyt kannasta (raportti on ehkä poistettu).")
            if pdf:
                st.download_button(f"Lataa mittausraportti (PDF, {valittu_raportti['pdf_kt']} kt)", pdf,
                                   file_name=f"mittausraportti_{valittu_raportti['kiinteistotunnus']}_"
                                             f"{os.path.splitext(valittu_raportti['lahdetiedosto'] or 'raportti')[0]}.pdf",
                                   mime="application/pdf", key="raportit_lataus")


# ---------------------------------------------------------------------------
# Tallennettujen JobXML-mittausten poisto kannasta
# ---------------------------------------------------------------------------
st.divider()
st.header("Poista tallennetut mittaukset kannasta")
st.caption(
    "Tietokanta kasvaa jokaisella tuonnilla ja sitä myötä Qgis:ssä näkyvät mittauspisteet. "
    "Pisteiden kanssa poistetaan samat seinälinjat, mittausraportit ja asemapisteet."
    " Tietokantaa ei tyhjennetä automaattisesti (toisin kuin kiintopistehaun "
    "väliaikaistaulut). Tässä voi siivota vanhoja tai virheellisiä tuonteja."
)

poisto_tapa = st.radio(
    "Mitä haluat poistaa?",
    ["Yhden kiinteistön kaikki mittaukset", "Vain yhden JobXML-tiedoston tuomat pisteet", "KOKO taulu (kaikki kiinteistöt)"],
    key="poisto_tapa",
)

if poisto_tapa == "Yhden kiinteistön kaikki mittaukset":
    poisto_tunnus = st.text_input("Kiinteistötunnus, jonka mittaukset poistetaan", key="poisto_tunnus")
    vahvistus = st.checkbox(f"Vahvistan: poista kaikki tallennetut mittaukset kiinteistölle '{poisto_tunnus}'", key="poisto_vahvistus_1")
    if st.button("Poista", key="poista_nappi_1"):
        if not poisto_tunnus.strip():
            st.warning("Anna kiinteistötunnus.")
        elif not vahvistus:
            st.warning("Rastita vahvistus ennen poistoa.")
        else:
            maara, viivoja, raportteja = jx.poista_mittaukset_kannasta(poisto_tunnus.strip(), hk.DB_CONN)
            st.success(f"{maara} pistettä, {viivoja} seinälinjaa ja {raportteja} raporttia poistettu "
                       f"kiinteistöltä {poisto_tunnus.strip()}.")

elif poisto_tapa == "Vain yhden JobXML-tiedoston tuomat pisteet":
    poisto_tiedosto = st.text_input(
        "Lähdetiedoston nimi (esim. torpparimaentie.xml -- sama nimi kuin ladatussa tiedostossa)",
        key="poisto_tiedosto",
    )
    vahvistus2 = st.checkbox(f"Vahvistan: poista kaikki pisteet, jotka tulivat tiedostosta '{poisto_tiedosto}'", key="poisto_vahvistus_2")
    if st.button("Poista", key="poista_nappi_2"):
        if not poisto_tiedosto.strip():
            st.warning("Anna tiedoston nimi.")
        elif not vahvistus2:
            st.warning("Rastita vahvistus ennen poistoa.")
        else:
            maara, viivoja, raportteja = jx.poista_mittaukset_lahdetiedostolla(poisto_tiedosto.strip(), hk.DB_CONN)
            st.success(f"{maara} pistettä, {viivoja} seinälinjaa ja {raportteja} raporttia poistettu "
                       f"tiedostosta {poisto_tiedosto.strip()}.")

else:
    st.warning("Tämä poistaa KAIKKIEN kiinteistöjen KAIKKI tallennetut mittaukset peruuttamattomasti.")
    vahvistus3 = st.checkbox("Vahvistan: tyhjennä kaikki tallennetut mittaukset (pisteet, seinälinjat, "
                             "raportit ja asemapisteet)",
                             key="poisto_vahvistus_3")
    if st.button("Tyhjennä koko taulu", key="poista_nappi_3"):
        if not vahvistus3:
            st.warning("Rastita vahvistus ennen tyhjennystä.")
        else:
            maara, viivoja, raportteja = jx.poista_kaikki_mittaukset(hk.DB_CONN)
            st.success(f"Taulut tyhjennetty -- {maara} pistettä, {viivoja} seinälinjaa ja {raportteja} "
                       "raporttia poistettu.")


if time.time() - _AJON_ALKU > 3.0:
    print(f"Aika: sivun ajo yhteensä {time.time() - _AJON_ALKU:.1f} s", flush=True)
