"""
seinalinjan_muokkain.py -- Seinälinjan muokkauskartta sovellukseen (Streamlitin oma komponentti,
st.components.v2). Toimii hiirellä, kynällä ja sormella (maastotabletti, esim. Trimble TSC7): kartan
yläpuolen työkalu valitaan napilla, joten oikeaa painiketta, tuplaklikkausta ja näppäimistöä ei tarvita.

- Siirrä: kärkeä raahataan, ja se napsahtaa mitattuun pisteeseen tai toisen viivan kärkeen.
- Lisää kärki: viivan napautus tekee uuden kärjen.
- Poista: kärjen tai janan napautus valitsee sen, ja poisto vahvistetaan.
- Suorakulmio: kolmen pisteen tai kärjen napautus täydentää ne suorakulmioksi.
- Uusi viiva, Jatka ja Yhdistä.
- Mittaa: kahden pisteen tai kärjen etäisyys; Siirrä-tilassa napautus näyttää janan pituuden ja kärjen kulman.
- Sivumitta: suorakulmainen mittaus kartalla (A, B, a- ja b-mitta) = irrallinen laskettu piste.
- Kumoa: viimeisin muokkaus pois.

Hiirellä vanhat pikatoiminnot toimivat edelleen: viivan klikkaus = uusi kärki, oikea klikkaus = poista,
tuplaklikkaus = suorakulmion kulma, Esc = peruuta. Kynällä ja sormella napsahdussäde on isompi.

Kartta toimii selaimessa WGS84:ssä (Leaflet samasta CDN:stä kuin foliumin kartat). Muokkaus palaa
Pythonille tapahtumana, ja muokkaukseksi() tekee siitä seinalinja.sovella_muokkaukset()-muokkauksen
EPSG:3879:ssä: napsautetun kärjen koordinaatit otetaan pisteestä sellaisenaan (ei latlon-muunnoksen
pyöristystä), vapaasti raahattu kärki muunnetaan pyprojilla.
"""

import streamlit as st

import hae_kiintopisteet as hk
import seinalinja as sl

LEAFLET = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist"
NAPSAHDUS_PX = 12        # hiirellä kärki napsahtaa pisteeseen tätä lähempänä (näytön pikseleinä)
NAPSAHDUS_KYNA_PX = 24   # kynällä ja sormella (kärki jää kynän alle, napautus osuu epätarkemmin)

_CSS = """
.slm-kartta { width: 100%; height: min(620px, calc(100vh - 220px)); min-height: 360px; border: 1px solid #ccc;
              border-radius: 4px; touch-action: none; }
.slm-kahva { background: transparent; border: none; }
.slm-karki { position: absolute; left: 8px; top: 8px; width: 12px; height: 12px; box-sizing: border-box;
             background: #fff; border: 2px solid #000; border-radius: 2px; }
.slm-karki.laskettu { border-color: #d62728; }
.slm-karki.kasin { border-color: #ff7f0e; }
.slm-karki.napsahtaa { background: #2ca02c; border-color: #2ca02c; }
.slm-nimi { background: transparent; border: none; box-shadow: none; font-size: 12px; color: #222;
            padding: 0; text-shadow: 0 0 3px #fff, 0 0 3px #fff; }
.slm-nimi::before { display: none; }
.slm-tyokalut { background: #fff; padding: 4px 0 6px; }
.slm-tyokalut button { font-size: 15px; min-height: 44px; min-width: 44px; margin: 2px; padding: 6px 12px;
                       border: 1px solid #999; border-radius: 6px; background: #f6f6f6; color: #111;
                       cursor: pointer; touch-action: manipulation; }
.slm-tyokalut button.paalla { background: #1f77b4; border-color: #1f77b4; color: #fff; font-weight: 600; }
.slm-tyokalut button.vahva { background: #d62728; border-color: #d62728; color: #fff; font-weight: 600; }
.slm-tyokalut button.valmis { background: #2ca02c; border-color: #2ca02c; color: #fff; font-weight: 600; }
/* Ohje ja toimintorivi vievät aina saman tilan: kartta ei hypi kynän alla työkalun vaihtuessa */
.slm-tyokalut .slm-ohje { font-size: 14px; margin: 6px 4px 2px; color: #222; min-height: 2.6em; }
.slm-toiminnot { min-height: 48px; }
.slm-tyokalut button:disabled { opacity: .4; cursor: default; }
.slm-tyokalut button.kumoa { float: right; }
.slm-sivu { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 15px; margin: 0 4px; }
.slm-sivu input { font-size: 16px; width: 90px; min-height: 40px; padding: 4px 8px; border: 1px solid #999;
                  border-radius: 6px; }
.slm-ab { background: #9467bd; color: #fff; border-radius: 50%; font: bold 13px sans-serif; text-align: center;
          line-height: 22px; box-shadow: 0 0 0 2px #fff; }
.slm-piirtaa { cursor: crosshair !important; }
.slm-kulma { background: #ff7f0e; color: #fff; border-radius: 50%; font: bold 14px sans-serif;
             text-align: center; line-height: 22px; box-shadow: 0 0 0 2px #fff; }
.slm-vihje { position: absolute; z-index: 1000; pointer-events: none; background: #2ca02c; color: #fff;
             font: bold 14px sans-serif; padding: 4px 8px; border-radius: 4px; white-space: nowrap;
             transform: translate(-50%, -100%); display: none; }
.slm-kartta .leaflet-bar a { width: 40px; height: 40px; line-height: 40px; font-size: 22px; }
.slm-kartta .leaflet-control-layers-toggle { width: 44px; height: 44px; }
"""

