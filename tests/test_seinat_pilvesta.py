"""Seinien tunnistus koko korkeudelta: julkisivu sokkelin yläpuolelta, ikkunat, pienten ulokkeiden
yleistys, sisäseinät ja laiteprofiili."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from seinat_pilvesta import WallOptions, extract_walls, guess_profile, las_profile  # noqa: E402


def _surface(rng, a, b, z0, z1, offset=0.0, density=3000, noise=0.004):
    """Pystypinta janan a–b suuntaisesti, siirrettynä offset normaalin suuntaan (vasemmalle), korkeus z0–z1."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    L = np.linalg.norm(b - a)
    n = int(L * (z1 - z0) * density)
    s = rng.uniform(0, L, n)
    nrm = np.array([-(b - a)[1], (b - a)[0]]) / L
    xy = a + np.outer(s / L, b - a) + np.outer(offset + rng.normal(0, noise, n), nrm)
    return np.column_stack([xy, rng.uniform(z0, z1, n)])


def _ground_ring(rng, lo, hi, house_lo, house_hi, n=80_000):
    g = rng.uniform(lo, hi, (n, 2))
    inside = np.all((g > house_lo) & (g < house_hi), axis=1)
    g = g[~inside]
    return np.column_stack([g, rng.normal(0, 0.004, len(g))])


def _house(rng, south):
    """12 x 8 m talo (kierto vastapäivään, normaali sisään), eteläseinä annettuna pintojen listana."""
    walls = [_surface(rng, (12, 0), (12, 8), 0, 3), _surface(rng, (12, 8), (0, 8), 0, 3),
             _surface(rng, (0, 8), (0, 0), 0, 3)]
    return np.vstack([_ground_ring(rng, (-4, -4), (16, 12), (0, 0), (12, 8))] + walls + south)


def _south(segs):
    return [s for s in segs if abs(s.direction[0]) > 0.99 and max(s.p0[1], s.p1[1]) < 1.0]


def test_line_on_facade_above_plinth():
    """Sokkeli 0–0,6 m on 5 cm julkisivua ulompana: linja julkisivuun, sokkelin ero ja yläreuna tietoihin."""
    rng = np.random.default_rng(1)
    xyz = _house(rng, [_surface(rng, (0, 0), (12, 0), 0, 0.6, offset=-0.05), _surface(rng, (0, 0), (12, 0), 0.6, 3)])
    segs = extract_walls(xyz, WallOptions())
    [wall] = _south(segs)
    assert abs(wall.p0[1]) < 0.005 and abs(wall.p1[1]) < 0.005 and wall.length > 11.9
    assert abs(wall.info["sokkeli"] - 0.05) < 0.01 and abs(wall.info["sokkeli_yla"] - 0.6) < 0.11
    assert wall.info["korkeus"][0] >= 0.5 and abs(wall.info["pinta"]) < 0.005 and wall.info["kohina"] < 0.01


def test_windows_do_not_break_wall():
    """Ikkunat (0,9–2,1 m, lasi 15 cm sisempänä) eivät katkaise seinää eivätkä siirrä linjaa."""
    rng = np.random.default_rng(2)
    south = []
    for x in range(0, 12, 2):
        south += [_surface(rng, (x, 0), (x + 0.4, 0), 0, 3), _surface(rng, (x + 0.4, 0), (x + 1.6, 0), 0, 0.9),
                  _surface(rng, (x + 0.4, 0), (x + 1.6, 0), 2.1, 3),
                  _surface(rng, (x + 0.4, 0), (x + 1.6, 0), 0.9, 2.1, offset=0.15, density=800),
                  _surface(rng, (x + 1.6, 0), (x + 2, 0), 0, 3)]
    segs = extract_walls(_house(rng, south), WallOptions())
    south_segs = _south(segs)
    assert len(south_segs) == 1 and south_segs[0].length > 11.9, [(s.p0, s.p1) for s in south_segs]
    assert abs(south_segs[0].p0[1]) < 0.005


