"""Processing-työkalu: Seinälinjat isosta pistepilvestä (ruuduittain). Kaupungin ajoneuvo- ja ilmakeilaus
(satoja miljoonia pisteitä) ei mahdu kerralla muistiin: pilvi luetaan ruutu kerrallaan limittäin COPC-
tiedostosta, jolloin rajaus lukee vain ruudun kohdan. Kustakin ruudusta pidetään linjat, joiden keskipiste on
ruudun ytimessä, saumojen tuplat poistetaan, ja ilmakeilauksen katot (rakennusluokka) pudottavat aidat ja
muurit (seinat_pilvesta: tile_core, drop_seam_duplicates, roof_share; sama kuin lidarpipe walls-tiled)."""

import os
import time

from qgis.core import (QgsFeature, QgsFeatureSink, QgsGeometry, QgsPointXY, QgsProcessing,
                       QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingParameterEnum,
                       QgsProcessingParameterExtent, QgsProcessingParameterFeatureSink, QgsProcessingParameterFile,
                       QgsProcessingParameterFileDestination, QgsProcessingParameterNumber, QgsProcessingUtils,
                       QgsCoordinateReferenceSystem, QgsRectangle, Qgis)

from . import ydin
from .pilvi_algoritmi import ALS_SEINALUOKKA, PROFIILIT, _dxf_viivat, _m
from .seinalinja_algoritmi import GK25, LUKU, TEKSTI, _cm, _kentat
from .tyylit import aseta_tyylit
from .vertailu_algoritmi import _gk25_alue, rajaa_pilvi

import seinat_pilvesta as sp  # noqa: E402  (lib-kansiosta, ks. ydin.py)

RUUTUKENTAT = _kentat(("taso", TEKSTI), ("pituus_m", LUKU), ("seina", TEKSTI), ("korkeus_ala_m", LUKU),
                      ("korkeus_yla_m", LUKU), ("sokkeli_cm", LUKU), ("sokkeli_yla_m", LUKU), ("pinta_cm", LUKU),
                      ("kohina_cm", LUKU), ("kallistus_cm_m", LUKU), ("katto_osuus", LUKU))
LIMITYS_M = 15.0          # ruudun reunan yli menevä seinä löytyy kokonaisena
KATTOSOLU_M = 0.5
KATTO_OSUUS = 0.5         # linjasta vähintään tämä osuus katon vieressä, muuten aita tai muuri
MIN_PISTEITA = 1000


def _copc(polku, context, feedback):
    """COPC-versio pistepilvestä: ruudun rajaus lukee siitä vain ruudun kohdan (tavallinen LAZ luettaisiin joka
    ruudulle kokonaan). Valmis COPC (QGIS tekee sellaisen LAZ:n viereen, kun pilvi avataan karttaan)
    käytetään sellaisenaan; muuten se tehdään kerran pdal:createcopc-työkalulla samaan kansioon."""
    import processing

    if polku.lower().endswith(".copc.laz"):
        return polku
    nimi = os.path.splitext(os.path.basename(polku))[0] + ".copc.laz"
    vieressa = os.path.join(os.path.dirname(polku), nimi)
    if os.path.isfile(vieressa) and os.path.getmtime(vieressa) >= os.path.getmtime(polku):
        feedback.pushInfo(f"Käytetään valmista COPC-tiedostoa {nimi}.")
        return vieressa
    kansio = os.path.dirname(polku)
    if not os.access(kansio, os.W_OK):
        kansio = QgsProcessingUtils.tempFolder()
    feedback.pushInfo(f"Tehdään pistepilvestä COPC ({os.path.join(kansio, nimi)}): kerran, iso pilvi vie "
                      "minuutteja. QGIS käyttää samaa tiedostoa myös kartalla.")
    processing.run("pdal:createcopc", {"LAYERS": [polku], "OUTPUT": kansio}, context=context, feedback=feedback,
                   is_child_algorithm=True)
    tulos = os.path.join(kansio, nimi)
    if not os.path.isfile(tulos):
        raise QgsProcessingException(f"COPC-tiedostoa ei syntynyt ({tulos}).")
    return tulos


