"""
seinalinjan_muokkain.py -- Seinälinjan muokkauskartta sovellukseen (Streamlitin oma komponentti,
st.components.v2): kärkiä raahataan hiirellä ja ne napsahtavat mitattuun pisteeseen tai toisen viivan
kärkeen, viivaa klikkaamalla tulee uusi kärki, viivan oikea klikkaus poistaa janan ja kärjen oikea klikkaus
poistaa kärjen. Kolmen pisteen tai kärjen tuplaklikkaus peräkkäin täydentää ne suorakulmioksi.

Kartta toimii selaimessa WGS84:ssä (Leaflet samasta CDN:stä kuin foliumin kartat). Muokkaus palaa
Pythonille tapahtumana, ja muokkaukseksi() tekee siitä seinalinja.sovella_muokkaukset()-muokkauksen
EPSG:3879:ssä: napsautetun kärjen koordinaatit otetaan pisteestä sellaisenaan (ei latlon-muunnoksen
pyöristystä), vapaasti raahattu kärki muunnetaan pyprojilla.
"""

import streamlit as st

import hae_kiintopisteet as hk
import seinalinja as sl

LEAFLET = "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist"
NAPSAHDUS_PX = 12   # kärki napsahtaa pisteeseen tätä lähempänä (näytön pikseleinä)

_CSS = """
.slm-kartta { width: 100%; height: 620px; border: 1px solid #ccc; border-radius: 4px; }
.slm-karki { background: #fff; border: 2px solid #000; border-radius: 2px; }
.slm-karki.laskettu { border-color: #d62728; }
.slm-karki.kasin { border-color: #ff7f0e; }
.slm-karki.napsahtaa { background: #2ca02c; border-color: #2ca02c; }
.slm-nimi { background: transparent; border: none; box-shadow: none; font-size: 11px; color: #333;
            padding: 0; text-shadow: 0 0 3px #fff, 0 0 3px #fff; }
.slm-nimi::before { display: none; }
.slm-piirto { background: #fff; padding: 4px; border-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,.3); }
.slm-piirto button { font-size: 13px; margin: 0 2px; padding: 3px 8px; cursor: pointer; }
.slm-piirto .slm-ohje { font-size: 12px; margin: 4px 2px 0; color: #333; max-width: 260px; }
.slm-piirtaa { cursor: crosshair !important; }
.slm-kulma { background: #ff7f0e; color: #fff; border-radius: 50%; font: bold 11px sans-serif;
             text-align: center; line-height: 16px; box-shadow: 0 0 0 2px #fff; }
"""