def test_small_bump_generalized_large_kept():
    """20 cm syvä ja 1 m leveä uloke yleistetään pois (suora linja), 0,8 m syvä säilyy."""
    rng = np.random.default_rng(3)

    def south(depth):
        return [_surface(rng, (0, 0), (5, 0), 0, 3), _surface(rng, (5, 0), (5, -depth), 0, 3),
                _surface(rng, (5, -depth), (6, -depth), 0, 3), _surface(rng, (6, -depth), (6, 0), 0, 3),
                _surface(rng, (6, 0), (12, 0), 0, 3)]

    segs = _south(extract_walls(_house(rng, south(0.2)), WallOptions()))
    on_line = [s for s in segs if abs(s.p0[1]) < 0.01 and abs(s.p1[1]) < 0.01]
    assert sum(s.length for s in on_line) > 11.9, [(s.p0.round(2), s.p1.round(2)) for s in segs]
    assert not any(abs(s.p0[1] + 0.2) < 0.03 for s in segs)
    segs = _south(extract_walls(_house(rng, south(0.8)), WallOptions()))
    assert any(abs(s.p0[1] + 0.8) < 0.02 and abs(s.p1[1] + 0.8) < 0.02 for s in segs)


def test_interior_wall_seen_through_window_dropped():
    """Ikkunasta näkyvä sisäseinä (talon keskellä) ei tule seinälinjaksi."""
    rng = np.random.default_rng(4)
    xyz = _house(rng, [_surface(rng, (0, 0), (12, 0), 0, 3)])
    inner = _surface(rng, (6, 2), (6, 6), 0.3, 2.8, density=1500)
    segs = extract_walls(np.vstack([xyz, inner]), WallOptions())
    assert not any(abs(s.p0[0] - 6) < 0.1 and abs(s.p1[0] - 6) < 0.1 for s in segs)
    assert len(segs) == 4


def test_profile_from_density_and_header(tmp_path):
    rng = np.random.default_rng(5)
    dense = np.column_stack([rng.uniform(0, 10, (3_000_000, 2)), rng.uniform(0, 3, 3_000_000)])
    sparse = np.column_stack([rng.uniform(0, 50, (3_000_000, 2)), rng.uniform(0, 3, 3_000_000)])
    als = np.column_stack([rng.uniform(0, 200, (3_000_000, 2)), rng.uniform(0, 3, 3_000_000)])
    assert guess_profile(dense) == "iphone" and guess_profile(sparse) == "stonex" and guess_profile(als) == "als"
    assert WallOptions.for_cloud(sparse).profile == "stonex" and WallOptions.for_cloud(sparse).voxel > 0
    for system, software, expected in ((b"STONEX", b"GOpost-2.4.8.0", "stonex"), (b"iPhone LiDAR", b"lidarpipe", "iphone"),
                                       (b"PDAL", b"PDAL 2.10.2", None)):
        p = tmp_path / "x.las"
        p.write_bytes(b"LASF" + bytes(22) + system.ljust(32, b"\0") + software.ljust(32, b"\0") + bytes(300))
        assert las_profile(p) == expected


def test_line_below_window_band():
    """Osuuskunnan seinä: sokkeli 0–0,4 m (4 cm ulompana), puuseinä 0,4–1,1 m ja koko seinän mittainen
    ikkunanauha 1,1–2,5 m (lasi 14 cm sisempänä). Linja puuseinään sokkelin yläpuolelle, ikkunoiden alle."""
    rng = np.random.default_rng(6)
    south = [_surface(rng, (0, 0), (12, 0), 0, 0.4, offset=-0.04), _surface(rng, (0, 0), (12, 0), 0.4, 1.1),
             _surface(rng, (0, 0), (12, 0), 1.1, 2.5, offset=0.14, density=1500)]
    segs = extract_walls(_house(rng, south), WallOptions())
    [wall] = [s for s in _south(segs) if s.length > 5]
    assert abs(wall.p0[1]) < 0.01 and abs(wall.p1[1]) < 0.01, (wall.p0, wall.p1)
    assert abs(wall.info["sokkeli"] - 0.04) < 0.01 and wall.info["korkeus"][1] < 1.2
    # sama ilman sokkelia: alin pinta on julkisivu, harvempi ikkunanauha ei ole sen yläpuolinen seinä
    south = [_surface(rng, (0, 0), (12, 0), 0, 1.1), _surface(rng, (0, 0), (12, 0), 1.1, 2.5, offset=0.14, density=1500)]
    [wall] = [s for s in _south(extract_walls(_house(rng, south), WallOptions())) if s.length > 5]
    assert abs(wall.p0[1]) < 0.01 and wall.info["sokkeli"] is None


