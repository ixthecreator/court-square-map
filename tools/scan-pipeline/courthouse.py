"""LOD3 detail for the Long Island City Courthouse (BIN 4000698), placed on its 2014 LOD2 massing.

The walls and roofs up to the main roof (21.2 m) are the NYC 3D Building Model. Everything added here is read off photos
(Wikimedia Commons, 2018-2026), so sizes and positions are approximate:
- limestone base with rustication, water table, string course, main cornice, parapet and corner pilasters on the brick walls
- windows with limestone surrounds and white sashes, set out in bays on every wall that is not covered by a lower block
- the park entrance: landing, arched doorway with fanlight, two pairs of columns on pedestals, entablature, balustrade,
  stair cheek walls, and the parapet with an oculus above it
- the mansard over the attic block and the copper roof over the centre pavilion (the survey has both as boxes)
"""
import math
import numpy as np
from shapely import affinity
from shapely.geometry import Polygon, Point, box
from shapely.ops import unary_union
import model_parts as mp

BRICK, LIME, LIME_DK, GLASS = (176, 92, 70), (226, 218, 200), (196, 188, 170), (46, 56, 66)
SASH, DOOR, COPPER, SLATE = (232, 230, 222), (70, 48, 36), (124, 176, 156), (108, 64, 56)
ROOF_Z = 21.2          # main roof; the survey's attic and centre blocks above it are rebuilt here
BASE_TOP = 4.8         # top of the limestone base (the low wings reach about the same height)
UP = np.array([0, 0, 1.0])


def _xy_poly(W, tri):
    return unary_union([Polygon(W[t][:, :2]) for t in tri if Polygon(W[t][:, :2]).area > 1e-6])