_JS = """
const LEAFLET = "%(leaflet)s";
const NAPSAHDUS_PX = %(napsahdus)d;
const NAPSAHDUS_KYNA_PX = %(napsahdus_kyna)d;
const LASKETTU_KOODI = "%(laskettu)s";

async function lataaLeaflet() {
  if (!document.getElementById("slm-leaflet-css")) {
    const css = document.createElement("link");
    css.id = "slm-leaflet-css"; css.rel = "stylesheet"; css.href = LEAFLET + "/leaflet.css";
    document.head.appendChild(css);
  }
  if (!window.__slmLeaflet) window.__slmLeaflet = import(LEAFLET + "/leaflet-src.esm.js");
  return await window.__slmLeaflet;
}

const TYOKALUT = [["siirra", "✋ Siirrä"], ["lisaa", "+ Lisää kärki"], ["poista", "🗑 Poista"],
                  ["suorakulmio", "∟ Suorakulmio"], ["piirra", "✏ Uusi viiva"], ["jatka", "⇥ Jatka"],
                  ["yhdista", "✕ Yhdistä"], ["mittaa", "📏 Mittaa"], ["sivumitta", "⊥ Sivumitta"]];
const OHJEET = {
  siirra: "Raahaa kärkeä: se napsahtaa mitattuun pisteeseen tai toisen viivan kärkeen (vihreä). "
    + "Napautus näyttää kärjen tai viivan tiedot.",
  lisaa: "Napauta viivaa: siihen tulee uusi kärki (napsahtaa lähellä olevaan pisteeseen).",
  poista: "Napauta kärkeä tai janaa, ja vahvista poisto.",
  suorakulmio: "Napauta kolmea pistettä tai kärkeä: neljäs kulma lasketaan (saman napautus = pois).",
  piirra: "Napauta pisteitä järjestyksessä (napsahtaa pisteeseen). Valmis lopettaa, ensimmäisen pisteen "
    + "napautus sulkee viivan.",
  jatka: "Napauta avointa viivaa sen pään läheltä, jota jatketaan lähimpään viivaan.",
  yhdista: "Napauta ensimmäistä avointa viivaa yhdistettävän pään läheltä, sitten toista.",
  mittaa: "Napauta kahta pistettä tai kärkeä: niiden etäisyys (ETRS-GK25).",
  sivumitta: "Suorakulmainen mittaus: napauta pisteet A ja B (linjan suunta A→B), anna a-mitta (pitkin linjaa "
    + "A:sta) ja b-mitta (kohtisuoraan, + oikealle). Uusi piste on irrallinen; yhdistä se viivaan itse.",
};

const mitta = (x) => x.toFixed(3).replace(".", ",");
const etaisyys = (a, b) => Math.hypot(b[0] - a[0], b[1] - a[1]);
// Kärjen kulma (astetta) naapurikärkien välillä tasokoordinaateissa, tai null päätekärjelle
function karjenKulma(v, j) {
  const n = v.karjet.length;
  if (n < 3 || (!v.suljettu && (j === 0 || j === n - 1))) return null;
  const k = (i) => v.karjet[(i + n) %% n], p = k(j), a = k(j - 1), b = k(j + 1);
  const u = [a[4] - p[4], a[5] - p[5]], w = [b[4] - p[4], b[5] - p[5]];
  const c = (u[0] * w[0] + u[1] * w[1]) / (Math.hypot(...u) * Math.hypot(...w));
  return Math.acos(Math.max(-1, Math.min(1, c))) * 180 / Math.PI;
}

// Työkalut kartan yläpuolella; tila.tyokalu = valittu työkalu. Kaikki napautukset kulkevat
// napautus()-funktion kautta, joka etsii kohteen pikseleinä (isompi säde kynällä ja sormella), joten
// pienen kärjen tai ohuen viivan ei tarvitse osua kohdalleen.
function luoTyokalut(L, tila) {
  const { kartta } = tila;
  const taso = L.layerGroup().addTo(kartta);
  // Palkki kartan yläpuolella (ei peitä karttaa pienellä näytöllä)
  const div = document.createElement("div");
  div.className = "slm-tyokalut";
  div.innerHTML = TYOKALUT.map(([t, n]) => `<button data-t="${t}">${n}</button>`).join("")
    + '<div class="slm-ohje"></div><div class="slm-toiminnot">'
    + '<button data-a="valmis" class="valmis">✔ Valmis</button>'
    + '<button data-a="vahvista" class="vahva">Poista valittu</button>'
    + '<button data-a="peruuta">Peruuta</button>'
    + '<span class="slm-sivu" style="display:none">a <input data-i="a" inputmode="decimal" placeholder="0,000"> m'
    + '&nbsp; b <input data-i="b" inputmode="decimal" placeholder="0,000"> m (+ oikealle)'
    + '<button data-a="lisaapiste" class="valmis">Lisää piste</button></span></div>';
  div.insertAdjacentHTML("afterbegin", '<button data-a="kumoa" class="kumoa" title="Kumoa viimeisin muokkaus">'
                                       + "↶ Kumoa</button>");
  for (const b of div.querySelectorAll("[data-t]")) b.onclick = () => aseta(b.dataset.t);
  div.querySelector('[data-a="valmis"]').onclick = () => valmis();
  div.querySelector('[data-a="vahvista"]').onclick = () => { if (tila.valittu) poista(tila.valittu); };
  div.querySelector('[data-a="peruuta"]').onclick = () => aseta("siirra");
  div.querySelector('[data-a="kumoa"]').onclick = () => tila.setTriggerValue("muokkaus", { tyyppi: "kumoa" });
  div.querySelector('[data-a="lisaapiste"]').onclick = () => lisaaSivupiste();
  for (const i of div.querySelectorAll(".slm-sivu input")) i.oninput = () => piirraSivu();
  kartta.getContainer().before(div);
  const nappi = (a) => div.querySelector(`[data-a="${a}"]`);
  const ohje = (teksti) => { div.querySelector(".slm-ohje").textContent = teksti; };
  const laheta = (m) => tila.setTriggerValue("muokkaus", m);

  function aseta(t) {
    tila.tyokalu = t;
    tila.piirto = [];
    tila.valittu = null;
    tila.kulmat = [];
    tila.yhdistettava = null;
    tila.mitattavat = [];
    tila.sivu = [];
    div.querySelector(".slm-sivu").style.display = "none";
    taso.clearLayers();
    for (const b of div.querySelectorAll("[data-t]")) b.classList.toggle("paalla", b.dataset.t === t);
    nappi("valmis").style.display = t === "piirra" ? "" : "none";
    nappi("vahvista").style.display = "none";
    nappi("peruuta").style.display = t === "siirra" ? "none" : "";
    ohje(OHJEET[t]);
    kartta.getContainer().classList.toggle("slm-piirtaa", t !== "siirra");
    for (const m of tila.merkit || []) t === "siirra" ? m.dragging.enable() : m.dragging.disable();
  }
  tila.aseta = aseta;

  function piirraUusi() {
    taso.clearLayers();
    const ll = tila.piirto.map((k) => k.ll);
    if (ll.length > 1) L.polyline(ll, { color: "#d62728", weight: 3, dashArray: "6 6", interactive: false }).addTo(taso);
    for (const p of ll) L.circleMarker(p, { radius: 6, color: "#d62728", fillOpacity: 1, interactive: false }).addTo(taso);
  }

  function piirraKulmat() {
    taso.clearLayers();
    tila.kulmat.forEach((k, i) => L.marker(k.ll, { icon: L.divIcon({ className: "slm-kulma", iconSize: [22, 22],
                                                                    html: String(i + 1) }), interactive: false })
      .addTo(taso));
    ohje(tila.kulmat.length ? `Suorakulmio: ${tila.kulmat.length}/3 kulmaa valittu. Napauta seuraavaa `
                              + "(saman napautus = pois)." : OHJEET.suorakulmio);
  }

  function valmis(suljettu = false) {
    if (tila.piirto.length >= 2) {
      laheta({ tyyppi: "uusi_viiva", suljettu, karjet: tila.piirto.map((k) => k.sijainti) });
    }
    aseta("siirra");
  }

  function poista(kohde) {
    if (kohde.karki !== undefined) laheta({ tyyppi: "poista", viiva: kohde.v.nimi, karki: kohde.karki });
    else laheta({ tyyppi: "poista_jana", viiva: kohde.v.nimi, jana: kohde.jana });
    tila.valittu = null;
    taso.clearLayers();
    nappi("vahvista").style.display = "none";
    ohje(OHJEET.poista);
  }

  // Suorakulmion kulma (työkalu tai hiiren tuplaklikkaus); kolmas lähettää kulmat Pythonille
  function valitseKulma(ll) {
    const k = tila.haku.lahin(ll);
    if (!k) { ohje("Napauta mitattua pistettä tai viivan kärkeä."); return; }
    const avain = `${k.ll.lat.toFixed(7)},${k.ll.lng.toFixed(7)}`;
    const i = tila.kulmat.findIndex((c) => c.avain === avain);
    if (i >= 0) tila.kulmat.splice(i, 1); else tila.kulmat.push({ ll: k.ll, sijainti: tila.haku.kohteenSijainti(k), avain });
    if (tila.kulmat.length === 3) {
      const kulmat = tila.kulmat.map((c) => c.sijainti);
      tila.kulmat = [];
      piirraKulmat();
      laheta({ tyyppi: "suorakulmio", kulmat });
      return;
    }
    piirraKulmat();
  }
  tila.valitseKulma = valitseKulma;

  const merkki = (ll, teksti) => L.marker(ll, { icon: L.divIcon({ className: "slm-ab", iconSize: [22, 22],
                                                                   html: teksti }), interactive: false }).addTo(taso);

  // Mittaa: kaksi napsahduskohdetta; kolmas aloittaa uuden mittauksen
  function mittaa(ll) {
    const k = tila.haku.lahin(ll);
    if (!k) { ohje("Napauta mitattua pistettä tai viivan kärkeä."); return; }
    if (tila.mitattavat.length === 2) tila.mitattavat = [];
    tila.mitattavat.push(k);
    taso.clearLayers();
    const [a, b] = tila.mitattavat;
    merkki(a.ll, "1");
    if (!b) { ohje(`1: ${a.nimi}. Napauta toista pistettä.`); return; }
    merkki(b.ll, "2");
    L.polyline([a.ll, b.ll], { color: "#9467bd", weight: 3, dashArray: "8 6", interactive: false }).addTo(taso);
    ohje(`${a.nimi} → ${b.nimi}: ${mitta(etaisyys(a.en, b.en))} m (ΔE ${mitta(b.en[0] - a.en[0])}, `
         + `ΔN ${mitta(b.en[1] - a.en[1])})`);
  }

  // Sivumitta: A ja B napsahduskohteista, a- ja b-mitta palkista; esikatselu kartalla
  const luku = (nimi) => {
    const t = div.querySelector(`[data-i="${nimi}"]`).value.trim().replace(",", ".");
    return t === "" ? 0 : Number(t);
  };
  function sivupiste() {
    const [A, B] = tila.sivu;
    const pituus = etaisyys(A.en, B.en);
    if (pituus < 1e-6) return null;
    const ue = (B.en[0] - A.en[0]) / pituus, un = (B.en[1] - A.en[1]) / pituus;
    const a = luku("a"), b = luku("b");
    if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
    // seinalinja.suorakulmainen_piste: + oikealle A:sta B:hen katsottuna
    const en = [A.en[0] + a * ue + b * un, A.en[1] + a * un - b * ue];
    // kartalle yhdenmuotoisuusmuunnoksella A:n ja B:n kautta (Mercator on paikallisesti kulmatarkka)
    const crs = kartta.options.crs, pa = crs.project(A.ll), pb = crs.project(B.ll);
    const de = B.en[0] - A.en[0], dn = B.en[1] - A.en[1], qe = en[0] - A.en[0], qn = en[1] - A.en[1];
    const d2 = de * de + dn * dn, zr = (qe * de + qn * dn) / d2, zi = (qn * de - qe * dn) / d2;
    const mx = pb.x - pa.x, my = pb.y - pa.y;
    return { en, a, b, ll: crs.unproject(L.point(pa.x + zr * mx - zi * my, pa.y + zr * my + zi * mx)) };
  }
  function piirraSivu() {
    taso.clearLayers();
    const [A, B] = tila.sivu;
    if (A) merkki(A.ll, "A");
    if (!B) { ohje(A ? `A: ${A.nimi}. Napauta piste B (linjan suunta).` : OHJEET.sivumitta); return; }
    merkki(B.ll, "B");
    L.polyline([A.ll, B.ll], { color: "#9467bd", weight: 2, dashArray: "8 6", interactive: false }).addTo(taso);
    const p = sivupiste();
    if (!p) { ohje("Tarkista mitat (esim. 1,25)." + (etaisyys(A.en, B.en) < 1e-6 ? " A ja B ovat samassa kohdassa." : ""));
              return; }
    L.circleMarker(p.ll, { radius: 7, color: "#d62728", weight: 3, fillOpacity: 0.2, interactive: false }).addTo(taso);
    ohje(`A ${A.nimi} → B ${B.nimi} (${mitta(etaisyys(A.en, B.en))} m). Uusi piste: E ${p.en[0].toFixed(3)} `
         + `N ${p.en[1].toFixed(3)}`);
  }
  function lisaaSivupiste() {
    const p = tila.sivu.length === 2 ? sivupiste() : null;
    if (!p) return;
    const [A, B] = tila.sivu;
    laheta({ tyyppi: "sivumitta", a: tila.haku.kohteenSijainti(A), b: tila.haku.kohteenSijainti(B),
             a_nimi: A.nimi, b_nimi: B.nimi, a_mitta: p.a, b_mitta: p.b });
  }
  function sivumitta(ll) {
    const k = tila.haku.lahin(ll);
    if (!k) { ohje("Napauta mitattua pistettä tai viivan kärkeä."); return; }
    if (tila.sivu.length === 2) tila.sivu = [];     // uusi linja
    tila.sivu.push(k);
    div.querySelector(".slm-sivu").style.display = tila.sivu.length === 2 ? "" : "none";
    piirraSivu();
  }
  tila.piirraSivu = piirraSivu;

  tila.napautus = (ll) => {
    const h = tila.haku;
    const t = tila.tyokalu;
    if (t === "siirra") {
      // Tiedot ja mitat: kärjen kulma, janan pituus
      const k = h.lahinKarki(ll);
      const j = k ? null : h.lahinJana(ll);
      taso.clearLayers();
      if (k) {
        const nimi = k.v.karjet[k.karki][2], kulma = karjenKulma(k.v, k.karki);
        ohje(`${k.v.nimi}: kärki ${k.karki + 1}${nimi ? " (piste " + nimi + ")" : ""}`
             + (kulma === null ? "" : `, kulma ${kulma.toFixed(1).replace(".", ",")}°`) + ". Raahaa siirtääksesi.");
      } else if (j) {
        const kk = j.v.karjet, a = kk[j.jana], b = kk[(j.jana + 1) %% kk.length];
        L.polyline([[a[0], a[1]], [b[0], b[1]]], { color: "#9467bd", weight: 7, opacity: 0.5,
                                                   interactive: false }).addTo(taso);
        ohje(`${j.v.nimi}: jana ${j.jana + 1} (${a[2] || "kärki " + (j.jana + 1)} – `
             + `${b[2] || "kärki " + ((j.jana + 1) %% kk.length + 1)}), pituus ${mitta(etaisyys([a[4], a[5]], [b[4], b[5]]))} m.`);
      } else ohje(OHJEET.siirra);
    } else if (t === "mittaa") {
      mittaa(ll);
    } else if (t === "sivumitta") {
      sivumitta(ll);
    } else if (t === "lisaa") {
      const j = h.lahinJana(ll);
      if (!j) { ohje("Napauta lähempää viivaa."); return; }
      laheta({ tyyppi: "lisaa", viiva: j.v.nimi, jalkeen: j.jana, ...h.sijainti(ll) });
    } else if (t === "poista") {
      const k = h.lahinKarki(ll);
      const kohde = k || h.lahinJana(ll);
      if (!kohde) { ohje("Napauta kärkeä tai janaa."); return; }
      const sama = tila.valittu && tila.valittu.v.nimi === kohde.v.nimi && tila.valittu.karki === kohde.karki
        && tila.valittu.jana === kohde.jana;
      if (sama) { poista(kohde); return; }
      tila.valittu = kohde;
      taso.clearLayers();
      const kk = kohde.v.karjet, n = kk.length;
      if (k) {
        L.circleMarker([kk[k.karki][0], kk[k.karki][1]], { radius: 14, color: "#d62728", weight: 3,
                                                          fillOpacity: 0.25, interactive: false }).addTo(taso);
        ohje(`Poistetaanko ${kohde.v.nimi}: kärki ${k.karki + 1}? Napauta uudelleen tai Poista valittu.`);
      } else {
        const a = kk[kohde.jana], b = kk[(kohde.jana + 1) %% n];
        L.polyline([[a[0], a[1]], [b[0], b[1]]], { color: "#d62728", weight: 9, opacity: 0.6,
                                                   interactive: false }).addTo(taso);
        ohje(`Poistetaanko ${kohde.v.nimi}: jana ${kohde.jana + 1}? Napauta uudelleen tai Poista valittu.`);
      }
      nappi("vahvista").style.display = "";
    } else if (t === "suorakulmio") {
      valitseKulma(ll);
    } else if (t === "piirra") {
      const [nakyva, sijainti] = h.piirtokohta(ll);
      const k = tila.piirto, p = kartta.latLngToContainerPoint(nakyva), r = h.sade();
      if (k.length >= 3 && p.distanceTo(kartta.latLngToContainerPoint(k[0].ll)) < r) { valmis(true); return; }
      if (k.length && p.distanceTo(kartta.latLngToContainerPoint(k[k.length - 1].ll)) < r) return;  // tuplanapautus
      k.push({ ll: nakyva, sijainti });
      piirraUusi();
    } else if (t === "jatka" || t === "yhdista") {
      const j = h.lahinJana(ll, true);
      if (!j) { ohje("Napauta avointa viivaa sen pään läheltä."); return; }
      const v = j.v;
      const p = kartta.latLngToContainerPoint(ll);
      const d = (k) => p.distanceTo(kartta.latLngToContainerPoint(L.latLng(k[0], k[1])));
      const paa = d(v.karjet[0]) <= d(v.karjet[v.karjet.length - 1]) ? "alku" : "loppu";
      if (t === "jatka") {
        laheta({ tyyppi: "jatka", viiva: v.nimi, paa });
        aseta("siirra");
      } else if (!tila.yhdistettava) {
        tila.yhdistettava = { viiva: v.nimi, paa };
        const k = paa === "alku" ? v.karjet[0] : v.karjet[v.karjet.length - 1];
        L.circleMarker([k[0], k[1]], { radius: 12, color: "#d62728", fillOpacity: 0.3, interactive: false }).addTo(taso);
        ohje(`${v.nimi} (${paa}) valittu. Napauta toista viivaa.`);
      } else {
        laheta({ tyyppi: "leikkaus", viiva1: tila.yhdistettava.viiva, paa1: tila.yhdistettava.paa,
                 viiva2: v.nimi, paa2: paa });
        aseta("siirra");
      }
    }
  };

  // Hiiren tuplaklikkaus: piirrossa Valmis, muuten suorakulmion kulma (kynällä työkalut)
  tila.tupla = (ll) => {
    if (tila.tyokalu === "piirra") valmis();
    else if (tila.tyokalu === "siirra" && !tila.kyna) valitseKulma(ll);
  };

  kartta.on("click", (e) => tila.napautus(e.latlng));
  kartta.on("dblclick", (e) => tila.tupla(e.latlng));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") aseta("siirra"); });
  aseta("siirra");
}

export default async function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const L = await lataaLeaflet();

  // Kartta säilyy säiliössä uudelleenpiirroissa (näkymä, taustakartta ja valittu työkalu pysyvät)
  let tila = parentElement.__slm;
  if (!tila) {
    const div = document.createElement("div");
    div.className = "slm-kartta";
    parentElement.appendChild(div);
    // keyboard: false: kartta ei ota fokusta, joten selain ei vieritä sivua kesken napautuksen (kynällä
    // napautus osui muuten ohi, kun kartan alareuna oli näytön alla)
    const kartta = L.map(div, { maxZoom: 22, doubleClickZoom: false, zoomSnap: 0.5, keyboard: false });
    const taustat = {};
    for (const t of data.taustat) {
      const taso = t.wms
        ? L.tileLayer.wms(t.url, { layers: t.wms, format: "image/png", version: "1.3.0", maxZoom: 22,
                                   attribution: t.attr })
        : L.tileLayer(t.url, { maxZoom: 22, maxNativeZoom: t.maxNative || 19, attribution: t.attr });
      taustat[t.nimi] = taso;
      if (t.oletus) taso.addTo(kartta);
    }
    L.control.layers(taustat, {}, { collapsed: true, position: "topright" }).addTo(kartta);
    L.control.scale({ imperial: false }).addTo(kartta);
    // Piilotettu välilehti tai suljettu osio muuttaa säiliön kokoa, jota Leaflet ei huomaa itse
    new ResizeObserver(() => kartta.invalidateSize()).observe(div);
    const ryhma = L.layerGroup().addTo(kartta);
    const vihje = document.createElement("div");
    vihje.className = "slm-vihje";
    kartta.getContainer().appendChild(vihje);
    tila = parentElement.__slm = { kartta, ryhma, vihje, rajattu: null, kyna: false };
    // Viimeisin syötetapa: kynällä ja sormella isompi napsahdussäde, eikä tuplaklikkaus tai pitkä painallus
    // (Windows tekee siitä oikean klikkauksen) tee hiiren pikatoimintoja
    div.addEventListener("pointerdown", (e) => { tila.kyna = e.pointerType !== "mouse"; }, true);
    luoTyokalut(L, tila);
  }
  const { kartta, ryhma } = tila;
  ryhma.clearLayers();
  tila.setTriggerValue = setTriggerValue;
  const laheta = (m) => setTriggerValue("muokkaus", m);

  const pisteet = data.pisteet;   // [lat, lon, nimi, koodi]
  const muokattavat = data.viivat.filter((v) => !data.valittu || data.valittu === v.nimi);
  // Napsahduskohteet: mitatut pisteet ja kaikkien viivojen kärjet
  // en = ETRS-GK25 (mitat), nimi näytetään Mittaa- ja Sivumitta-työkaluissa
  const kohteet = pisteet.map((p, i) => ({ ll: L.latLng(p[0], p[1]), piste: i, en: [p[4], p[5]], nimi: p[2] }));
  data.viivat.forEach((v) => v.karjet.forEach((k, j) =>
    kohteet.push({ ll: L.latLng(k[0], k[1]), viiva: v.nimi, karki: j, en: [k[4], k[5]],
                   nimi: `${v.nimi}: kärki ${j + 1}${k[2] ? " (" + k[2] + ")" : ""}` })));
  const kumoa = tila.kartta.getContainer().previousElementSibling.querySelector('[data-a="kumoa"]');
  kumoa.disabled = !data.kumottavia;

  const sade = () => (tila.kyna ? NAPSAHDUS_KYNA_PX : NAPSAHDUS_PX);
  const px = (ll) => kartta.latLngToContainerPoint(ll);
  const kpx = (k) => px(L.latLng(k[0], k[1]));

  function lahin(ll, ohita) {
    const p = px(ll);
    let paras = null, etaisyys = sade();
    for (const k of kohteet) {
      if (ohita && k.viiva === ohita.viiva && k.karki === ohita.karki) continue;
      const d = p.distanceTo(px(k.ll));
      if (d < etaisyys) { etaisyys = d; paras = k; }
    }
    return paras;
  }
  const kohteenSijainti = (k) => (k.piste !== undefined ? { piste: k.piste } : { kohde_viiva: k.viiva, kohde_karki: k.karki });
  function sijainti(ll, ohita) {
    const k = lahin(ll, ohita);
    return k ? kohteenSijainti(k) : { lat: ll.lat, lon: ll.lng };
  }
  // Viivan v lähin jana (kärjestä i seuraavaan) ja etäisyys pikseleinä
  function janaan(v, ll) {
    const p = px(ll);
    const n = v.karjet.length, janoja = v.suljettu ? n : n - 1;
    let jana = 0, d = Infinity;
    for (let i = 0; i < janoja; i++) {
      const e = L.LineUtil.pointToSegmentDistance(p, kpx(v.karjet[i]), kpx(v.karjet[(i + 1) %% n]));
      if (e < d) { d = e; jana = i; }
    }
    return { v, jana, d };
  }
  function lahinJana(ll, avoimet) {
    let paras = null;
    for (const v of muokattavat) {
      if (v.karjet.length < 2 || (avoimet && v.suljettu)) continue;
      const j = janaan(v, ll);
      if (j.d < Math.max(sade(), 10) && (!paras || j.d < paras.d)) paras = j;
    }
    return paras;
  }
  function lahinKarki(ll) {
    const p = px(ll);
    let paras = null;
    for (const v of muokattavat) v.karjet.forEach((k, j) => {
      const d = p.distanceTo(kpx(k));
      if (d < sade() && (!paras || d < paras.d)) paras = { v, karki: j, d };
    });
    return paras;
  }
  // Piirron napautus: [näytettävä sijainti, sijainti Pythonille]; napsahtaa lähimpään kohteeseen
  const piirtokohta = (ll) => { const k = lahin(ll); return [k ? k.ll : ll, sijainti(ll)]; };
  tila.haku = { lahin, sijainti, kohteenSijainti, lahinJana, lahinKarki, piirtokohta, sade };

  // Pisteet eivät ota napautuksia itse: kartan napautus etsii lähimmän (isompi osuma-alue)
  pisteet.forEach((p) => {
    const laskettu = p[3] === LASKETTU_KOODI;   // suorakulmaisella mittauksella laskettu piste
    L.circleMarker([p[0], p[1]], { radius: laskettu ? 5 : 4, color: laskettu ? "#d62728" : "#1f77b4", weight: 1,
                                   fillOpacity: 0.9, interactive: false })
      .bindTooltip(String(p[2]), { permanent: true, direction: "right", className: "slm-nimi", offset: [4, 0] })
      .addTo(ryhma);
  });

  const kaikki = [];
  tila.merkit = [];
  for (const v of data.viivat) {
    const muokattava = muokattavat.includes(v);
    const viiva = L.polyline(v.piirto, { color: muokattava ? "#000" : "#888", weight: muokattava ? 3 : 2 })
      .bindTooltip(v.nimi).addTo(ryhma);
    v.piirto.forEach((q) => kaikki.push(q));
    if (!muokattava) continue;
    // Hiirellä viivan klikkaus = uusi kärki ja oikea klikkaus = jana pois (kuten ennen); muuten työkalu
    viiva.on("click", (e) => {
      L.DomEvent.stop(e);
      if (tila.tyokalu === "siirra" && !tila.kyna) {
        laheta({ tyyppi: "lisaa", viiva: v.nimi, jalkeen: janaan(v, e.latlng).jana, ...sijainti(e.latlng) });
        return;
      }
      tila.napautus(e.latlng);
    });
    viiva.on("contextmenu", (e) => {
      L.DomEvent.stop(e);
      if (tila.kyna || tila.tyokalu === "piirra") return;
      laheta({ tyyppi: "poista_jana", viiva: v.nimi, jana: janaan(v, e.latlng).jana });
    });
    v.karjet.forEach((k, j) => {
      const luokka = "slm-karki" + (k[3] === "laskettu" ? " laskettu" : k[3] === "käsin" ? " kasin" : "");
      // Kahva 28 px (näkyvä kärki 12 px keskellä): kynällä raahaus alkaa, vaikka ei osu aivan kärkeen
      const ikoni = L.divIcon({ className: "slm-kahva", iconSize: [28, 28], html: `<div class="${luokka}"></div>` });
      const ll = L.latLng(k[0], k[1]);
      const m = L.marker(ll, { draggable: true, icon: ikoni, autoPan: true, keyboard: false })
        .bindTooltip(`${v.nimi}: ${k[2]}`, { direction: "top", offset: [0, -10] }).addTo(ryhma);
      const merkki = () => m.getElement().firstChild;
      // Kynällä ja sormella Leaflet aloittaa kärjen raahauksen lisäksi kartan panoroinnin, jolloin kärki
      // karkaa kynän alta: kartan raahaus pois, kunnes kynä nousee
      // (elementti on olemassa vasta, kun kartalla on näkymä: ensimmäisellä kerralla rajauksen jälkeen)
      const kahva = () => m.getElement().addEventListener("pointerdown", () => {
        if (tila.tyokalu !== "siirra") return;
        kartta.dragging.disable();
        document.addEventListener("pointerup", () => kartta.dragging.enable(), { once: true });
      });
      if (m.getElement()) kahva(); else m.once("add", kahva);
      m.on("dragstart", () => m.closeTooltip());
      m.on("drag", (e) => {
        const kohde = lahin(e.latlng, { viiva: v.nimi, karki: j });
        merkki().classList.toggle("napsahtaa", !!kohde);
        // Napsahduskohde näkyy kynän yläpuolella (kärki itse jää kynän alle)
        const p = px(e.latlng);
        tila.vihje.style.display = kohde ? "block" : "none";
        if (kohde) {
          tila.vihje.textContent = kohde.piste !== undefined ? `→ ${pisteet[kohde.piste][2]}`
            : `→ ${kohde.viiva}: kärki ${kohde.karki + 1}`;
          tila.vihje.style.left = `${p.x}px`;
          tila.vihje.style.top = `${p.y - 30}px`;
        }
      });
      m.on("dragend", () => {
        tila.vihje.style.display = "none";
        laheta({ tyyppi: "siirra", viiva: v.nimi, karki: j, ...sijainti(m.getLatLng(), { viiva: v.nimi, karki: j }) });
      });
      m.on("click", (e) => { L.DomEvent.stop(e); tila.napautus(ll); });
      m.on("dblclick", (e) => { L.DomEvent.stop(e); tila.tupla(ll); });
      m.on("contextmenu", (e) => {
        L.DomEvent.stop(e);
        if (tila.kyna || tila.tyokalu === "piirra") return;
        laheta({ tyyppi: "poista", viiva: v.nimi, karki: j });
      });
      if (tila.tyokalu !== "siirra") m.dragging.disable();
      tila.merkit.push(m);
    });
  }
  // Rajaus aluksi ja kun valittu viiva vaihtuu; muuten näkymä säilyy
  const rajaus = data.valittu || "*";
  if (tila.rajattu !== rajaus && (kaikki.length || pisteet.length)) {
    const alue = kaikki.length ? kaikki : pisteet.map((p) => [p[0], p[1]]);
    kartta.fitBounds(L.latLngBounds(alue).pad(0.15));
    tila.rajattu = rajaus;
  }
  setTimeout(() => kartta.invalidateSize(), 0);
}
""" % {"leaflet": LEAFLET, "napsahdus": NAPSAHDUS_PX, "napsahdus_kyna": NAPSAHDUS_KYNA_PX,
       "laskettu": sl.LASKETTU_KOODI}