def test_low_wall_under_window_band_found_with_iphone_profile():
    """Matala puuseinä (0,4–1,1 m) koko seinän mittaisen ikkunanauhan alla (lasi 14 cm sisempänä, harva):
    solu ei yksin peitä puolta korkeudesta, mutta 0,5 m ympäristö peittää. Linja puuseinään."""
    rng = np.random.default_rng(8)
    south = [_surface(rng, (0, 0), (12, 0), 0.4, 1.1), _surface(rng, (0, 0), (12, 0), 1.1, 2.5, offset=0.14,
                                                                    density=1000)]
    segs = [s for s in _south(extract_walls(_house(rng, south), WallOptions())) if s.length > 5]
    assert len(segs) == 1 and abs(segs[0].p0[1]) < 0.01 and abs(segs[0].p1[1]) < 0.01, [(s.p0, s.p1) for s in segs]


def test_short_piece_on_same_surface_does_not_drop_long_facade():
    """Kruna2: 3,6 m pala (julkisivu alkaa 0,6 m, oven kohta) 1,7 cm sivussa 59 m julkisivusta (alkaa 1,4 m,
    kivijalka) ei saa pudottaa pitkää: sama pinta."""
    from seinat_pilvesta import Segment, _drop_upper_duplicates

    d = np.array([1.0, 0.0])
    long_ = Segment(np.array([0.0, 0.0]), np.array([59.0, 0.0]), d, 0.0, np.zeros((0, 2)),
                    info={"korkeus": (1.4, 3.5), "pinta": 0.0})
    short = Segment(np.array([35.0, 0.017]), np.array([38.6, 0.017]), d, 0.017, np.zeros((0, 2)),
                    info={"korkeus": (0.6, 3.5), "pinta": 0.0})
    upper = Segment(np.array([10.0, -0.25]), np.array([20.0, -0.25]), d, -0.25, np.zeros((0, 2)),
                    info={"korkeus": (1.9, 3.5), "pinta": 0.0})
    kept = {id(s) for s in _drop_upper_duplicates([long_, short, upper])}
    assert kept == {id(long_)}


def test_line_does_not_continue_onto_fence_from_corner():
    """1,8 m umpiaita jatkaa eteläseinää nurkasta 4 m: linja päättyy nurkkaan (iPhonen cover_top 1,8
    hyväksyy aidan seinäsoluiksi, joten aita lyhennetään linjan päästä korkeuden perusteella)."""
    rng = np.random.default_rng(11)
    walls = [_surface(rng, (12, 0), (12, 8), 0, 3), _surface(rng, (12, 8), (0, 8), 0, 3),
             _surface(rng, (0, 8), (0, 0), 0, 3), _surface(rng, (0, 0), (12, 0), 0, 3),
             _surface(rng, (12, 0), (16, 0), 0, 1.8)]
    xyz = np.vstack([_ground_ring(rng, (-4, -4), (20, 12), (0, 0), (12, 8))] + walls)
    south = _south(extract_walls(xyz, WallOptions.for_cloud(xyz, "iphone")))
    assert south, "eteläseinä puuttuu"
    assert max(max(s.p0[0], s.p1[0]) for s in south) < 12.3, [(s.p0, s.p1) for s in south]


