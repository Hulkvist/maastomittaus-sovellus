"""
mittausraportti.py -- JobXML-työn mittausraportti PDF:nä
--------------------------------------------------------
Korvaa Trimble Accessin mittausraportin: samat tiedot (työ, koordinaatisto, kalusto,
liitospisteet, asemapisteet residuaaleineen, mitatut pisteet, raakahavainnot), mutta
kalusto kerran, asemapisteen laatuluokitus ja pieni kartta jokaiselle asemalle.

raportin_sisalto() kokoaa taulukot valmiiksi teksteiksi (testattavissa ilman PDF:ää),
tee_pdf() taittaa ne A4-sivuille (reportlab).
"""

import io
import math
import os
import tempfile
from collections import defaultdict
from datetime import datetime

import jobxml_tuonti as jx

KAYTTO = {"HorizontalAndVertical": "vaaka+pysty", "HorizontalOnly": "vaaka", "VerticalOnly": "pysty"}
MITATUT_KATEGORIAT = ("Kartoituspiste", "Merkintäpiste", "Suunnittelupiste (Construction)")
HUONOT_LUOKAT = ("Tyydyttävä", "Heikko", "Huono", "Ei laskettavissa")
KORKEUSRESIDUAALI_RAJA_M = 0.030   # laatuluokka arvioi vain tasosijaintia; korkeus tarkistetaan erikseen


def _luku(arvo, desimaalit=3):
    return f"{arvo:.{desimaalit}f}" if arvo is not None else "-"


def _mm(arvo_m, desimaalit=1):
    return f"{arvo_m * 1000:.{desimaalit}f}" if arvo_m is not None else "-"


def _vaaka(residuaali):
    """Vaakaresiduaali sqrt(dN² + dE²) metreinä (sama kuin laatuluokan suurin residuaali)."""
    if residuaali.get("delta_n") is None or residuaali.get("delta_e") is None:
        return None
    return math.hypot(residuaali["delta_n"], residuaali["delta_e"])


def _kulmamuunnin(raportti):
    """(muunnos asteista raportin kulmayksikköön, yksikön nimi). JobXML tallentaa asteina."""
    if (raportti.get("tyon_tiedot") or {}).get("kulmayksikko") == "Gons":
        return (lambda deg: deg / 0.9 if deg is not None else None), "gon"
    return (lambda deg: deg), "°"


KYLLA_EI = {"true": "kyllä", "false": "ei"}
LUKITUS = {"AutoLock": "Autolock", "FineLock": "FineLock", "LongRangeFineLock": "Long Range FineLock"}
ETAISYYDET = {"GroundDistance": "maasto", "GridDistance": "kartta", "EllipsoidDistance": "ellipsoidi"}
ORIENTOINTI = {"SetToAzimuth": "aseta suuntakulmaksi", "SetToZero": "aseta nollaksi", "NoChange": "ei muutosta"}


def _kylla(arvo):
    return KYLLA_EI.get(arvo, arvo or "-")