_JS = """
const LEAFLET = "%(leaflet)s";
const NAPSAHDUS_PX = %(napsahdus)d;
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

// Uuden viivan piirto: nappi kartan kulmassa; klikkaukset lisäävät kärkiä (napsahtavat pisteisiin),
// tuplaklikkaus tai Valmis lopettaa, ensimmäisen kärjen klikkaus sulkee viivan, Esc peruuttaa.
function luoPiirto(L, tila) {
  const { kartta } = tila;
  const taso = L.layerGroup().addTo(kartta);
  const piirto = tila.piirto = { paalla: false, karjet: [] };
  const ohjain = L.control({ position: "topleft" });
  ohjain.onAdd = () => {
    const div = L.DomUtil.create("div", "slm-piirto");
    div.innerHTML = '<button data-t="aloita">✏ Uusi viiva</button>'
      + '<button data-t="jatka" title="Jatka avoimen viivan päätä lähimpään viivaan">⇥ Jatka</button>'
      + '<button data-t="yhdista" title="Yhdistä kaksi avointa viivaa leikkauspisteessä">✕ Yhdistä</button>'
      + '<button data-t="valmis" style="display:none">Valmis</button>'
      + '<button data-t="peruuta" style="display:none">Peruuta</button>'
      + '<div class="slm-ohje" style="display:none"></div>';
    L.DomEvent.disableClickPropagation(div);
    div.querySelector('[data-t="aloita"]').onclick = () => aseta(true);
    div.querySelector('[data-t="jatka"]').onclick = () => aseta("jatka");
    div.querySelector('[data-t="yhdista"]').onclick = () => aseta("yhdista");
    div.querySelector('[data-t="valmis"]').onclick = () => piirto.valmis();
    div.querySelector('[data-t="peruuta"]').onclick = () => aseta(false);
    piirto.div = div;
    return div;
  };
  ohjain.addTo(kartta);

  const OHJEET = {
    piirto: "Klikkaa pisteitä järjestyksessä (napsahtaa pisteeseen). Tuplaklikkaus tai Valmis lopettaa, "
      + "ensimmäisen pisteen klikkaus sulkee viivan, Esc peruuttaa.",
    jatka: "Klikkaa avointa viivaa sen pään läheltä, jota jatketaan. Esc peruuttaa.",
    yhdista: "Klikkaa ensimmäistä avointa viivaa yhdistettävän pään läheltä, sitten toista. Esc peruuttaa.",
  };
  // tila: false, true (uusi viiva), "jatka" tai "yhdista"
  function aseta(t) {
    const paalla = !!t;
    tila.tyhjennaKulmat();
    piirto.paalla = t === true;
    tila.tyokalu = typeof t === "string" ? t : null;
    piirto.valittu = null;
    piirto.karjet = [];
    taso.clearLayers();
    for (const n of ["aloita", "jatka", "yhdista"]) piirto.div.querySelector(`[data-t="${n}"]`).style.display = paalla ? "none" : "";
    piirto.div.querySelector('[data-t="valmis"]').style.display = t === true ? "" : "none";
    piirto.div.querySelector('[data-t="peruuta"]').style.display = paalla ? "" : "none";
    const ohje = piirto.div.querySelector(".slm-ohje");
    ohje.style.display = paalla ? "" : "none";
    ohje.textContent = paalla ? OHJEET[t === true ? "piirto" : t] : "";
    kartta.getContainer().classList.toggle("slm-piirtaa", paalla);
    tila.ryhma.eachLayer((l) => { if (l.dragging) paalla ? l.dragging.disable() : l.dragging.enable(); });
  }
  piirto.aseta = aseta;

  // Jatka / Yhdistä: viivan klikkaus; pää = klikkausta lähempi pää
  tila.tyokaluKlikkaus = (v, ll) => {
    if (v.suljettu) return;
    const p = kartta.latLngToContainerPoint(ll);
    const d = (k) => p.distanceTo(kartta.latLngToContainerPoint(L.latLng(k[0], k[1])));
    const paa = d(v.karjet[0]) <= d(v.karjet[v.karjet.length - 1]) ? "alku" : "loppu";
    if (tila.tyokalu === "jatka") {
      tila.setTriggerValue("muokkaus", { tyyppi: "jatka", viiva: v.nimi, paa });
      aseta(false);
    } else if (!piirto.valittu) {
      piirto.valittu = { viiva: v.nimi, paa };
      const k = paa === "alku" ? v.karjet[0] : v.karjet[v.karjet.length - 1];
      L.circleMarker([k[0], k[1]], { radius: 8, color: "#d62728", fillOpacity: 0.3 }).addTo(taso);
      piirto.div.querySelector(".slm-ohje").textContent = `${v.nimi} (${paa}) valittu. Klikkaa toista viivaa.`;
    } else {
      tila.setTriggerValue("muokkaus", { tyyppi: "leikkaus", viiva1: piirto.valittu.viiva, paa1: piirto.valittu.paa,
                                         viiva2: v.nimi, paa2: paa });
      aseta(false);
    }
  };

  function piirra() {
    taso.clearLayers();
    const ll = piirto.karjet.map((k) => k.ll);
    if (ll.length > 1) L.polyline(ll, { color: "#d62728", weight: 3, dashArray: "6 6" }).addTo(taso);
    for (const p of ll) L.circleMarker(p, { radius: 5, color: "#d62728", fillOpacity: 1 }).addTo(taso);
  }

  piirto.lisaa = (ll, sijainti) => {
    const k = piirto.karjet;
    const p = kartta.latLngToContainerPoint(ll);
    if (k.length >= 3 && p.distanceTo(kartta.latLngToContainerPoint(k[0].ll)) < 3) { piirto.valmis(true); return; }
    if (k.length && p.distanceTo(kartta.latLngToContainerPoint(k[k.length - 1].ll)) < 3) return;  // tuplaklikkaus
    k.push({ ll, sijainti });
    piirra();
  };

  piirto.valmis = (suljettu = false) => {
    if (piirto.karjet.length >= 2) {
      tila.setTriggerValue("muokkaus", { tyyppi: "uusi_viiva", suljettu,
                                         karjet: piirto.karjet.map((k) => k.sijainti) });
    }
    aseta(false);
  };

  kartta.on("click", (e) => { if (piirto.paalla) piirto.lisaa(...tila.piirtokohta(e.latlng)); });
  kartta.on("dblclick", (e) => { if (piirto.paalla) { L.DomEvent.stop(e); piirto.valmis(); } });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (piirto.paalla || tila.tyokalu) aseta(false); else tila.tyhjennaKulmat();
  });
}

// Suorakulmio kartalta: kolmen pisteen tai kärjen tuplaklikkaus peräkkäin (saman uudelleen = valinta pois,
// Esc tyhjentää). Kolmas valinta lähettää kulmat Pythonille (suorakulmion_neljas laskee neljännen).
function luoKulmavalinta(L, tila) {
  const taso = L.layerGroup().addTo(tila.kartta);
  tila.kulmat = [];
  const ohje = () => tila.piirto.div.querySelector(".slm-ohje");
  function piirra() {
    taso.clearLayers();
    tila.kulmat.forEach((k, i) => L.marker(k.ll, { icon: L.divIcon({ className: "slm-kulma", iconSize: [16, 16],
                                                                      html: String(i + 1) }), interactive: false })
      .addTo(taso));
    const o = ohje();
    if (tila.piirto.paalla || tila.tyokalu) return;
    o.style.display = tila.kulmat.length ? "" : "none";
    o.textContent = tila.kulmat.length
      ? `Suorakulmio: ${tila.kulmat.length}/3 kulmaa. Tuplaklikkaa seuraavaa kulmaa (sama uudelleen = pois, Esc = tyhjennä).`
      : "";
  }
  tila.tyhjennaKulmat = () => { tila.kulmat = []; piirra(); };
  tila.valitseKulma = (ll, sijainti) => {
    if (tila.piirto.paalla || tila.tyokalu) return;
    const avain = `${ll.lat.toFixed(7)},${ll.lng.toFixed(7)}`;
    const i = tila.kulmat.findIndex((k) => k.avain === avain);
    if (i >= 0) tila.kulmat.splice(i, 1); else tila.kulmat.push({ ll, sijainti, avain });
    if (tila.kulmat.length === 3) {
      const kulmat = tila.kulmat.map((k) => k.sijainti);
      tila.kulmat = [];
      piirra();
      tila.setTriggerValue("muokkaus", { tyyppi: "suorakulmio", kulmat });
      return;
    }
    piirra();
  };
}

export default async function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const L = await lataaLeaflet();

  // Kartta säilyy säiliössä uudelleenpiirroissa (näkymä ja taustakartan valinta pysyvät)
  let tila = parentElement.__slm;
  if (!tila) {
    const div = document.createElement("div");
    div.className = "slm-kartta";
    parentElement.appendChild(div);
    const kartta = L.map(div, { maxZoom: 22, doubleClickZoom: false, zoomSnap: 0.5 });
    const taustat = {};
    for (const t of data.taustat) {
      const taso = t.wms
        ? L.tileLayer.wms(t.url, { layers: t.wms, format: "image/png", version: "1.3.0", maxZoom: 22,
                                   attribution: t.attr })
        : L.tileLayer(t.url, { maxZoom: 22, maxNativeZoom: t.maxNative || 19, attribution: t.attr });
      taustat[t.nimi] = taso;
      if (t.oletus) taso.addTo(kartta);
    }
    L.control.layers(taustat, {}, { collapsed: true }).addTo(kartta);
    L.control.scale({ imperial: false }).addTo(kartta);
    const ryhma = L.layerGroup().addTo(kartta);
    tila = parentElement.__slm = { kartta, ryhma, rajattu: null };
    luoPiirto(L, tila);
    luoKulmavalinta(L, tila);
  }
  const { kartta, ryhma } = tila;
  ryhma.clearLayers();
  tila.setTriggerValue = setTriggerValue;

  const pisteet = data.pisteet;   // [lat, lon, nimi, koodi]
  // Napsahduskohteet: mitatut pisteet ja kaikkien viivojen kärjet
  const kohteet = pisteet.map((p, i) => ({ ll: L.latLng(p[0], p[1]), piste: i }));
  data.viivat.forEach((v) => v.karjet.forEach((k, j) =>
    kohteet.push({ ll: L.latLng(k[0], k[1]), viiva: v.nimi, karki: j })));

  function lahin(ll, ohita) {
    const p = kartta.latLngToContainerPoint(ll);
    let paras = null, etaisyys = NAPSAHDUS_PX;
    for (const k of kohteet) {
      if (ohita && k.viiva === ohita.viiva && k.karki === ohita.karki) continue;
      const d = p.distanceTo(kartta.latLngToContainerPoint(k.ll));
      if (d < etaisyys) { etaisyys = d; paras = k; }
    }
    return paras;
  }

  function sijainti(ll, ohita) {
    const k = lahin(ll, ohita);
    if (!k) return { lat: ll.lat, lon: ll.lng };
    return k.piste !== undefined ? { piste: k.piste } : { kohde_viiva: k.viiva, kohde_karki: k.karki };
  }
  // Piirtotilan klikkaus: [näytettävä sijainti, sijainti Pythonille]; napsahtaa lähimpään kohteeseen
  tila.piirtokohta = (ll) => {
    const k = lahin(ll);
    return [k ? k.ll : ll, sijainti(ll)];
  };

  pisteet.forEach((p, i) => {
    const laskettu = p[3] === LASKETTU_KOODI;   // suorakulmaisella mittauksella laskettu piste
    L.circleMarker([p[0], p[1]], { radius: laskettu ? 5 : 4, color: laskettu ? "#d62728" : "#1f77b4", weight: 1,
                                   fillOpacity: 0.9 })
      .bindTooltip(String(p[2]), { permanent: true, direction: "right", className: "slm-nimi", offset: [4, 0] })
      .on("click", (e) => {
        if (!tila.piirto.paalla) return;
        L.DomEvent.stop(e);
        tila.piirto.lisaa(L.latLng(p[0], p[1]), { piste: i });
      })
      .on("dblclick", (e) => { L.DomEvent.stop(e); tila.valitseKulma(L.latLng(p[0], p[1]), { piste: i }); })
      .addTo(ryhma);
  });

  const kaikki = [];
  for (const v of data.viivat) {
    const muokattava = !data.valittu || data.valittu === v.nimi;
    const viiva = L.polyline(v.piirto, { color: muokattava ? "#000" : "#888", weight: muokattava ? 3 : 2 })
      .bindTooltip(v.nimi).addTo(ryhma);
    v.piirto.forEach((q) => kaikki.push(q));
    if (!muokattava) continue;
    // Klikatun kohdan jana (kärjestä i seuraavaan)
    const lahinJana = (ll) => {
      const p = kartta.latLngToContainerPoint(ll);
      const n = v.karjet.length, janoja = v.suljettu ? n : n - 1;
      let paras = 0, pienin = Infinity;
      for (let i = 0; i < janoja; i++) {
        const a = kartta.latLngToContainerPoint(L.latLng(v.karjet[i][0], v.karjet[i][1]));
        const b = kartta.latLngToContainerPoint(L.latLng(v.karjet[(i + 1) %% n][0], v.karjet[(i + 1) %% n][1]));
        const d = L.LineUtil.pointToSegmentDistance(p, a, b);
        if (d < pienin) { pienin = d; paras = i; }
      }
      return paras;
    };
    // Klikkaus viivalle: uusi kärki; oikea klikkaus: jana pois
    viiva.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      if (tila.piirto.paalla) { tila.piirto.lisaa(...tila.piirtokohta(e.latlng)); return; }
      if (tila.tyokalu) { tila.tyokaluKlikkaus(v, e.latlng); return; }
      setTriggerValue("muokkaus", { tyyppi: "lisaa", viiva: v.nimi, jalkeen: lahinJana(e.latlng), ...sijainti(e.latlng) });
    });
    viiva.on("contextmenu", (e) => {
      L.DomEvent.stop(e);
      if (tila.piirto.paalla) return;
      setTriggerValue("muokkaus", { tyyppi: "poista_jana", viiva: v.nimi, jana: lahinJana(e.latlng) });
    });
    v.karjet.forEach((k, j) => {
      const luokka = "slm-karki" + (k[3] === "laskettu" ? " laskettu" : k[3] === "käsin" ? " kasin" : "");
      const ikoni = L.divIcon({ className: luokka, iconSize: [12, 12] });
      const m = L.marker([k[0], k[1]], { draggable: true, icon: ikoni, autoPan: true })
        .bindTooltip(`${v.nimi}: ${k[2]}`, { direction: "top", offset: [0, -6] }).addTo(ryhma);
      m.on("drag", (e) => {
        const kohde = lahin(e.latlng, { viiva: v.nimi, karki: j });
        m.getElement().classList.toggle("napsahtaa", !!kohde);
      });
      m.on("dragend", () => {
        const ll = m.getLatLng();
        setTriggerValue("muokkaus", { tyyppi: "siirra", viiva: v.nimi, karki: j,
                                      ...sijainti(ll, { viiva: v.nimi, karki: j }) });
      });
      m.on("dblclick", (e) => {
        L.DomEvent.stop(e);
        if (tila.piirto.paalla) { tila.piirto.valmis(); return; }
        tila.valitseKulma(L.latLng(k[0], k[1]), { kohde_viiva: v.nimi, kohde_karki: j });
      });
      m.on("contextmenu", (e) => {
        L.DomEvent.stop(e);
        if (tila.piirto.paalla) return;
        setTriggerValue("muokkaus", { tyyppi: "poista", viiva: v.nimi, karki: j });
      });
      m.on("click", (e) => {
        if (tila.tyokalu) { L.DomEvent.stop(e); tila.tyokaluKlikkaus(v, L.latLng(k[0], k[1])); return; }
        if (!tila.piirto.paalla) return;
        L.DomEvent.stop(e);
        tila.piirto.lisaa(L.latLng(k[0], k[1]), { kohde_viiva: v.nimi, kohde_karki: j });
      });
      if (tila.piirto.paalla || tila.tyokalu) m.dragging.disable();
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
""" % {"leaflet": LEAFLET, "napsahdus": NAPSAHDUS_PX, "laskettu": sl.LASKETTU_KOODI}

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


