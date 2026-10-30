"""Processing-työkalu: Seinälinjat pistepilvestä. Seinät tunnistetaan suoraan LAS/LAZ-pistepilvestä
(seinat_pilvesta.py, sama laskenta kuin lidarscanin lidarpipessä ja CloudCompare-lisäosassa): linja
julkisivuun sokkelin yläpuolelle, pienet ulokkeet yleistettynä, luokat SEINA / EPAVARMA / PAATELTY.
Tulokset: seinälinjat tietoineen (sokkeli, korkeus, kohina), Seinät 3D väritettynä linjan ja pilven
erolla, pistepilvi karttaan ja valinnainen DXF. Tuloksen voi verrata kantakarttaan tai mittaukseen
työkalulla Vertaa seinälinjaa LiDARiin."""

import os
import time

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsFeatureSink,
                       QgsCircularString, QgsGeometry, QgsPoint, QgsPointXY, QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum, QgsProcessingParameterExtent,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterFeatureSource, QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination, QgsProcessingParameterString, QgsRectangle, Qgis)

from . import ydin
from .seinalinja_algoritmi import GK25, LUKU, SEINA3DKENTAT, TEKSTI, _cm, _kentat, lisaa_seinapalat
from .tyylit import SEINAN_KORKEUS_M, aseta_tyylit
from .vertailu_algoritmi import VARITYKSET, _gk25_alue, rajaa_pilvi

import seinat_pilvesta as sp  # noqa: E402  (lib-kansiosta, ks. ydin.py)

# Seinälinjojen kentät: taso = SEINA / EPAVARMA / PAATELTY (tyyli kuten LiDAR-seinissä), korkeus_ala/yla =
# julkisivun korkeuskerrokset maasta, sokkeli_cm = sokkelin ero julkisivuun (+ = ulompana), pinta_cm =
# julkisivun ero linjasta, kohina_cm = pinnan hajonta, kallistus_cm_m = pinnan siirtymä ylöspäin (+ = ulos)
SEINAKENTAT = _kentat(("taso", TEKSTI), ("pituus_m", LUKU), ("seina", TEKSTI), ("korkeus_ala_m", LUKU),
                      ("korkeus_yla_m", LUKU), ("sokkeli_cm", LUKU), ("sokkeli_yla_m", LUKU), ("pinta_cm", LUKU),
                      ("kohina_cm", LUKU), ("kallistus_cm_m", LUKU))
PROFIILIT = [("Automaattinen (LAS-otsikosta tai pistetiheydestä)", "auto"), ("iPhone", "iphone"),
             ("Stonex (reppukeilain)", "stonex"), ("Ilmakeilauksen seinäluokka (ALS, luokka 13)", "als")]
ALS_SEINALUOKKA = 13
ALUEEN_PUSKURI_M = 5.0     # rajausalueen (talot) ympäriltä luetaan myös seinien ulkopuoli
VAROITUS_KM2 = 0.25        # isompi alue: varoitus (aika ja muisti)


