"""Seinälinjat ilmakeilauksen seinäluokasta (profiili als): harva, noin 5 cm kohiseva pistejoukko koko
seinän korkeudelta, ei maanpintaa."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from seinat_pilvesta import WallOptions, extract_walls, read_wall_class  # noqa: E402

# L-talo (m), kierretty 17°: ilmakeilauksen talot ovat missä asennossa tahansa
L_TALO = [(0, 0), (20, 0), (20, 10), (12, 10), (12, 18), (0, 18)]
KULMA = np.radians(17)
R = np.array([[np.cos(KULMA), -np.sin(KULMA)], [np.sin(KULMA), np.cos(KULMA)]])


def _seina(rng, a, b, per_m, korkeus=9.0, kohina=0.05):
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = int(np.linalg.norm(b - a) * per_m)
    xy = a + np.outer(rng.uniform(0, 1, n), b - a) + rng.normal(0, kohina, (n, 2))
    return np.column_stack([xy, rng.uniform(0.5, korkeus, n)])


def _als_talo(rng, harva=1):
    """Seinät 40 pistettä / m, seinä harva vain 15 / m (lentolinjan suuntainen). Kattoreunan pisteet
    (0,5 m ulompana, korkeusväli 0,2 m) eivät ole seinää."""
    k = [R @ p for p in np.asarray(L_TALO, float)]
    seinat = [_seina(rng, k[i], k[(i + 1) % len(k)], 15 if i == harva else 40) for i in range(len(k))]
    keski = np.mean(k, axis=0)
    reuna = [_seina(rng, keski + (k[i] - keski) * 1.05, keski + (k[(i + 1) % len(k)] - keski) * 1.05, 10)
             for i in range(len(k))]
    for r in reuna:
        r[:, 2] = rng.uniform(9.4, 9.6, len(r))
    return np.vstack(seinat + reuna), k


def test_als_l_talo():
    rng = np.random.default_rng(1)
    xyz, kulmat = _als_talo(rng)
    segs = extract_walls(xyz, WallOptions.for_cloud(None, "als"))
    for i, a in enumerate(kulmat):
        b = kulmat[(i + 1) % len(kulmat)]
        d = (b - a) / np.linalg.norm(b - a)
        n = np.array([-d[1], d[0]])
        osuvat = [s for s in segs if abs(s.direction @ d) > np.cos(np.radians(2))
                  and abs((s.p0 + s.p1) / 2 @ n - a @ n) < 0.1]
        assert osuvat, f"seinä {i} puuttuu"
        assert sum(s.length for s in osuvat) > 0.9 * np.linalg.norm(b - a), f"seinä {i} vajaa"
    # Nurkat suljettu ja kattoreuna ei tullut linjaksi
    paat = np.array([p for s in segs for p in (s.p0, s.p1)])
    for c in kulmat:
        assert np.min(np.linalg.norm(paat - c, axis=1)) < 0.2
    assert len(segs) == len(kulmat)


def test_als_seinaluokka_luetaan(tmp_path):
    """read_wall_class: seinäluokan pisteet, jos niitä on; muuten kaikki."""
    laspy = pytest.importorskip("laspy")
    rng = np.random.default_rng(2)
    xyz = rng.uniform(0, 10, (100, 3))
    h = laspy.LasHeader(point_format=6, version="1.4")
    h.scales = [0.001] * 3
    las = laspy.LasData(h)
    las.x, las.y, las.z = xyz.T
    las.classification = np.where(np.arange(100) < 30, 13, 2).astype(np.uint8)
    las.write(tmp_path / "a.las")
    assert len(read_wall_class(tmp_path / "a.las")) == 30
    las.classification = np.full(100, 2, np.uint8)
    las.write(tmp_path / "b.las")
    assert len(read_wall_class(tmp_path / "b.las")) == 100


def test_als_kattorakenne_korkeudesta():
    """Katolla oleva IV-konehuone on seinälinja, mutta sen alin piste on katon tasolla (info["korkeus"]):
    sen voi erottaa kantakartan seinistä."""
    rng = np.random.default_rng(3)
    xyz, _ = _als_talo(rng)
    k = [R @ np.array(p, float) for p in [(4, 4), (8, 4), (8, 8), (4, 8)]]
    kone = np.vstack([_seina(rng, k[i], k[(i + 1) % 4], 40) for i in range(4)])
    kone[:, 2] = rng.uniform(9.6, 12.0, len(kone))
    segs = extract_walls(np.vstack([xyz, kone]), WallOptions.for_cloud(None, "als"))
    katolla = [s for s in segs if s.info["korkeus"][0] > 9]
    assert len(katolla) == 4 and all(abs(s.length - 4) < 0.2 for s in katolla)
    assert all(s.info["korkeus"][0] < 0.5 and s.info["korkeus"][1] > 8 for s in segs if s.info["korkeus"][0] <= 9)
