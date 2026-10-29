"""Seinälinjat isosta pistepilvestä: yhden ruudun laskenta ja ruutujen rinnakkaisajo aliprosesseissa
(ruutu_algoritmi). QGIS:ssä sys.executable on itse QGIS, joten multiprocessing ei toimi; ruudut ajetaan QGIS:n
omalla Python-tulkilla erillisinä prosesseina: pisteet .npy-tiedostona, asetukset ja tulos picklenä. Sama
ruutu antaa saman tuloksen kummin tahansa (aja), ja saumojen tuplien poisto ei riipu valmistumisjärjestyksestä.

Aliprosessina: python ruututyo.py LIB TYO.pkl (tulos TYO.pkl.tulos); pelkkä LIB tarkistaa, että tulkki ja
numpy toimivat. Ei QGIS-riippuvuuksia."""

import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import time

MUISTI_GT = 4.0           # ruutu vie huipussaan enintään noin 3–4 Gt (tiheä katu, 65 milj. pistettä)
VARA_GT = 6.0             # QGIS ja ruutua lukeva pääprosessi
ENINTAAN = 4


def aja(xyz, opt, base, koko):
    """Yhden ruudun linjat (seinat_pilvesta.tile_core) ja maanpinta DXF:n korkeuksiin."""
    import seinat_pilvesta as sp

    t0 = time.time()
    segs = sp.extract_walls(xyz, opt)
    return {"linjat": sp.tile_core(segs, base, koko), "maa": sp.Ground(sp.ground_sample(xyz), opt.ground_cell),
            "pisteita": len(xyz), "aika": time.time() - t0}