_KOMPONENTIT = {}


def _komponentti():
    """Komponentti rekisteröitynä nykyiseen Streamlitin ajoympäristöön (kerran ympäristöä kohden: moduuli
    voi olla jo ladattu, kun ympäristö vaihtuu, esim. testeissä)."""
    from streamlit.runtime import Runtime

    avain = id(Runtime.instance()) if Runtime.exists() else None
    if avain not in _KOMPONENTIT:
        _KOMPONENTIT[avain] = st.components.v2.component("seinalinjan_muokkain", css=_CSS, js=_JS,
                                                          isolate_styles=False)
    return _KOMPONENTIT[avain]


def napsahduspisteet(pisteet, tulos=None):
    """Mitatut pisteet ja seinälinjan (tulos) lasketut pisteet, joihin kärki voi napsahtaa:
    [(nimi, koodi, e, n, korkeus)]; laskettujen koodi on seinalinja.LASKETTU_KOODI."""
    return ([(p.get("nimi"), p.get("koodi"), p["e"], p["n"], p.get("korkeus"))
             for p in pisteet if p.get("e") is not None and p.get("n") is not None]
            + [(p["nimi"], sl.LASKETTU_KOODI, p["e"], p["n"], None) for p in (tulos or {}).get("lasketut_pisteet", [])])


