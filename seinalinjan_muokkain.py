"""
seinalinjan_muokkain.py -- Seinälinjan muokkauskartta sovellukseen (Streamlitin oma komponentti,
st.components.v2): kärkiä raahataan hiirellä ja ne napsahtavat mitattuun pisteeseen tai toisen viivan
kärkeen, viivaa klikkaamalla tulee uusi kärki ja kärjen tuplaklikkaus (tai oikea klikkaus) poistaa sen.

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
"""

_JS = """
const LEAFLET = "%(leaflet)s";
const NAPSAHDUS_PX = %(napsahdus)d;

async function lataaLeaflet() {
  if (!document.getElementById("slm-leaflet-css")) {
    const css = document.createElement("link");
    css.id = "slm-leaflet-css"; css.rel = "stylesheet"; css.href = LEAFLET + "/leaflet.css";
    document.head.appendChild(css);
  }
  if (!window.__slmLeaflet) window.__slmLeaflet = import(LEAFLET + "/leaflet-src.esm.js");
  return await window.__slmLeaflet;
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
  }
  const { kartta, ryhma } = tila;
  ryhma.clearLayers();

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

  for (const p of pisteet) {
    L.circleMarker([p[0], p[1]], { radius: 4, color: "#1f77b4", weight: 1, fillOpacity: 0.9 })
      .bindTooltip(String(p[2]), { permanent: true, direction: "right", className: "slm-nimi", offset: [4, 0] })
      .addTo(ryhma);
  }

  const kaikki = [];
  for (const v of data.viivat) {
    const muokattava = !data.valittu || data.valittu === v.nimi;
    const viiva = L.polyline(v.piirto, { color: muokattava ? "#000" : "#888", weight: muokattava ? 3 : 2 })
      .bindTooltip(v.nimi).addTo(ryhma);
    v.piirto.forEach((q) => kaikki.push(q));
    if (!muokattava) continue;
    // Klikkaus viivalle: uusi kärki lähimmälle janalle
    viiva.on("click", (e) => {
      L.DomEvent.stopPropagation(e);
      const p = kartta.latLngToContainerPoint(e.latlng);
      const n = v.karjet.length, janoja = v.suljettu ? n : n - 1;
      let paras = 0, pienin = Infinity;
      for (let i = 0; i < janoja; i++) {
        const a = kartta.latLngToContainerPoint(L.latLng(v.karjet[i][0], v.karjet[i][1]));
        const b = kartta.latLngToContainerPoint(L.latLng(v.karjet[(i + 1) %% n][0], v.karjet[(i + 1) %% n][1]));
        const d = L.LineUtil.pointToSegmentDistance(p, a, b);
        if (d < pienin) { pienin = d; paras = i; }
      }
      setTriggerValue("muokkaus", { tyyppi: "lisaa", viiva: v.nimi, jalkeen: paras, ...sijainti(e.latlng) });
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
      const poista = (e) => { L.DomEvent.stop(e); setTriggerValue("muokkaus", { tyyppi: "poista", viiva: v.nimi, karki: j }); };
      m.on("dblclick", poista);
      m.on("contextmenu", poista);
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
""" % {"leaflet": LEAFLET, "napsahdus": NAPSAHDUS_PX}

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


def napsahduspisteet(pisteet):
    """Mitatut pisteet, joihin kärki voi napsahtaa: [(nimi, koodi, e, n, korkeus)]."""
    return [(p.get("nimi"), p.get("koodi"), p["e"], p["n"], p.get("korkeus"))
            for p in pisteet if p.get("e") is not None and p.get("n") is not None]


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


def muokkaukseksi(tapahtuma, tulos, kohteet):
    """Kartan tapahtuma seinalinja.sovella_muokkaukset()-muokkaukseksi EPSG:3879:ssä."""
    m = {k: tapahtuma[k] for k in ("tyyppi", "viiva", "karki", "jalkeen") if k in tapahtuma}
    if m["tyyppi"] == "poista":
        return m
    if tapahtuma.get("piste") is not None:
        nimi, _, e, n, z = kohteet[int(tapahtuma["piste"])]
        m.update(e=e, n=n, z=z, nimi=str(nimi))
    elif tapahtuma.get("kohde_viiva") is not None:
        viiva = next(v for v in tulos["viivat"] if v["nimi"] == tapahtuma["kohde_viiva"])
        k = viiva["karjet"][int(tapahtuma["kohde_karki"])]
        m.update(e=k["e"], n=k["n"], z=k.get("z"), nimi=str(k.get("nimi") or ""))
    else:
        e, n = _3879(tapahtuma["lat"], tapahtuma["lon"])
        m.update(e=round(e, 3), n=round(n, 3), z=None, nimi=None)
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
    if m["tyyppi"] == "uusi_viiva":
        return f"{m['nimi']}: uusi viiva ({len(m['karjet'])} kärkeä)"
    return str(m)
