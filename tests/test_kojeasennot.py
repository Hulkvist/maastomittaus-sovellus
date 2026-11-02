"""Kahden kojeasennon (Face1/Face2 -> MTA) havaintojen yhdistäminen synteettisillä JobXML-töillä:
RTK:lla mitattu liitospiste ei sulaudu takymetrin MTA:han, toiselta asemalta mitattu samanniminen piste
säilyy, ja kierrosten ja monen liitospisteen Face-havainnot löytyvät kaukaakin."""
import math
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jobxml_tuonti as jx

N, E = 6672000.0, 25496000.0
GNSS_LAATU = ("<QualityControl1><PDOP>1.4</PDOP><HDOP>0.8</HDOP><VDOP>1.1</VDOP>"
              "<NumberOfSatellites>18</NumberOfSatellites></QualityControl1>")


class Tyo:
    def __init__(self):
        self.osat, self.n, self.lopulliset = [], 0x100, []

    def _id(self):
        self.n += 1
        return f"{self.n:08x}", f"2026-10-01T10:{self.n // 60 % 60:02d}:{self.n % 60:02d}"

    def asema(self, nimi, tyyppi="StandardResection"):
        i, t = self._id()
        self.osat.append(f'<StationRecord ID="{i}" TimeStamp="{t}"><StationName>{nimi}</StationName>'
                         f'<TheodoliteHeight>1.5</TheodoliteHeight><StationType>{tyyppi}</StationType>'
                         '</StationRecord>')
        return i

    def piste(self, nimi, koodi, n, e, luokka="Normal", method="DirectReading", face="Face1", asema=None,
              lisa=""):
        i, t = self._id()
        kehä = (f"<Circle><HorizontalCircle>1</HorizontalCircle><VerticalCircle>90</VerticalCircle>"
                f"<EDMDistance>5</EDMDistance><Face>{face}</Face></Circle>") if face else ""
        st = f"<StationID>{asema}</StationID>" if asema else ""
        self.osat.append(f'<PointRecord ID="{i}" TimeStamp="{t}"><Name>{nimi}</Name><Code>{koodi}</Code>'
                         f'<Method>{method}</Method><SurveyMethod>Fix</SurveyMethod>'
                         f'<Classification>{luokka}</Classification><Deleted>false</Deleted>{kehä}{st}{lisa}'
                         f'<ComputedGrid><North>{n}</North><East>{e}</East><Elevation>10</Elevation>'
                         '</ComputedGrid></PointRecord>')

    def kahdesti(self, nimi, n, e, asema):
        for f in ("Face1", "Face2"):
            self.piste(nimi, "LIP", n, e, luokka="BackSight", face=f, asema=asema)

    def mta(self, nimi, n, e, asema, koodi="LIP"):
        self.piste(nimi, koodi, n, e, luokka="MTA", method="MeanTurnedAngle", face=None, asema=asema)

    def resektio(self, nimi, asema):
        self.piste(nimi, "", N, E, method="Resection", face=None, asema=asema)

    def lopullinen(self, nimi, n, e):
        """Piste Reductions-osioon (esim. koordinaattilistasta tuotu kiintopiste ilman PointRecordia)."""
        self.lopulliset.append(f"<Point><Name>{nimi}</Name><Code>KP</Code><Grid><North>{n}</North>"
                               f"<East>{e}</East><Elevation>12</Elevation></Grid></Point>")

    def jasenna(self):
        xml = ('<?xml version="1.0"?><JOBFile jobName="syn" product="x" TimeStamp="2026-10-01T10:00:00">'
               "<FieldBook>" + "".join(self.osat) + "</FieldBook>"
               "<Reductions>" + "".join(self.lopulliset) + "</Reductions></JOBFile>")
        return jx.jasenna_tyo(xml.encode())


def test_rtk_liitospisteet_eivat_sulaudu_mtahan():
    tyo = Tyo()
    liitokset = [("2000", N + 20, E), ("5000", N, E + 20), ("6000", N - 20, E - 5)]
    for nimi, n, e in liitokset:
        tyo.piste(nimi, "LIP", n, e, method="GpsStaticObservation", face=None, lisa=GNSS_LAATU)
    a = tyo.asema("1111")
    for nimi, n, e in liitokset:
        tyo.kahdesti(nimi, n, e, a)
    for nimi, n, e in liitokset:
        tyo.mta(nimi, n, e, a)
    tyo.resektio("1111", a)
    raportti, pisteet, _ = tyo.jasenna()
    kategoriat = Counter(p["kategoria"] for p in pisteet if p["nimi"] != "1111")
    assert kategoriat == {"Liitospiste": 3, "Liitospiste (alkuperäinen RTK-mittaus)": 3}
    asema = raportti["asemapisteet"][0]
    assert asema["liitospisteet"] == ["2000", "5000", "6000"]
    assert asema["laatu"]["liitospisteita"] == 3


def test_toiselta_asemalta_mitattu_piste_sailyy():
    tyo = Tyo()
    a = tyo.asema("A")
    for k, (dn, de) in enumerate([(10, 0), (0, 10), (-10, 0)]):
        tyo.piste(f"L{k}", "LIP", N + dn, E + de, luokka="BackSight", asema=a)
    tyo.resektio("A", a)
    tyo.piste("P", "9", N + 5, E + 5, asema=a)                  # yksi kojeasento asemalta A
    b = tyo.asema("B")
    tyo.kahdesti("P", N + 5.001, E + 5, b)                     # liitospisteenä asemalta B
    tyo.mta("P", N + 5.001, E + 5, b, koodi="9")
    _, pisteet, _ = tyo.jasenna()
    p = [(x["kategoria"], x["station_record_id"], x["kahdesta_kojeasennosta"]) for x in pisteet if x["nimi"] == "P"]
    assert p == [("Kartoituspiste", a, False), ("Liitospiste", b, True)]


def test_kierrosten_face_havainnot_kaukaakin():
    for liitoksia, kierroksia in [(4, 2), (8, 1)]:
        tyo = Tyo()
        a = tyo.asema("A")
        liitokset = [(f"L{k}", N + 10 * math.cos(k), E + 10 * math.sin(k)) for k in range(liitoksia)]
        for _ in range(kierroksia):
            for nimi, n, e in liitokset:
                tyo.kahdesti(nimi, n, e, a)
        for nimi, n, e in liitokset:
            tyo.mta(nimi, n, e, a)
        tyo.resektio("A", a)
        raportti, pisteet, _ = tyo.jasenna()
        nimet = [x["nimi"] for x in pisteet if x["kategoria"] == "Liitospiste"]
        assert sorted(nimet) == [n for n, _, _ in liitokset]
        assert all(x["kahdesta_kojeasennosta"] for x in pisteet if x["kategoria"] == "Liitospiste")
        assert raportti["asemapisteet"][0]["liitospisteet"] == [n for n, _, _ in liitokset]