def _asetusrivit(raportti, kulma, kulmayksikko):
    """Koordinaatiston parametrit, korjaukset ja asetukset [(otsikko, arvo)]."""
    a = raportti.get("asetukset") or {}
    rivit = []
    pr = a.get("projektio") or {}
    if pr.get("tyyppi"):
        rivit.append(("Projektio", f"{'Transverse Mercator' if pr['tyyppi'] == 'TransverseMercator' else pr['tyyppi']}, "
                      f"keskimeridiaani {_luku(pr.get('keskimeridiaani_deg'), 0)}°, leveyden origo "
                      f"{_luku(pr.get('keskileveys_deg'), 0)}°, itäkorjaus {_luku(pr.get('itakorjaus'))}, "
                      f"pohjoiskorjaus {_luku(pr.get('pohjoiskorjaus'))}, mittakaava {_luku(pr.get('mittakaava'), 8)}"))
    el = a.get("ellipsoidi") or {}
    if el.get("isoakseli"):
        rivit.append(("Ellipsoidi", f"isoakseli {_luku(el['isoakseli'])}, litistyneisyys "
                                    f"1/{_luku(el.get('litistyneisyys_1_per'), 6)}"))
    dm = a.get("datumimuunnos")
    if dm:
        tyyppi = "7-parametrinen" if dm["tyyppi"] == "SevenParameter" else (dm["tyyppi"] or "-")
        kierrot = " / ".join(f"{k * 3600:.4f}\"" if k is not None else "-" for k in dm["kierrot_deg"])
        siirrot = " / ".join(_luku(v) for v in dm["siirrot_m"])
        rivit.append(("Datumimuunnos", f"{tyyppi} ({dm.get('vertauskehys') or '-'}, epookki {dm.get('epookki') or '-'}): "
                                       f"kierrot X/Y/Z {kierrot}, siirrot X/Y/Z {siirrot} m, "
                                       f"mittakaava {_luku(dm.get('mittakaava_ppm'), 5)} ppm"))
    kr = a.get("korjaukset")
    if kr:
        rivit.append(("Korjaukset", f"etäisyydet: {ETAISYYDET.get(kr['etaisyydet'], kr['etaisyydet'] or '-')}, "
                                    f"karttakoordinaatit: {'kasvavat pohjoiseen ja itään' if kr['karttakoordinaatit'] == 'IncreasingNorthEast' else kr['karttakoordinaatit']}, "
                                    f"eteläatsimuutti: {_kylla(kr['eteläatsimuutti'])}, "
                                    f"merenpintakorjaus: {_kylla(kr['merenpintakorjaus'])}, "
                                    f"magneettinen deklinaatio: {_luku(kr['magneettinen_deklinaatio'], 4)}, "
                                    f"lähipistetasoitus: {_kylla(kr['lahipistetasoitus'])}"))
    for m in a.get("kartoitusasetukset") or []:
        rivit.append(("GNSS-kartoitusasetukset", f"korkeusmaski {_luku(m['korkeusmaski_deg'], 0)}°, "
                                                 f"PDOP-maski {_luku(m['pdop_maski'], 0)}"))
    kalusto = raportti.get("kalusto") or {}
    for k in kalusto.get("ilmastokorjaukset") or []:
        rivit.append(("Ilmastokorjaukset", f"kaarevuuskorjaus: {_kylla(k['kaarevuus'])}, refraktiokorjaus: "
                                           f"{_kylla(k['refraktio'])} (refraktiovakio {_luku(k['refraktiovakio'], 3)})"))
    for t in kalusto.get("takymetrit") or []:
        rivit.append((f"Takymetri {t['sarjanumero'] or ''}".strip(),
                      f"taitekerroin {_luku(t.get('taitekerroin'), 1)}, aallonpituus {_luku(t.get('aallonpituus'), 1)}, "
                      f"orientoinnin vaakakulma: {ORIENTOINTI.get(t.get('orientointitapa'), t.get('orientointitapa') or '-')}, "
                      f"vaakakollimaatio {_luku(kulma(t.get('vaakakollimaatio')), 4)}, pystykollimaatio "
                      f"{_luku(kulma(t.get('pystykollimaatio')), 4)}, tappikaltevuuskorjaus "
                      f"{_luku(kulma(t.get('tappikaltevuus')), 4)} {kulmayksikko}, EDM-vakio {_mm(t.get('edm_vakio'), 1)} mm"))
    return rivit


def _aika(t):
    return t.strftime("%d.%m.%Y %H:%M") if t else "-"


def _korkeusvaroitus(asemapiste):
    """Varoitus, jos jonkin korkeuteen käytetyn liitospisteen korkeusresiduaali ylittää rajan."""
    suuret = [r for r in asemapiste.get("residuaalit", [])
              if r.get("delta_h") is not None and abs(r["delta_h"]) > KORKEUSRESIDUAALI_RAJA_M
              and r.get("kaytto") != "HorizontalOnly"]
    if not suuret:
        return None
    return "Suuri korkeusresiduaali: " + ", ".join(f"{r['liitospiste']} {r['delta_h'] * 1000:.0f} mm" for r in suuret)