class _RuutujenMaa:
    """Maanpinta ruuduittain (seinat_pilvesta.Ground ruudun omissa koordinaateissa) koko alueen paikallisille
    koordinaateille: DXF:n korkeus (pilvi_algoritmi._dxf_viivat kutsuu at)."""

    def __init__(self, koko, e0, n0):
        self.koko, self.e0, self.n0 = koko, e0, n0
        self.maat = {}

    def lisaa(self, i, j, maa):
        self.maat[(i, j)] = maa

    def at(self, xy):
        import math

        import numpy as np

        out = np.zeros(len(xy))
        for k, (x, y) in enumerate(np.asarray(xy, float)):
            i, j = math.floor((x + self.e0) / self.koko), math.floor((y + self.n0) / self.koko)
            maa = self.maat.get((i, j))
            if maa is not None:
                base = (i * self.koko - self.e0, j * self.koko - self.n0)
                out[k] = maa.at(np.array([[x - base[0], y - base[1]]]))[0]
        return out


class SeinatRuuduittainAlgoritmi(QgsProcessingAlgorithm):
    PILVI = "PILVI"
    LAAJUUS = "LAAJUUS"
    PROFIILI = "PROFIILI"
    RUUTU = "RUUTU"
    KATTOLUOKKA = "KATTOLUOKKA"
    KATTO_ETAISYYS = "KATTO_ETAISYYS"
    DXF = "DXF"
    SEINAT = "SEINAT"
    POISTETUT = "POISTETUT"

    def createInstance(self):  # noqa: N802
        return SeinatRuuduittainAlgoritmi()

    def name(self):
        return "seinalinjat_ruuduittain"

    def displayName(self):  # noqa: N802
        return "Seinälinjat isosta pistepilvestä (ruuduittain)"

    def shortHelpString(self):  # noqa: N802
        return ("Seinälinjat isosta pistepilvestä, esimerkiksi kaupungin ajoneuvo- ja ilmakeilauksesta (satoja "
                "miljoonia pisteitä, gigatavuja), joka ei mahdu kerralla muistiin. Pilvi luetaan ruutu "
                f"kerrallaan ({LIMITYS_M:.0f} m limityksellä), seinät tunnistetaan kuten työkalulla Seinälinjat "
                "pistepilvestä ja ruutujen saumoista poistetaan tuplat.\n\n"
                "Rajaus luetaan COPC-tiedostosta: jos LAZ:n vieressä ei ole valmista .copc.laz-tiedostoa (QGIS "
                "tekee sen, kun pilvi avataan karttaan), se tehdään kerran samaan kansioon. Alue: koko pilvi "
                "tai kartalta piirretty alue.\n\n"
                "Kattosuodatin: ilmakeilauksen rakennusluokan (ASPRS 6) pisteet ovat kattoja. Ajoneuvokeilaus "
                "näkee kadun varressa myös aidat, pensasaidat ja muurit; niiden vieressä ei ole kattoa, joten "
                "linjat, joiden pituudesta alle puolet on katon lähellä, menevät tasolle 'Kattosuodattimen "
                "poistamat'. Luokka -1 = ei suodatinta.\n\n"
                "Laite 'Ilmakeilauksen seinäluokka': ruuduista luetaan vain luokan 13 seinäpisteet (nopea, "
                "tarkkuus desimetriluokkaa).\n\n"
                "Muisti: yksi ruutu kerrallaan (tiheä katu 150 m ruudussa noin 2–3 Gt). Isompi ruutu on nopeampi "
                "mutta vie enemmän muistia ja tilapäistä levytilaa.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile(
            self.PILVI, "Pistepilvi (LAS/LAZ/COPC)", behavior=QgsProcessingParameterFile.Behavior.File,
            fileFilter="Pistepilvi (*.las *.laz *.LAS *.LAZ)"))
        self.addParameter(QgsProcessingParameterExtent(
            self.LAAJUUS, "Alue (valinnainen, tyhjä = koko pistepilvi)", optional=True))
        self.addParameter(QgsProcessingParameterEnum(
            self.PROFIILI, "Laite", options=[n for n, _ in PROFIILIT], defaultValue=0))
        self.addParameter(QgsProcessingParameterNumber(
            self.RUUTU, "Ruudun koko (m)", type=QgsProcessingParameterNumber.Type.Double, defaultValue=150.0,
            minValue=50.0, maxValue=500.0))
        self.addParameter(QgsProcessingParameterNumber(
            self.KATTOLUOKKA, "Kattojen luokka (ilmakeilauksen rakennus, -1 = ei kattosuodatinta)",
            type=QgsProcessingParameterNumber.Type.Integer, defaultValue=6, minValue=-1, maxValue=255))
        self.addParameter(QgsProcessingParameterNumber(
            self.KATTO_ETAISYYS, "Seinä enintään näin kaukana katosta (m)",
            type=QgsProcessingParameterNumber.Type.Double, defaultValue=1.5, minValue=0.5, maxValue=5.0))
        self.addParameter(QgsProcessingParameterFileDestination(
            self.DXF, "Tallenna seinälinjat DXF:ksi (valinnainen)", fileFilter="DXF (*.dxf)", optional=True,
            createByDefault=False))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SEINAT, "Seinälinjat (ruuduittain)", QgsProcessing.SourceType.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.POISTETUT, "Kattosuodattimen poistamat", QgsProcessing.SourceType.TypeVectorLine, optional=True,
            createByDefault=False))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        # Pitkä ajo: ei App Napia (macOS) eikä nukahtamista, säie täydelle nopeudelle (ydin.valveilla)
        with ydin.valveilla():
            return self._aja(parameters, context, feedback)

    def _aja(self, parameters, context, feedback):
        import numpy as np

        polku = self.parameterAsFile(parameters, self.PILVI, context)
        try:
            koord = ydin.las_koordinaatisto(polku)
        except (OSError, ValueError) as e:
            raise QgsProcessingException(str(e))
        feedback.pushInfo(f"Pistepilven koordinaatisto: {koord['selitys']}.")
        koko = self.parameterAsDouble(parameters, self.RUUTU, context)
        kattoluokka = self.parameterAsInt(parameters, self.KATTOLUOKKA, context)
        katto_etaisyys = self.parameterAsDouble(parameters, self.KATTO_ETAISYYS, context)
        profiili = PROFIILIT[self.parameterAsEnum(parameters, self.PROFIILI, context)][1]

        alue = _gk25_alue(ydin.las_alue(polku), koord, context)
        if parameters.get(self.LAAJUUS) not in (None, ""):
            r = self.parameterAsExtent(parameters, self.LAAJUUS, context, QgsCoordinateReferenceSystem(GK25))
            if not r.isNull() and r.width() > 0 and r.height() > 0:
                alue = (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum())
        if alue is None:
            raise QgsProcessingException("Pistepilven aluetta ei saatu otsikosta.")
        ruudut = ydin.ruudut(*alue, koko)
        feedback.pushInfo(f"Alue {alue[2] - alue[0]:.0f} x {alue[3] - alue[1]:.0f} m: {len(ruudut)} ruutua "
                          f"({koko:.0f} m).")
        lahde = _copc(polku, context, feedback)
        if feedback.isCanceled():
            return {}

        e0, n0 = ruudut[0][2], ruudut[0][3]               # paikallisten koordinaattien origo
        katto = None
        if kattoluokka >= 0:
            katto = ydin.Kattorasteri((alue[0] - LIMITYS_M, alue[1] - LIMITYS_M, alue[2] + LIMITYS_M,
                                       alue[3] + LIMITYS_M), KATTOSOLU_M)
        maa = _RuutujenMaa(koko, e0, n0)
        loydetyt, opt, alku = {}, None, time.time()
        for k, (i, j, re, rn) in enumerate(ruudut):
            if feedback.isCanceled():
                return {}
            feedback.setProgress(5 + 85 * k / len(ruudut))
            rajaus = QgsGeometry.fromRect(QgsRectangle(re - LIMITYS_M, rn - LIMITYS_M, re + koko + LIMITYS_M,
                                                       rn + koko + LIMITYS_M))
            tulos = rajaa_pilvi(lahde, rajaus, koord, f"ruutu_{i}_{j}", context, feedback)
            if tulos is None:
                return {}
            luettava, rajattu = tulos
            try:
                xyz, origo, luokka = ydin.lue_las_paikallinen(luettava, luokat=True)
            except Exception as e:
                raise QgsProcessingException(f"Ruutua ei voitu lukea: {e}")
            finally:
                if rajattu:
                    try:
                        os.remove(luettava)
                    except OSError:
                        pass
            origo[0] += koord["siirto_x"]
            if katto is not None and len(xyz):
                kattoa = luokka == kattoluokka
                katto.lisaa(xyz[kattoa, :2] + origo[:2])
                xyz, luokka = xyz[~kattoa], luokka[~kattoa]
            if len(xyz) < MIN_PISTEITA:
                continue
            if opt is None:
                if profiili == "auto":
                    otsikosta = sp.las_profile(polku)
                    profiili = otsikosta or sp.guess_profile(xyz)
                    feedback.pushInfo(f"Laite: {profiili} ({'LAS-otsikosta' if otsikosta else 'pistetiheydestä'}).")
                opt = sp.WallOptions.for_cloud(None, profiili)
            if profiili == "als":
                seina = luokka == ALS_SEINALUOKKA       # ilmakeilauksesta vain seinäluokka (jos on)
                if seina.any():
                    xyz = xyz[seina]
            del luokka
            if len(xyz) < MIN_PISTEITA:
                continue
            xyz[:, :2] += (origo[:2] - (re, rn)).astype(np.float32)          # ruudun omiin koordinaatteihin
            t0 = time.time()
            segs = sp.extract_walls(xyz, opt)
            loydetyt[(i, j)] = sp.tile_core(segs, (re - e0, rn - n0), koko)
            maa.lisaa(i, j, sp.Ground(sp.ground_sample(xyz), opt.ground_cell))
            feedback.pushInfo(f"Ruutu {k + 1}/{len(ruudut)}: {len(xyz) / 1e6:.1f} milj. pistettä, "
                              f"{sum(d >= 0 for _, d in loydetyt[(i, j)])} linjaa ({time.time() - t0:.0f} s).")
            del xyz

        segs = sp.drop_seam_duplicates(loydetyt)
        osuus = None
        if katto is not None and katto.rasteri.any():
            osuus = sp.roof_share(segs, katto.rasteri, katto.solu, katto_etaisyys,
                                  offset=(e0 - katto.e0, n0 - katto.n0))
        elif katto is not None:
            feedback.pushWarning(f"Pilvessä ei ole luokan {kattoluokka} pisteitä: kattosuodatinta ei käytetty.")
        pidetty = [True] * len(segs) if osuus is None else [bool(o >= KATTO_OSUUS) for o in osuus]
        pidetyt = [s for s, p in zip(segs, pidetty) if p]
        feedback.pushInfo(f"{len(pidetyt)} seinälinjaa, {sum(s.length for s in pidetyt):.0f} m "
                          f"({(time.time() - alku) / 60:.1f} min)."
                          + (f" Kattosuodatin poisti {len(segs) - len(pidetyt)} linjaa "
                             f"({sum(s.length for s, p in zip(segs, pidetty) if not p):.0f} m)." if osuus is not None
                             else ""))
        feedback.setProgress(92)

        crs = QgsCoordinateReferenceSystem(GK25)
        tulokset_id = {}
        seinat, tulokset_id[self.SEINAT] = self.parameterAsSink(parameters, self.SEINAT, context, RUUTUKENTAT,
                                                                Qgis.WkbType.LineString, crs)
        poistetut, poistetut_id = self.parameterAsSink(parameters, self.POISTETUT, context, RUUTUKENTAT,
                                                       Qgis.WkbType.LineString, crs)
        for k, s in enumerate(segs, start=1):
            kohde = seinat if pidetty[k - 1] else poistetut
            if kohde is None:
                continue
            info = s.info or {}
            korkeus = info.get("korkeus") or (None, None)
            for a, b, mitattu, varma in sp.measured_pieces([s]):
                f = QgsFeature(RUUTUKENTAT)
                f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(a[0] + e0, a[1] + n0),
                                                          QgsPointXY(b[0] + e0, b[1] + n0)]))
                f.setAttributes(["PAATELTY" if not mitattu else "SEINA" if varma else "EPAVARMA",
                                 round(float(((b - a) ** 2).sum() ** 0.5), 3), f"Seinä {k}", _m(korkeus[0]),
                                 _m(korkeus[1]), _cm(info.get("sokkeli")), _m(info.get("sokkeli_yla")),
                                 _cm(info.get("pinta")), _cm(info.get("kohina")), _cm(info.get("kallistus")),
                                 None if osuus is None else round(float(osuus[k - 1]), 2)])
                kohde.addFeature(f, QgsFeatureSink.Flag.FastInsert)
        if poistetut is not None:
            tulokset_id[self.POISTETUT] = poistetut_id

        dxf_polku = self.parameterAsFileOutput(parameters, self.DXF, context)
        if dxf_polku and pidetyt:
            sp.write_dxf_r12(dxf_polku, _dxf_viivat(pidetyt, maa, e0, n0))
            feedback.pushInfo(f"DXF: {dxf_polku}")
            tulokset_id[self.DXF] = dxf_polku
        aseta_tyylit(context, [(tulokset_id.get(self.SEINAT), "pilven_seinat"), (poistetut_id, "pilven_seinat")])
        return tulokset_id