class SeinatPilvestaAlgoritmi(QgsProcessingAlgorithm):
    PILVI = "PILVI"
    ALUE = "ALUE"
    LAAJUUS = "LAAJUUS"
    PROFIILI = "PROFIILI"
    SISATILA = "SISATILA"
    LUOKAT = "LUOKAT"
    PISTEPILVI = "PISTEPILVI"
    VARITYS = "VARITYS"
    DXF = "DXF"
    SEINAT = "SEINAT"
    SEINAT_3D = "SEINAT_3D"

    def createInstance(self):  # noqa: N802
        return SeinatPilvestaAlgoritmi()

    def name(self):
        return "seinalinjat_pistepilvesta"

    def displayName(self):  # noqa: N802
        return "Seinälinjat pistepilvestä"

    def shortHelpString(self):  # noqa: N802
        return ("Tunnistaa rakennusten seinälinjat suoraan pistepilvestä (LAS tai LAZ): iPhonen keilaus "
                "(lidarpipe), Stonexin reppukeilain tai ilmakeilauksen seinäluokka. Laite päätellään "
                "LAS-otsikosta tai pistetiheydestä, tai sen voi valita.\n\n"
                "Rajaus: valitse talot kartalta (esim. kantakartta, 'Vain valitut kohteet'; pistepilvestä luetaan "
                "talot ja 5 m ympäriltä) tai piirrä alue: kentän 'alue kartalta' valikosta Piirrä kartalle ja "
                "vedä suorakaide (myös kartan näkymä tai tason laajuus käy). Rajaus QGIS:n PDAL-työkalulla "
                "pdal:clip. Valitut talot menevät piirretyn alueen edelle. Ilman rajausta "
                "luetaan koko pistepilvi (iso Stonexin pilvi: minuutteja ja gigatavuja muistia).\n\n"
                "Seinäksi hyväksytään pystypinnat, joissa on pisteitä suurimmalla osalla korkeutta 0,3–2,5 m "
                "maasta ja myös ylempänä (iPhone 1,8 m, Stonex 2,0 m): aidat, autot, kalusteet ja "
                "kasvillisuus jäävät pois, eivätkä ikkunat katkaise seinää. Linja asetetaan julkisivuun "
                "sokkelin yläpuolelle (julkisivu yli 1 m korkeudelta, 10 cm kerroksittain). Pienet ulokkeet ja "
                "sisennykset (enintään 0,5 m syvät ja 2 m leveät) yleistetään pois. Ikkunoista näkyvät "
                "sisäseinät jäävät pois, eikä linja jatku nurkasta aidan päälle. Rinteessä julkisivu luetaan "
                "seinän keskimääräisestä maasta.\n\n"
                "Ilmakeilauksen seinäluokka (ALS, luokka 13, esim. kaupungin TerraScan-luokittelu): linjat "
                "seinäpisteistä ylhäältä katsottuna, ilman maanpintaa ja julkisivun tarkistusta. Tarkkuus "
                "desimetriluokkaa (kantakarttaa vastaan mediaani noin 8 cm): luonnos tai kantakartan tarkistus, "
                "ei mittaus. Katon rakenteet (IV-konehuoneet) erottaa kentästä korkeus_ala_m (alin seinäpiste "
                "paikallisesta alimmasta, esim. yli 4 m).\n\n"
                "Tulokset: Seinälinjat pistepilvestä (taso SEINA = varma, EPAVARMA = lyhyt tai vino, "
                "PAATELTY = ääriviivan liitos ilman pisteitä; kentät sokkeli_cm = sokkelin ero julkisivuun, "
                "+ = ulompana, korkeus_ala/yla_m = julkisivun korkeus maasta, kohina_cm, kallistus_cm_m), "
                "Seinät 3D väritettynä linjan ja pistepilven seinäpinnan erolla (luokkarajat valittavissa) ja "
                "pistepilvi karttaan. 3D-näkymä: Näytä -> 3D-karttanäkymät. Seinälinjat voi tallentaa DXF:ksi "
                "(layerit SEINA, EPAVARMA, PAATELTY) ja verrata kantakarttaan tai mittaukseen työkalulla "
                "Vertaa seinälinjaa LiDARiin.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile(
            self.PILVI, "Pistepilvi (LAS/LAZ)", behavior=QgsProcessingParameterFile.Behavior.File,
            fileFilter="Pistepilvi (*.las *.laz *.LAS *.LAZ)"))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.ALUE, "Rajaus: talot tai alue (valinnainen, tyhjä = koko pistepilvi)",
            [QgsProcessing.SourceType.TypeVectorAnyGeometry], optional=True))
        self.addParameter(QgsProcessingParameterExtent(
            self.LAAJUUS, "Rajaus: alue kartalta (valinnainen; kentän valikosta 'Piirrä kartalle')", optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.PROFIILI, "Laite", options=[n for n, _ in PROFIILIT], defaultValue=0))
        self.addParameter(QgsProcessingParameterBoolean(
            self.SISATILA, "Sisätila (yksi lattiataso maanpinnan sijaan)", defaultValue=False))
        self.addParameter(QgsProcessingParameterString(
            self.LUOKAT, "Seinät 3D: poikkeaman luokkarajat (cm, välilyönnein, esim. 3 5 15)",
            defaultValue=ydin.LUOKKARAJAT_OLETUS, optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.PISTEPILVI, "Lataa pistepilvi karttaan", defaultValue=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.VARITYS, "Pistepilven väritys kartalla ja 3D-näkymässä", options=[n for n, _ in VARITYKSET],
            defaultValue=0))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.DXF, "Tallenna seinälinjat DXF:ksi (valinnainen)", fileFilter="DXF (*.dxf)", optional=True,
            createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SEINAT, "Seinälinjat pistepilvestä", QgsProcessing.SourceType.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SEINAT_3D, "Seinät 3D", QgsProcessing.SourceType.TypeVectorPolygon, optional=True))

    def _alue(self, parameters, context, feedback, polku, koord):
        """Rajausalue ETRS-GK25:ssä (QgsGeometry): annetut kohteet puskuroituna, muuten pistepilven alue
        otsikosta."""
        lahde = self.parameterAsSource(parameters, self.ALUE, context)
        if lahde is not None:
            gk25 = QgsCoordinateReferenceSystem(GK25)
            muunnos = None
            if lahde.sourceCrs().isValid() and lahde.sourceCrs() != gk25:
                muunnos = QgsCoordinateTransform(lahde.sourceCrs(), gk25, context.transformContext())
            osat = []
            for f in lahde.getFeatures():
                g = QgsGeometry(f.geometry())
                if g.isEmpty():
                    continue
                if muunnos is not None:
                    g.transform(muunnos)
                osat.append(g.buffer(ALUEEN_PUSKURI_M, 4))
            if not osat:
                raise QgsProcessingException("Rajaustasossa ei ole kohteita.")
            feedback.pushInfo(f"Rajaus: {len(osat)} kohdetta ja {ALUEEN_PUSKURI_M:.0f} m ympäriltä.")
            return QgsGeometry.unaryUnion(osat)
        if parameters.get(self.LAAJUUS) not in (None, ""):
            r = self.parameterAsExtent(parameters, self.LAAJUUS, context, QgsCoordinateReferenceSystem(GK25))
            if not r.isNull() and r.width() > 0 and r.height() > 0:
                feedback.pushInfo(f"Rajaus: piirretty alue {r.width():.0f} x {r.height():.0f} m.")
                return QgsGeometry.fromRect(r)
        alue = _gk25_alue(ydin.las_alue(polku), koord, context)
        if alue is None:
            raise QgsProcessingException("Pistepilven aluetta ei saatu otsikosta.")
        x0, y0, x1, y1 = alue
        km2 = (x1 - x0) * (y1 - y0) / 1e6
        if km2 > VAROITUS_KM2:
            feedback.pushWarning(f"Koko pistepilvi luetaan ({km2:.2f} km²): tämä voi viedä minuutteja ja paljon "
                                 "muistia. Rajaa tarvittaessa talot kartalta.")
        return QgsGeometry.fromRect(QgsRectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1))

    def _lue(self, polku, alue, koord, context, feedback):
        """Pistepilvi alueelta: (paikalliset float32-koordinaatit n x 3, siirto (e0, n0, 0) ETRS-GK25:een,
        pisteiden luokat)."""
        feedback.pushInfo(f"Luetaan pistepilvi {os.path.basename(polku)} (pdal:clip)...")
        rajaus = rajaa_pilvi(polku, alue, koord, "seinat_pistepilvi", context, feedback)
        if rajaus is None:
            return None, None, None
        luettava, rajattu = rajaus
        try:
            xyz, origo, luokka = ydin.lue_las_paikallinen(luettava, luokat=True)
        except Exception as e:
            raise QgsProcessingException(f"Pistepilveä ei voitu lukea: {e}")
        finally:
            if rajattu:
                try:
                    os.remove(luettava)
                except OSError:
                    pass
        origo[0] += koord["siirto_x"]
        feedback.pushInfo(f"Pistepilvestä {len(xyz):,} pistettä.".replace(",", " "))
        return xyz, origo, luokka

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        # Pitkä ajo: ei App Napia (macOS) eikä nukahtamista, säie täydelle nopeudelle (ydin.valveilla)
        with ydin.valveilla():
            return self._aja(parameters, context, feedback)

    def _aja(self, parameters, context, feedback):
        polku = self.parameterAsFile(parameters, self.PILVI, context)
        from qgis.core import QgsSettings
        QgsSettings().setValue("maastomittaus/viimeisin_pilvi", polku)   # valikko täyttää seuraavalla kerralla
        try:
            rajat = ydin.lue_luokkarajat(self.parameterAsString(parameters, self.LUOKAT, context))
            luokat = ydin.poikkeamaluokat(rajat)
            koord = ydin.las_koordinaatisto(polku)
        except (OSError, ValueError) as e:
            raise QgsProcessingException(str(e))
        if koord["epsg"] != ydin.GK25_EPSG and not QgsCoordinateReferenceSystem(f"EPSG:{koord['epsg']}").isValid():
            raise QgsProcessingException(f"Pistepilven koordinaatisto EPSG:{koord['epsg']} ei ole QGIS:n tuntema.")
        feedback.pushInfo(f"Pistepilven koordinaatisto: {koord['selitys']}.")
        alue = self._alue(parameters, context, feedback, polku, koord)
        xyz, origo, luokka = self._lue(polku, alue, koord, context, feedback)
        if xyz is None or feedback.isCanceled():
            return {}
        if len(xyz) < 1000:
            raise QgsProcessingException("Pistepilvessä ei ole pisteitä rajatulla alueella (eri alue?).")

        profiili = PROFIILIT[self.parameterAsEnum(parameters, self.PROFIILI, context)][1]
        if profiili == "auto":
            otsikosta = sp.las_profile(polku)
            profiili = otsikosta or sp.guess_profile(xyz)
            feedback.pushInfo(f"Laite: {profiili} ({'LAS-otsikosta' if otsikosta else 'pistetiheydestä'}).")
        als = profiili == "als"
        if als:
            seina = luokka == ALS_SEINALUOKKA
            if seina.any():
                xyz = xyz[seina]
                feedback.pushInfo(f"Ilmakeilaus: seinäluokan {ALS_SEINALUOKKA} pisteet "
                                  f"({len(xyz):,}).".replace(",", " "))
            else:
                feedback.pushWarning(f"Pilvessä ei ole luokan {ALS_SEINALUOKKA} pisteitä: käytetään kaikkia "
                                     "pisteitä seinäpisteinä (tulos on huono, jos pilvi ei ole valmiiksi "
                                     "seinäpisteitä).")
        del luokka
        opt = sp.WallOptions.for_cloud(xyz, profiili,
                                       indoor=self.parameterAsBoolean(parameters, self.SISATILA, context))
        feedback.setProgress(10)
        feedback.pushInfo("Tunnistetaan seinät (iso pilvi: muutama minuutti)...")
        alku = time.time()
        segs = sp.extract_walls(xyz, opt)
        if feedback.isCanceled():
            return {}
        feedback.pushInfo(f"{len(segs)} seinälinjaa, yhteensä {sum(s.length for s in segs):.1f} m "
                          f"({time.time() - alku:.0f} s).")
        if not segs:
            feedback.pushWarning("Seiniä ei löytynyt. Onko alueella keilattuja seiniä (vähintään 2 m korkeita)?")
        feedback.setProgress(60)
        if als:
            # Ilmakeilauksessa ei ole maanpintaa eikä tiheää julkisivua: ei julkisivun tarkistusta. Linjan
            # korkeus_ala_m / korkeus_yla_m: alin ja ylin seinäpiste paikallisesta alimmasta (kattorakenteilla
            # alin piste on korkealla, mutta niin on myös ahtaiden sisäpihojen seinillä).
            import numpy as np
            tarkistus = [np.zeros((0, 2)) for _ in segs]
            feedback.pushInfo("Ilmakeilaus: tarkkuus on desimetriluokkaa (luonnos). Katon rakenteet erottaa "
                              "kentästä korkeus_ala_m (esim. yli 4 m).")
        else:
            feedback.pushInfo("Tarkistetaan julkisivu linjojen kohdalta 25 cm välein...")
            alku = time.time()
            tarkistus = sp.facade_check(xyz, segs, opt)
            feedback.pushInfo(_yhteenveto(segs, tarkistus) + f" ({time.time() - alku:.0f} s)")
        if feedback.isCanceled():
            return {}
        feedback.setProgress(80)
        # Maanpinta Seinät 3D:tä ja DXF:ää varten otoksesta (koko pilven läpikäynti seinittäin olisi hidas)
        maa = sp.Ground(xyz[::max(1, len(xyz) // 3_000_000)], opt.ground_cell)

        crs = QgsCoordinateReferenceSystem(GK25)
        e0, n0 = float(origo[0]), float(origo[1])
        tulokset_id = {}
        seinat, tulokset_id[self.SEINAT] = self.parameterAsSink(parameters, self.SEINAT, context, SEINAKENTAT,
                                                                Qgis.WkbType.CompoundCurve, crs)
        for k, s in enumerate(segs, start=1):
            info = s.info or {}
            korkeus = info.get("korkeus") or (None, None)
            if "kaari" in info:
                f = QgsFeature(SEINAKENTAT)
                f.setGeometry(kaari_geometria(s, e0, n0))
                f.setAttributes(["SEINA", round(s.length, 3), f"Seinä {k}"] + [None] * 7)
                seinat.addFeature(f, QgsFeatureSink.Flag.FastInsert)
            for a, b, mitattu, varma in sp.measured_pieces([s]):
                taso = "PAATELTY" if not mitattu else "SEINA" if varma else "EPAVARMA"
                f = QgsFeature(SEINAKENTAT)
                f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(a[0] + e0, a[1] + n0),
                                                          QgsPointXY(b[0] + e0, b[1] + n0)]))
                f.setAttributes([taso, round(float(((b - a) ** 2).sum() ** 0.5), 3), f"Seinä {k}",
                                 _m(korkeus[0]), _m(korkeus[1]), _cm(info.get("sokkeli")),
                                 _m(info.get("sokkeli_yla")), _cm(info.get("pinta")), _cm(info.get("kohina")),
                                 _cm(info.get("kallistus"))])
                seinat.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        seinat3d, seinat3d_id = self.parameterAsSink(parameters, self.SEINAT_3D, context, SEINA3DKENTAT,
                                                     Qgis.WkbType.Polygon, crs)
        if seinat3d is not None and segs:
            tulokset_id[self.SEINAT_3D] = seinat3d_id
            feedback.pushInfo("Tehdään tasot (Seinät 3D)...")
            for viiva, naytteet in _seinat_3d(segs, tarkistus, maa, e0, n0):
                lisaa_seinapalat(seinat3d, viiva, naytteet, luokat)

        dxf_polku = self.parameterAsFileOutput(parameters, self.DXF, context)
        if dxf_polku and segs:
            sp.write_dxf_r12(dxf_polku, _dxf_viivat(segs, maa, e0, n0), _dxf_kaaret(segs, maa, e0, n0))
            feedback.pushInfo(f"DXF: {dxf_polku}")
            tulokset_id[self.DXF] = dxf_polku

        pistepilvi = None
        if self.parameterAsBoolean(parameters, self.PISTEPILVI, context):
            import numpy as np
            korkeudet = tuple(float(z) for z in np.percentile(xyz[::max(1, len(xyz) // 1_000_000), 2], [1, 99]))
            varitys = VARITYKSET[self.parameterAsEnum(parameters, self.VARITYS, context)][1]
            pistepilvi = (polku, f"Pistepilvi ({os.path.basename(polku)})", korkeudet, None, varitys)
            feedback.pushInfo("Pistepilvi lisätään karttaan ajon jälkeen (iso LAZ: indeksointi kestää hetken). "
                              "3D-näkymä: Näytä -> 3D-karttanäkymät.")
        aseta_tyylit(context, [(tulokset_id.get(self.SEINAT), "pilven_seinat"),
                               (tulokset_id.get(self.SEINAT_3D), "seinat_3d")], pistepilvi, luokat)
        return tulokset_id


def kaari_geometria(s, e0, n0):
    """Kaari (Segment.info["kaari"]) QGIS:n kaarigeometriaksi alku-, keski- ja loppupisteestä."""
    cx, cy, r, a0, a1 = s.info["kaari"]
    am = (a0 + a1) / 2
    import math
    return QgsGeometry(QgsCircularString(QgsPoint(cx + r * math.cos(a0) + e0, cy + r * math.sin(a0) + n0),
                                         QgsPoint(cx + r * math.cos(am) + e0, cy + r * math.sin(am) + n0),
                                         QgsPoint(cx + r * math.cos(a1) + e0, cy + r * math.sin(a1) + n0)))


def _dxf_kaaret(segs, maa, e0, n0):
    """DXF:n kaaret [(layer, (x, y, z), säde, alku°, loppu°)]; z = maanpinta keskipisteessä + 1 m."""
    import math
    out = []
    for s in segs:
        if "kaari" in s.info:
            cx, cy, r, a0, a1 = s.info["kaari"]
            out.append(("SEINA", (cx + e0, cy + n0, _maanpinta(maa, (cx, cy)) + 1.0), r, math.degrees(a0),
                        math.degrees(a1)))
    return out


def _m(arvo):
    return None if arvo is None else round(float(arvo), 2)


def _maanpinta(maa, p):
    """Maanpinnan korkeus paikallisessa pisteessä p (seinat_pilvesta.Ground)."""
    import numpy as np
    return float(maa.at(np.asarray(p, dtype=float)[None, :2])[0])


def _seinat_3d(segs, tarkistus, maa, e0, n0):
    """Seinät 3D -palat: [(viiva ydin.viivat_pisteista-muodossa, naytteet [(e, n, ero_m)])]. Ero on
    julkisivun (sokkelin yläpuolelta) etumerkillinen etäisyys linjasta (+ = ulompana) 25 cm välein
    (seinat_pilvesta.facade_check); seinä alkaa maanpinnasta."""
    import numpy as np
    tulos = []
    for k, (s, rivit) in enumerate(zip(segs, tarkistus), start=1):
        z = _maanpinta(maa, (s.p0 + s.p1) / 2) + SEINAN_KORKEUS_M / 2
        viiva = ydin.viivat_pisteista([(f"Seinä {k}", [(float(x) + e0, float(y) + n0, z)
                                                       for x, y in sp.arc_points(s)])])["viivat"][0]
        naytteet = [(float(s.p0[0] + s.direction[0] * t + e0), float(s.p0[1] + s.direction[1] * t + n0),
                     None if np.isnan(o) else float(o)) for t, o in rivit]
        tulos.append((viiva, naytteet or None))
    return tulos


def _yhteenveto(segs, tarkistus):
    """Julkisivun ero linjoista yhdellä rivillä (pituuksilla painotettu)."""
    import numpy as np
    rivit = [(s.length, np.nanmean(np.abs(r[:, 1])), np.mean(np.abs(r[:, 1][~np.isnan(r[:, 1])]) <= 0.03))
             for s, r in zip(segs, tarkistus) if len(r) and (~np.isnan(r[:, 1])).sum() >= 2]
    if not rivit:
        return "Julkisivua ei löytynyt linjojen kohdalta."
    w, ero, osuus = map(np.array, zip(*rivit))
    return (f"Julkisivu keskimäärin {np.average(ero, weights=w) * 100:.1f} cm linjasta; alle 3 cm "
            f"{np.average(osuus, weights=w) * 100:.0f} % pituudesta ({len(rivit)} linjaa).")


def _dxf_viivat(segs, maa, e0, n0):
    """DXF:n murtoviivat [(layer, [(x, y, z)], suljettu)] kuten lidarpipen DXF: mitatut osat SEINA /
    EPAVARMA, päätellyt PAATELTY; z = maanpinta kärjen kohdalla + 1 m (julkisivun korkeus noin)."""
    import numpy as np
    palat = sp.measured_pieces(segs)
    out = []
    for taso, ryhma in (("SEINA", [p for p in palat if p[2] and p[3]]),
                        ("EPAVARMA", [p for p in palat if p[2] and not p[3]]),
                        ("PAATELTY", [p for p in palat if not p[2]])):
        for ketju in sp.chains(sp._pieces_as_segments(ryhma)):
            suljettu = len(ketju) > 3 and np.linalg.norm(ketju[0] - ketju[-1]) < 0.002
            pts = [(float(p[0] + e0), float(p[1] + n0), _maanpinta(maa, p) + 1.0)
                   for p in (ketju[:-1] if suljettu else ketju)]
            out.append((taso, pts, suljettu))
    return out