def raportin_sisalto(raportti, pisteet, hylatyt):
    """Raportin osiot valmiina tekstitaulukkoina: {"perustiedot": [(otsikko, arvo)], "kalusto": {...},
    "tarkistukset": [teksti], "maarat": [[...]], "liitospisteet": [[...]], "muut_liitospisteet": [nimi],
    "asemat": [{...}], "mitatut": [[...]], "hylatyt": [[...]], "raakahavainnot": [{"asema", "rivit"}]}.
    Taulukoiden ensimmäinen rivi on otsikkorivi."""
    kulma, kulmayksikko = _kulmamuunnin(raportti)
    tyo = raportti.get("tyon_tiedot") or {}
    ks = raportti.get("koordinaatisto") or {}

    jaksot = raportti.get("tyojaksot") or []
    paivat = sorted({j["alku"].strftime("%d.%m.%Y") for j in jaksot})
    perustiedot = [
        ("Työn nimi", raportti.get("job_nimi") or "-"),
        ("Tiedosto", raportti.get("lahdetiedosto") or "-"),
        ("Ohjelma", " ".join(x for x in (tyo.get("ohjelma"), tyo.get("ohjelmaversio")) if x) or "-"),
        ("Ohjaimen sarjanumero", tyo.get("ohjaimen_sarjanumero") or "-"),
        ("Mittauspäivä", ", ".join(paivat) or "-"),
        ("Työaika", "; ".join(f"{j['alku']:%H:%M}-{j['loppu']:%H:%M}" for j in jaksot)
         + (f" (yhteensä {jx._muotoile_kesto(raportti['tyoaika_yhteensa_s'])})" if jaksot else "-")),
        ("Koodikirjasto", raportti.get("koodikirjasto") or "-"),
        ("Koordinaatisto", " / ".join(x for x in (ks.get("jarjestelma"), ks.get("kaista"), ks.get("datumi")) if x) or "-"),
        ("Geoidimalli", ks.get("geoidi") or "-"),
        ("Yksiköt", f"kulmat {kulmayksikko}, etäisyydet m"),
    ]

    kalusto = raportti.get("kalusto") or {}
    takymetrit = [["Takymetri", "Sarjanumero", "Firmware", f"Kulmatarkkuus ({kulmayksikko})", "EDM-tarkkuus"]] + [
        [t["malli"] or t["tyyppi"] or "-", t["sarjanumero"] or "-", t["firmware"] or "-",
         f"{_luku(kulma(t['ha_tarkkuus_deg']), 4)} / {_luku(kulma(t['va_tarkkuus_deg']), 4)}",
         f"{_mm(t['edm_tarkkuus_m'], 0)} mm + {_luku(t['edm_ppm'], 0)} ppm"]
        for t in kalusto.get("takymetrit", [])]
    gnss = [["GNSS-vastaanotin", "Sarjanumero", "Firmware", "Antenni", "Antennikorkeus (m)", "Mittaustapa"]] + [
        [g["vastaanotin"] or "-", g["sarjanumero"] or "-", g["firmware"] or "-", g["antenni"] or "-",
         ", ".join(f"{h:.3f}" for h in g["antennikorkeudet"]) or "-", g["mittaustapa"] or "-"]
        for g in kalusto.get("gnss", [])]
    tahykset = [["Tähys", "Prismatyyppi", "Prismavakio (mm)", "Tähyskorkeus (m)"]] + [
        [t["nimi"] or "-", t["prismatyyppi"] or "-", _mm(t["prismavakio_m"], 1), _luku(t["korkeus_m"])]
        for t in kalusto.get("tahykset", [])]

    asetukset = _asetusrivit(raportti, kulma, kulmayksikko)
    tapahtumat = [["Aika", "Tapahtuma", "Lisätieto"]] + [
        [(t["aika"].strftime("%H:%M:%S" if len(paivat) <= 1 else "%d.%m.%Y %H:%M:%S") if t["aika"] else "-"),
         t["tapahtuma"], t["lisatieto"]]
        for t in raportti.get("tapahtumat") or []]

    asemat_raportissa = raportti.get("asemapisteet") or []
    asema_nimi = {a.get("station_record_id"): a["nimi"] for a in asemat_raportissa}

    tarkistukset = []
    for a in asemat_raportissa:
        laatu = a.get("laatu") or {}
        korkeus = _korkeusvaroitus(a)
        if laatu.get("luokka") in HUONOT_LUOKAT or laatu.get("varoitukset") or korkeus:
            selitys = ", ".join((laatu.get("varoitukset") or []) + ([korkeus] if korkeus else []))
            tarkistukset.append(f"Asema {a['nimi']}: laatuluokka {laatu.get('luokka')} "
                                f"({_luku(laatu.get('kokonaispiste'), 0)}/100)" + (f" - {selitys}" if selitys else ""))
    for v in raportti.get("varoitukset_2x") or []:
        tarkistukset.append(f"MML:n 2x-sääntö: piste {v['piste']} on {v['etaisyys_m']} m asemasta {v['asema']} "
                            f"(raja {v['raja_m']} m)")
    if hylatyt:
        tarkistukset.append(f"{len(hylatyt)} pistettä hylättiin (ks. Hylätyt pisteet)")

    maarat = [["Kategoria", "Lukumäärä"]] + [[k, str(v)] for k, v in (raportti.get("maara") or {}).items()]
    maarat.append(["Hylätyt", str(len(hylatyt))])

    rtk = [p for p in pisteet if p["kategoria"] == "Liitospiste (alkuperäinen RTK-mittaus)"]
    liitospisteet = [["Piste", "Koodi", "N", "E", "H", "Vaakatark. (mm)", "Pystytark. (mm)",
                      "PDOP", "HDOP", "VDOP", "Satel.", "Aika"]] + [
        [p["nimi"], p.get("koodi") or "-", _luku(p["n"]), _luku(p["e"]), _luku(p["korkeus"]),
         _mm(p.get("tarkkuus_h")), _mm(p.get("tarkkuus_v")), _luku(p.get("pdop"), 1), _luku(p.get("hdop"), 1),
         _luku(p.get("vdop"), 1), str(p.get("satelliitteja") or "-"), _aika(p.get("aikaleima"))]
        for p in rtk]
    rtk_lisatiedot = [["Piste", "X (ECEF)", "Y (ECEF)", "Z (ECEF)", "Antennikork. (m)", "Kallistusetäis. (m)",
                       "GDOP", "Tukiaseman tiedon ikä (s)", "Sijainteja"]]
    vcv = [["Piste", "VCV xx", "VCV xy", "VCV xz", "VCV yy", "VCV yz", "VCV zz"]]
    for p in rtk:
        g = p.get("gnss") or {}
        if not g:
            continue
        x, y, z = g.get("ecef") or (None, None, None)
        rtk_lisatiedot.append([p["nimi"], _luku(x), _luku(y), _luku(z), _luku(g.get("antennikorkeus")),
                               _luku(g.get("kallistusetaisyys")), _luku(g.get("gdop"), 1),
                               _luku(g.get("tukiaseman_ika_s"), 1), str(g.get("sijainteja") or "-")])
        if g.get("vcv"):
            vcv.append([p["nimi"]] + [_luku(g["vcv"][k], 6) for k in ("xx", "xy", "xz", "yy", "yz", "zz")])
    rtk_nimet = {p["nimi"] for p in rtk}
    muut_liitospisteet = sorted({n for a in asemat_raportissa for n in a.get("liitospisteet", [])} - rtk_nimet)

    asemat = []
    for a in asemat_raportissa:
        laatu = a.get("laatu") or {}
        ilmasto = a.get("ilmasto") or {}
        mittakaava = a.get("mittakaava")
        tiedot = [
            ("Määrittely", f"{a.get('maarittely') or '-'}, mittakaava {_luku(mittakaava, 8)}"
                           + (" (vakio)" if a.get("mittakaava_tyyppi") == "Fixed" else "")),
            ("N / E / H", f"{_luku(a['n'])} / {_luku(a['e'])} / {_luku(a.get('korkeus'))}"),
            ("Keskivirhe N / E / H (mm)", f"{_mm(a.get('se_n_m'))} / {_mm(a.get('se_e_m'))} / {_mm(a.get('se_korkeus_m'))}"),
            ("Kojekorkeus (m)", _luku(a.get("kojekorkeus"))),
            ("Ilmasto", f"{_luku(ilmasto.get('paine'), 1)} mbar, {_luku(ilmasto.get('lampotila'), 1)} °C, "
                        f"{_luku(ilmasto.get('ppm'), 1)} ppm" if ilmasto else "-"),
            ("Orientointi", "; ".join(
                f"{o['liitospiste']}: korjaus {_luku(kulma(o['korjaus_deg']), 4)}, keskivirhe "
                f"{_luku(kulma(o['keskivirhe_deg']), 4)} {kulmayksikko}" for o in a.get("orientointi", [])) or "-"),
            ("Laatuluokka", f"{laatu.get('luokka', '-')} ({_luku(laatu.get('kokonaispiste'), 0)}/100)"),
            ("dHz RMS / suurin (mm)", f"{_mm(laatu.get('rms_residuaali_m'))} / {_mm(laatu.get('suurin_residuaali_m'))}"),
            ("Liitospisteitä / kulmapeitto", f"{laatu.get('liitospisteita', '-')} / {_luku(laatu.get('kulmapeitto_deg'), 0)}°"),
            ("PDOP ka. / huonoin", f"{_luku(laatu.get('pdop_keskiarvo'), 2)} / {_luku(laatu.get('pdop_huonoimmillaan'), 2)}"),
        ]
        if a.get("sijainti"):
            tiedot.append(("Sijaintiluokka (S)", f"{a['sijainti'].get('S')}"))
        residuaalit = [["Liitospiste", "dN (mm)", "dE (mm)", "dHz (mm)", "dH (mm)", f"dHA ({kulmayksikko})",
                        f"dVA ({kulmayksikko})", "dSD (mm)", "Käyttö"]] + [
            [r.get("liitospiste") or "-", _mm(r.get("delta_n")), _mm(r.get("delta_e")), _mm(_vaaka(r)),
             _mm(r.get("delta_h")),
             _luku(kulma(r.get("d_ha_deg")), 4), _luku(kulma(r.get("d_va_deg")), 4), _mm(r.get("d_sd_m")),
             KAYTTO.get(r.get("kaytto"), r.get("kaytto") or "-")]
            for r in a.get("residuaalit", [])]
        korkeus = _korkeusvaroitus(a)
        asemat.append({"nimi": a["nimi"], "tiedot": tiedot,
                       "varoitukset": (laatu.get("varoitukset") or []) + ([korkeus] if korkeus else []),
                       "residuaalit": residuaalit, "asemapiste": a})

    mitatut = [["Piste", "Koodi", "N", "E", "H", "Kategoria", "Tapa", "Asema", "2 kojeas."]] + [
        [p["nimi"], p.get("koodi") or "-", _luku(p["n"]), _luku(p["e"]), _luku(p["korkeus"]),
         p["kategoria"].replace(" (Construction)", ""), p.get("mittaustapa") or "-",
         asema_nimi.get(p.get("station_record_id"), "-"), "kyllä" if p.get("kahdesta_kojeasennosta") else ""]
        for p in pisteet if p["kategoria"] in MITATUT_KATEGORIAT]

    hylatyt_taulu = [["Piste", "Koodi", "Syy"]] + [[h.get("nimi") or "-", h.get("koodi") or "-", h["syy"]]
                                                   for h in hylatyt]

    asemittain = defaultdict(list)
    for p in pisteet:
        if p.get("havainto"):
            asemittain[p.get("station_record_id")].append(p)
    raakahavainnot = []
    for srid, lista in asemittain.items():
        rivit = [["Piste", "Koodi", "Kategoria", f"HA ({kulmayksikko})", f"VA ({kulmayksikko})", "SD (m)",
                  "Tähyskork. (m)", "Prismavakio (mm)", "Kojeasento", "Lukitus"]]
        for p in lista:
            h = p["havainto"]
            rivit.append([p["nimi"], p.get("koodi") or "-", p["kategoria"].replace(" (Construction)", ""),
                          _luku(kulma(h["ha_deg"]), 4), _luku(kulma(h["va_deg"]), 4), _luku(h["sd_m"]),
                          _luku(h["tahyskorkeus_m"]), _mm(h["prismavakio_m"]), h["kojeasento"] or "-",
                          LUKITUS.get(h.get("lukitustyyppi"), h.get("lukitustyyppi") or "kyllä") if h.get("lukittu") == "true" else "ei"])
        raakahavainnot.append({"asema": asema_nimi.get(srid, srid or "-"), "rivit": rivit})

    return {
        "perustiedot": perustiedot,
        "kalusto": {"takymetrit": takymetrit, "gnss": gnss, "tahykset": tahykset},
        "asetukset": asetukset,
        "tapahtumat": tapahtumat,
        "rtk_lisatiedot": rtk_lisatiedot,
        "vcv": vcv,
        "tarkistukset": tarkistukset,
        "maarat": maarat,
        "liitospisteet": liitospisteet,
        "muut_liitospisteet": muut_liitospisteet,
        "asemat": asemat,
        "mitatut": mitatut,
        "hylatyt": hylatyt_taulu,
        "raakahavainnot": raakahavainnot,
    }