def _bays(s0, s1, bay, margin):
    L = s1 - s0 - 2 * margin
    if L < 0:
        return []
    n = int(L // bay) + 1
    return [(s0 + s1) / 2 + (k - (n - 1) / 2) * bay for k in range(n)]


class Wall:
    """A vertical wall of the massing: s runs along it, d outward from it, z up (park frame)."""

    def __init__(self, n, off, s0, s1, z0, z1):
        self.n = np.array([n[0], n[1], 0.0]); self.a = np.array([-n[1], n[0], 0.0])
        self.o = self.n * off            # the wall plane passes through o; s = 0 there
        self.s0, self.s1, self.z0, self.z1 = s0, s1, z0, z1

    def at(self, s, d=0.0, z=0.0):
        return self.o + s * self.a + d * self.n + z * UP

    def box(self, s0, s1, d0, d1, z0, z1):
        return mp.frame_box(self.o, self.a[:2], self.n[:2], s0, s1, d0, d1, z0, z1)

    def prism(self, poly, d0, d1):
        """Shapely polygon drawn in the wall plane (x = s, y = z), pushed out from d0 to d1."""
        pts, tri, rings = mp.triangulate(poly)
        place = lambda d: self.o + pts[:, :1] * self.a + pts[:, 1:2] * UP + d * self.n
        k = len(pts)
        V = np.vstack([place(d1), place(d0)])
        F, start = [tri, tri[:, [0, 2, 1]] + k], 0
        for r in rings:
            m = len(r); idx = np.arange(start, start + m); nxt = np.roll(idx, -1)
            F.append(np.column_stack([idx, nxt, nxt + k])); F.append(np.column_stack([idx, nxt + k, idx + k]))
            start += m
        return V, np.vstack(F)


def _arch(half, z0, zs, grow=0.0, n=16):
    r = half + grow
    pts = [(-r, z0), (r, z0)] + [(r * math.cos(t), zs + r * math.sin(t)) for t in np.linspace(0, math.pi, n)]
    return Polygon(pts)


def _hip(rect, profile):
    """Roof lofted through rectangles inset by profile [(inset, z), ...], capped at the top."""
    x0, y0, x1, y1 = rect
    rings = [[(x0 + i, y0 + i, z), (x1 - i, y0 + i, z), (x1 - i, y1 - i, z), (x0 + i, y1 - i, z)] for i, z in profile]
    V = np.array([p for r in rings for p in r], float); F = []
    for k in range(len(rings) - 1):
        for j in range(4):
            a, b = 4 * k + j, 4 * k + (j + 1) % 4
            F += [(a, b, b + 4), (a, b + 4, a + 4)]
    t = 4 * (len(rings) - 1)
    F += [(t, t + 1, t + 2), (t, t + 2, t + 3)]
    return V, np.array(F)


def build(faces, axis_u, facade_v, z_entry):
    """faces: LOD2 faces from build_model.lod2_faces. Returns (massing, parts):
    massing = {'walls': [...], 'roofs': [...]} kept from the survey; parts = [(part name, colour, (V, F), smooth), ...]."""
    out = {}

    def put(key, vf):
        out.setdefault(key, []).append(vf)

    upper, kept_walls, kept_roofs, bottoms = [], [], [], []
    for (W, tri), is_roof, z0, z1, nz in faces:
        if nz < -0.5:
            bottoms.append(_xy_poly(W, tri)); kept_walls.append((W, tri)); continue
        if z0 > ROOF_Z - 0.05 and not is_roof:
            upper.append(((W, tri), is_roof, z0, z1)); continue
        if is_roof and z1 > ROOF_Z + 0.05:
            upper.append(((W, tri), is_roof, z0, z1)); continue
        (kept_roofs if is_roof else kept_walls).append(((W, tri), z1) if is_roof else (W, tri))
    up_roofs = [(_xy_poly(W, tri), z1) for (W, tri), is_roof, z0, z1 in upper if is_roof]
    tower_poly, tower_z = max(up_roofs, key=lambda r: r[1])
    attic = unary_union([p for p, z in up_roofs]).union(tower_poly)
    # a second survey roof at 21.2 m lies under the attic: drop it (it would fight with the mansard)
    kept_roofs = [(vf, z) for vf, z in kept_roofs if not _xy_poly(*vf).within(attic.buffer(0.3))]
    roofs_xy = [(_xy_poly(*vf), z) for vf, z in kept_roofs] + [(attic, 25.4), (tower_poly, tower_z)]

    def H(p):
        pt = Point(p[0], p[1])
        return max([z for poly, z in roofs_xy if poly.contains(pt)], default=-99.0)

    # ---- walls: merge coplanar survey faces into one wall each
    recs = {}
    for W, tri in kept_walls:
        n = np.cross(W[tri[:, 1]] - W[tri[:, 0]], W[tri[:, 2]] - W[tri[:, 0]]).sum(0)
        n /= np.linalg.norm(n)
        if abs(n[2]) > 0.2:
            continue
        nh = n[:2] / np.linalg.norm(n[:2]); a = np.array([-nh[1], nh[0]])
        s = W[:, :2] @ a; off = float(np.mean(W[:, :2] @ nh))
        key = (round(math.degrees(math.atan2(nh[1], nh[0]))), round(off * 5) / 5, round(W[:, 2].min(), 1), round(W[:, 2].max(), 1))
        recs.setdefault(key, []).append((s.min(), s.max(), nh, off, W[:, 2].min(), W[:, 2].max()))
    walls = []
    for key, segs in recs.items():
        segs.sort(key=lambda t: t[0])
        cur = list(segs[0])
        for sg in segs[1:] + [None]:
            if sg is not None and sg[0] <= cur[1] + 0.1:
                cur[1] = max(cur[1], sg[1]); continue
            walls.append(Wall(cur[2], cur[3], cur[0], cur[1], cur[4], cur[5]))
            if sg is not None:
                cur = list(sg)

    def hidden(w, s, z, d=0.4):
        return H(w.at(s, d)) > z

    def band(w, z0, z1, d1, d0=0.0, key='lime', wrap=True):
        """Horizontal band along the wall, left out where a lower block covers the wall."""
        z0 = max(z0, w.z0)
        if z0 < w.z1 - 0.01:              # bands that start at the wall head (parapets) may rise above it
            z1 = min(z1, w.z1)
        if z1 <= z0:
            return
        L = w.s1 - w.s0; n = max(1, int(L / 1.0)); edges = np.linspace(w.s0, w.s1, n + 1)
        vis = [not hidden(w, (edges[i] + edges[i + 1]) / 2, (z0 + z1) / 2) for i in range(n)]
        i = 0
        while i < n:
            if not vis[i]:
                i += 1; continue
            j = i
            while j + 1 < n and vis[j + 1]:
                j += 1
            e0 = edges[i] - (d1 if wrap and i == 0 else 0); e1 = edges[j + 1] + (d1 if wrap and j == n - 1 else 0)
            put(key, w.box(e0, e1, d0, d1, z0, z1)); i = j + 1

    def window(w, sc, za, zb, wd, d0=0.0, hood=True, rail=True):
        h = wd / 2
        put('glass', w.box(sc - h, sc + h, d0, d0 + 0.03, za, zb))
        put('sash', w.box(sc - 0.03, sc + 0.03, d0 + 0.03, d0 + 0.06, za, zb))
        if rail:
            zm = za + 0.55 * (zb - za); put('sash', w.box(sc - h, sc + h, d0 + 0.03, d0 + 0.06, zm - 0.03, zm + 0.03))
        put('lime', w.box(sc - h - 0.16, sc - h, d0, d0 + 0.12, za - 0.12, zb + 0.12))
        put('lime', w.box(sc + h, sc + h + 0.16, d0, d0 + 0.12, za - 0.12, zb + 0.12))
        put('lime', w.box(sc - h - 0.2, sc + h + 0.2, d0, d0 + 0.16, za - 0.24, za - 0.12))
        if hood:
            put('lime', w.box(sc - h - 0.28, sc + h + 0.28, d0, d0 + 0.2, zb + 0.12, zb + 0.42))

    def oculus(w, sc, zc, r, d0=0.0):
        put('glass', w.prism(Point(sc, zc).buffer(r, 4), d0, d0 + 0.03))
        put('lime', w.prism(Point(sc, zc).buffer(r + 0.18, 4).difference(Point(sc, zc).buffer(r, 4)), d0, d0 + 0.14))

    # ---- the park facade and its entrance
    park_wall = max((w for w in walls if w.n[1] > 0.95 and w.z1 > 17), key=lambda w: w.s1 - w.s0)
    wall_v = float(park_wall.o[1])
    s_c = float(np.dot([axis_u, wall_v, 0], park_wall.a))
    z_top = z_entry
    ENT = 5.7                                    # half width of the limestone centre pavilion

    for w in walls:
        L = w.s1 - w.s0
        main, mid = w.z1 > 17, 8 < w.z1 <= 17
        is_park = w is park_wall
        in_ent = (lambda s: abs(s - s_c) < ENT + 0.2) if is_park else (lambda s: False)
        if main:
            base_top, bay, rows = BASE_TOP, 3.3, [(1.0, 3.4, 1.2, False), (6.0, 9.4, 1.3, True), (10.4, 13.1, 1.3, True),
                                                  (14.5, 17.0, 1.3, True), (19.0, 20.4, 1.0, False)]
        elif mid:
            base_top, bay, rows = 1.0, 3.3, [(1.8, 4.2, 1.2, True), (5.4, 8.4, 1.2, True)]
        else:
            base_top, bay, rows = 0.8, 3.6, [(1.3, 3.4, 1.4, True)]
        dbase = 0.08
        # base cladding with rustication grooves
        if w.z0 < base_top:
            band(w, w.z0, base_top, dbase)
            if main:
                for zg in np.arange(0.4, base_top - 0.3, 0.55):
                    band(w, zg, zg + 0.03, dbase + 0.006, key='lime_dk')
                band(w, base_top - 0.05, base_top + 0.25, 0.16)
        if main:
            band(w, 13.55, 13.85, 0.10)
            band(w, 17.55, 17.8, 0.22); band(w, 17.8, 18.4, 0.5)
            if L >= 6:
                for e0, e1 in ((w.s0, w.s0 + 0.9), (w.s1 - 0.9, w.s1)):
                    zs = max(base_top, w.z0, H(w.at((e0 + e1) / 2, 0.4)))
                    if zs < 17.5:
                        put('lime', w.box(e0, e1, 0, 0.06, zs, 17.55))
        if abs(w.z1 - ROOF_Z) < 0.1:
            band(w, ROOF_Z, ROOF_Z + 0.8, 0.05, d0=-0.3)            # parapet on the wall head
            band(w, ROOF_Z + 0.8, ROOF_Z + 0.95, 0.12, d0=-0.36)
        else:
            band(w, w.z1 - (0.6 if mid else 0.35), w.z1, 0.3 if mid else 0.14)
        for za, zb, wd, hood in rows:
            if za < w.z0 + 0.3 or zb > w.z1 - 0.4:
                continue
            d0 = dbase if zb <= base_top else 0.0
            for sc in _bays(w.s0, w.s1, bay, 1.4 if L > 4 else 0.9):
                if (in_ent(sc) and zb < 17.5) or hidden(w, sc, za - 0.2):
                    continue
                window(w, sc, za, zb, wd, d0, hood)
                if not main and not mid and zb + 1.0 < w.z1 - 0.35:
                    oculus(w, sc, zb + 0.75, 0.28)

    # entrance pavilion (centred on the park axis, like the stair)
    w = park_wall
    put('lime', w.box(s_c - ENT, s_c + ENT, 0, 0.1, BASE_TOP, 17.55))
    land = facade_v - wall_v
    put('lime', w.box(s_c - ENT - 0.5, s_c + ENT + 0.5, 0, land, z_top - 2.2, z_top))
    for sgn in (-1, 1):                          # narrow windows between the paired columns
        for za, zb in ((6.0, 9.4), (10.4, 13.1)):
            window(w, s_c + sgn * 3.5, za, zb, 0.75, 0.1, hood=False)
        window(w, s_c + sgn * 3.5, 15.6, 17.3, 0.75, 0.1, hood=False)
    window(w, s_c, 15.6, 17.3, 1.3, 0.1, hood=False)
    # arched doorway with fanlight
    half, spring = 1.6, z_top + 4.6
    put('glass', w.prism(affinity.translate(_arch(half, z_top, spring), s_c, 0), 0.1, 0.13))
    put('door', w.box(s_c - 1.1, s_c + 1.1, 0.13, 0.16, z_top, z_top + 3.2))
    put('sash', w.box(s_c - half, s_c + half, 0.13, 0.17, z_top + 3.2, z_top + 3.35))
    for sm in (-0.8, 0.0, 0.8):
        put('sash', w.box(s_c + sm - 0.03, s_c + sm + 0.03, 0.13, 0.17, z_top + 3.35, spring + math.sqrt(half ** 2 - sm ** 2) - 0.05))
    ring = _arch(half, z_top, spring, 0.45).difference(_arch(half, z_top - 1, spring))
    put('lime', w.prism(affinity.translate(ring, s_c, 0), 0.1, 0.35))
    put('lime', w.box(s_c - 0.3, s_c + 0.3, 0.1, 0.45, spring + half - 0.1, spring + half + 0.7))
    # columns on pedestals, entablature and balustrade
    z_cap = 13.8
    for sgn in (-1, 1):
        for so in (2.6, 4.4):
            s = s_c + sgn * so; p = w.at(s, 0.75)
            put('lime', w.box(s - 0.5, s + 0.5, 0.25, 1.25, z_top, z_top + 1.5))
            zb = z_top + 1.5; Hs = z_cap - 0.85 - zb
            prof = [(0.48, 0), (0.48, 0.12), (0.42, 0.22), (0.4, 0.3)] + [(0.4 - 0.06 * (t ** 1.5), 0.3 + t * (Hs - 0.3)) for t in np.linspace(0.1, 1, 6)] \
                + [(0.38, Hs + 0.3), (0.5, Hs + 0.8), (0.5, Hs + 0.85)]
            put('lime_s', mp.revolve(prof, (p[0], p[1], zb), 20))
            put('lime', w.box(s - 0.55, s + 0.55, 0.2, 1.3, z_cap - 0.05, z_cap + 0.12))
    put('lime', w.box(s_c - 5.3, s_c + 5.3, 0, 1.3, z_cap, z_cap + 0.8))
    put('lime', w.box(s_c - 5.5, s_c + 5.5, 0, 1.5, z_cap + 0.8, z_cap + 1.25))
    zr = z_cap + 1.25
    put('lime', w.box(s_c - 5.4, s_c + 5.4, 0.95, 1.4, zr, zr + 0.15))
    put('lime', w.box(s_c - 5.4, s_c + 5.4, 0.95, 1.4, zr + 0.85, zr + 1.0))
    for s in np.arange(s_c - 5.25, s_c + 5.3, 0.3):
        put('lime', w.box(s - 0.06, s + 0.06, 1.1, 1.25, zr + 0.15, zr + 0.85))
    # stair cheek walls with their end blocks
    zs = z_top - 10 * 0.165
    for sgn in (-1, 1):
        u0 = axis_u + sgn * 4.5
        prof = Polygon([(0, -0.4), (3.3, -0.4), (3.3, 0.7), (0, 10 * 0.165 + 0.7)])
        put('lime', mp.extrude_profile(prof, (u0, facade_v, zs), (1, 0), (0, 1), 0 if sgn > 0 else -0.8, 0.8 if sgn > 0 else 0))
        put('lime', mp.frame_box((u0 + sgn * 0.4, facade_v + 3.0, zs), (1, 0), (0, 1), -0.5, 0.5, -0.45, 0.45, -0.4, 1.3))
    # parapet with oculus and finials above the pavilion
    put('lime', w.box(s_c - ENT, s_c + ENT, -0.3, 0.12, ROOF_Z, ROOF_Z + 2.2))
    put('lime', w.box(s_c - ENT - 0.1, s_c + ENT + 0.1, -0.4, 0.22, ROOF_Z + 2.2, ROOF_Z + 2.4))
    oculus(w, s_c, ROOF_Z + 1.15, 0.7, 0.12)
    for sgn in (-1, 1):
        p = w.at(s_c + sgn * ENT, -0.05)
        put('lime_s', mp.revolve([(0.32, 0), (0.32, 0.25), (0.18, 0.4), (0.3, 0.75), (0.12, 1.05), (0.02, 1.2)], (p[0], p[1], ROOF_Z + 2.4), 12))

    # ---- roofs: mansard over the attic block, copper roof over the centre pavilion
    ax0, ay0, ax1, ay1 = unary_union([p for p, z in up_roofs if z < tower_z - 1]).bounds
    put('slate', _hip((ax0, ay0, ax1, ay1), [(0, ROOF_Z), (1.3, 25.0), (1.3, 25.4)]))
    tx0, ty0, tx1, ty1 = tower_poly.bounds
    put('lime', mp.prism(box(tx0, ty0, tx1, ty1), ROOF_Z, 24.0))
    put('lime', mp.prism(box(tx0 - 0.25, ty0 - 0.25, tx1 + 0.25, ty1 + 0.25), 23.7, 24.0))
    top = 31.4
    put('copper', _hip((tx0, ty0, tx1, ty1), [(0, 24.0), (0.7, 25.6), (1.6, 27.4), (2.5, 29.4), (3.1, 30.8), (3.3, top)]))
    ring = box(tx0 + 3.3, ty0 + 3.3, tx1 - 3.3, ty1 - 3.3)
    put('copper', mp.prism(ring.difference(ring.buffer(-0.08)), top, top + 0.7))
    for nrm, off, s0, s1 in (((0, 1), ty1, -tx1, -tx0), ((0, -1), -ty0, tx0, tx1)):
        tw = Wall(nrm, off, s0, s1, ROOF_Z, 24.0)
        sm = (s0 + s1) / 2
        for so in (-3.5, 3.5):
            oculus(tw, sm + so, 22.6, 0.5)

    colours = {'lime': (LIME, False), 'lime_s': (LIME, True), 'lime_dk': (LIME_DK, False), 'glass': (GLASS, False), 'sash': (SASH, False),
               'door': (DOOR, False), 'copper': (COPPER, False), 'slate': (SLATE, False)}
    names = {'lime': 'limestone trim', 'lime_s': 'limestone columns and finials', 'lime_dk': 'rustication joints', 'glass': 'windows',
             'sash': 'window sashes', 'door': 'entrance doors', 'copper': 'copper roof', 'slate': 'mansard roof'}
    parts = [(names[k], colours[k][0], mp.merge(v), colours[k][1]) for k, v in out.items()]
    massing = dict(walls=kept_walls, roofs=[vf for vf, z in kept_roofs], bottoms=unary_union(bottoms), wall_v=wall_v)
    return massing, parts
