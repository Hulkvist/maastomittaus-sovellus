"""Processing-työkalu: Seinälinja JXL-tiedostosta. Tasoille tulevat vain seinälinja, lasketut
kulmat ja poikkeama kantakartasta; mitatut pisteet tulevat QGIS:iin muuta kautta. Valinnaisesti
LiDAR-keilauksen seinät (lidarpipe) piilokulmien ja järjestyksen apuna ja vertailuun sekä
pistepilvi karttaan."""

import os

from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsFeatureSink, QgsField, QgsFields, QgsGeometry,
                       QgsLineString, QgsPoint, QgsPointXY, QgsProcessing, QgsProcessingAlgorithm, QgsProcessingException,
                       QgsProcessingParameterBoolean, QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSink, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFile, QgsProcessingParameterString, Qgis)
from qgis.PyQt.QtCore import QMetaType

from . import kantakartta as kk
from . import lidar as ld
from . import ydin
from .tyylit import aseta_tyylit
from .ydin import sl


def _keskikorkeus(viiva):
    """Viivan kärkien korkeuksien keskiarvo (3D-näkymän seinän korkeus), tai None."""
    korkeudet = [k["z"] for k in viiva["karjet"] if k.get("z") is not None]
    return round(sum(korkeudet) / len(korkeudet), 3) if korkeudet else None


def _cm(arvo_m):
    return round(arvo_m * 100, 1) if arvo_m is not None else None


def lisaa_seinapalat(kohde, viiva, naytteet, luokat):
    """Viivan Seinät 3D -palat tasolle (ydin.seinapalat); naytteet = [(e, n, ero_m tai None)] tai None."""
    for kulmat_xy, korkeus, ero in ydin.seinapalat(viiva, naytteet=naytteet):
        f = QgsFeature(SEINA3DKENTAT)
        f.setGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(e, n) for e, n in kulmat_xy]]))
        f.setAttributes([viiva["nimi"], None if korkeus is None else round(korkeus, 3), _cm(ero),
                         _cm(None if ero is None else abs(ero)),
                         None if ero is None else ydin.poikkeamaluokka(abs(ero), luokat)[0]])
        kohde.addFeature(f, QgsFeatureSink.Flag.FastInsert)


def _kentat(*maaritykset):
    kentat = QgsFields()
    for nimi, tyyppi in maaritykset:
        kentat.append(QgsField(nimi, tyyppi))
    return kentat


TEKSTI, LUKU, KOKONAISLUKU, TOTUUS = (QMetaType.Type.QString, QMetaType.Type.Double, QMetaType.Type.Int,
                                      QMetaType.Type.Bool)
GK25 = "EPSG:3879"
JXL_SUODATIN = "JobXML (*.jxl *.JXL *.xml *.XML)"
VIIVAKENTAT = _kentat(("nimi", TEKSTI), ("kohde", TEKSTI), ("rakennetyyppi", TEKSTI), ("numero", KOKONAISLUKU),
                      ("suljettu", TOTUUS), ("pituus_m", LUKU), ("karkia", KOKONAISLUKU), ("korkeus_m", LUKU),
                      ("poikkeama_ka_cm", LUKU), ("poikkeama_max_cm", LUKU), ("poikkeama_lidar_ka_cm", LUKU),
                      ("poikkeama_lidar_max_cm", LUKU), ("lidar_peitto_pct", LUKU), ("tyo", TEKSTI),
                      ("tiedosto", TEKSTI))
KULMAKENTAT = _kentat(("nimi", TEKSTI), ("viiva", TEKSTI), ("korkeus", LUKU))
POIKKEAMAKENTAT = _kentat(("viiva", TEKSTI), ("poikkeama_cm", LUKU), ("luokka", TEKSTI))
LIDARKENTAT = _kentat(("taso", TEKSTI), ("pituus_m", LUKU))
# Seinät 3D: ero_cm = vertailun poikkeama palan kohdalla (pistepilvestä etumerkillinen, + = seinä
# ulompana), luokka värittää seinän (ks. tyylit._seina_3d)
SEINA3DKENTAT = _kentat(("viiva", TEKSTI), ("korkeus_m", LUKU), ("ero_cm", LUKU), ("poikkeama_cm", LUKU),
                        ("luokka", TEKSTI))


