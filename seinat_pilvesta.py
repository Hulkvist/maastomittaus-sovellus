"""Seinälinjat pistepilvestä: seinäsolut, RANSAC-suorat, julkisivun tarkennus, suoristus, nurkat ja DXF.

Seinäksi hyväksytään vain XY-solut, joissa on pisteitä suurimmassa osassa korkeuskerroksia
(esim. 0,3–2,5 m maasta) ja myös ylhäällä. Matalat kalusteet, aidat, autot ja kasvillisuus putoavat
näin pois, eivätkä ikkunat tai pensaat katkaise seinää. Suorat haetaan seinäsolujen painopisteistä,
ja jokainen suora tarkennetaan julkisivuun sokkelin yläpuolelle (refine_segment): seinäpinnan paikka
korkeuskerroksittain, sokkelin porras erikseen. Pienet ulokkeet ja sisennykset yleistetään pois
(merge_walls: general_depth, general_width) kuten kartoituksessa.

Sama tiedosto kahdessa paikassa: maastomittaus-sovelluksen seinat_pilvesta.py (QGIS-lisäosa) ja
lidarscanin pipeline/src/lidarpipe/walls.py (lidarpipe, CloudCompare). Vain numpy (ezdxf vain write_dxf).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np


@dataclass
class WallOptions:
    profile: str = "iphone"      # asetusten lähtökohta (for_cloud / PROFILES): iphone tai stonex
    height: float = 1.0          # vanhan vaakaleikkauksen (horizontal_slice) ja DXF:n korkeus maanpinnasta [m]
    band: float = 0.2            # ± [m]
    ground_cell: float = 2.0     # paikallisen maanpinnan ruutukoko [m]
    indoor: bool = False         # sisätila: yksi lattiataso paikallisen maanpinnan sijaan
    grid: float = 0.01           # 2D-harvennus [m]
    wall_cell: float = 0.03      # seinäsolujen koko [m]
    cover_min: float = 0.3       # pystypeiton alaraja maasta [m]
    cover_max: float = 2.5       # pystypeiton yläraja maasta [m]
    cover_top: float = 1.8       # seinäsolussa on oltava pisteitä tätä ylempänä (aidat, autot ja pensaat pois) [m]
    voxel: float = 0.0           # tunnistuksen harvennus (0 = ei): Stonexin raskas pilvi [m]
    cover_layer: float = 0.1     # korkeuskerroksen paksuus [m]
    cover_ratio: float = 0.5     # vähimmäisosuus kerroksista, joissa solulla (tai 0,5 m ympäristöllä) on pisteitä
    cell_layers: int = 5         # ympäristön peitolla solulta itseltään vaaditaan näin monta kerrosta
    cover_near: bool = True      # peitto myös 0,5 m ympäristöstä (Stonexilla pois: puut ja autot täyttäisivät sen)
    inlier_tol: float = 0.03     # RANSAC-toleranssi [m] (noin 3 × pinnan kohina)
    min_length: float = 0.3      # lyhin hyväksytty seinäsegmentti [m]
    max_gap: float = 0.3         # suurempi aukko katkaisee segmentin [m]
    min_density: float = 20.0    # seinäsolujen painopisteitä / m (enintään 1 / wall_cell)
    iterations: int = 400
    max_lines: int = 200
    # Konsensus: RANSAC ajetaan consensus_runs kertaa eri siemenillä, ja seinäsolu hyväksytään, jos se kuuluu
    # samansuuntaiseen linjaan vähintään consensus_need ajossa. Ahne haku vahvistaa pieniä syötemuutoksia
    # (Katajaharju: siemen tai maanpinnan otos vaihtoi 12–18 % linjapituudesta); kasvillisuuden solut
    # osuvat ajosta toiseen eri suuntiin ja putoavat pois. 1 = ei konsensusta.
    consensus_runs: int = 7
    consensus_need: int = 4
    consensus_deg: float = 5.0
    snap_deg: float = 5.0        # pää- tai kohtisuoran suunnan toleranssi: SEINA-luokka (muuten EPAVARMA) [°]
    # Käännetäänkö SEINA-luokan seinät tarkasti pääsuuntaan. Pois oletuksena: kääntö siirtää seinän päitä
    # (2° vino 5 m seinä: 9 cm), ja oikeissa keilauksissa seinät poikkesivat pilvestä päästä päähän 5–17 cm.
    straighten: bool = False
    dominant_min_length: float = 1.0  # pääsuunta lasketaan vain tätä pidemmistä linjoista [m]
    merge_offset: float = 0.05   # kollineaaristen yhdistäminen [m]
    merge_gap: float = 0.5
    corner_dist: float = 0.6     # päätepisteet tätä lähempänä yhdistetään nurkaksi [m]
    # Pirstaleisuus: saman seinän palat yhdistetään ikkunoiden, pensaiden ym. aukkojen yli, kun välissä ei ole
    # toista seinää, ja irralliset lyhyet palat poistetaan.
    wall_gap: float = 2.0        # suurin yhdistettävä aukko samalla seinällä [m]
    wall_offset: float = 0.08    # saman seinän palojen suurin sivuero [m] (3 cm: Osuuskunta 37 linjaa, 8 cm: 30, tarkkuus sama)
    wall_angle_deg: float = 2.0  # saman seinän palojen suurin suuntaero
    min_keep: float = 0.5        # lyhyemmät palat pois, ellei kumpikin pää liity nurkkaan [m]
    # Yhtenäinen ääriviiva (outline): saman seinän palat, nurkat ja porrastukset yhdeksi murtoviivaksi
    outline: bool = True
    outline_offset: float = 0.15   # saman seinän palojen suurin sivuero (iPhonen ajelehtiminen) [m]
    outline_gap: float = 6.0       # suurin yhdistettävä aukko samalla seinällä, ellei välissä ole toista seinää [m]
    outline_fragment: float = 1.0  # lyhyemmät irralliset palat pois (ellei pala liitä kahta seinää) [m]
    corner_reach: float = 3.0      # katveessa oleva nurkka: seinää jatketaan leikkauspisteeseen enintään [m]
    jog_reach: float = 1.0         # porrastus: rinnakkaisten seinien päät enintään näin kaukana pituussuunnassa [m]
    jog_max: float = 1.5           # porrastuksen suurin syvyys [m]
    # Julkisivun tarkennus (refine_segment): seinäpinta korkeuskerroksittain, sokkeli erikseen
    refine: bool = True
    search: float = 0.25         # seinäpinnan haku suoran molemmin puolin [m]
    facade_min: float = 0.1      # korkeusprofiili maasta [m]
    facade_max: float = 3.0
    facade_ref: float = 1.0      # ilman sokkelia julkisivu on alin pinta, joka ulottuu tätä ylemmäs [m]
    plinth_max: float = 1.6      # sokkeli (esim. kivijalka) päättyy viimeistään tähän [m]
    facade_tol: float = 0.015    # saman pinnan kerrosten suurin ero [m]
    # Kartoitusyleistys: enintään general_depth syvät ja general_width leveät ulokkeet/sisennykset pois
    # Sisälinjojen poisto (_drop_inside): tiheä maanpinta merkitsee ulkoaluetta (sisäpiha), mutta vain jos se
    # on enintään floor_raise ympäristön (8 m) alimman maan yläpuolella. Ikkunoista näkyvä sisälattia on
    # talon sisällä alin pinta ja näytti maalta, jolloin sisäseinien linjat jäivät (Katajaharju, sim/lasi).
    floor_raise: float = 0.3
    slope_min: float = 0.3       # julkisivun korkeudet seinän keskimääräisestä maasta, kun maa vaihtelee enemmän [m]
    sure_length: float = 2.0     # tätä pidempi julkisivullinen seinä on SEINA, vaikka se on vino pääsuuntaan
    general_depth: float = 0.5
    general_width: float = 2.0
    # Pensassuodatin: pensaan reunasta löytyy "julkisivu" vain ohuelta korkeusväliltä ja se kohisee (virtuaali-
    # keilaus: 0,2–0,4 m ja 19–23 mm; seinät 1,3–2,4 m ja 6–10 mm). Molempien on täytyttävä, jotta matala seinä
    # ikkunanauhan alla (0,4–1,1 m) säilyy.
    bush_span: float = 0.5       # julkisivun korkeusväli alle [m] ...
    bush_noise: float = 0.015    # ... ja kohina yli [m] -> linja pois (0 = ei suodatinta)
    # Aita seinälinjan jatkeena (_trim_fences): linjan päästä pois vähintään fence_min matala osuus, jonka ylin
    # piste on alle fence_top ja vähintään fence_drop linjan tyypillistä matalampi (0 = ei lyhennystä)
    fence_top: float = 2.2
    fence_drop: float = 0.5
    fence_min: float = 0.75
    seed: int = 0

    @classmethod
    def for_cloud(cls, xyz: np.ndarray | None = None, profile: str = "auto", **kw) -> "WallOptions":
        """Asetukset pilven mukaan: profile = iphone, stonex tai auto (pistetiheydestä, ks. guess_profile).
        kw ohittaa yksittäiset arvot."""
        if profile == "auto":
            profile = guess_profile(xyz) if xyz is not None else "iphone"
        return cls(**{**PROFILES[profile], "profile": profile, **kw})


# Laitekohtaiset arvot (WallOptions.for_cloud). iPhone: harva, kohinainen ja ajelehtiva pilvi (saman seinän
# palat voivat olla eri kohdissa). Stonex: tiheä ja tarkka, raskas (kymmeniä miljoonia pisteitä).
PROFILES = {
    "iphone": {},
    # cover_top 2,0 (oli 2,2): 2,0 m matala seinä löytyy (räystään alapinta riittää); oikeissa pilvissä
    # kattavuus parani 4/5 kohteessa, roskaa vähän lisää. 1,8: roskaa selvästi enemmän (Käärmetalo +85 m).
    # Pensassuodatin pois: oikeissa Stonex-pilvissä pitkienkin seinien julkisivu oli ohut ja kohiseva (Kruna2
    # 30 m, Katajaharju 17 m); viidessä kohteessa suodatin pudotti seiniä yhtä paljon kuin roskaa.
    "stonex": dict(voxel=0.03, wall_cell=0.03, cover_top=2.0, cover_near=False, facade_max=3.5, inlier_tol=0.03,
                   wall_offset=0.04, outline_offset=0.06, facade_tol=0.01, bush_noise=0.0),
}


def guess_profile(xyz: np.ndarray, sample: int = 2_000_000) -> str:
    """iphone tai stonex pistetiheydestä, kun laitetta ei tiedetä (las_profile): iPhone keilataan läheltä,
    joten pisteitä on maastossa neliömetriä kohden paljon (testikohteissa 34 000–70 000 / m² 0,5 m
    ruuduissa), Stonexin reppukeilaimella vähemmän ja laajemmalle (5 000–10 000 / m²)."""
    if len(xyz) == 0:
        return "iphone"
    p = xyz if len(xyz) <= sample else xyz[np.random.default_rng(0).choice(len(xyz), sample, replace=False)]
    q = np.floor(p[:, :2] / 0.5).astype(np.int64)
    cells = len(np.unique(q[:, 0] * 10**9 + q[:, 1]))
    return "iphone" if len(xyz) / (cells * 0.25) > 20_000 else "stonex"


def las_profile(path) -> str | None:
    """Laite LAS/LAZ-otsikosta (System identifier, Generating software): stonex, iphone tai None."""
    try:
        with open(path, "rb") as f:
            head = f.read(90)
    except OSError:
        return None
    text = head[26:90].upper()
    if b"STONEX" in text or b"GOPOST" in text:
        return "stonex"
    if b"IPHONE" in text or b"LIDARPIPE" in text:
        return "iphone"
    return None


@dataclass
class Segment:
    p0: np.ndarray
    p1: np.ndarray
    direction: np.ndarray
    offset: float              # n · p
    points: np.ndarray = field(repr=False)
    snapped: bool = False
    info: dict = field(default_factory=dict, repr=False)   # wall_info: korkeus, sokkeli, kohina

    @property
    def normal(self) -> np.ndarray:
        return np.array([-self.direction[1], self.direction[0]])

    @property
    def length(self) -> float:
        return float(np.linalg.norm(self.p1 - self.p0))


def ground_sample(xyz: np.ndarray, n: int = 5_000_000, chunk: int = 5_000_000) -> np.ndarray:
    """Maanpinnan otos isosta pilvestä: noin n pistettä, valittuna pisteen omasta paikasta (millimetreinä
    tiivistetty) eikä järjestyksestä. Sama pilvi antaa saman otoksen, luettiinpa se LAZ:sta tai COPC:sta tai
    rajattiinpa se usealla säikeellä (QGIS:n pdal:clip: järjestys vaihtelee ajosta toiseen; joka k:s piste
    muutti tulosta). Ei satunnainen: satunnainen otos muutti maanpintaa seinien kohdalla 10 %:ssa pisteistä
    yli 2,7 cm, mikä vaihtoi Katajaharjussa 22 % seinäsoluista ja 11 % linjapituudesta."""
    if len(xyz) <= n:
        return xyz
    k = -(-len(xyz) // n)
    keep = np.empty(len(xyz), bool)
    for start in range(0, len(xyz), chunk):
        q = np.round(xyz[start:start + chunk, :3].astype(np.float64) * 1000).astype(np.int64)
        h = (q[:, 0] * 73856093) ^ (q[:, 1] * 19349663) ^ (q[:, 2] * 83492791)
        h ^= h >> 17
        keep[start:start + chunk] = (h * 0x9E3779B1) % k == 0
    return xyz[keep]


class Ground:
    """Paikallinen maanpinta ruudukkona: ruudun alin 2 %-piste (enintään 50. alin), ja jokainen ruutu saa
    naapuriruutujensa (3 x 3) matalimman arvon (seinäruuduissa ja talon sisällä ei ole maata). Naapurin arvo
    siirretään ensin maaston kaltevuudella ruudun kohdalle: rinteessä 2 m:n päässä alarinteessä oleva naapuri
    teki maasta 0,2–0,4 m liian matalan (10 % rinne), jolloin sokkeli näytti kivijalalta. Kaltevuus on
    korjaamattoman minimin gradientista (ei sisälattioita), tasamaalla korjaus on nolla. Tyhjät ruudut
    täytetään naapureista, joten korkeuden saa myös muille kuin ruudukon laskemiseen käytetyille pisteille (at)."""

    def __init__(self, xyz: np.ndarray, cell: float, max_slope: float = 0.3):
        self.cell = cell
        ij = np.floor(xyz[:, :2] / cell).astype(np.int64)
        self.off = ij.min(0)
        ij -= self.off
        self.shape = (int(ij[:, 0].max()) + 1, int(ij[:, 1].max()) + 1)
        flat = ij[:, 0] * self.shape[1] + ij[:, 1]
        order = np.lexsort((xyz[:, 2], flat))
        fs = flat[order]
        starts = np.flatnonzero(np.r_[True, fs[1:] != fs[:-1]])
        counts = np.diff(np.r_[starts, len(fs)])
        low = np.full(self.shape[0] * self.shape[1], np.inf)
        # 2 %-piste, mutta enintään 50. alin: seinän vieressä maata voi olla alle 2 % ruudun pisteistä (pensas,
        # harvennettu maa), jolloin 2 %-piste osuisi seinään
        low[fs[starts]] = xyz[order[starts + np.minimum((0.02 * counts).astype(np.int64), 49)], 2]
        low = low.reshape(self.shape)
        rough = self._fill(self._min3(low), xyz)
        if min(rough.shape) > 1:
            gx, gy = (np.clip(g, -max_slope, max_slope) for g in np.gradient(rough, cell))
        else:
            gx = gy = np.zeros_like(rough)
        p = np.pad(low, 1, constant_values=np.inf)
        n0, n1 = low.shape
        grid = np.min([p[1 + di:n0 + 1 + di, 1 + dj:n1 + 1 + dj] - (gx * di + gy * dj) * cell
                       for di in (-1, 0, 1) for dj in (-1, 0, 1)], axis=0)
        self.grid = self._fill(grid, xyz)

    @classmethod
    def _fill(cls, grid: np.ndarray, xyz: np.ndarray) -> np.ndarray:
        """Tyhjät ruudut naapureista (enintään 50 kierrosta), lopuksi koko pilven alin taso."""
        for _ in range(50):
            empty = ~np.isfinite(grid)
            if not empty.any():
                break
            grid = np.where(empty, cls._min3(grid), grid)
        grid[~np.isfinite(grid)] = float(np.min(xyz[:, 2]))
        return grid

    @staticmethod
    def _min3(a: np.ndarray) -> np.ndarray:
        p = np.pad(a, 1, constant_values=np.inf)
        return np.min([p[1 + di:p.shape[0] - 1 + di, 1 + dj:p.shape[1] - 1 + dj]
                       for di in (-1, 0, 1) for dj in (-1, 0, 1)], axis=0)

    def _idx(self, xy: np.ndarray):
        ij = np.floor(xy / self.cell).astype(np.int64) - self.off
        return np.clip(ij[:, 0], 0, self.shape[0] - 1), np.clip(ij[:, 1], 0, self.shape[1] - 1)

    def at(self, xy: np.ndarray) -> np.ndarray:
        return self.grid[self._idx(xy)]

    def raised(self, xy: np.ndarray, radius: float = 8.0) -> np.ndarray:
        """Paikallinen maanpinta ympäristön (radius) alimman maanpinnan yläpuolella [m]: ikkunoista näkyvä
        sisälattia on koholla (ruudun alin pinta talon sisällä), katu ja sisäpiha eivät."""
        low = self.grid
        for _ in range(int(radius / self.cell)):
            low = self._min3(low)
        i = self._idx(xy)
        return self.grid[i] - low[i]


def local_ground(xyz: np.ndarray, cell: float) -> np.ndarray:
    """Maanpinnan korkeus jokaiselle pisteelle (Ground)."""
    return Ground(xyz, cell).at(xyz[:, :2])


def floor_level(xyz: np.ndarray, min_share: float = 0.2) -> float:
    """Sisätilan lattia: alin 1 cm korkeusluokka, jossa on vähintään `min_share` suurimman
    vaakapinnan pisteistä (pöydät ja sängyt voivat näkyä lattiaa laajempina)."""
    z = xyz[:, 2]
    low = z[z < np.median(z)]
    bins = np.arange(low.min(), low.max() + 0.02, 0.01)
    hist, edges = np.histogram(low, bins)
    k = int(np.flatnonzero(hist >= min_share * hist.max())[0])
    # Paikallinen huippu valitun luokan ympäriltä
    k = max(0, k - 2) + int(np.argmax(hist[max(0, k - 2): k + 3]))
    return float(0.5 * (edges[k] + edges[k + 1]))


def relative_height(xyz: np.ndarray, opt: WallOptions) -> np.ndarray:
    if opt.indoor:
        return xyz[:, 2] - floor_level(xyz)
    return xyz[:, 2] - local_ground(xyz, opt.ground_cell)


def wall_mask(xyz: np.ndarray, rel: np.ndarray, opt: WallOptions) -> np.ndarray:
    """Pisteet, joiden XY-solussa on pisteitä riittävän monessa korkeuskerroksessa."""
    band = (rel >= opt.cover_min) & (rel < opt.cover_max)
    cell = np.floor(xyz[:, :2] / opt.wall_cell).astype(np.int64)
    layer = np.floor((rel[band] - opt.cover_min) / opt.cover_layer).astype(np.int64)
    n_layers = int(np.ceil((opt.cover_max - opt.cover_min) / opt.cover_layer))
    # Uniikit (solu, kerros) -parit -> kerrosten määrä solua kohden
    c = cell[band]
    key = np.stack([c[:, 0], c[:, 1], layer], 1)
    uniq = np.unique(key, axis=0)
    cells, counts = np.unique(uniq[:, :2], axis=0, return_counts=True)
    good = cells[counts >= opt.cover_ratio * n_layers]
    if len(good) == 0:
        return np.zeros(len(xyz), dtype=bool)
    # Tiivis avain solulle
    off = cell.min(0)
    width = int(cell[:, 1].max() - off[1] + 1)
    flat = (cell[:, 0] - off[0]) * width + (cell[:, 1] - off[1])
    good_flat = (good[:, 0] - off[0]) * width + (good[:, 1] - off[1])
    return np.isin(flat, good_flat)


def voxel_thin(xyz: np.ndarray, size: float, chunk: int = 5_000_000) -> np.ndarray:
    """Pilvi size-kuutioihin: yksi piste (kuution keskipiste) kustakin kuutiosta, jossa on pisteitä.
    Paloittain, joten iso pilvi (Stonex, ~100 milj. pistettä) ei vie moninkertaisesti muistia."""
    lo = np.array([float(np.min(xyz[:, k])) for k in range(3)])
    keys = []
    for start in range(0, len(xyz), chunk):
        part = xyz[start:start + chunk]
        q = [np.floor((part[:, k] - lo[k]) / size).astype(np.int64) for k in range(3)]
        keys.append(np.unique((q[0] << 42) | (q[1] << 21) | q[2]))
    key = np.unique(np.concatenate(keys)) if keys else np.zeros(0, np.int64)
    del keys
    out = np.empty((len(key), 3), dtype=np.float32 if xyz.dtype == np.float32 else np.float64)
    for k, shift in enumerate((42, 21, 0)):
        out[:, k] = (((key >> shift) & ((1 << 21) - 1)) + 0.5) * size + lo[k]
    return out


def wall_cells(xyz: np.ndarray, rel: np.ndarray, opt: WallOptions) -> np.ndarray:
    """Seinäsolujen (wall_cell) pisteiden painopisteet (m x 2): solussa on pisteitä vähintään
    cover_ratio korkeuskerroksista cover_min–cover_max ja myös cover_top ylempänä. Koko korkeus
    yhden leikkauksen sijaan: ikkunat, ovet ja pensaat eivät katkaise seinää."""
    band = (rel >= opt.cover_min) & (rel < opt.cover_max)
    xy, h = xyz[band, :2], rel[band]
    if len(xy) == 0:
        return np.zeros((0, 2))
    # Yläpisteet (cover_top–facade_max) riittää löytyä 25 cm ympäristöstä: seinän yläosa voi olla eri
    # kohdassa kuin alaosa (ikkunanauha, ulkoneva yläosa)
    top = (rel >= opt.cover_top) & (rel < max(opt.facade_max, opt.cover_max))
    high = _near_cells(xy, xyz[top, :2], 0.25) if top.any() else np.zeros(len(xy), bool)
    cell = np.floor(xy / opt.wall_cell).astype(np.int64)
    off = cell.min(0)
    cell -= off
    width = int(cell[:, 1].max()) + 1
    flat = cell[:, 0] * width + cell[:, 1]
    layer = np.floor((h - opt.cover_min) / opt.cover_layer).astype(np.int64)
    n_layers = int(np.ceil((opt.cover_max - opt.cover_min) / opt.cover_layer))
    uniq = np.unique(flat * (n_layers + 1) + layer)
    cells, counts = np.unique(uniq // (n_layers + 1), return_counts=True)
    # Peitto myös 0,5 m ympäristöstä (kaksi puolen ruudun verran siirrettyä ruudukkoa): matala seinä
    # ikkunanauhan alla (esim. 0,4–1,1 m puuseinä, lasi 14 cm sisempänä) on seinää, kun pinnat yhdessä
    # peittävät korkeuden. Solulta itseltään vaaditaan silloin cell_layers yhtenäistä kerrosta.
    centres = (np.column_stack([cells // width, cells % width]) + off + 0.5) * opt.wall_cell
    near = np.zeros(len(cells))
    for shift in ((0.0, 0.25) if opt.cover_near else ()):
        ck = np.floor((xy + shift) / 0.5).astype(np.int64)
        ck -= ck.min(0)
        cw = int(ck[:, 1].max()) + 1
        ckey = ck[:, 0] * cw + ck[:, 1]
        cu = np.unique(ckey * (n_layers + 1) + layer)
        ccells, ccounts = np.unique(cu // (n_layers + 1), return_counts=True)
        q = np.floor((centres + shift) / 0.5).astype(np.int64) - np.floor((xy + shift) / 0.5).astype(np.int64).min(0)
        qk = q[:, 0] * cw + q[:, 1]
        pos = np.clip(np.searchsorted(ccells, qk), 0, len(ccells) - 1)
        near = np.maximum(near, np.where(ccells[pos] == qk, ccounts[pos], 0))
    ratio = opt.cover_ratio * n_layers
    good = cells[(counts >= ratio) | ((counts >= opt.cell_layers) & (near >= ratio))]
    good = np.intersect1d(good, flat[high])
    sel = np.isin(flat, good)
    inv = np.searchsorted(good, flat[sel])
    n = np.bincount(inv, minlength=len(good))
    cx = np.bincount(inv, xy[sel, 0], minlength=len(good)) / n
    cy = np.bincount(inv, xy[sel, 1], minlength=len(good)) / n
    return np.column_stack([cx, cy])


class _GridIndex:
    """Pisteiden haku ruuduittain (cell): indeksit ruutujen alueelta."""

    def __init__(self, xy: np.ndarray, cell: float):
        self.cell = cell
        ij = np.floor(xy / cell).astype(np.int64)
        self.off = ij.min(0) if len(ij) else np.zeros(2, np.int64)
        ij -= self.off
        self.w = int(ij[:, 1].max()) + 3 if len(ij) else 1
        key = ij[:, 0] * self.w + ij[:, 1]
        self.order = np.argsort(key, kind="stable")
        self.keys = key[self.order]

    def box(self, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        i0, j0 = (np.floor(lo / self.cell).astype(np.int64) - self.off)
        i1, j1 = (np.floor(hi / self.cell).astype(np.int64) - self.off)
        j0, j1 = max(j0, 0), min(j1, self.w - 1)
        out = []
        for i in range(max(i0, 0), i1 + 1):
            a = np.searchsorted(self.keys, i * self.w + j0)
            b = np.searchsorted(self.keys, i * self.w + j1, side="right")
            if b > a:
                out.append(self.order[a:b])
        return np.concatenate(out) if out else np.zeros(0, np.int64)


def ransac_local(pts: np.ndarray, opt: WallOptions, window: float = 1.0, tries: int = 40) -> list[Segment]:
    """Suorat seinäsolujen painopisteistä: siemenpisteen ympäristöstä (3 x 3 ruutua à window) paras suora
    tries ehdokkaasta, sitten suoran kaikki pisteet koko alueelta, yhtenäisiin osiin (max_gap) ja
    pituus- ja tiheysehdot. Paikallinen haku pitää ajan kurissa isollakin alueella (Stonex)."""
    rng = np.random.default_rng(opt.seed)
    segments: list[Segment] = []
    if len(pts) < 5:
        return segments
    index = _GridIndex(pts, window)
    alive = np.ones(len(pts), bool)
    min_pts = max(5, int(opt.min_length * opt.min_density))
    live = np.flatnonzero(alive)
    for it in range(50 * len(pts)):
        # Elävien pisteiden lista päivitetään harvoin (iso pilvi); kuolleet siemenet ohitetaan
        if it % 200 == 0:
            live = np.flatnonzero(alive)
            if len(live) < min_pts:
                break
        i = live[rng.integers(len(live))]
        if not alive[i]:
            continue
        near = index.box(pts[i] - window, pts[i] + window)
        near = near[alive[near]]
        if len(near) < min_pts:
            alive[i] = False
            continue
        j = near[rng.integers(len(near), size=tries)]
        d = pts[j] - pts[i]
        norm = np.linalg.norm(d, axis=1)
        ok = norm > 0.05
        if not ok.any():
            alive[i] = False
            continue
        nrm = np.column_stack([-d[ok, 1], d[ok, 0]]) / norm[ok, None]
        counts = (np.abs((pts[near] - pts[i]) @ nrm.T) < opt.inlier_tol).sum(0)
        best = int(np.argmax(counts))
        if counts[best] < min_pts:
            alive[i] = False
            continue
        inl = near[np.abs((pts[near] - pts[i]) @ nrm[best]) < opt.inlier_tol]
        d, off = _fit_line(pts[inl])
        n = np.array([-d[1], d[0]])
        cand = np.flatnonzero(alive)
        on = cand[np.abs(pts[cand] @ n - off) < opt.inlier_tol]
        accepted = False
        for run in _split_runs(pts[on], d, opt.max_gap):
            run_pts = pts[on[run]]
            if len(run_pts) < 5:
                continue
            seg = _segment_from(run_pts, *_fit_line(run_pts))
            if seg.length >= opt.min_length and len(run_pts) / max(seg.length, 1e-6) >= opt.min_density:
                segments.append(seg)
                alive[on[run]] = False
                accepted = True
        if not accepted:
            alive[inl] = False
    return segments


def stable_cells(pts: np.ndarray, opt: WallOptions) -> np.ndarray:
    """Seinäsolut, jotka ransac_local liittää samansuuntaiseen (consensus_deg) linjaan vähintään
    consensus_need ajossa consensus_runs:sta (siemenet opt.seed, opt.seed + 1, ...)."""
    if opt.consensus_runs <= 1 or len(pts) < 5:
        return np.ones(len(pts), bool)
    key = np.ascontiguousarray(pts).view(np.dtype((np.void, pts.dtype.itemsize * 2))).ravel()
    order = np.argsort(key)
    angle = np.full((len(pts), opt.consensus_runs), np.nan)
    for k in range(opt.consensus_runs):
        for seg in ransac_local(pts, replace(opt, seed=opt.seed + k)):
            q = np.ascontiguousarray(seg.points).view(key.dtype).ravel()
            idx = order[np.searchsorted(key[order], q)]
            angle[idx, k] = np.degrees(np.arctan2(seg.direction[1], seg.direction[0])) % 180
    d = np.abs(angle[:, :, None] - angle[:, None, :])
    agree = (np.minimum(d, 180 - d) <= opt.consensus_deg).sum(axis=2)    # nan-vertailut epätosia
    return agree.max(axis=1) >= opt.consensus_need


def _facade_layers(t: np.ndarray, h: np.ndarray, opt: WallOptions, min_pts: int = 15):
    """Seinäpinnan paikka 10 cm korkeuskerroksittain: (kerroksen keskikorkeus, paikka t, tuki) riveittäin.
    Paikka on tiheimmän 5 mm lokeron kohta (ikkunat, syvennykset ja kasvillisuus eivät siirrä sitä),
    tarkennettuna sen ympäristön (±1,5 cm) keskiarvoksi."""
    k = np.floor((h - opt.facade_min) / 0.1).astype(np.int64)
    n_layers = int(np.ceil((opt.facade_max - opt.facade_min) / 0.1))
    nb = int(round(2 * opt.search / 0.005))
    b = np.clip(((t + opt.search) / 0.005).astype(np.int64), 0, nb - 1)
    ok = (k >= 0) & (k < n_layers)
    H = np.zeros((n_layers, nb))
    np.add.at(H, (k[ok], b[ok]), 1)
    Hs = H.copy()
    Hs[:, 1:] += H[:, :-1]
    Hs[:, :-1] += H[:, 1:]
    rows = []
    for layer in np.flatnonzero(H.sum(1) >= min_pts):
        peak = (int(np.argmax(Hs[layer])) + 0.5) * 0.005 - opt.search
        sel = ok & (k == layer) & (np.abs(t - peak) <= 0.015)
        if sel.sum() >= min_pts // 3:
            rows.append((opt.facade_min + (layer + 0.5) * 0.1, float(np.mean(t[sel])), int(sel.sum())))
    return np.array(rows).reshape(-1, 3)


def _surfaces(layers: np.ndarray, tol: float) -> list[np.ndarray]:
    """Korkeuskerrokset (alhaalta ylös) pinnoiksi: uusi pinta alkaa, kun kerroksen paikka poikkeaa nykyisen
    pinnan mediaanista yli tol. Yhden kerroksen välikappaleet (kohina, ikkunalauta) liitetään pois.
    Palauttaa pinnat kerrosindeksien taulukkoina."""
    groups: list[list[int]] = []
    for k, o in enumerate(layers[:, 1]):
        if groups and abs(o - np.median(layers[groups[-1], 1])) <= tol:
            groups[-1].append(k)
        else:
            groups.append([k])
    return [np.array(g) for g in groups if len(g) >= 2]


def _facade(layers: np.ndarray, opt: WallOptions):
    """Julkisivun paikka korkeuskerroksista (kartoituskäytäntö: sokkelin yläpuolelta ja ikkunanauhan
    alapuolelta). Kerrokset jaetaan pinnoiksi alhaalta ylös (_surfaces). Alin pinta on sokkeli, jos se päättyy
    viimeistään plinth_max ja on matala tai sen päällä on yhtä tiheä umpipinta (kivijalka). Julkisivu on
    sokkelin yläpuolisista, alle plinth_max alkavista pinnoista se, jolla on eniten pisteitä alle 2 m
    korkeudella (harva ikkunanauha ei voita). Palauttaa (paikka, julkisivukerrosten maski, sokkelin ero
    julkisivuun tai None, sokkelin yläreuna)."""
    hz, off, sup = layers.T
    surfaces = _surfaces(layers, 1.5 * opt.facade_tol)
    if not surfaces:
        k = int(np.argmax(sup))
        return float(off[k]), np.arange(len(hz)) == k, None, None
    # Sokkeli: alin pinta, joka päättyy viimeistään plinth_max ja on matala (enintään 0,6 m) tai jonka päällä
    # on yhtä tiheä umpipinta (esim. 1,3 m kivijalka julkisivun alla). Selvästi harvempi yläpinta on
    # ikkunanauha (lasista vähän paluita), jolloin alin pinta on itse julkisivu.
    first = surfaces[0]
    plinth_g = None
    if (len(surfaces) >= 2 and hz[first].max() + 0.05 <= opt.plinth_max and hz[first].min() < opt.plinth_max - 0.3
            and (np.ptp(hz[first]) + 0.1 <= 0.6
                 or max(np.median(sup[g]) for g in surfaces[1:]) >= 0.6 * np.median(sup[first]))):
        plinth_g = first
    rest = surfaces[1:] if plinth_g is not None else surfaces
    # Julkisivu: sokkelin yläpuolisista pinnoista, jotka alkavat alle plinth_max, se jolla on eniten pisteitä
    # alle 2 m korkeudella (puuseinä ikkunanauhan alla voittaa harvan lasin; ikkunat eivät ole seinälinjaa)
    low = [g for g in rest if hz[g].min() < opt.plinth_max]
    if low:
        facade_g = max(low, key=lambda g: float(sup[g][hz[g] < 2.0].sum()))
    else:
        facade_g = rest[0]
    w = sup[facade_g]
    f = float(np.average(off[facade_g], weights=w))
    on = np.zeros(len(hz), bool)
    on[facade_g] = True
    plinth, plinth_top = None, None
    if plinth_g is not None and hz[plinth_g].max() < hz[facade_g].min():
        plinth = float(np.median(off[plinth_g])) - f
        plinth_top = float(hz[plinth_g].max() + 0.05)
    return f, on, plinth, plinth_top


def _near_points(seg: Segment, xyz: np.ndarray, rel: np.ndarray, index: _GridIndex, opt: WallOptions, pad: float = 0.1):
    """Suoran ympäristön pisteet suoran koordinaateissa: (s pituussuunnassa, t normaalin suunnassa, h maasta).
    Rinteessä (maa vaihtelee seinän matkalla yli slope_min) h on seinän keskimääräisestä maasta: sokkelin
    yläreuna on vaakasuora, ja paikallisesta maasta mitattuna sokkeli ja julkisivu sekoittuisivat samoille
    korkeuksille.
    Alimmasta maasta mitattuna alarinteen pää näyttäisi kivijalalta (sokkeli yli plinth_max)."""
    lo = np.minimum(seg.p0, seg.p1) - opt.search - pad
    hi = np.maximum(seg.p0, seg.p1) + opt.search + pad
    idx = index.box(lo, hi)
    rel_p = xyz[idx, :2] - seg.p0
    sv, tv = rel_p @ seg.direction, rel_p @ seg.normal
    sel = (sv >= -pad) & (sv <= seg.length + pad) & (np.abs(tv) <= opt.search)
    idx, hv = idx[sel], rel[idx[sel]]
    if len(idx) and opt.slope_min > 0:
        ground = xyz[idx, 2] - hv
        g_lo, g_mid, g_hi = np.percentile(ground, [2, 50, 98])
        if g_hi - g_lo > opt.slope_min:
            hv = xyz[idx, 2] - g_mid
    return idx, sv[sel], tv[sel], hv


def refine_segment(seg: Segment, xyz: np.ndarray, rel: np.ndarray, index: _GridIndex,
                   opt: WallOptions) -> Segment | None:
    """Suora julkisivuun: seinäpinnan paikka korkeuskerroksittain (_facade_layers), julkisivu sokkelin
    yläpuolelta (_facade) ja suora sovitetaan julkisivukerrosten pinnan pisteisiin (Huber-TLS). Pisteiksi
    jäävät julkisivun pisteet 2D:nä (yhdistely, päätellyt osat). None, jos seinäpintaa ei löydy."""
    idx, sv, tv, hv = _near_points(seg, xyz, rel, index, opt)
    layers = _facade_layers(tv, hv, opt)
    if len(layers) < 3:
        return None
    f, on, _, _ = _facade(layers, opt)
    if on.sum() < 2:
        return None
    hz = layers[on, 0]
    sel = (np.abs(tv - f) <= max(opt.facade_tol, 0.5 * opt.inlier_tol) + 0.005)
    sel &= (hv >= hz.min() - 0.05) & (hv <= hz.max() + 0.05)
    if sel.sum() < 20:
        return None
    xy = xyz[idx[sel], :2]
    # 1 cm ruudukkoon harvennettuna (muisti; pinnan paikka ei muutu)
    q = np.floor(xy / 0.01).astype(np.int64)
    _, keep = np.unique(q[:, 0] * 10**9 + q[:, 1], return_index=True)
    xy = xy[keep]
    d, off = _fit_line(xy)
    if d @ seg.direction < 0:
        d, off = -d, -off
    if abs(d @ seg.direction) < np.cos(np.radians(10)):
        return None
    # Päät suoran omien pisteiden mukaan, mutta vähintään alkuperäisen suoran mitta: ajelehtiva (iPhone)
    # tai kalteva pinta ei osu tarkasti julkisivun paikkaan koko matkalta, eikä suora saa siksi lyhentyä
    n = np.array([-d[1], d[0]])
    s_all = np.r_[xy @ d, seg.p0 @ d, seg.p1 @ d]
    out = Segment(d * s_all.min() + n * off, d * s_all.max() + n * off, d, off, xy)
    return out if out.length >= opt.min_length else None


def wall_info(segs: list[Segment], xyz: np.ndarray, rel: np.ndarray, index: _GridIndex,
              opt: WallOptions) -> None:
    """Lopullisille linjoille Segment.info: korkeus (julkisivukerrokset maasta, m), sokkeli (sokkelin ero
    julkisivuun, + = ulompana, m) ja sokkelin yläreuna, pinta (julkisivun etäisyys linjasta, m), kohina
    (pinnan hajonta, m) ja kallistus (pinnan siirtymä ylöspäin metriä kohden, + = ulos)."""
    normals = outward_normals(segs)
    for seg, n in zip(segs, normals):
        seg.info = {}
        if seg.length < 0.1:
            continue
        idx, sv, tv, hv = _near_points(seg, xyz, rel, index, opt, pad=0.0)
        sign = 1.0 if seg.normal @ n >= 0 else -1.0
        layers = _facade_layers(tv, hv, opt)
        if len(layers) < 3:
            continue
        f, on, plinth, plinth_top = _facade(layers, opt)
        hz, off = layers[on, 0], layers[on, 1]
        sel = np.abs(tv - f) <= 0.03
        resid = tv[sel] - f
        tilt = float(np.polyfit(hz, off, 1)[0]) * sign if on.sum() >= 3 and np.ptp(hz) > 0.3 else None
        seg.info = {"korkeus": (float(hz.min() - 0.05), float(hz.max() + 0.05)),
                    "sokkeli": plinth * sign if plinth is not None else None, "sokkeli_yla": plinth_top,
                    "pinta": f * sign,
                    "kohina": float(1.4826 * np.median(np.abs(resid - np.median(resid)))) if len(resid) else None,
                    "kallistus": tilt}


def horizontal_slice(xyz: np.ndarray, opt: WallOptions) -> np.ndarray:
    rel = relative_height(xyz, opt)
    sel = (np.abs(rel - opt.height) <= opt.band) & wall_mask(xyz, rel, opt)
    pts = xyz[sel, :2]
    if len(pts) == 0:
        return pts
    q = np.floor(pts / opt.grid).astype(np.int64)
    _, idx = np.unique(q, axis=0, return_index=True)
    return pts[idx]


def _fit_line(pts: np.ndarray, iterations: int = 5, huber: float = 0.01) -> tuple[np.ndarray, float]:
    """Kokonaispienimmän neliösumman suora, Huber-painotettu (poikkeavat pisteet vähemmällä painolla)."""
    w = np.ones(len(pts))
    for _ in range(iterations):
        c = (pts * w[:, None]).sum(0) / w.sum()
        X = (pts - c) * np.sqrt(w)[:, None]
        _, _, Vt = np.linalg.svd(X, full_matrices=False)
        d = Vt[0]
        n = np.array([-d[1], d[0]])
        r = np.abs((pts - c) @ n)
        w = np.minimum(1.0, huber / np.maximum(r, 1e-9))
    return d, float(n @ c)


def _robust_offset(proj: np.ndarray, huber: float = 0.01) -> float:
    off = float(np.median(proj))
    for _ in range(5):
        r = np.abs(proj - off)
        w = np.minimum(1.0, huber / np.maximum(r, 1e-9))
        off = float(np.sum(w * proj) / np.sum(w))
    return off


def _split_runs(pts: np.ndarray, d: np.ndarray, max_gap: float) -> list[np.ndarray]:
    s = pts @ d
    order = np.argsort(s)
    breaks = np.flatnonzero(np.diff(s[order]) > max_gap) + 1
    return [order[g] for g in np.split(np.arange(len(order)), breaks)]


def _segment_from(pts: np.ndarray, d: np.ndarray, offset: float) -> Segment:
    n = np.array([-d[1], d[0]])
    s = pts @ d
    p0 = d * s.min() + n * offset
    p1 = d * s.max() + n * offset
    return Segment(p0, p1, d, offset, pts)


def ransac_segments(pts: np.ndarray, opt: WallOptions) -> list[Segment]:
    rng = np.random.default_rng(opt.seed)
    remaining = pts.copy()
    segments: list[Segment] = []
    min_pts = max(5, int(opt.min_length * opt.min_density))
    for _ in range(opt.max_lines):
        if len(remaining) < min_pts:
            break
        best_mask, best_count = None, 0
        for _ in range(opt.iterations):
            i, j = rng.choice(len(remaining), 2, replace=False)
            d = remaining[j] - remaining[i]
            norm = np.linalg.norm(d)
            if norm < 0.05:
                continue
            nrm = np.array([-d[1], d[0]]) / norm
            mask = np.abs((remaining - remaining[i]) @ nrm) < opt.inlier_tol
            count = int(mask.sum())
            if count > best_count:
                best_mask, best_count = mask, count
        if best_mask is None or best_count < min_pts:
            break
        d, off = _fit_line(remaining[best_mask])
        n = np.array([-d[1], d[0]])
        mask = np.abs(remaining @ n - off) < opt.inlier_tol
        accepted = np.zeros(len(remaining), dtype=bool)
        inliers = np.flatnonzero(mask)
        for run in _split_runs(remaining[inliers], d, opt.max_gap):
            run_pts = remaining[inliers[run]]
            if len(run_pts) < 5:
                continue
            seg = _segment_from(run_pts, *_fit_line(run_pts))
            if seg.length >= opt.min_length and len(run_pts) / max(seg.length, 1e-6) >= opt.min_density:
                segments.append(seg)
                accepted[inliers[run]] = True
        # Hylätyt lyhyet palat poistetaan myös, jotta sama suora ei toistu.
        remaining = remaining[~mask]
        if not accepted.any() and best_count < 2 * min_pts:
            break
    return segments


def dominant_direction(segments: list[Segment]) -> float:
    """Rakennuksen pääsuunta (rad) pituuksilla painotettuna, 90° jaksollisuus."""
    ang = np.array([np.arctan2(s.direction[1], s.direction[0]) for s in segments])
    w = np.array([s.length for s in segments])
    z = np.sum(w * np.exp(4j * ang))
    return float(np.angle(z) / 4)


def _groups(segments: list[Segment], dist: float) -> list[int]:
    """Linjat ryhmiin: samaan ryhmään, jos linjojen välinen etäisyys on alle dist (näytteet ruuduissa)."""
    parent = list(range(len(segments)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cells: dict = {}
    for k, s in enumerate(segments):
        t = np.linspace(0, 1, max(2, int(np.ceil(s.length / (dist / 2))) + 1))
        for c in {tuple(v) for v in np.floor((s.p0 + np.outer(t, s.p1 - s.p0)) / dist).astype(np.int64)}:
            cells.setdefault(c, []).append(k)
    for (i, j), members in cells.items():
        near = [m for di in (-1, 0, 1) for dj in (-1, 0, 1) for m in cells.get((i + di, j + dj), [])]
        for m in near[1:]:
            parent[root(m)] = root(near[0])
    return [root(i) for i in range(len(segments))]


def regularize(segments: list[Segment], opt: WallOptions) -> list[Segment]:
    if not segments:
        return []
    # Pääsuunta rakennuksittain (lähekkäiset linjat samaan ryhmään): eri asennoissa olevat talot
    groups = _groups(segments, 2.0)
    theta = {}
    for g in set(groups):
        members = [s for s, k in zip(segments, groups) if k == g]
        long = [s for s in members if s.length >= opt.dominant_min_length]
        theta[g] = dominant_direction(long or members)
    out = []
    for s, g in zip(segments, groups):
        theta0 = theta[g]
        ang = np.arctan2(s.direction[1], s.direction[0])
        diff = (ang - theta0 + np.pi / 4) % (np.pi / 2) - np.pi / 4
        if abs(np.degrees(diff)) <= opt.snap_deg:
            if opt.straighten:
                k = np.round((ang - theta0 - diff) / (np.pi / 2))
                a = theta0 + k * np.pi / 2
                d = np.array([np.cos(a), np.sin(a)])
                n = np.array([-d[1], d[0]])
                seg = _segment_from(s.points, d, _robust_offset(s.points @ n))
            else:
                seg = _segment_from(s.points, s.direction, s.offset)
            seg.snapped = True
            out.append(seg)
        else:
            out.append(s)
    return merge_collinear(out, opt)


def _merged(pts: np.ndarray, d: np.ndarray, a: Segment, b: Segment, opt: WallOptions) -> Segment:
    """Yhdistetty seinä: suunta sovitetaan kaikkiin pisteisiin (ensimmäisen palan suunta voi olla lyhyestä
    palasta vino), paitsi kun kumpikin pala on käännetty tarkasti pääsuuntaan (straighten)."""
    if opt.straighten and a.snapped and b.snapped:
        n = np.array([-d[1], d[0]])
        return _segment_from(pts, d, _robust_offset(pts @ n))
    return _segment_from(pts, *_fit_line(pts))


def merge_collinear(segments: list[Segment], opt: WallOptions) -> list[Segment]:
    segs = list(segments)
    merged = True
    while merged:
        merged = False
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i], segs[j]
                if abs(a.direction @ b.direction) < np.cos(np.radians(0.5)):
                    continue
                d = a.direction
                n = a.normal
                sa = sorted([a.p0 @ d, a.p1 @ d])
                sb = sorted([b.p0 @ d, b.p1 @ d])
                gap = max(sb[0] - sa[1], sa[0] - sb[1])
                if gap > opt.merge_gap or abs((b.p0 + b.p1) @ n / 2 - a.p0 @ n) > opt.merge_offset + 0.1:
                    continue
                if abs(_robust_offset(b.points @ n) - _robust_offset(a.points @ n)) > opt.merge_offset:
                    continue
                pts = np.vstack([a.points, b.points])
                seg = _merged(pts, d, a, b, opt)
                seg.snapped = a.snapped and b.snapped
                segs[i] = seg
                segs.pop(j)
                merged = True
                break
            if merged:
                break
    return segs


def _intersect(a: Segment, b: Segment) -> np.ndarray | None:
    A = np.array([a.normal, b.normal])
    if abs(np.linalg.det(A)) < np.sin(np.radians(20)):
        return None
    return np.linalg.solve(A, [a.offset, b.offset])


def close_corners(segments: list[Segment], opt: WallOptions) -> list[Segment]:
    """Jatkaa/lyhentää lähekkäiset päät seinien leikkauspisteeseen."""
    for i, a in enumerate(segments):
        for j in range(i + 1, len(segments)):
            b = segments[j]
            x = _intersect(a, b)
            if x is None:
                continue
            ea = 0 if np.linalg.norm(a.p0 - x) < np.linalg.norm(a.p1 - x) else 1
            eb = 0 if np.linalg.norm(b.p0 - x) < np.linalg.norm(b.p1 - x) else 1
            pa = a.p0 if ea == 0 else a.p1
            pb = b.p0 if eb == 0 else b.p1
            if np.linalg.norm(pa - x) < opt.corner_dist and np.linalg.norm(pb - x) < opt.corner_dist:
                if ea == 0:
                    a.p0 = x.copy()
                else:
                    a.p1 = x.copy()
                if eb == 0:
                    b.p0 = x.copy()
                else:
                    b.p1 = x.copy()
    return segments


def _cross(p, q, a, b, tol: float = 0.05) -> bool:
    """Leikkaako jana p–q janan a–b (pienellä toleranssilla päissä)?"""
    d1, d2 = q - p, b - a
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-12:
        return False
    w = a - p
    t = (w[0] * d2[1] - w[1] * d2[0]) / den
    u = (w[0] * d1[1] - w[1] * d1[0]) / den
    lt, lu = tol / max(np.linalg.norm(d1), 1e-9), tol / max(np.linalg.norm(d2), 1e-9)
    return -lt <= t <= 1 + lt and -lu <= u <= 1 + lu


def _snap_recesses(segs: list[Segment], opt: WallOptions, ground_xy: np.ndarray, min_depth: float = 0.15,
                   facade_share: float = 0.3) -> list[Segment]:
    """Kartoitusyleistys ennen yhdistämistä: seinän pienet syvennykset ja pilarit julkisivun tasolle.

    Rinnakkaiset palat, jotka ovat enintään general_depth sivussa toisistaan ja enintään general_width
    päässä toisistaan seinän suunnassa, ovat saman seinän vyöhyke. Ulkopuoli päätellään maanpinnasta
    (_outside). Julkisivu on uloin taso, joka kattaa vähintään facade_share vyöhykkeen pituudesta. Muun tason
    pala, joka on min_depth–general_depth julkisivusta, enintään general_width pitkä ja jonka molemmin puolin
    (enintään general_width päässä) on julkisivun pala, siirretään julkisivun tasolle. Kruna2: täyskorkeiden
    ikkunasyvennysten (0,33 m) pohjat yhdistyivät julkisivun aukkojen yli pidemmäksi linjaksi kuin julkisivu
    itse, joka katkesi pilarien (0,28 m ulos) kohdalla."""
    n_seg = len(segs)
    if n_seg < 3 or len(ground_xy) == 0:
        return segs
    cos_lim = np.cos(np.radians(5.0))
    parent = list(range(n_seg))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    mids = np.array([(q.p0 + q.p1) / 2 for q in segs])
    for i in range(n_seg):
        a = segs[i]
        for j in range(i + 1, n_seg):
            b = segs[j]
            if abs(a.direction @ b.direction) < cos_lim:
                continue
            long_, short = (a, b) if a.length >= b.length else (b, a)
            d, n = long_.direction, long_.normal
            if abs((mids[j] - mids[i]) @ n) > opt.general_depth + 0.05:
                continue
            sa, sb = sorted([a.p0 @ d, a.p1 @ d]), sorted([b.p0 @ d, b.p1 @ d])
            if max(sb[0] - sa[1], sa[0] - sb[1]) <= opt.general_width:
                parent[root(i)] = root(j)
    groups = {}
    for i in range(n_seg):
        groups.setdefault(root(i), []).append(i)
    gindex = _GridIndex(ground_xy, 1.0)
    for members in groups.values():
        if len(members) < 3:
            continue
        ref = max((segs[k] for k in members), key=lambda q: q.length)
        d, n = ref.direction, ref.normal
        s01 = np.array([sorted([segs[k].p0 @ d, segs[k].p1 @ d]) for k in members])
        span = Segment(d * s01[:, 0].min() + n * (ref.p0 @ n), d * s01[:, 1].max() + n * (ref.p0 @ n), d,
                       float(ref.p0 @ n), np.zeros((0, 2)))
        out = _outside(span, ground_xy, gindex)
        if out == 0:
            continue
        off = np.array([(mids[k] @ n) * out for k in members])          # suurempi = ulompana
        lengths = np.array([segs[k].length for k in members])
        order = np.argsort(off)
        levels, cur = [], [order[0]]
        for k in order[1:]:
            if off[k] - off[cur[-1]] <= opt.wall_offset + 0.02:
                cur.append(k)
            else:
                levels.append(cur)
                cur = [k]
        levels.append(cur)
        extent = s01[:, 1].max() - s01[:, 0].min()
        facade = next((lv for lv in reversed(levels) if lengths[lv].sum() >= facade_share * extent), None)
        if facade is None or len(levels) < 2:
            continue
        f_off = float(np.average(off[facade], weights=lengths[facade]))
        f_s = s01[facade]
        for k, m in enumerate(members):
            q = segs[m]
            depth = abs(off[k] - f_off)
            if k in facade or not (min_depth <= depth <= opt.general_depth + 0.05) or q.length > opt.general_width:
                continue
            s0, s1 = s01[k]
            left = np.any((f_s[:, 1] <= s0 + 0.1) & (s0 - f_s[:, 1] <= opt.general_width))
            right = np.any((f_s[:, 0] >= s1 - 0.1) & (f_s[:, 0] - s1 <= opt.general_width))
            if not (left and right):
                continue
            shift = n * (out * (f_off - off[k]))
            segs[m] = Segment(q.p0 + shift, q.p1 + shift, q.direction, float((q.p0 + shift) @ q.normal),
                              q.points + shift, snapped=q.snapped, info=q.info)
    return segs


def merge_walls(segments: list[Segment], opt: WallOptions) -> list[Segment]:
    """Saman seinän (suunta ja sivusijainti samat) palat yhdeksi linjaksi aukkojen yli, ellei aukon
    kohdalla ole toista seinää (esim. sisäänveto tai poikkiseinä)."""
    segs = list(segments)
    cos_lim = np.cos(np.radians(opt.wall_angle_deg))
    merged = True
    while merged:
        merged = False
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                a, b = segs[i], segs[j]
                if b.length > a.length:
                    # Suunta pidemmästä: lyhyen palan suunta voi poiketa muutaman asteen, jolloin toisen palan
                    # pisteet muutaman metrin päässä näyttivät 10 cm sivussa olevilta (Kruna2: 0,5 m palat)
                    a, b = b, a
                cos_ab = abs(a.direction @ b.direction)
                # Kulmaraja ei koske lyhyttä palaa, jonka pää poikkeaa kulman takia alle wall_offset: 0,5 m
                # palan suunta heittää 2–5° (pilarin ja ikkunasyvennyksen väli), ja yhdistetty linja
                # sovitetaan uudelleen
                if cos_ab < cos_lim and b.length * np.sqrt(max(0.0, 1 - cos_ab ** 2)) > opt.wall_offset:
                    continue
                d, n = a.direction, a.normal
                sa, sb = sorted([a.p0 @ d, a.p1 @ d]), sorted([b.p0 @ d, b.p1 @ d])
                gap = max(sb[0] - sa[1], sa[0] - sb[1])
                if gap > opt.wall_gap or abs((b.p0 + b.p1) @ n / 2 - a.p0 @ n) > opt.wall_offset + 0.1:
                    continue
                if abs(_robust_offset(b.points @ n) - _robust_offset(a.points @ n)) > opt.wall_offset:
                    continue
                if gap > opt.merge_gap:
                    off = _robust_offset(np.vstack([a.points, b.points]) @ n)
                    lo, hi = (sa[1], sb[0]) if sa[1] <= sb[0] else (sb[1], sa[0])
                    p, q = d * lo + n * off, d * hi + n * off
                    # Kartoitusyleistys: pienen ulokkeen tai sisennyksen kyljet (päät enintään general_depth
                    # linjasta) eivät estä yhdistämistä, kun aukko on enintään general_width. Pilarin ja
                    # ikkunasyvennyksen kyljet voivat olla samassa linjassa (Kruna2: 0,28 m ulos + 0,33 m sisään)
                    small = gap <= opt.general_width
                    if any(_cross(p, q, c.p0, c.p1) and not (
                            small and max(abs((c.p0 - p) @ n), abs((c.p1 - p) @ n)) <= opt.general_depth + 0.05)
                           for k, c in enumerate(segs) if k not in (i, j)):
                        continue
                pts = np.vstack([a.points, b.points])
                seg = _merged(pts, d, a, b, opt)
                # Yhdistetty linja ei saa siirtää kumpaakaan palaa yli wall_offset: lähes samansuuntaiset eri
                # seinät (Konala: talousrakennus 2 m talon seinän jatkeena, 1,8°) eivät ole sama seinä
                if any(abs(_robust_offset((c.points - seg.p0) @ seg.normal)) > opt.wall_offset for c in (a, b)):
                    continue
                seg.snapped = a.snapped or b.snapped
                segs[i] = seg
                segs.pop(j)
                merged = True
                break
            if merged:
                break
    return segs


def prune_short(segments: list[Segment], opt: WallOptions) -> list[Segment]:
    """Lyhyet palat pois, ellei kumpikin pää liity toiseen linjaan (nurkka, esim. sisäänveto)."""
    def joined(p, k):
        return any(min(np.linalg.norm(p - c.p0), np.linalg.norm(p - c.p1)) < 0.02
                   for j, c in enumerate(segments) if j != k)
    return [s for k, s in enumerate(segments)
            if s.length >= opt.min_keep or (joined(s.p0, k) and joined(s.p1, k))]


def chains(segments: list[Segment], tol: float = 0.002) -> list[list[np.ndarray]]:
    """Nurkissa toisiinsa liittyvät linjat murtoviivoiksi (samaan suuntaan kulkevat ketjut)."""
    left = list(range(len(segments)))
    ends = [(s.p0, s.p1) for s in segments]
    out = []
    while left:
        k = left.pop(0)
        poly = [ends[k][0].copy(), ends[k][1].copy()]
        grew = True
        while grew:
            grew = False
            for j in list(left):
                a, b = ends[j]
                for head in (True, False):
                    tip = poly[-1] if head else poly[0]
                    for x, y in ((a, b), (b, a)):
                        if np.linalg.norm(tip - x) < tol:
                            if head:
                                poly.append(y.copy())
                            else:
                                poly.insert(0, y.copy())
                            left.remove(j)
                            grew = True
                            break
                    if grew:
                        break
                if grew:
                    break
        out.append(poly)
    return out


def _end(s: Segment, k: int) -> np.ndarray:
    return s.p0 if k == 0 else s.p1


def _set_end(s: Segment, k: int, p: np.ndarray) -> None:
    if k == 0:
        s.p0 = np.array(p, dtype=float)
    else:
        s.p1 = np.array(p, dtype=float)


def _point_segment(p: np.ndarray, s: Segment) -> float:
    d = s.p1 - s.p0
    t = np.clip((p - s.p0) @ d / max(d @ d, 1e-12), 0, 1)
    return float(np.linalg.norm(p - (s.p0 + t * d)))


def _joined(segs: list[Segment], k: int, e: int, tol: float = 0.002) -> bool:
    p = _end(segs[k], e)
    return any(min(np.linalg.norm(p - c.p0), np.linalg.norm(p - c.p1)) < tol for j, c in enumerate(segs) if j != k)


def _drop_fragments(segs: list[Segment], opt: WallOptions, tol: float = 0.3) -> list[Segment]:
    """Lyhyet palat pois, ellei kumpikin pää ole toisen (eri) seinän lähellä (nurkan tai porrastuksen pala)."""
    keep = []
    for k, s in enumerate(segs):
        if s.length >= opt.outline_fragment:
            keep.append(s)
            continue
        near = [{j for j, c in enumerate(segs) if j != k and c.length >= opt.outline_fragment
                 and _point_segment(p, c) < tol} for p in (s.p0, s.p1)]
        if near[0] and near[1] and len(near[0] | near[1]) >= 2:
            keep.append(s)
        elif _joined(segs, k, 0, 0.02) and _joined(segs, k, 1, 0.02):
            keep.append(s)      # nurkista kiinni (esim. yli general_depth syvän ulokkeen kyljet ja etupinta)
    return keep


def connect_corners(segs: list[Segment], opt: WallOptions) -> list[Segment]:
    """Vapaat päät (ei vielä nurkassa) seinien leikkauspisteeseen: lähimmät parit ensin, kukin pää kerran.
    Seinää jatketaan enintään corner_reach (katveessa oleva nurkka) tai lyhennetään enintään corner_dist."""
    cands = []
    for i, a in enumerate(segs):
        for j in range(i + 1, len(segs)):
            b = segs[j]
            if abs(a.direction @ b.direction) > np.cos(np.radians(30)):
                continue
            x = _intersect(a, b)
            if x is None:
                continue
            ends = []
            for s in (a, b):
                e = 0 if np.linalg.norm(s.p0 - x) < np.linalg.norm(s.p1 - x) else 1
                p, q = _end(s, e), _end(s, 1 - e)
                dist = float(np.linalg.norm(p - x))
                outward = (x - p) @ (p - q) > 0        # x on seinän jatkeella, ei sen sisällä
                if dist > (opt.corner_reach if outward else opt.corner_dist):
                    break
                ends.append((e, dist))
            else:
                (ea, da), (eb, db) = ends
                cands.append((da + db, i, ea, j, eb, x))
    used = set()
    for _, i, ea, j, eb, x in sorted(cands, key=lambda c: c[0]):
        if (i, ea) in used or (j, eb) in used or _joined(segs, i, ea) or _joined(segs, j, eb):
            continue
        _set_end(segs[i], ea, x)
        _set_end(segs[j], eb, x)
        used |= {(i, ea), (j, eb)}
    return segs


def _drop_shadows(segs: list[Segment], opt: WallOptions) -> list[Segment]:
    """Seinän edessä/takana oleva lyhyempi rinnakkainen pala (kaide, porras, kuisti tai ajelehtimisen
    haamu): enintään jog_max sivussa ja pituussuunnassa vähintään puoliksi pidemmän seinän kohdalla."""
    drop = set()
    for i, a in enumerate(segs):
        for j, b in enumerate(segs):
            # selvästi pidemmän seinän varjo (samanmittaiset rinnakkaiset palat ovat esim. ulokkeen kyljet)
            if i == j or b.length < 1.5 * a.length or j in drop:
                continue
            if abs(a.direction @ b.direction) < np.cos(np.radians(5)):
                continue
            d, n = b.direction, b.normal
            side = abs(((a.p0 + a.p1) / 2 - b.p0) @ n)
            if side <= 0.02 or side > opt.jog_max:
                continue
            sa, sb = sorted([a.p0 @ d, a.p1 @ d]), sorted([b.p0 @ d, b.p1 @ d])
            overlap = min(sa[1], sb[1]) - max(sa[0], sb[0])
            if overlap >= 0.5 * a.length:
                drop.add(i)
                break
    return [s for k, s in enumerate(segs) if k not in drop]


def link_parallel(segs: list[Segment], opt: WallOptions, side_min: float, side_max: float,
                  gap_max: float, overlap_max: float = 2.0) -> list[Segment]:
    """Rinnakkaisten seinien vapaat päät toisiinsa: päät tasataan samaan kohtaan pituussuunnassa (aukon
    keskelle tai limityksen keskelle) ja väliin tulee poikittainen pätkä. side = päiden sivuero,
    gap = aukko pituussuunnassa (limitys negatiivinen). Aukon yli ei liitetä, jos välissä on toinen seinä."""
    out = list(segs)
    cands = []
    for i, a in enumerate(segs):
        for j in range(i + 1, len(segs)):
            b = segs[j]
            if abs(a.direction @ b.direction) < np.cos(np.radians(5)):
                continue
            d, n = a.direction, a.normal
            for ea in (0, 1):
                for eb in (0, 1):
                    pa, pb = _end(a, ea), _end(b, eb)
                    da = np.sign((pa - _end(a, 1 - ea)) @ d)          # a:n pään suunta seinää pitkin
                    if da * ((pb - _end(b, 1 - eb)) @ d) >= 0:      # päät eivät osoita toisiaan kohti
                        continue
                    gap, side = ((pb - pa) @ d) * da, abs((pb - pa) @ n)
                    if side_min < side <= side_max and -overlap_max <= gap <= gap_max:
                        cands.append((max(gap, 0) + side, i, ea, j, eb))
    used = set()
    for _, i, ea, j, eb in sorted(cands):
        if (i, ea) in used or (j, eb) in used or _joined(out, i, ea) or _joined(out, j, eb):
            continue
        a, b = segs[i], segs[j]
        d = a.direction
        pa, pb = _end(a, ea), _end(b, eb)
        s_mid = ((pa @ d) + (pb @ d)) / 2
        qa, qb = pa + d * (s_mid - pa @ d), pb + d * (s_mid - pb @ d)
        if np.linalg.norm(pb - pa) > 0.5 and any(_cross(pa, pb, c.p0, c.p1) for k, c in enumerate(out)
                                                 if k not in (i, j)):
            continue
        # lyhennys enintään puolet seinästä (ettei limitys syö seinää)
        if np.linalg.norm(qa - pa) > 0.5 * a.length or np.linalg.norm(qb - pb) > 0.5 * b.length:
            continue
        _set_end(a, ea, qa)
        _set_end(b, eb, qb)
        if np.linalg.norm(qb - qa) > 0.002:
            ld = (qb - qa) / np.linalg.norm(qb - qa)
            out.append(Segment(qa.copy(), qb.copy(), ld, float(np.array([-ld[1], ld[0]]) @ qa), np.zeros((0, 2)),
                               snapped=True))
        else:
            _set_end(b, eb, qa)
        used |= {(i, ea), (j, eb)}
    return out


def _drop_spurs(segs: list[Segment], opt: WallOptions) -> list[Segment]:
    """Lyhyet sivuhaarat pois: pala, jonka toinen pää on vapaa ja toinen kiinni muussa ääriviivassa
    (alle outline_fragment). Toistetaan, kunnes mitään ei poistu."""
    while True:
        drop = [k for k, s in enumerate(segs) if s.length < opt.outline_fragment
                and _joined(segs, k, 0) != _joined(segs, k, 1)]
        if not drop:
            return segs
        segs = [s for k, s in enumerate(segs) if k not in drop]


def outline(segs: list[Segment], opt: WallOptions) -> list[Segment]:
    """Yhtenäinen ääriviiva talolle: varjopalat ja irtopalat pois, saman seinän palat päistään yhteen
    (ajelehtimisen takia hieman eri kohdissa olevat palat säilyvät omina suorinaan), nurkat ja
    porrastukset kiinni. Suljettuun kierrokseen kuuluvat linjat ovat SEINA-luokkaa (kierros vahvistaa)."""
    segs = _drop_shadows(segs, opt)
    segs = _drop_fragments(segs, opt)
    segs = close_corners(segs, opt)
    segs = link_parallel(segs, opt, -1.0, opt.outline_offset, opt.outline_gap)      # sama seinä
    segs = connect_corners(segs, opt)
    segs = link_parallel(segs, opt, opt.outline_offset, opt.jog_max, opt.jog_reach)  # porrastus
    segs = connect_corners(segs, opt)
    segs = _drop_spurs([s for s in segs if s.length > 0.002], opt)
    segs = _drop_spurs(connect_corners(segs, opt), opt)   # sivuhaaran varaama nurkka vapautui
    for poly in chains(segs):
        if len(poly) > 3 and np.linalg.norm(poly[0] - poly[-1]) < 0.002:
            ring = {tuple(p) for p in poly}
            for s in segs:
                if tuple(s.p0) in ring and tuple(s.p1) in ring:
                    s.snapped = True
    return segs


def _generalize(segs: list[Segment], opt: WallOptions) -> list[Segment]:
    """Yhdistetyn seinän edessä tai takana olevat pienet ulokkeen/sisennyksen palat pois: rinnakkainen pala
    enintään general_depth sivussa ja kokonaan pidemmän seinän kohdalla, pituus enintään general_width,
    sekä niiden lyhyet poikittaiset kyljet (enintään general_depth), joiden kumpikin pää on lähellä seinää
    tai poistettavaa palaa."""
    drop = set()
    for i, a in enumerate(segs):
        if a.length > opt.general_width:
            continue
        for j, b in enumerate(segs):
            if i == j or b.length <= a.length or abs(a.direction @ b.direction) < np.cos(np.radians(5)):
                continue
            side = abs(((a.p0 + a.p1) / 2 - b.p0) @ b.normal)
            sa, sb = sorted([a.p0 @ b.direction, a.p1 @ b.direction]), sorted([b.p0 @ b.direction, b.p1 @ b.direction])
            if 0.02 < side <= opt.general_depth and sa[0] >= sb[0] - 0.05 and sa[1] <= sb[1] + 0.05:
                drop.add(i)
                break
    keep = [s for k, s in enumerate(segs) if k not in drop]
    gone = [segs[k] for k in drop]
    if not gone:
        return segs
    out = []
    for s in keep:
        if s.length <= opt.general_depth + 0.05 and all(
                min(_point_segment(p, c) for c in keep + gone if c is not s) < 0.1 for p in (s.p0, s.p1)) and any(
                min(_point_segment(p, g) for p in (s.p0, s.p1)) < 0.1 for g in gone):
            continue
        out.append(s)
    return out


def extract_walls(xyz: np.ndarray, opt: WallOptions | None = None) -> list[Segment]:
    """Seinälinjat pilvestä (paikalliset koordinaatit, n x 3). Lopullisilla linjoilla on Segment.info
    (wall_info), kun opt.refine."""
    opt = opt or WallOptions()
    # Maanpinta otoksesta (iso pilvi), seinäkorkeuden pisteet paloittain koko pilvestä
    sample = ground_sample(xyz)
    if opt.indoor:
        floor = floor_level(sample)
        height = lambda p: p[:, 2] - floor                                     # noqa: E731
    else:
        ground = Ground(sample, opt.ground_cell)
        height = lambda p: p[:, 2] - ground.at(p[:, :2])                      # noqa: E731
    lo, hi = min(opt.cover_min, opt.facade_min), max(opt.cover_max, opt.facade_max)
    band = _band(xyz, height, lo, hi)
    det = voxel_thin(band, opt.voxel) if opt.voxel > 0 else band
    cells = wall_cells(det, height(det), opt)
    del det
    ropt = replace(opt, min_density=min(opt.min_density, 0.6 / opt.wall_cell))
    cells = cells[stable_cells(cells, ropt)]
    segs = ransac_local(cells, ropt)
    if opt.refine and segs:
        # Tarkennus alkuperäisillä pisteillä seinien läheltä (tunnistuksen harvennus ei vaikuta paikkaan)
        pts = band[_near_cells(band[:, :2], cells, opt.search + 0.1)]
        if opt.voxel > 0:
            pts = voxel_thin(pts, 0.02)       # Stonex: pinnan paikka säilyy, muisti pysyy kurissa
        rel = height(pts)
        keep = (rel >= opt.facade_min) & (rel < opt.facade_max)
        pts, rel = pts[keep], rel[keep]
        index = _GridIndex(pts[:, :2], 1.0)
        segs = [r for r in (refine_segment(s, pts, rel, index, opt) for s in segs) if r is not None]
    del band
    # Maanpinta kertoo seinän ulkopuolen (_snap_recesses, _drop_upper_duplicates)
    gxy = None if opt.indoor else sample[height(sample) < 0.15, :2]
    segs = regularize(segs, opt)
    if gxy is not None:
        segs = _snap_recesses(segs, opt, gxy)
    segs = merge_walls(segs, opt)
    segs = close_corners(segs, opt)
    segs = prune_short(segs, opt)
    segs = _generalize(segs, opt)
    segs = outline(segs, opt) if opt.outline else segs
    if not opt.indoor:
        segs = _drop_inside(segs, gxy[ground.raised(gxy) < opt.floor_raise])
    if opt.refine and segs:
        wall_info(segs, pts, rel, index, opt)
        # Ulkopuoli suodattamattomasta maasta: talon sisälle täyttyy kadun matalampi maa, jolloin
        # sisäpiha näytti koholla olevalta lattialta (Kruna2: 0,5–0,7 m) ja putosi outdoor-joukosta
        segs = _drop_upper_duplicates(segs, ground_xy=gxy)
        if opt.bush_noise > 0 and not opt.straighten:      # käännetty linja osuu pintaan vain osin
            segs = [s for s in segs if not _bush(s, opt)]
        if opt.fence_top > 0:
            segs = close_corners(_trim_fences(segs, pts, rel, index, opt), opt)
        # Pitkä seinä, jolta julkisivu löytyi, on varma suunnasta riippumatta (vinot korttelit)
        for s in segs:
            if s.length >= opt.sure_length and s.info.get("kohina") is not None:
                s.snapped = True
    return segs


def facade_check(xyz: np.ndarray, segments: list[Segment], opt: WallOptions | None = None, step: float = 0.25,
                 side: float = 0.25) -> list[np.ndarray]:
    """Julkisivun etäisyys linjoista step välein samalla säännöllä kuin linjan paikka (refine_segment):
    kohdan ympäriltä (±side) seinäpinta korkeuskerroksittain ja julkisivu sokkelin yläpuolelta. Linjoittain
    taulukko [(matka linjan alusta, etäisyys m: + = talosta ulospäin, NaN = ei julkisivua)]."""
    opt = opt or WallOptions()
    if not segments:
        return []
    sample = ground_sample(xyz)
    if opt.indoor:
        floor = floor_level(sample)
        height = lambda p: p[:, 2] - floor                                     # noqa: E731
    else:
        ground = Ground(sample, opt.ground_cell)
        height = lambda p: p[:, 2] - ground.at(p[:, :2])                      # noqa: E731
    ends = np.array([p for s in segments for p in (s.p0, s.p1)])
    lo, hi = ends.min(0) - opt.search - 1, ends.max(0) + opt.search + 1
    parts = []
    for start in range(0, len(xyz), 5_000_000):
        p = xyz[start:start + 5_000_000]
        p = p[np.all((p[:, :2] >= lo) & (p[:, :2] <= hi), axis=1)]
        h = height(p)
        parts.append(p[(h >= opt.facade_min) & (h < opt.facade_max)])
    pts = np.concatenate(parts)
    if opt.voxel > 0:
        pts = voxel_thin(pts, 0.02)
    rel = height(pts)
    index = _GridIndex(pts[:, :2], 1.0)
    normals = outward_normals(segments)
    out = []
    for seg, n in zip(segments, normals):
        sign = 1.0 if seg.normal @ n >= 0 else -1.0
        _, sv, tv, hv = _near_points(seg, pts, rel, index, opt, pad=0.0)
        order = np.argsort(sv)             # kohdan ikkuna lajitellusta (nopea pitkälläkin seinällä)
        sv, tv, hv = sv[order], tv[order], hv[order]
        k = max(1, int(round(seg.length / step)))
        rows = []
        for sk in (np.arange(k) + 0.5) * seg.length / k:
            a, b = np.searchsorted(sv, sk - side), np.searchsorted(sv, sk + side, side="right")
            layers = _facade_layers(tv[a:b], hv[a:b], opt, min_pts=8) if b - a >= 30 else np.zeros((0, 3))
            if len(layers) >= 3:
                f, on, _, _ = _facade(layers, opt)
                rows.append((sk, f * sign if on.sum() >= 2 else np.nan))
            else:
                rows.append((sk, np.nan))
        out.append(np.array(rows).reshape(-1, 2))
    return out


def _trim_fences(segs: list[Segment], xyz: np.ndarray, rel: np.ndarray, index: _GridIndex, opt: WallOptions,
                 step: float = 0.25) -> list[Segment]:
    """Aita seinän jatkeena: linjan päistä pois osuus, jossa ylin piste (enintään search sivussa ja
    fence_top + 0,6 korkeudella) jää alle
    fence_top ja vähintään fence_drop linjan tyypillistä ylintä pistettä matalammaksi (virtuaalikeilaus: talo
    3,2 m räystäineen, nurkasta jatkuva aita 1,8 m). Matalan piharakennuksen koko linja on samaa korkeutta,
    eikä se lyhene. Tyhjät kohdat (katveeseen jatkettu nurkka) eivät ole matalia, mutta matalan osuuden takana
    ne lähtevät sen mukana. Matalaa vähintään fence_min, ettei yksittäinen ikkuna-aukko lyhennä seinää."""
    out = []
    for seg in segs:
        _, sv, tv, hv = _near_points(seg, xyz, rel, index, opt, pad=0.0)
        n = max(1, int(np.ceil(seg.length / step)))
        k = np.clip((sv / step).astype(np.int64), 0, n - 1)
        # Ylin piste enintään fence_top + 0,6: räystäs ulottuu nurkan yli aidan yläpuolelle, mutta sen alla on
        # tyhjää
        cap = hv < opt.fence_top + 0.6
        top = np.full(n, -np.inf)
        np.maximum.at(top, k[cap], hv[cap])
        seen = np.isfinite(top)
        if seen.sum() < 4:
            out.append(seg)
            continue
        limit = min(opt.fence_top, float(np.median(top[seen])) - opt.fence_drop)
        low = seen & (top < limit)
        start, end = 0, n
        for forward in (True, False):
            run = 0
            idx = range(n) if forward else range(n - 1, -1, -1)
            cut = None
            for i in idx:
                if seen[i] and not low[i]:
                    break
                run += int(low[i])
                cut = i
            if cut is not None and run * step >= opt.fence_min:
                if forward:
                    start = cut + 1
                else:
                    end = cut
        if start == 0 and end == n:
            out.append(seg)
            continue
        if (end - start) * step < opt.min_length:
            continue
        a, length = seg.p0.copy(), seg.length
        u = (seg.p1 - a) / length
        seg.p0 = a + u * (start * step)
        seg.p1 = a + u * min(end * step, length)
        out.append(seg)
    return out


def _bush(seg: Segment, opt: WallOptions) -> bool:
    """Pensaan reuna (ks. WallOptions.bush_span): ohut ja kohiseva julkisivu."""
    h, noise = seg.info.get("korkeus"), seg.info.get("kohina")
    return h is not None and noise is not None and h[1] - h[0] < opt.bush_span and noise > opt.bush_noise


def _outside(seg: Segment, gxy: np.ndarray, index: _GridIndex, near: float = 0.4, far: float = 3.0) -> int:
    """Kummalla puolella linjaa on ulkoalue: +1 normaalin puolella, -1 vastakkaisella, 0 ei tiedetä. Ulkona on
    maanpintaa (gxy) linjan vieressä, talon sisällä ei (tai vain ikkunoista näkyvää lattiaa)."""
    lo = np.minimum(seg.p0, seg.p1) - far
    hi = np.maximum(seg.p0, seg.p1) + far
    q = gxy[index.box(lo, hi)] - seg.p0
    sv, tv = q @ seg.direction, q @ seg.normal
    on = (sv >= 0) & (sv <= seg.length) & (np.abs(tv) >= near) & (np.abs(tv) <= far)
    plus, minus = int(np.sum(on & (tv > 0))), int(np.sum(on & (tv < 0)))
    if max(plus, minus) < 20 or max(plus, minus) < 2 * min(plus, minus):
        return 0
    return 1 if plus > minus else -1


def _comparable(a: Segment, b: Segment) -> bool:
    """Kaksoislinjat ovat yhtä uskottavia julkisivuja: lyhyempi vähintään puolet pidemmästä eikä kohise selvästi
    enemmän (Pajalahti: 1,7 m kasvillisuuslinja seinän edessä, kohina 22 mm, ei saa voittaa 5,7 m seinää)."""
    short, long_ = (a, b) if a.length <= b.length else (b, a)
    ns, nl = short.info.get("kohina"), long_.info.get("kohina")
    return short.length >= 0.5 * long_.length and (ns is None or nl is None or ns <= nl + 0.005)


def _drop_upper_duplicates(segs: list[Segment], side: float = 0.35, angle_deg: float = 10.0,
                           ground_xy: np.ndarray | None = None) -> list[Segment]:
    """Rinnakkaiset kaksoislinjat (enintään side sivussa, lyhyempi vähintään puoliksi toisen kohdalla) samasta
    seinästä: ikkunanauha tai seinän yläosa julkisivun takana. Jäljelle jää linja, jonka julkisivu alkaa
    alempaa (wall_info: korkeus), sitten linja lähempänä julkisivua (pinta), sitten ulompi (ground_xy:
    maanpinta kertoo ulkopuolen; Kruna2: täyskorkeiden ikkunasyvennysten pohjista koottu pidempi linja
    0,33 m julkisivun takana), sitten pidempi. Alle 5 cm toisistaan olevat ovat samaa pintaa: pidempi jää.
    Nurkkien liitospalat (ilman tietoja) säilyvät."""
    gindex = _GridIndex(ground_xy, 1.0) if ground_xy is not None and len(ground_xy) else None
    cos_lim = np.cos(np.radians(angle_deg))
    drop = set()
    order = sorted(range(len(segs)), key=lambda k: -segs[k].length)
    for i in order:
        a = segs[i]
        if i in drop or not a.info.get("korkeus") or a.length < 0.5:
            continue
        for j in order:
            b = segs[j]
            if j == i or j in drop or not b.info.get("korkeus") or abs(a.direction @ b.direction) < cos_lim:
                continue
            short, long_ = (a, b) if a.length <= b.length else (b, a)
            d, n = long_.direction, long_.normal
            offset = abs(((short.p0 + short.p1) / 2 - long_.p0) @ n)
            if offset > side:
                continue
            ss, sl = sorted([short.p0 @ d, short.p1 @ d]), sorted([long_.p0 @ d, long_.p1 @ d])
            if min(ss[1], sl[1]) - max(ss[0], sl[0]) < 0.5 * short.length:
                continue
            ha, hb = a.info["korkeus"][0], b.info["korkeus"][0]
            pa, pb = abs(a.info.get("pinta") or 0.0), abs(b.info.get("pinta") or 0.0)
            if offset < 0.05:
                # Sama pinta (esim. oven kohta, jossa julkisivu alkaa kivijalkaa alempaa): pidempi jää.
                # Muuten 3,6 m pala pudotti Kruna2:n 59 m julkisivun.
                loser = j if b is short else i
            elif hb > ha + 0.3 or ha > hb + 0.3:
                loser = j if hb > ha else i
            elif abs(pa - pb) > 0.03:          # linja kauempana julkisivusta (esim. lasin tasossa)
                loser = j if pb > pa else i
            elif gindex is not None and (out := _outside(long_, ground_xy, gindex)) != 0 and _comparable(a, b):
                # ulompi jää: sisempi on syvennysten (ikkunat, ovet) pohjista koottu
                oa, ob = (a.p0 + a.p1) / 2 @ n * out, (b.p0 + b.p1) / 2 @ n * out
                loser = i if oa < ob else j
            else:
                loser = j if b is short else i
            drop.add(loser)
            if loser == i:
                break
    return [s for k, s in enumerate(segs) if k not in drop]


def _band(xyz: np.ndarray, height, lo: float, hi: float, chunk: int = 5_000_000) -> np.ndarray:
    """Pisteet korkeusvälillä lo–hi maasta (height(pisteet) -> korkeus), paloittain."""
    parts = []
    for start in range(0, len(xyz), chunk):
        p = xyz[start:start + chunk]
        h = height(p)
        parts.append(p[(h >= lo) & (h < hi)])
    return np.concatenate(parts) if parts else np.zeros((0, 3))


def _drop_inside(segs: list[Segment], ground_xy: np.ndarray, res: float = 0.25, seal: int = 2) -> list[Segment]:
    """Rakennuksen sisällä olevat linjat pois (ikkunoista ja ovista näkyvät sisäseinät). Ruudukko täytetään
    ulkoreunalta seiniin asti (seinät levennetty seal ruutua, jolloin pienet aukot sulkeutuvat); myös
    alueet, joilla on keilattua maan tason pintaa (ground_xy: esim. sisäpiha), ovat ulkona; niistä täytetään
    seinillä, joiden alle 3 m aukot on suljettu, jottei täyttö valu ovista sisätiloihin.
    Linja on sisällä, jos kumpikaan sen puoli ei ole ulkona."""
    if len(segs) < 3:
        return segs
    ends = np.array([p for s in segs for p in (s.p0, s.p1)])
    lo = ends.min(0) - 2.0
    shape = tuple((np.ceil((ends.max(0) + 2.0 - lo) / res)).astype(int) + 1)
    if shape[0] * shape[1] > 40_000_000:
        return segs

    def cells(p):
        ij = np.floor((p - lo) / res).astype(np.int64)
        ok = np.all((ij >= 0) & (ij < shape), axis=1)
        return ij[ok]

    wall = np.zeros(shape, bool)
    for s in segs:
        t = np.linspace(0, 1, max(2, int(np.ceil(s.length / (res / 2))) + 1))
        ij = cells(s.p0 + np.outer(t, s.p1 - s.p0))
        wall[ij[:, 0], ij[:, 1]] = True
    for _ in range(seal):
        w = wall.copy()
        w[1:] |= wall[:-1]
        w[:-1] |= wall[1:]
        w[:, 1:] |= wall[:, :-1]
        w[:, :-1] |= wall[:, 1:]
        wall = w
    free = ~wall

    def flood_in(out, space):
        out = out & space
        while True:
            grown = out.copy()
            grown[1:] |= out[:-1]
            grown[:-1] |= out[1:]
            grown[:, 1:] |= out[:, :-1]
            grown[:, :-1] |= out[:, 1:]
            grown &= space
            if (grown == out).all():
                return out
            out = grown

    flood = lambda out: flood_in(out, free)                                    # noqa: E731

    edge = np.zeros(shape, bool)
    edge[[0, -1], :] = True
    edge[:, [0, -1]] = True
    from_edge = flood(edge)
    dense = np.zeros(shape, bool)
    if len(ground_xy):
        gij = cells(ground_xy)
        count = np.zeros(shape)
        np.add.at(count, (gij[:, 0], gij[:, 1]), 1)
        # Muutama piste riittää: ground_xy on jo rajattu maan tasoon (Ground.raised), joten sisälattia ei
        # kelpaa, ja harvemmin keilattu pieni sisäpiha jäi tiheysrajalla (puolet tyypillisestä) sisätilaksi.
        dense = count >= 2
    # Täyttö maanpinnasta (sisäpiha) seinillä, joita on levennetty lisää: täyttö kadulta tai sisäpihalta ei
    # valu alle 3 m aukoista (ovet, porttikäytävät) rakennuksen sisään. Lopuksi alue levennetään takaisin
    # seinien viereen.
    def grow(a, n):
        for _ in range(n):
            g = a.copy()
            g[1:] |= a[:-1]
            g[:-1] |= a[1:]
            g[:, 1:] |= a[:, :-1]
            g[:, :-1] |= a[:, 1:]
            a = g
        return a

    widen = int(1.5 / res)
    tight = ~grow(wall, widen)
    near_ground = grow(flood_in(dense, tight), widen + seal + 1)
    keep = []
    for s in segs:
        if s.length < 1.0:          # nurkkien ja porrastusten liitospalat
            keep.append(s)
            continue
        # Kummaltakin puolelta linjan kolmesta kohdasta: ensimmäinen vapaa ruutu enintään 2 m päästä
        outside = False
        for t in (0.25, 0.5, 0.75):
            p = s.p0 + t * (s.p1 - s.p0)
            for sign in (1, -1):
                ij = cells(p + sign * np.outer(np.arange(seal + 1, int(2.0 / res)) * res, s.normal))
                f = ij[free[ij[:, 0], ij[:, 1]]]
                if len(f) == 0 or near_ground[f[0, 0], f[0, 1]] or from_edge[f[0, 0], f[0, 1]]:
                    outside = True
                    break
            if outside:
                break
        if outside:
            keep.append(s)
    return keep


def _near_cells(xy: np.ndarray, cells: np.ndarray, dist: float, chunk: int = 5_000_000) -> np.ndarray:
    """Maski: pisteet, joiden lähellä (dist, ruuduittain) on seinäsolu. Paloittain (iso pilvi)."""
    if len(cells) == 0:
        return np.zeros(len(xy), bool)
    c = np.floor(cells / dist).astype(np.int64)
    off = c.min(0) - 1
    c -= off
    w = int(c[:, 1].max()) + 2
    keys = np.unique([(c[:, 0] + di) * w + (c[:, 1] + dj) for di in (-1, 0, 1) for dj in (-1, 0, 1)])
    out = np.zeros(len(xy), bool)
    for start in range(0, len(xy), chunk):
        q = np.floor(xy[start:start + chunk] / dist).astype(np.int64) - off
        inside = (q[:, 1] >= 0) & (q[:, 1] < w)
        part = np.zeros(len(q), bool)
        part[inside] = np.isin(q[inside, 0] * w + q[inside, 1], keys)
        out[start:start + chunk] = part
    return out


@dataclass
class WallCheck:
    """Seinälinjan etäisyys pilven seinäpinnasta (wall_residuals): offsets = etumerkillinen ero [m]
    näytteittäin (+ = pinta normaalin puolella, NaN = ei seinäpintaa), tilt = lineaarinen ero päästä päähän."""
    segment: Segment
    offsets: np.ndarray

    @property
    def found(self) -> np.ndarray:
        return self.offsets[~np.isnan(self.offsets)]

    @property
    def tilt(self) -> float:
        ok = ~np.isnan(self.offsets)
        if ok.sum() < 4:
            return float("nan")
        t = np.linspace(0, 1, len(self.offsets))[ok]
        return float(np.polyfit(t, self.offsets[ok], 1)[0])


def wall_residuals(xyz: np.ndarray, segments: list[Segment], opt: WallOptions | None = None, step: float = 0.25,
                   search: float = 0.6, side: float = 0.15, min_layers: int = 5) -> list[WallCheck]:
    """Kuinka kaukana pilven seinäpinta on kustakin linjasta step välein. Kohdassa seinäpinta on se
    etäisyys normaalin suunnassa (enintään search), jolla pisteitä on eniten eri korkeuksilla (10 cm
    kerrokset cover_min–cover_max maasta): pystysuora pinta erottuu räystäästä ja kasvillisuudesta.
    Näytteet alkavat 2 × side linjan päistä, jottei nurkan toinen seinä osu ikkunaan."""
    opt = opt or WallOptions()
    if not segments:
        return []
    ends = np.array([p for s in segments for p in (s.p0, s.p1)])
    lo, hi = ends.min(0) - search - 1, ends.max(0) + search + 1
    near = xyz[np.all((xyz[:, :2] >= lo) & (xyz[:, :2] <= hi), axis=1)]
    rel = relative_height(near, opt)
    keep = (rel >= opt.cover_min) & (rel < opt.cover_max)
    near, layer = near[keep, :2], np.floor((rel[keep] - opt.cover_min) / 0.1).astype(np.int64)
    out = []
    for seg in segments:
        d, n, L = seg.direction, seg.normal, seg.length
        end = 2 * side
        if L < 2 * end:
            continue
        sv, tv = (near - seg.p0) @ d, (near - seg.p0) @ n
        band = (sv > -side) & (sv < L + side) & (np.abs(tv) < search)
        sv, tv, lv = sv[band], tv[band], layer[band]
        k = max(1, int((L - 2 * end) / step))
        offsets = np.full(k + 1, np.nan)
        for i, sk in enumerate(end + (L - 2 * end) * np.arange(k + 1) / k):
            sel = np.abs(sv - sk) < side
            if sel.sum() < min_layers:
                continue
            bins = np.floor((tv[sel] + search) / 0.02).astype(np.int64)
            pairs = np.unique(bins * 1000 + lv[sel])
            cover = np.bincount(pairs // 1000, minlength=int(2 * search / 0.02) + 2)
            peak = int(np.argmax(np.convolve(cover, np.ones(3), "same")))
            if cover[max(0, peak - 1):peak + 2].max() < min_layers:
                continue
            centre = (peak + 0.5) * 0.02 - search
            offsets[i] = float(np.mean(tv[sel][np.abs(tv[sel] - centre) < 0.03]))
        out.append(WallCheck(seg, offsets))
    return out


def check_summary(checks: list[WallCheck]) -> str:
    """Seinälinjojen tarkkuus pilveen nähden yhdellä rivillä (pituuksilla painotettu)."""
    rows = [(c.segment.length, np.mean(np.abs(c.found)), abs(c.tilt)) for c in checks if len(c.found) >= 4]
    if not rows:
        return "Seinäpintaa ei löytynyt linjojen kohdalta."
    w, err, tilt = map(np.array, zip(*rows))
    return (f"Seinäpinta keskimäärin {np.average(err, weights=w) * 100:.1f} cm linjasta, kallistus päästä "
            f"päähän {np.average(tilt, weights=w) * 100:.1f} cm ({len(rows)} linjaa; yli 3 cm kallellaan "
            f"{int((tilt > 0.03).sum())}).")


def outward_normals(segments: list[Segment], tol: float = 0.002) -> np.ndarray:
    """Linjojen normaalit (n x 2) talosta ulospäin: poispäin oman ketjun (nurkissa toisiinsa liittyvät
    linjat) painopisteestä. Yksittäinen linja tai suora ketju suunnataan kaikkien linjojen painopisteestä."""
    if not segments:
        return np.zeros((0, 2))
    parent = list(range(len(segments)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ends = [(s.p0, s.p1) for s in segments]
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            if min(np.linalg.norm(a - b) for a in ends[i] for b in ends[j]) < tol:
                parent[root(i)] = root(j)
    mids = np.array([(s.p0 + s.p1) / 2 for s in segments])
    w = np.array([max(s.length, 1e-6) for s in segments])
    overall = np.average(mids, axis=0, weights=w)
    normals = np.array([s.normal for s in segments], dtype=float)
    groups = np.array([root(i) for i in range(len(segments))])
    for g in set(groups):
        k = np.flatnonzero(groups == g)
        bent = any(abs(segments[a].direction @ segments[b].direction) < 0.9 for a in k for b in k)
        centre = np.average(mids[k], axis=0, weights=w[k]) if bent else overall
        flip = np.einsum("ij,ij->i", mids[k] - centre, normals[k]) < 0
        normals[k[flip]] *= -1
    return normals


def signed_distances(xy: np.ndarray, p0: np.ndarray, p1: np.ndarray, normals: np.ndarray,
                     max_dist: float = 0.5, sample: float = 0.02, chunk: int = 5_000_000) -> np.ndarray:
    """Pisteiden (n x 2) etumerkillinen etäisyys lähimpään linjaan p0–p1 (+ = normaalin puolella eli
    ulompana); NaN, jos lähin linja on kauempana kuin max_dist. Lähin linja haetaan linjoille
    sample välein tehdyistä näytteistä (k-d-puu), etäisyys lasketaan tarkasti siihen. Ilman scipyä
    (esim. CloudComparen Python) linjat käydään läpi yksitellen."""
    out = np.full(len(xy), np.nan)
    if len(p0) == 0 or len(xy) == 0:
        return out
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return _signed_distances_numpy(xy, p0, p1, normals, max_dist)
    d = p1 - p0
    length = np.linalg.norm(d, axis=1)
    samples, owner = [], []
    for k in range(len(p0)):
        t = np.linspace(0, 1, max(2, int(np.ceil(length[k] / sample)) + 1))
        samples.append(p0[k] + np.outer(t, d[k]))
        owner.append(np.full(len(t), k))
    samples, owner = np.vstack(samples), np.concatenate(owner)
    lo, hi = samples.min(0) - max_dist, samples.max(0) + max_dist
    tree = cKDTree(samples)
    # Osissa, jottei iso pilvi (Stonex: ~100 milj. pistettä) vie kymmeniä gigatavuja muistia
    for start in range(0, len(xy), chunk):
        part = xy[start:start + chunk]
        cand = np.flatnonzero(np.all((part >= lo) & (part <= hi), axis=1))
        # Muutama lähin näyte: nurkassa lähin linja ratkaistaan tarkasti (_closest)
        dist, idx = tree.query(part[cand], k=4, distance_upper_bound=max_dist + sample, workers=-1)
        best = np.full(len(cand), np.inf)
        value = np.full(len(cand), np.nan)
        for col in range(idx.shape[1]):
            hit = np.flatnonzero(np.isfinite(dist[:, col]))
            k = owner[idx[hit, col]]
            rank, val = _closest(part[cand[hit]], p0[k], d[k], normals[k])
            better = rank < best[hit]
            best[hit[better]], value[hit[better]] = rank[better], val[better]
        ok = np.abs(value) <= max_dist
        out[start + cand[ok]] = value[ok]
    return out


def _closest(xy, a, d, n):
    """Etäisyys janoihin a + t·d rivettäin: (järjestysarvo, etumerkillinen etäisyys). Pään ohi oleva
    piste (nurkan ulkopuolella) saa pienen lisän, jotta kohdalla oleva linja ratkaisee etumerkin."""
    rel = xy - a
    t_raw = np.einsum("ij,ij->i", rel, d) / np.maximum(np.einsum("ij,ij->i", d, d), 1e-12)
    t = np.clip(t_raw, 0, 1)
    diff = rel - d * t[:, None]
    dist = np.linalg.norm(diff, axis=1)
    return dist + 1e-6 * (t != t_raw), dist * np.sign(np.einsum("ij,ij->i", diff, n))


def _signed_distances_numpy(xy, p0, p1, normals, max_dist):
    """signed_distances ilman scipyä: jokaiselle linjalle sen ympäristön pisteet, lähin linja voittaa."""
    out = np.full(len(xy), np.nan)
    best = np.full(len(xy), np.inf)
    for a, b, n in zip(p0, p1, normals):
        lo, hi = np.minimum(a, b) - max_dist, np.maximum(a, b) + max_dist
        cand = np.flatnonzero(np.all((xy >= lo) & (xy <= hi), axis=1))
        m = len(cand)
        rank, val = _closest(xy[cand], np.tile(a, (m, 1)), np.tile(b - a, (m, 1)), np.tile(n, (m, 1)))
        better = (rank < best[cand]) & (np.abs(val) <= max_dist)
        best[cand[better]], out[cand[better]] = rank[better], val[better]
    return out


# --- Iso pilvi ruuduittain (lidarpipe walls-tiled ja QGIS-lisäosan ruutuajo): ruudut luetaan limittäin, ja
# kustakin pidetään linjat, joiden keskipiste on ruudun ytimessä; saumojen tuplat ja aidat (kattosuodatin) pois.

def tile_core(segs: list[Segment], base: np.ndarray, tile: float,
              margin: float = 2.0) -> list[tuple[Segment, float]]:
    """Ruudun (paikalliset koordinaatit, ydin 0..tile) linjat, joiden keskipiste on ytimessä tai enintään margin
    sen ulkopuolella, siirrettynä base:lla ja keskipisteen syvyys ytimessä (m, + = sisällä). Pisteet
    harvennetaan 5 cm:iin: ne kertovat DXF:ään mitatun ja päätellyn osan (measured_pieces, aukko yli 0,5 m)."""
    base = np.asarray(base, float)[:2]
    out = []
    for s in segs:
        m = (s.p0[:2] + s.p1[:2]) / 2
        depth = float(min(m[0], m[1], tile - m[0], tile - m[1]))
        if depth <= -margin:
            continue                       # limitysalueen linja kuuluu naapuriruudulle
        s.p0 = s.p0 + np.r_[base, np.zeros(len(s.p0) - 2)]
        s.p1 = s.p1 + np.r_[base, np.zeros(len(s.p1) - 2)]
        pts = s.points[:, :2]
        _, first = np.unique(np.floor(pts / 0.05).astype(np.int64), axis=0, return_index=True)
        s.points = pts[np.sort(first)] + base
        out.append((s, depth))
    return out


def drop_seam_duplicates(found: dict, margin: float = 2.0, side: float = 0.2,
                         angle_deg: float = 5.0) -> list[Segment]:
    """Ruutujen rajalla sama seinä voi löytyä kahdesta ruudusta (keskipiste rajan kummallakin puolella
    pyöristyksen tai hieman eri päätepisteiden takia). found: {ruutu: tile_core-tulos}. Reunavaran linjoista
    pidetään päällekkäisistä se, jonka keskipiste on syvemmällä omassa ruudussaan (vaikka se olisi hieman ytimen
    ulkopuolella); ilman vastinetta reunavaran linja pidetään vain, jos sen keskipiste on ytimessä."""
    items = [(k, s, d) for k in sorted(found) for s, d in found[k]]
    edge = [i for i, (_, _, d) in enumerate(items) if d < margin]
    drop, won = set(), set()
    cos = np.cos(np.radians(angle_deg))
    for a in edge:
        ka, sa, da = items[a]
        for b in edge:
            kb, sb, db = items[b]
            if kb == ka or (db, b) <= (da, a):
                continue                  # vain syvempi b voi pudottaa a:n
            if abs(sa.direction @ sb.direction) < cos:
                continue
            mb = (sb.p0 + sb.p1) / 2
            if abs(sa.normal @ (mb - (sa.p0 + sa.p1) / 2)) > side:
                continue
            ta = sorted((sa.p0 @ sa.direction, sa.p1 @ sa.direction))
            tb = sorted((sb.p0 @ sa.direction, sb.p1 @ sa.direction))
            if min(ta[1], tb[1]) - max(ta[0], tb[0]) > 0.5 * min(sa.length, sb.length):
                drop.add(a)
                won.add(b)
                break
    return [s for i, (_, s, d) in enumerate(items) if i not in drop and (d >= 0 or i in won)]


def roof_share(segs: list[Segment], roof: np.ndarray, cell: float, dist: float, offset=(0.0, 0.0),
               step: float = 0.25) -> np.ndarray:
    """Osuus kunkin linjan pituudesta, jonka dist-säteellä on kattoa. roof: kattorasteri (bool, x, y), solu
    cell, origo = linjojen koordinaatit + offset. Ilmakeilauksen katot erottavat seinät aidoista ja muureista,
    joilla ei ole kattoa vieressä (seinä on räystään alla). Ilman scipyä (QGIS:n Python)."""
    r = int(np.ceil(dist / cell))
    near = np.zeros_like(roof, dtype=bool)
    nx, ny = roof.shape
    for di in range(-r, r + 1):
        for dj in range(-r, r + 1):
            if di * di + dj * dj > r * r:
                continue
            near[max(0, di):nx + min(0, di), max(0, dj):ny + min(0, dj)] |= \
                roof[max(0, -di):nx + min(0, -di), max(0, -dj):ny + min(0, -dj)]
    out = np.zeros(len(segs))
    for i, s in enumerate(segs):
        n = max(2, int(np.ceil(s.length / step)) + 1)
        p = s.p0[:2] + np.linspace(0, 1, n)[:, None] * (s.p1[:2] - s.p0[:2]) + np.asarray(offset, float)
        q = np.floor(p / cell).astype(np.int64)
        inside = (q[:, 0] >= 0) & (q[:, 0] < nx) & (q[:, 1] >= 0) & (q[:, 1] < ny)
        hit = np.zeros(n, bool)
        hit[inside] = near[q[inside, 0], q[inside, 1]]
        out[i] = hit.mean()
    return out


def measured_pieces(segments: list[Segment], gap: float = 0.5, tol: float = 0.1) -> list[tuple]:
    """Linjat mitattuihin ja pääteltyihin osiin: [(alku, loppu, mitattu, snapped)]. Mitattu = linjan omien
    pisteiden kattama matka (yli gap aukot ja yli tol jatkeet ovat päätelty: ääriviivan liitokset,
    katveisiin jatketut nurkat ja porrastusten poikkipalat, joiden kohdalla ei ole pisteitä)."""
    out = []
    for s in segments:
        L = s.length
        if L < 1e-9:
            continue
        d = (s.p1 - s.p0) / L
        t = np.sort((s.points - s.p0) @ d) if len(s.points) else np.zeros(0)
        t = t[(t > -tol) & (t < L + tol)]
        runs = []
        if len(t):
            breaks = np.flatnonzero(np.diff(t) > gap)
            starts, ends = np.r_[t[0], t[breaks + 1]], np.r_[t[breaks], t[-1]]
            runs = [(max(0.0, a), min(L, b)) for a, b in zip(starts, ends) if b - a > 0.05]
            if runs and runs[0][0] <= tol:
                runs[0] = (0.0, runs[0][1])
            if runs and runs[-1][1] >= L - tol:
                runs[-1] = (runs[-1][0], L)
        pos = 0.0
        for a, b in runs + [(L, L)]:
            if a - pos > 1e-6:
                out.append((s.p0 + d * pos, s.p0 + d * a, False, s.snapped))
            if b - a > 1e-6:
                out.append((s.p0 + d * a, s.p0 + d * b, True, s.snapped))
            pos = max(pos, b)
    return out


def _pieces_as_segments(pieces) -> list[Segment]:
    out = []
    for a, b, _, snapped in pieces:
        d = (b - a) / np.linalg.norm(b - a)
        out.append(Segment(np.array(a, float), np.array(b, float), d, float(np.array([-d[1], d[0]]) @ a),
                           np.zeros((0, 2)), snapped=snapped))
    return out


# DXF-layerit ja AutoCAD-värit (write_dxf ja write_dxf_r12): PAATELTY harmaa katkoviiva
DXF_LAYERS = {"SEINA": (7, "CONTINUOUS"), "EPAVARMA": (1, "CONTINUOUS"), "PAATELTY": (8, "DASHED")}


def write_dxf_r12(path, polylines) -> None:
    """Murtoviivat DXF R12:ksi ilman lisäkirjastoja (CloudComparen Pythonissa ei ole ezdxf:ää):
    polylines = [(layer, [(x, y, z), ...], suljettu)]. Layer-taulukossa värit ja PAATELTY-layerin
    katkoviiva (DXF_LAYERS); muut layerit valkoisina. QGIS, MicroStation ja AutoCAD lukevat."""
    def r(*pairs):
        return [str(v) for pair in pairs for v in pair]

    layers = dict(DXF_LAYERS)
    for layer, _, _ in polylines:
        layers.setdefault(layer, (7, "CONTINUOUS"))
    out = r(("0", "SECTION"), ("2", "TABLES"), ("0", "TABLE"), ("2", "LTYPE"), ("70", 2),
            ("0", "LTYPE"), ("2", "CONTINUOUS"), ("70", 0), ("3", "Solid line"), ("72", 65), ("73", 0), ("40", "0.0"),
            ("0", "LTYPE"), ("2", "DASHED"), ("70", 0), ("3", "__ __ __"), ("72", 65), ("73", 2), ("40", "0.75"),
            ("49", "0.5"), ("49", "-0.25"), ("0", "ENDTAB"), ("0", "TABLE"), ("2", "LAYER"), ("70", len(layers)))
    for name, (color, ltype) in layers.items():
        out += r(("0", "LAYER"), ("2", name), ("70", 0), ("62", color), ("6", ltype))
    out += r(("0", "ENDTAB"), ("0", "ENDSEC"), ("0", "SECTION"), ("2", "ENTITIES"))
    for layer, pts, closed in polylines:
        color = layers[layer][0]
        out += r(("0", "POLYLINE"), ("8", layer), ("62", color), ("66", 1), ("70", 9 if closed else 8))
        for x, y, z in pts:
            out += r(("0", "VERTEX"), ("8", layer), ("10", f"{x:.4f}"), ("20", f"{y:.4f}"), ("30", f"{z:.4f}"),
                     ("70", 32))
        out += r(("0", "SEQEND"), ("8", layer))
    out += r(("0", "ENDSEC"), ("0", "EOF"))
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write("\n".join(out) + "\n")


def write_dxf(path, segments: list[Segment], z: float = 0.0, targets: dict[str, np.ndarray] | None = None,
              offset: np.ndarray | None = None) -> None:
    """offset (E, N) lisätään kaikkiin koordinaatteihin (paikallinen -> kartta)."""
    off = np.zeros(2) if offset is None else np.asarray(offset, float)[:2]
    import ezdxf

    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.M
    for name, (color, ltype) in DXF_LAYERS.items():
        doc.layers.add(name, color=color, linetype=ltype)
    doc.layers.add("TAHYKSET", color=3)
    msp = doc.modelspace()
    # Päätellyt osat (ääriviivan liitokset, ks. measured_pieces) omalle layerilleen: ääriviiva näkyy
    # yhtenäisenä, mutta SEINA/EPAVARMA ovat vain mitattua (QGIS-lisäosa vertaa niihin)
    pieces = measured_pieces(segments)
    for layer, group in (("SEINA", [p for p in pieces if p[2] and p[3]]),
                         ("EPAVARMA", [p for p in pieces if p[2] and not p[3]]),
                         ("PAATELTY", [p for p in pieces if not p[2]])):
        for poly in chains(_pieces_as_segments(group)):
            closed = len(poly) > 3 and np.linalg.norm(poly[0] - poly[-1]) < 0.002
            pts = [tuple(p + off) for p in (poly[:-1] if closed else poly)]
            msp.add_lwpolyline(pts, close=closed, dxfattribs={"layer": layer, "elevation": z})
    for name, p in (targets or {}).items():
        q = np.asarray(p, float)[:2] + off
        msp.add_point((q[0], q[1], z), dxfattribs={"layer": "TAHYKSET"})
        msp.add_text(str(name), height=0.15, dxfattribs={"layer": "TAHYKSET"}).set_placement(
            (q[0] + 0.1, q[1] + 0.1, z)
        )
    doc.saveas(str(path))