def nayta(tulos, kohteet, api_key=None, helsinki=False, valittu=None, key="seinalinjan_muokkain"):
    """Muokkauskartta. tulos = (muokattu) seinälinja, kohteet = napsahduspisteet(). Palauttaa
    muokkaustapahtuman (dict) tai None."""
    latlon = hk._latlon_muunnin()
    data = {
        "viivat": [{"nimi": v["nimi"], "suljettu": v["suljettu"],
                    "karjet": [[*latlon(k["e"], k["n"]), str(k.get("nimi") or ""), k.get("laji")] for k in v["karjet"]],
                    "piirto": [list(latlon(e, n)) for e, n in sl.viivan_pisteet(v)]}
                   for v in tulos["viivat"]],
        "pisteet": [[*latlon(e, n), str(nimi), str(koodi or "")] for nimi, koodi, e, n, _ in kohteet],
        "valittu": valittu,
        "taustat": _taustat(api_key, helsinki),
    }
    tulos_k = _komponentti()(key=key, data=data, height=625, on_muokkaus_change=lambda: None)
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


def muokkaukseksi(tapahtuma, tulos, kohteet, uuden_nimi="Uusi viiva", suorakulmion_nimi="Suorakulmio 1"):
    """Kartan tapahtuma seinalinja.sovella_muokkaukset()-muokkaukseksi EPSG:3879:ssä. uuden_nimi = piirretyn
    uuden viivan nimi, suorakulmion_nimi = kartalta kolmen kulman tuplaklikkauksella täydennetyn nimi."""
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