class SeinalinjaJxlAlgoritmi(QgsProcessingAlgorithm):
    JXL = "JXL"
    TAPA = "TAPA"
    RAKENNUKSET = "RAKENNUKSET"
    HAE_HELSINKI = "HAE_HELSINKI"
    KANTAKARTTA_JARJESTYKSEEN = "KANTAKARTTA_JARJESTYKSEEN"
    NAKYVYYS = "NAKYVYYS"
    LIDAR = "LIDAR"
    PISTEPILVI = "PISTEPILVI"
    LUOKAT = "LUOKAT"
    SEINALINJA = "SEINALINJA"
    SEINAT_3D = "SEINAT_3D"
    KULMAT = "KULMAT"
    POIKKEAMA = "POIKKEAMA"
    LIDAR_SEINAT = "LIDAR_SEINAT"
    POIKKEAMA_LIDAR = "POIKKEAMA_LIDAR"

    def createInstance(self):  # noqa: N802
        return SeinalinjaJxlAlgoritmi()

    def name(self):
        return "seinalinja_jxl"

    def displayName(self):  # noqa: N802
        return "Lännen nopein seinälinja"

    def shortHelpString(self):  # noqa: N802
        return ("Seinälinja JXL-tiedostosta. Muodostaa seinälinjan JobXML-tiedoston (.jxl) pisteistä samoilla säännöillä kuin "
                "Tietokanta-sovellus: 8 = viivan alku/loppu, 5 = kulma, 100 = piste seinällä, 4 = kaari "
                "(myös RAK 8, RAK 5 ...). Kohdekoodit ja rakennetyyppi (esim. Sokkeli) erottavat viivat.\n\n"
                "Tasoille tulevat vain seinälinja, lasketut piilokulmat ja poikkeama kantakartasta; "
                "mitattuja pisteitä ei tuoda.\n\n"
                "Kantakartta: valitse rakennustaso, tai Helsingissä rakennukset haetaan kaupungin avoimesta "
                "WFS-palvelusta. Poikkeama-taso näyttää viivaa pitkin 25 cm välein, kuinka kaukana viiva on "
                "kantakartan rakennuksen reunasta (luokkarajat valittavissa, oletuksena 3, 5 ja 15 cm: "
                "tummanvihreä, vaaleanvihreä, keltainen ja punainen). "
                "Varoitukset ja kantakartan riskit näkyvät lokissa.\n\n"
                "LiDAR (kokeilu): valitse keilauksen seinät (lidarpipen <nimi>_seinat.dxf). Piilokulman "
                "seinän suunta otetaan LiDAR-seinästä suoran kulman oletuksen sijaan, ja jos seinistä syntyy "
                "suljettu ääriviiva, järjestys otetaan siitä, kun sitä ei saada seinälinjoista. Lisäksi tasot "
                "LiDAR-seinät ja Poikkeama LiDARista (kohdat ilman LiDAR-seinää jäävät pois), ja valittaessa "
                "pistepilvi (<nimi>.las samasta kansiosta) karttaan.\n\n"
                "3D-näkymä (Näytä -> 3D-karttanäkymät): taso Seinät 3D näyttää seinälinjan 3 m korkeana "
                "seinänä, jonka keskellä on mitattu korkeus; sitä voi verrata pistepilven seinäpintaan.")

    def initAlgorithm(self, config=None):  # noqa: N802
        self.addParameter(QgsProcessingParameterFile(
            self.JXL, "JXL-tiedosto", behavior=QgsProcessingParameterFile.Behavior.File,
            fileFilter=JXL_SUODATIN))
        self.addParameter(QgsProcessingParameterEnum(
            self.TAPA, "Pisteiden järjestys 8-pisteiden välillä", options=[n for n, _ in ydin.TAVAT], defaultValue=0))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.RAKENNUKSET, "Rakennustaso kantakartaksi (valinnainen)",
            [QgsProcessing.SourceType.TypeVectorPolygon], optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.HAE_HELSINKI, "Hae Helsingin kantakartan rakennukset, jos rakennustasoa ei ole valittu",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.KANTAKARTTA_JARJESTYKSEEN, "Käytä kantakarttaa järjestyksen apuna (Automaattinen)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.NAKYVYYS, "Tarkista näkyvyys asemapisteiltä (pois, jos seiniä ei vielä ole, esim. pelkkä sokkeli)",
            defaultValue=True))
        self.addParameter(QgsProcessingParameterFile(
            self.LIDAR, "LiDAR-seinät (valinnainen, lidarpipen _seinat.dxf)",
            behavior=QgsProcessingParameterFile.Behavior.File, fileFilter="LiDAR-seinät (*_seinat.dxf *.dxf)",
            optional=True))
        self.addParameter(QgsProcessingParameterBoolean(
            self.PISTEPILVI, "Lataa keilauksen pistepilvi (LAS samasta kansiosta) karttaan", defaultValue=False))
        self.addParameter(QgsProcessingParameterString(
            self.LUOKAT, "Poikkeaman luokkarajat (cm, välilyönnein, esim. 3 5 15)",
            defaultValue=ydin.LUOKKARAJAT_OLETUS, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SEINALINJA, "Seinälinja", QgsProcessing.SourceType.TypeVectorLine))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.SEINAT_3D, "Seinät 3D", QgsProcessing.SourceType.TypeVectorPolygon,
            optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.KULMAT, "Lasketut kulmat", QgsProcessing.SourceType.TypeVectorPoint, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.POIKKEAMA, "Poikkeama kantakartasta", QgsProcessing.SourceType.TypeVectorPoint, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.LIDAR_SEINAT, "LiDAR-seinät", QgsProcessing.SourceType.TypeVectorLine, optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.POIKKEAMA_LIDAR, "Poikkeama LiDARista", QgsProcessing.SourceType.TypeVectorPoint, optional=True))

    def _lidar(self, parameters, context, feedback):
        """LiDAR-seinät DXF:stä ja keilauksen tiedot lokiin: (seinät, kaikki tasot, viereiset tiedostot)."""
        dxf = self.parameterAsFile(parameters, self.LIDAR, context)
        if not dxf:
            return None, {}, {}
        try:
            tasot = ld.lue_seinat(dxf)
        except Exception as e:
            feedback.pushWarning(f"LiDAR-seiniä ei saatu ({e}) -- jatketaan ilman niitä.")
            return None, {}, {}
        viereiset = ld.viereiset_tiedostot(dxf)
        paatelty = f", {len(tasot[ld.PAATELTY])} päätelty (vain järjestykseen)" if tasot[ld.PAATELTY] else ""
        feedback.pushInfo(f"LiDAR: {len(tasot[ld.SEINA])} seinää, {len(tasot[ld.EPAVARMA])} epävarmaa{paatelty} "
                          f"({os.path.basename(dxf)}).")
        if viereiset["raportti"]:
            try:
                for rivi in ydin.keilausraportti(viereiset["raportti"]):
                    feedback.pushInfo(f"Keilaus: {rivi}")
            except Exception as e:
                feedback.pushInfo(f"Keilauksen raporttia ei voitu lukea ({e}).")
        return tasot[ld.SEINA] or None, tasot, viereiset

    def _kantakartta(self, parameters, context, feedback, pisteet):
        alue = ydin.seinalinjan_alue(pisteet)
        lahde = self.parameterAsSource(parameters, self.RAKENNUKSET, context)
        try:
            if lahde is not None:
                rakennukset = kk.rakennukset_tasosta(lahde, alue, context)
                kuvaus = "valitulta rakennustasolta"
            elif self.parameterAsBoolean(parameters, self.HAE_HELSINKI, context) and \
                    kk.on_helsingissa(alue, context.transformContext()):
                feedback.pushInfo("Haetaan Helsingin kantakartan rakennukset...")
                rakennukset = kk.hae_helsinki(alue, context.transformContext())
                kuvaus = "Helsingin kantakartasta"
            else:
                feedback.pushInfo("Kantakarttaa ei käytetä (ei rakennustasoa, kohde ei ole Helsingissä tai "
                                  "haku on pois päältä).")
                return None
        except Exception as e:
            feedback.pushWarning(f"Kantakartan rakennuksia ei saatu ({e}) -- jatketaan ilman niitä.")
            return None
        if not rakennukset:
            feedback.pushInfo(f"Seinälinjan alueella ei ole rakennuksia {kuvaus}.")
            return None
        feedback.pushInfo(f"Kantakartta: {len(rakennukset)} {'rakennus' if len(rakennukset) == 1 else 'rakennusta'} {kuvaus}.")
        return rakennukset

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        polku = self.parameterAsFile(parameters, self.JXL, context)
        try:
            luokat = ydin.poikkeamaluokat(ydin.lue_luokkarajat(self.parameterAsString(parameters, self.LUOKAT, context)))
        except ValueError as e:
            raise QgsProcessingException(str(e))
        try:
            raportti, pisteet, _ = ydin.lue_jxl(polku)
        except Exception as e:
            raise QgsProcessingException(f"JXL-tiedostoa ei voitu lukea: {e}")
        if not sl.on_seinalinjapisteita(pisteet):
            raise QgsProcessingException("Tiedostossa ei ole viivan alkupistettä (koodi 8, esim. 8 tai RAK 8), "
                                         "joten seinälinjaa ei voi muodostaa.")
        feedback.pushInfo(f"{raportti['job_nimi']}: {len(sl.seinalinjan_pisteet(pisteet))} seinälinjan pistettä, "
                          f"koodikirjasto {raportti.get('koodikirjasto')}.")

        kantakartta = self._kantakartta(parameters, context, feedback, pisteet)
        lidar, lidar_tasot, viereiset = self._lidar(parameters, context, feedback)
        tapa = ydin.TAVAT[self.parameterAsEnum(parameters, self.TAPA, context)][1]
        tulokset = ydin.muodosta(pisteet, tapa, kantakartta,
                                 self.parameterAsBoolean(parameters, self.KANTAKARTTA_JARJESTYKSEEN, context), lidar,
                                 lidar_tasot.get(ld.PAATELTY),
                                 self.parameterAsBoolean(parameters, self.NAKYVYYS, context))
        tulos, poikkeamat, poikkeamat_lidar = tulokset["tulos"], tulokset["poikkeamat"], tulokset["poikkeamat_lidar"]
        if lidar:
            feedback.pushInfo("LiDAR-seinistä syntyi suljettu ääriviiva (käytetään järjestyksen apuna)."
                              if tulokset["lidar_aariviiva"] else
                              "LiDAR-seinistä ei syntynyt suljettua ääriviivaa (keilaus kattaa vain osan talosta?), "
                              "joten järjestystä ei oteta LiDARista; piilokulmat ja vertailu toimivat silti.")

        for varoitus in tulos["varoitukset"]:
            feedback.pushWarning(varoitus)
        for riski in tulokset["riskit"]:
            feedback.pushInfo(f"Kantakartan talossa huomioitavaa: {riski}")
        for nimi, p in poikkeamat.items():
            feedback.pushInfo(f"{nimi}: poikkeaa kantakartasta keskimäärin {p['keskiarvo_m'] * 100:.0f} cm, "
                              f"enimmillään {p['suurin_m'] * 100:.0f} cm.")
        for nimi, p in poikkeamat_lidar.items():
            if p["keskiarvo_m"] is None:
                feedback.pushInfo(f"{nimi}: LiDAR-seinät eivät kata viivaa.")
            else:
                feedback.pushInfo(f"{nimi}: poikkeaa LiDAR-seinistä keskimäärin {p['keskiarvo_m'] * 100:.1f} cm, "
                                  f"enimmillään {p['suurin_m'] * 100:.1f} cm (LiDAR kattaa {p['peitto'] * 100:.0f} % "
                                  "viivasta).")

        crs = QgsCoordinateReferenceSystem(GK25)
        tulokset_id = {}
        # Seinälinja 3D-viivana: korkeus = kärkien mitattu korkeus (3D-näkymässä seinä pistepilven kohdalla)
        viivat, viivat_id = self.parameterAsSink(parameters, self.SEINALINJA, context, VIIVAKENTAT,
                                                 Qgis.WkbType.LineStringZ, crs)
        tulokset_id[self.SEINALINJA] = viivat_id
        for viiva in tulos["viivat"]:
            xyz = sl.viivan_pisteet_z(viiva)
            if len(xyz) < 2:
                continue
            if xyz[0][2] is None:
                feedback.pushInfo(f"{viiva['nimi']}: pisteillä ei ole korkeuksia, joten viiva on 3D-näkymässä "
                                  "korkeudella 0.")
            geom = QgsGeometry(QgsLineString([QgsPoint(e, n, z or 0.0) for e, n, z in xyz]))
            poikkeama = poikkeamat.get(viiva["nimi"])
            p_lidar = poikkeamat_lidar.get(viiva["nimi"]) or {}
            tiedot = ydin.viivan_tiedot(viiva)
            f = QgsFeature(VIIVAKENTAT)
            f.setGeometry(geom)
            f.setAttributes([viiva["nimi"], tiedot["kohde"], tiedot["rakennetyyppi"], tiedot["numero"],
                             viiva["suljettu"], round(geom.length(), 3), len(viiva["karjet"]),
                             _keskikorkeus(viiva),
                             round(poikkeama["keskiarvo_m"] * 100, 1) if poikkeama else None,
                             round(poikkeama["suurin_m"] * 100, 1) if poikkeama else None,
                             _cm(p_lidar.get("keskiarvo_m")), _cm(p_lidar.get("suurin_m")),
                             round(p_lidar["peitto"] * 100, 0) if p_lidar else None,
                             raportti["job_nimi"], os.path.basename(polku)])
            viivat.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        # Seinät 3D-näkymään: ohuet monikulmiot korkeuskentällä (ks. tyylit._seina_3d)
        seinat3d, seinat3d_id = self.parameterAsSink(parameters, self.SEINAT_3D, context, SEINA3DKENTAT,
                                                     Qgis.WkbType.Polygon, crs)
        if seinat3d is not None:
            tulokset_id[self.SEINAT_3D] = seinat3d_id
            for viiva in tulos["viivat"]:
                # LiDARin kanssa seinä väritetään poikkeaman mukaan
                vertailu = poikkeamat_lidar.get(viiva["nimi"])
                lisaa_seinapalat(seinat3d, viiva, vertailu["naytteet"] if vertailu else None, luokat)

        kulmat, kulmat_id = self.parameterAsSink(parameters, self.KULMAT, context, KULMAKENTAT,
                                                 Qgis.WkbType.Point, crs)
        if kulmat is not None:
            tulokset_id[self.KULMAT] = kulmat_id
            for viiva in tulos["viivat"]:
                for k in viiva["karjet"]:
                    if k["laji"] != "laskettu":
                        continue
                    f = QgsFeature(KULMAKENTAT)
                    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(k["e"], k["n"])))
                    f.setAttributes([k["nimi"], viiva["nimi"], round(k["z"], 3) if k.get("z") is not None else None])
                    kulmat.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        naytteet, naytteet_id = self.parameterAsSink(parameters, self.POIKKEAMA, context, POIKKEAMAKENTAT,
                                                     Qgis.WkbType.Point, crs)
        if naytteet is not None:
            tulokset_id[self.POIKKEAMA] = naytteet_id
            for nimi, p in poikkeamat.items():
                for e, n, d in p["naytteet"]:
                    f = QgsFeature(POIKKEAMAKENTAT)
                    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(e, n)))
                    f.setAttributes([nimi, round(d * 100, 1), ydin.poikkeamaluokka(d, luokat)[0]])
                    naytteet.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        if lidar_tasot:
            seinat, seinat_id = self.parameterAsSink(parameters, self.LIDAR_SEINAT, context, LIDARKENTAT,
                                                     Qgis.WkbType.LineString, crs)
            if seinat is not None:
                tulokset_id[self.LIDAR_SEINAT] = seinat_id
                for taso, janat in lidar_tasot.items():
                    for a, b in janat:
                        f = QgsFeature(LIDARKENTAT)
                        f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*a), QgsPointXY(*b)]))
                        f.setAttributes([taso, round(f.geometry().length(), 3)])
                        seinat.addFeature(f, QgsFeatureSink.Flag.FastInsert)
        if poikkeamat_lidar:
            naytteet, naytteet_id = self.parameterAsSink(parameters, self.POIKKEAMA_LIDAR, context, POIKKEAMAKENTAT,
                                                         Qgis.WkbType.Point, crs)
            if naytteet is not None:
                tulokset_id[self.POIKKEAMA_LIDAR] = naytteet_id
                for nimi, p in poikkeamat_lidar.items():
                    for e, n, d in p["naytteet"]:
                        if d is None:
                            continue
                        f = QgsFeature(POIKKEAMAKENTAT)
                        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(e, n)))
                        f.setAttributes([nimi, round(d * 100, 1), ydin.poikkeamaluokka(d, luokat)[0]])
                        naytteet.addFeature(f, QgsFeatureSink.Flag.FastInsert)

        pistepilvi = None
        if self.parameterAsBoolean(parameters, self.PISTEPILVI, context):
            if viereiset.get("las"):
                pistepilvi = (viereiset["las"], f"Pistepilvi ({os.path.basename(viereiset['las'])})")
            else:
                feedback.pushWarning("Pistepilveä (.las) ei löytynyt LiDAR-seinien DXF:n vierestä.")

        # Pistepilvi lisätään karttaan vasta ajon jälkeen pääsäikeessä (ks. tyylit._Tyyli)
        lisataan = aseta_tyylit(context, [(tulokset_id.get(self.SEINALINJA), "viiva"),
                                          (tulokset_id.get(self.SEINAT_3D), "seinat_3d"),
                                          (tulokset_id.get(self.KULMAT), "kulmat"),
                                          (tulokset_id.get(self.POIKKEAMA), "poikkeama"),
                                          (tulokset_id.get(self.LIDAR_SEINAT), "lidar_seinat"),
                                          (tulokset_id.get(self.POIKKEAMA_LIDAR), "poikkeama")],
                                pistepilvi, luokat)
        if pistepilvi and lisataan:
            feedback.pushInfo(f"Pistepilvi lisätään karttaan ajon jälkeen ({os.path.getsize(pistepilvi[0]) / 1e6:.0f} "
                              "Mt). QGIS tekee ensimmäisellä avauksella indeksin, joten pisteet tulevat näkyviin "
                              "hetken kuluttua.")
        elif pistepilvi:
            feedback.pushWarning("Pistepilvi lisätään karttaan vain, kun jokin tulostaso avataan karttaan.")
        return tulokset_id