def tee_pdf(raportti, pisteet, hylatyt, kartat=True):
    """Mittausraportti PDF-tiedostona (bytes). kartat=False jättää asemien pienet kartat pois
    (ne haetaan Helsingin WMS:stä)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    sisalto = raportin_sisalto(raportti, pisteet, hylatyt)
    tyylit = getSampleStyleSheet()
    normaali = ParagraphStyle("normaali", parent=tyylit["Normal"], fontSize=8, leading=10)
    pieni = ParagraphStyle("pieni", parent=normaali, fontSize=7, leading=8.5)
    otsikko = ParagraphStyle("otsikko", parent=tyylit["Title"], fontSize=15, leading=18, spaceAfter=4,
                             alignment=0)
    h2 = ParagraphStyle("h2", parent=tyylit["Heading2"], fontSize=11, leading=13, spaceBefore=8, spaceAfter=3)
    h3 = ParagraphStyle("h3", parent=tyylit["Heading3"], fontSize=9, leading=11, spaceBefore=6, spaceAfter=2)
    varoitus = ParagraphStyle("varoitus", parent=normaali, textColor=colors.HexColor("#9a3412"))
    leveys = A4[0] - 3 * cm

    def taulukko(rivit, sarakkeet=None, fontti=7, oikealle=()):
        rivit = [[Paragraph(str(solu), pieni) if isinstance(solu, str) and len(solu) > 40 else solu
                  for solu in rivi] for rivi in rivit]
        t = Table(rivit, colWidths=sarakkeet, repeatRows=1, hAlign="LEFT")
        tyyli = [("FONTSIZE", (0, 0), (-1, -1), fontti), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                 ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5e7eb")),
                 ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#9ca3af")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f9")]),
                 ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
                 ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                 ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        tyyli += [("ALIGN", (i, 0), (i, -1), "RIGHT") for i in oikealle]
        t.setStyle(TableStyle(tyyli))
        return t

    def avainarvot(parit, sarakkeet):
        t = Table([[Paragraph(f"<b>{a}</b>", normaali), Paragraph(str(b), normaali)] for a, b in parit],
                  colWidths=sarakkeet, hAlign="LEFT")
        t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                               ("LEFTPADDING", (0, 0), (-1, -1), 2), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    luotu = datetime.now().strftime("%d.%m.%Y %H:%M")
    alatunniste = f"{raportti.get('job_nimi') or ''} | {raportti.get('lahdetiedosto') or ''} | luotu {luotu}"

    class NumeroituCanvas(rl_canvas.Canvas):
        """Alatunniste ja sivunumero muodossa 'sivu X / Y' (sivujen määrä tiedetään vasta lopussa)."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._sivut = []

        def showPage(self):
            self._sivut.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            for tila in self._sivut:
                self.__dict__.update(tila)
                self.setFont("Helvetica", 7)
                self.setFillColor(colors.HexColor("#6b7280"))
                self.drawString(1.5 * cm, 1 * cm, alatunniste)
                self.drawRightString(A4[0] - 1.5 * cm, 1 * cm, f"sivu {self._pageNumber} / {len(self._sivut)}")
                super().showPage()
            super().save()

    e = [Paragraph(f"Mittausraportti: {raportti.get('job_nimi') or ''}", otsikko)]
    e.append(avainarvot(sisalto["perustiedot"], [4 * cm, leveys - 4 * cm]))

    e.append(Paragraph("Kalusto", h2))
    kalusto = sisalto["kalusto"]
    if len(kalusto["takymetrit"]) > 1:
        e += [taulukko(kalusto["takymetrit"]), Spacer(1, 3)]
    if len(kalusto["gnss"]) > 1:
        e += [taulukko(kalusto["gnss"]), Spacer(1, 3)]
    if len(kalusto["tahykset"]) > 1:
        e.append(taulukko(kalusto["tahykset"]))

    if sisalto["asetukset"]:
        e.append(Paragraph("Koordinaatisto ja asetukset", h2))
        e.append(avainarvot(sisalto["asetukset"], [4 * cm, leveys - 4 * cm]))

    e.append(Paragraph("Yhteenveto ja tarkistukset", h2))
    tarkistukset = ([Paragraph("- " + t, varoitus) for t in sisalto["tarkistukset"]]
                    or [Paragraph("Ei huomautettavaa.", normaali)])
    yhteenveto = Table([[taulukko(sisalto["maarat"], [5.2 * cm, 1.8 * cm], oikealle=[1]), tarkistukset]],
                       colWidths=[7.5 * cm, leveys - 7.5 * cm], hAlign="LEFT")
    yhteenveto.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    e.append(yhteenveto)

    if len(sisalto["liitospisteet"]) > 1 or sisalto["muut_liitospisteet"]:
        e.append(Paragraph("Liitospisteet", h2))
    if len(sisalto["liitospisteet"]) > 1:
        e.append(Paragraph("RTK-mittaukset (liitospisteiden koordinaatit)", h3))
        e.append(taulukko(sisalto["liitospisteet"], oikealle=range(2, 11)))
    if len(sisalto["rtk_lisatiedot"]) > 1:
        e.append(KeepTogether([Paragraph("RTK-mittausten lisätiedot", h3),
                               taulukko(sisalto["rtk_lisatiedot"], oikealle=range(1, 9))]))
    if len(sisalto["vcv"]) > 1:
        e.append(KeepTogether([Paragraph("RTK-mittausten kovarianssit (m²)", h3),
                               taulukko(sisalto["vcv"], oikealle=range(1, 7))]))
    if sisalto["muut_liitospisteet"]:
        e.append(Paragraph("Liitospisteinä käytetty myös (koordinaatit mitattujen pisteiden taulukossa): "
                           + ", ".join(sisalto["muut_liitospisteet"]), normaali))

    tmp = tempfile.mkdtemp()
    for n, asema in enumerate(sisalto["asemat"]):
        kartta = None
        if kartat:
            try:
                polku = jx.piirra_asemapiste_kartta(asema["asemapiste"], os.path.join(tmp, f"asema_{n}.png"))
                if polku and os.path.exists(polku):
                    kartta = Image(polku, width=4.5 * cm, height=4.5 * cm)
            except Exception:
                kartta = None
        tiedot = [avainarvot(asema["tiedot"], [4.3 * cm, leveys - (9.3 if kartta else 4.8) * cm])]
        tiedot += [Paragraph("- " + v, varoitus) for v in asema["varoitukset"]]
        if kartta:
            ylaosa = Table([[kartta, tiedot]], colWidths=[4.8 * cm, leveys - 4.8 * cm], hAlign="LEFT")
            ylaosa.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            ylaosa = [ylaosa]
        else:
            ylaosa = tiedot
        lohko = ([Paragraph("Asemapisteet", h2)] if n == 0 else []) + [Paragraph(f"Asema {asema['nimi']}", h3)] + ylaosa
        if len(asema["residuaalit"]) > 1:
            lohko += [Spacer(1, 2), taulukko(asema["residuaalit"], oikealle=range(1, 8))]
        e.append(KeepTogether(lohko))

    if len(sisalto["tapahtumat"]) > 1:
        e.append(Paragraph("Mittaustapahtumat", h2))
        e.append(taulukko(sisalto["tapahtumat"], [2.6 * cm, 4.5 * cm, leveys - 7.1 * cm]))
    if len(sisalto["mitatut"]) > 1:
        e.append(Paragraph(f"Mitatut pisteet ({len(sisalto['mitatut']) - 1})", h2))
        e.append(taulukko(sisalto["mitatut"], oikealle=[2, 3, 4]))
    if len(sisalto["hylatyt"]) > 1:
        e.append(Paragraph("Hylätyt pisteet", h2))
        e.append(taulukko(sisalto["hylatyt"], [3 * cm, 2 * cm, leveys - 5 * cm]))

    if sisalto["raakahavainnot"]:
        e.append(PageBreak())
        e.append(Paragraph("Liite: raakahavainnot asemittain", h2))
        for ryhma in sisalto["raakahavainnot"]:
            e.append(Paragraph(f"Asema {ryhma['asema']}", h3))
            e.append(taulukko(ryhma["rivit"], oikealle=range(3, 8)))

    puskuri = io.BytesIO()
    SimpleDocTemplate(puskuri, pagesize=A4, leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.3 * cm,
                      bottomMargin=1.6 * cm, title=f"Mittausraportti {raportti.get('job_nimi') or ''}",
                      ).build(e, canvasmaker=NumeroituCanvas)
    return puskuri.getvalue()