def _muisti_gt():
    """Koneen keskusmuisti (Gt) tai None."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Tila(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            tila = _Tila()
            tila.dwLength = ctypes.sizeof(tila)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(tila)):
                return tila.ullTotalPhys / 2**30
            return None
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 2**30
    except (AttributeError, OSError, ValueError):
        return None


def oletus_rinnakkain(ytimet=None, muisti_gt=None):
    """Montako ruutua kerrallaan: ytimiä yksi vähemmän (QGIS lukee seuraavaa ruutua), muistia 4 Gt ruudulle
    6 Gt:n varan jälkeen, enintään 4. 16 Gt:n koneessa 2."""
    ytimet = ytimet or os.cpu_count() or 1
    muisti_gt = muisti_gt or _muisti_gt()
    n = ytimet - 1 if muisti_gt is None else min(ytimet - 1, int((muisti_gt - VARA_GT) // MUISTI_GT))
    return max(1, min(n, ENINTAAN))


def qgis_python():
    """QGIS:n Python-tulkki (Windows: apps/Python3xx/python.exe, macOS: QGIS.app/Contents/MacOS/python3.x) tai
    None. Pelkkä Python (testit) käy sellaisenaan."""
    if os.path.basename(sys.executable).lower().startswith("python"):
        return sys.executable
    versio = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for kansio in (sys.exec_prefix, os.path.join(sys.exec_prefix, "bin"), os.path.dirname(sys.executable),
                   os.path.join(os.path.dirname(sys.executable), "bin")):
        for nimi in ("python.exe", versio, "python3", "python"):
            polku = os.path.join(kansio, nimi)
            if os.path.isfile(polku):
                return polku
    return None


def _ikkunaton():
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)            # Windows: ei komentoikkunaa


def _ymparisto():
    """Tämän prosessin moduulipolut aliprosessille: macOS:n QGIS.app:n tulkki ei löydä omaa vakiokirjastoaan
    (Contents/Resources/python3.x, ei lib/-kansiota) eikä numpya ilman PYTHONPATHia."""
    env = dict(os.environ)
    polut = [p for p in sys.path if p and os.path.isdir(p)]
    if env.get("PYTHONPATH"):
        polut.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(polut)
    return env


def toimiiko(python, lib):
    """Käynnistyykö tulkki ja löytyvätkö numpy ja seinat_pilvesta (lib-kansio)."""
    try:
        return subprocess.run([python, os.path.abspath(__file__), lib], capture_output=True, timeout=120,
                              env=_ymparisto(), creationflags=_ikkunaton()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class Ruututyot:
    """Ruudut aliprosesseissa, enintään n kerrallaan: aloita(avain, ...) kun vapaa(), valmiit() palauttaa
    valmistuneet [(avain, aja-tulos)], lopeta() pysäyttää keskeneräiset ja poistaa välitiedostot."""

    def __init__(self, python, lib, n, kansio=None):
        self.python, self.lib, self.n = python, lib, n
        self.kansio = tempfile.mkdtemp(prefix="seinaruudut_", dir=kansio)
        self.kaynnissa = {}
        self._nro = 0
        self._env = _ymparisto()

    def vapaa(self):
        return len(self.kaynnissa) < self.n

    def aloita(self, avain, xyz, opt, base, koko):
        import numpy as np

        self._nro += 1
        polku = os.path.join(self.kansio, f"ruutu_{self._nro}")
        np.save(polku + ".npy", xyz)
        with open(polku + ".pkl", "wb") as f:
            pickle.dump({"pisteet": polku + ".npy", "opt": opt, "base": base, "koko": koko}, f)
        with open(polku + ".err", "wb") as virhe:
            p = subprocess.Popen([self.python, os.path.abspath(__file__), self.lib, polku + ".pkl"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=virhe,
                                 env=self._env, creationflags=_ikkunaton())
        self.kaynnissa[avain] = (p, polku)

    def valmiit(self):
        out = []
        for avain, (p, polku) in list(self.kaynnissa.items()):
            if p.poll() is None:
                continue
            del self.kaynnissa[avain]
            if p.returncode != 0 or not os.path.isfile(polku + ".pkl.tulos"):
                with open(polku + ".err", "rb") as f:
                    viesti = f.read().decode("utf-8", "replace").strip().splitlines()[-3:]
                raise RuntimeError(f"ruudun laskenta keskeytyi (koodi {p.returncode}): "
                                   + (" ".join(viesti) or "ei virheilmoitusta, muisti loppui? Pienennä "
                                      "rinnakkaisten ruutujen määrää tai ruudun kokoa."))
            with open(polku + ".pkl.tulos", "rb") as f:
                out.append((avain, pickle.load(f)))
            for paate in (".npy", ".pkl", ".pkl.tulos", ".err"):
                try:
                    os.remove(polku + paate)
                except OSError:
                    pass
        return out

    def odota(self, peruttu, vali=0.2):
        """Valmiit, kun vähintään yksi on valmistunut (tai ei ole käynnissä mitään); None, jos peruttu()."""
        while self.kaynnissa:
            out = self.valmiit()
            if out:
                return out
            if peruttu():
                return None
            time.sleep(vali)
        return []

    def lopeta(self):
        for p, _ in self.kaynnissa.values():
            if p.poll() is None:
                p.kill()
                p.wait()
        self.kaynnissa = {}
        shutil.rmtree(self.kansio, ignore_errors=True)


if __name__ == "__main__":
    sys.path.insert(0, sys.argv[1])
    import numpy as np
    import seinat_pilvesta  # noqa: F401

    if len(sys.argv) > 2:
        tyo_polku = sys.argv[2]
        with open(tyo_polku, "rb") as f:
            tyo = pickle.load(f)
        pisteet = np.load(tyo["pisteet"])
        os.remove(tyo["pisteet"])                                 # levytila: pisteet ovat nyt muistissa
        tulos = aja(pisteet, tyo["opt"], tyo["base"], tyo["koko"])
        del pisteet
        with open(tyo_polku + ".osa", "wb") as f:
            pickle.dump(tulos, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tyo_polku + ".osa", tyo_polku + ".tulos")