def _bridge_case(rng, upper_gap=True, middle=None):
    """Kaksi samansuuntaista seinälinjaa (0–4 m ja 10–14 m), välissä näyteikkuna: yläjulkisivu 2–6 m
    linjojen kohdalla ja upper_gap-tapauksessa myös välissä."""
    from seinat_pilvesta import Segment

    d = np.array([1.0, 0.0])
    segs = [Segment(np.array([0.0, 0.0]), np.array([4.0, 0.0]), d, 0.0, np.zeros((0, 2))),
            Segment(np.array([10.0, 0.0]), np.array([14.0, 0.0]), d, 0.0, np.zeros((0, 2)))] + (middle or [])
    parts = [_surface(rng, (0, 0), (4, 0), 2, 6), _surface(rng, (10, 0), (14, 0), 2, 6)]
    if upper_gap:
        parts.append(_surface(rng, (4, 0), (10, 0), 2, 6, offset=0.15))   # yläjulkisivu 15 cm ulompana
    return segs, np.vstack(parts)


def test_bridge_over_shop_window_when_upper_facade_continues():
    """Näyteikkunan yli silta, kun yläjulkisivu jatkuu; silta ilman pisteitä (DXF: PAATELTY)."""
    from seinat_pilvesta import _bridge_upper

    segs, xyz = _bridge_case(np.random.default_rng(21))
    [b] = _bridge_upper(segs, xyz, lambda p: p[:, 2], WallOptions(bridge_max=40.0))
    assert sorted([b.p0[0], b.p1[0]]) == [4.0, 10.0] and b.info["silta"] and len(b.points) == 0


def test_no_bridge_without_upper_facade_or_over_existing_wall():
    """Ei siltaa kahden talon välisen kadun yli (ei yläjulkisivua) eikä samassa tasossa olevan linjan
    ohi (vain sen päihin); syvennyksen pala 0,4 m sisempänä ei estä siltaa."""
    from seinat_pilvesta import Segment, _bridge_upper

    rng = np.random.default_rng(22)
    opt = WallOptions(bridge_max=40.0)
    segs, xyz = _bridge_case(rng, upper_gap=False)
    assert _bridge_upper(segs, xyz, lambda p: p[:, 2], opt) == []
    d = np.array([1.0, 0.0])
    same = Segment(np.array([5.0, 0.05]), np.array([9.0, 0.05]), d, 0.05, np.zeros((0, 2)))
    segs, xyz = _bridge_case(rng, middle=[same])
    assert sorted(round(b.length, 1) for b in _bridge_upper(segs, xyz, lambda p: p[:, 2], opt)) == [1.0, 1.0]
    recess = Segment(np.array([5.0, 0.4]), np.array([6.5, 0.4]), d, 0.4, np.zeros((0, 2)))
    segs, xyz = _bridge_case(rng, middle=[recess])
    assert len(_bridge_upper(segs, xyz, lambda p: p[:, 2], opt)) == 1


def test_no_bridge_along_balcony_fronts():
    """Parvekkeiden väliseinät (2 m kohtisuorat palat 2,4 m välein): ei siltaa etureunaa pitkin, vaikka
    kaiteet ja lasitukset täyttävät yläjulkisivun ehdon; pitkien päätyseinien välille silta tulee."""
    from seinat_pilvesta import Segment, _bridge_upper

    rng = np.random.default_rng(23)
    up = np.array([0.0, 1.0])
    def wall(x, L):
        return Segment(np.array([x, 0.0]), np.array([x, L]), up, -x, np.zeros((0, 2)))
    front = _surface(rng, (0, 0), (2.4, 0), 2, 6)
    opt = WallOptions(bridge_max=40.0)
    assert _bridge_upper([wall(0.0, 2.0), wall(2.4, 2.0)], front, lambda p: p[:, 2], opt) == []
    assert len(_bridge_upper([wall(0.0, 8.0), wall(2.4, 8.0)], front, lambda p: p[:, 2], opt)) == 1