def _taustat(api_key, helsinki):
    """Taustakartat kuten hk._lisaa_taustakartat (oletus Helsingissä kantakartta, muualla MML tai OSM)."""
    oletus = "helsinki" if helsinki else ("taustakartta" if api_key else "osm")
    taustat = [{"nimi": "Helsingin kantakartta", "url": hk.HELSINKI_WMS_URL, "wms": hk.HELSINKI_KANTAKARTTA_LAYER,
                "attr": "© Helsingin kaupunki", "oletus": oletus == "helsinki"},
               {"nimi": "Kantakartta (harmaa)", "url": hk.HELSINKI_WMS_URL,
                "wms": hk.HELSINKI_KANTAKARTTA_HARMAA_LAYER, "attr": "© Helsingin kaupunki", "oletus": False}]
    if api_key:
        for taso, nimi in hk.MML_WMTS_TASOT:
            taustat.append({"nimi": nimi, "url": f"{hk.BASE_KARTTAKUVA_WMTS}/{taso}/default/WGS84_Pseudo-Mercator/"
                                                 f"{{z}}/{{y}}/{{x}}.png?api-key={api_key}",
                            "attr": "© Maanmittauslaitos", "maxNative": 16, "oletus": taso == oletus})
    taustat.append({"nimi": "OpenStreetMap", "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                    "attr": "© OpenStreetMap", "oletus": oletus == "osm"})
    return taustat


def nayta(tulos, kohteet, api_key=None, helsinki=False, valittu=None, kumottavia=0, key="seinalinjan_muokkain"):
    """Muokkauskartta. tulos = (muokattu) seinälinja, kohteet = napsahduspisteet(), kumottavia = muokkausten
    määrä (Kumoa-nappi). Palauttaa muokkaustapahtuman (dict) tai None."""
    latlon = hk._latlon_muunnin()
    data = {
        "viivat": [{"nimi": v["nimi"], "suljettu": v["suljettu"],
                    "karjet": [[*latlon(k["e"], k["n"]), str(k.get("nimi") or ""), k.get("laji"), k["e"], k["n"]]
                               for k in v["karjet"]],
                    "piirto": [list(latlon(e, n)) for e, n in sl.viivan_pisteet(v)]}
                   for v in tulos["viivat"]],
        "pisteet": [[*latlon(e, n), str(nimi), str(koodi or ""), e, n] for nimi, koodi, e, n, _ in kohteet],
        "valittu": valittu,
        "kumottavia": kumottavia,
        "taustat": _taustat(api_key, helsinki),
    }
    tulos_k = _komponentti()(key=key, data=data, height="content", on_muokkaus_change=lambda: None)
    return tulos_k.get("muokkaus") if tulos_k else None


def _3879(lat, lon):
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4326", f"EPSG:{hk.DB_SRID}", always_xy=True).transform(lon, lat)


def _koordinaatit(sijainti, tulos, kohteet):
    """Kartan sijainti (mitattu piste, viivan kärki tai lat/lon) -> {"e", "n", "z", "nimi"} EPSG:3879:ssä."""
    if sijainti.get("piste") is not None:
        nimi, koodi, e, n, z = kohteet[int(sijainti["piste"])]
        return {"e": e, "n": n, "z": z, "nimi": str(nimi),
                "laji": "laskettu" if koodi == sl.LASKETTU_KOODI else "mitattu"}
    if sijainti.get("kohde_viiva") is not None:
        viiva = next(v for v in tulos["viivat"] if v["nimi"] == sijainti["kohde_viiva"])
        k = viiva["karjet"][int(sijainti["kohde_karki"])]
        return {"e": k["e"], "n": k["n"], "z": k.get("z"), "nimi": str(k.get("nimi") or ""), "laji": k.get("laji")}
    e, n = _3879(sijainti["lat"], sijainti["lon"])
    return {"e": round(e, 3), "n": round(n, 3), "z": None, "nimi": None, "laji": None}


def suorakulmio(kulmat, nimi, pohja):
    """Kolmesta kulmasta ({"e", "n", "z", "nimi", "laji"}) suorakulmion muokkaus (seinalinja.sovella_muokkaukset):
    kulmat kehän järjestykseen ja neljäs lasketuksi (seinalinja.suorakulmion_neljas). ValueError, jos kulmissa
    on sama piste kahdesti tai mikään kulma ei ole 90 ± SUORAKULMIO_MAX_KULMA astetta."""
    if len({(round(k["e"], 3), round(k["n"], 3)) for k in kulmat}) < 3:
        raise ValueError("Valitse kolme eri pistettä.")
    r = sl.suorakulmion_neljas(*((k["e"], k["n"]) for k in kulmat))
    karjet = [{"e": kulmat[i]["e"], "n": kulmat[i]["n"], "z": kulmat[i].get("z"), "nimi": kulmat[i].get("nimi"),
               "laji": kulmat[i].get("laji") or "laskettu"} for i in r["jarjestys"]]
    karjet.append({"e": round(r["neljas"][0], 3), "n": round(r["neljas"][1], 3), "z": None, "nimi": "suorakulmio",
                   "laji": "laskettu"})
    return {"tyyppi": "suorakulmio", "nimi": nimi, "pohja": pohja, "karjet": karjet,
            "kulma": r["kulma"], "lavistajaero": r["lavistajaero"]}


def muokkaukseksi(tapahtuma, tulos, kohteet, uuden_nimi="Uusi viiva", suorakulmion_nimi="Suorakulmio 1",
                  pisteen_nimi="L1"):
    """Kartan tapahtuma seinalinja.sovella_muokkaukset()-muokkaukseksi EPSG:3879:ssä. uuden_nimi = piirretyn
    uuden viivan nimi, suorakulmion_nimi = kartalta kolmesta kulmasta täydennetyn nimi, pisteen_nimi =
    Sivumitta-työkalun (suorakulmainen mittaus) laskeman irrallisen pisteen nimi. ("kumoa"-tapahtuman
    käsittelee kutsuja.)"""
    if tapahtuma["tyyppi"] == "sivumitta":
        a = _koordinaatit(tapahtuma["a"], tulos, kohteet)
        b = _koordinaatit(tapahtuma["b"], tulos, kohteet)
        a_mitta, b_mitta = float(tapahtuma["a_mitta"]), float(tapahtuma["b_mitta"])
        e, n = sl.suorakulmainen_piste((a["e"], a["n"]), (b["e"], b["n"]), a_mitta, b_mitta)
        return {"tyyppi": "piste", "nimi": pisteen_nimi, "e": round(e, 3), "n": round(n, 3),
                "a": tapahtuma.get("a_nimi") or a["nimi"], "b": tapahtuma.get("b_nimi") or b["nimi"],
                "a_mitta": a_mitta, "b_mitta": b_mitta}
    if tapahtuma["tyyppi"] == "suorakulmio":
        kulmat = [_koordinaatit(s, tulos, kohteet) for s in tapahtuma["kulmat"]]
        for k, s in zip(kulmat, tapahtuma["kulmat"]):
            k["laji"] = k["laji"] or ("mitattu" if k["nimi"] else "käsin")
            k["nimi"] = k["nimi"] or "kulma"
        pohja = next((s["kohde_viiva"] for s in tapahtuma["kulmat"] if s.get("kohde_viiva")),
                     tulos["viivat"][0]["nimi"] if tulos["viivat"] else None)
        return suorakulmio(kulmat, suorakulmion_nimi, pohja)
    if tapahtuma["tyyppi"] == "uusi_viiva":
        karjet = [_koordinaatit(s, tulos, kohteet) for s in tapahtuma["karjet"]]
        for k in karjet:
            k["laji"] = k["laji"] or ("mitattu" if k["nimi"] else "käsin")
        return {"tyyppi": "uusi_viiva", "nimi": uuden_nimi, "suljettu": bool(tapahtuma.get("suljettu")),
                "pohja": tulos["viivat"][0]["nimi"] if tulos["viivat"] else None, "karjet": karjet}
    if tapahtuma["tyyppi"] in ("jatka", "leikkaus"):
        return {k: tapahtuma[k] for k in ("tyyppi", "viiva", "paa", "viiva1", "paa1", "viiva2", "paa2")
                if k in tapahtuma}
    m = {k: tapahtuma[k] for k in ("tyyppi", "viiva", "karki", "jalkeen", "jana") if k in tapahtuma}
    if m["tyyppi"] in ("poista", "poista_jana"):
        return m
    m.update(_koordinaatit(tapahtuma, tulos, kohteet))
    return m


def kuvaus(m):
    """Muokkaus luettavana rivinä muokkauslistaan."""
    if m["tyyppi"] == "siirra":
        kohde = f"pisteeseen {m['nimi']}" if m.get("nimi") else f"kohtaan E {m['e']:.3f} N {m['n']:.3f}"
        return f"{m['viiva']}: kärki {m['karki'] + 1} siirretty {kohde}"
    if m["tyyppi"] == "lisaa":
        kohde = m.get("nimi") or f"E {m['e']:.3f} N {m['n']:.3f}"
        return f"{m['viiva']}: uusi kärki ({kohde}) kärjen {m['jalkeen'] + 1} jälkeen"
    if m["tyyppi"] == "poista":
        return f"{m['viiva']}: kärki {m['karki'] + 1} poistettu"
    if m["tyyppi"] == "poista_jana":
        return f"{m['viiva']}: jana kärjestä {m['jana'] + 1} seuraavaan poistettu"
    if m["tyyppi"] == "jatka":
        return f"{m['viiva']}: {m['paa']} jatkettu lähimpään viivaan"
    if m["tyyppi"] == "leikkaus":
        if m["viiva1"] == m["viiva2"]:
            return f"{m['viiva1']}: päät yhdistetty leikkauspisteessä (suljettu)"
        return f"{m['viiva1']} ja {m['viiva2']} yhdistetty leikkauspisteessä"
    if m["tyyppi"] == "uusi_viiva":
        return f"{m['nimi']}: uusi {'suljettu ' if m.get('suljettu') else ''}viiva ({len(m['karjet'])} kärkeä)"
    if m["tyyppi"] == "piste":
        return f"laskettu piste {m['nimi']} (A {m['a']}, B {m['b']}, a {m['a_mitta']:g} m, b {m['b_mitta']:g} m)"
    if m["tyyppi"] == "suorakulmio":
        kulma = f" (suora kulma {m['kulma']:.1f}°)" if m.get("kulma") is not None else ""
        return f"{m.get('nimi', 'suorakulmio')}: kolmesta kulmasta täydennetty{kulma}"
    return str(m)
