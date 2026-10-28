"""Mesh generators for the detailed site model (park frame: x = u, y = v, z up, meters).

Every generator returns (V, F): float (n, 3) vertices and int (m, 3) triangles, counter-clockwise seen from outside.
"""
import math
import numpy as np
import mapbox_earcut as earcut
from shapely.geometry import Polygon, Point, LineString
from shapely.geometry.polygon import orient


def merge(parts):
    V, F, off = [], [], 0
    for v, f in parts:
        if len(v) == 0:
            continue
        V.append(np.asarray(v, float)); F.append(np.asarray(f, int) + off); off += len(v)
    if not V:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.vstack(V), np.vstack(F)


def triangulate(poly):
    """Polygon (with holes) -> (2D points, triangles) via earcut, CCW."""
    poly = orient(poly, 1.0)
    rings = [list(poly.exterior.coords)[:-1]] + [list(h.coords)[:-1] for h in poly.interiors]
    pts = np.array([p[:2] for r in rings for p in r], float)
    ends = np.cumsum([len(r) for r in rings]).astype(np.uint32)
    tri = earcut.triangulate_float64(pts, ends).reshape(-1, 3)
    if len(tri):
        a, b, c = pts[tri[:, 0]], pts[tri[:, 1]], pts[tri[:, 2]]
        cw = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0]) < 0
        tri[cw] = tri[cw][:, [0, 2, 1]]
    return pts, tri, rings


# ------------------------------------------------------------------ basic solids
def box(origin, ax, ay, az, sx, sy, sz):
    """Box spanning origin + [0,sx]*ax + [0,sy]*ay + [0,sz]*az (axes are unit vectors)."""
    o, ax, ay, az = (np.asarray(t, float) for t in (origin, ax, ay, az))
    c = [o + i * sx * ax + j * sy * ay + k * sz * az for k in (0, 1) for j in (0, 1) for i in (0, 1)]
    F = [(0, 2, 3), (0, 3, 1), (4, 5, 7), (4, 7, 6), (0, 1, 5), (0, 5, 4), (2, 6, 7), (2, 7, 3), (0, 4, 6), (0, 6, 2), (1, 3, 7), (1, 7, 5)]
    V = np.array(c)
    # make faces outward whatever the handedness of (ax, ay, az)
    if np.dot(np.cross(ax, ay), az) < 0:
        F = [(a, c_, b) for a, b, c_ in F]
    return V, np.array(F)


def frame_box(c, a, n, s0, s1, d0, d1, z0, z1):
    """Box in a horizontal frame: c + s*a + d*n, z from z0 to z1 (c is 3D, z offsets added to c[2])."""
    a = np.array([a[0], a[1], 0.0]); n = np.array([n[0], n[1], 0.0]); up = np.array([0, 0, 1.0])
    o = np.asarray(c, float) + s0 * a + d0 * n + z0 * up
    return box(o, a, n, up, s1 - s0, d1 - d0, z1 - z0)


def prism(poly, z0, z1):
    """Vertical prism of a shapely polygon (holes allowed) from z0 to z1."""
    pts, tri, rings = triangulate(poly)
    n = len(pts)
    V = np.vstack([np.column_stack([pts, np.full(n, z1)]), np.column_stack([pts, np.full(n, z0)])])
    F = [tri, tri[:, [0, 2, 1]] + n]
    start = 0
    for r in rings:
        k = len(r)
        idx = np.arange(start, start + k); nxt = np.roll(idx, -1)
        F.append(np.column_stack([idx + n, nxt + n, nxt])); F.append(np.column_stack([idx + n, nxt, idx]))
        start += k
    return V, np.vstack(F)


def extrude_profile(poly2d, c, a, n, t0, t1):
    """Extrude a profile drawn in the vertical plane (x = d along n, y = z) along a from t0 to t1."""
    pts, tri, rings = triangulate(poly2d)
    a = np.array([a[0], a[1], 0.0]); n = np.array([n[0], n[1], 0.0]); up = np.array([0, 0, 1.0]); c = np.asarray(c, float)
    def place(t):
        return c + t * a + pts[:, :1] * n + pts[:, 1:2] * up
    k = len(pts)
    V = np.vstack([place(t1), place(t0)])
    F = [tri, tri[:, [0, 2, 1]] + k]
    start = 0
    for r in rings:
        m = len(r); idx = np.arange(start, start + m); nxt = np.roll(idx, -1)
        F.append(np.column_stack([idx, nxt, nxt + k])); F.append(np.column_stack([idx, nxt + k, idx + k]))
        start += m
    F = np.vstack(F)
    if np.dot(np.cross(n, up), a) < 0:     # keep faces outward
        F = F[:, [0, 2, 1]]
    return V, F


def revolve(profile, center, seg=24):
    """Lathe: profile [(r, z), ...] bottom to top around a vertical axis at center (x, y, z0)."""
    cx, cy, cz = center
    ang = np.linspace(0, 2 * math.pi, seg, endpoint=False)
    V, F = [], []
    for r, z in profile:
        for t in ang:
            V.append((cx + r * math.cos(t), cy + r * math.sin(t), cz + z))
    m = len(profile)
    for i in range(m - 1):
        for j in range(seg):
            a, b = i * seg + j, i * seg + (j + 1) % seg
            c, d = a + seg, b + seg
            F += [(a, b, d), (a, d, c)]
    V = np.array(V)
    # caps
    bot, top = len(V), len(V) + 1
    V = np.vstack([V, [(cx, cy, cz + profile[0][1])], [(cx, cy, cz + profile[-1][1])]])
    for j in range(seg):
        F.append((bot, (j + 1) % seg, j))
        F.append((top, (m - 1) * seg + j, (m - 1) * seg + (j + 1) % seg))
    return V, np.array(F)


def tube(path, radius, sides=8, closed=False):
    """Round tube along a 3D polyline."""
    P = np.asarray(path, float)
    if closed:
        P = np.vstack([P, P[:1]])
    V, F = [], []
    up = np.array([0, 0, 1.0])
    for i, p in enumerate(P):
        t = P[min(i + 1, len(P) - 1)] - P[max(i - 1, 0)]
        t /= np.linalg.norm(t) or 1
        ref = up if abs(np.dot(t, up)) < 0.9 else np.array([1.0, 0, 0])
        u = np.cross(t, ref); u /= np.linalg.norm(u); w = np.cross(t, u)
        for k in range(sides):
            ang = 2 * math.pi * k / sides
            V.append(p + radius * (math.cos(ang) * u + math.sin(ang) * w))
    for i in range(len(P) - 1):
        for k in range(sides):
            a, b = i * sides + k, i * sides + (k + 1) % sides
            F += [(a, b + sides, b), (a, a + sides, b + sides)]
    return np.array(V), np.array(F)


def icosphere(sub=1):
    t = (1 + 5 ** .5) / 2
    V = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
         (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    V = [np.array(v) / np.linalg.norm(v) for v in V]
    for _ in range(sub):
        cache, F2 = {}, []
        def mid(i, j):
            k = (min(i, j), max(i, j))
            if k not in cache:
                m = (V[i] + V[j]) / 2; V.append(m / np.linalg.norm(m)); cache[k] = len(V) - 1
            return cache[k]
        for i, j, k in F:
            a, b, c = mid(i, j), mid(j, k), mid(k, i)
            F2 += [(i, a, c), (j, b, a), (k, c, b), (a, b, c)]
        F = F2
    return np.array(V), np.array(F)


SPH1 = icosphere(1)


def cone(cx, cy, z0, r, h, seg=12):
    return revolve([(r, 0), (r * 0.02, h)], (cx, cy, z0), seg)


# ------------------------------------------------------------------ ground draped on terrain
def drape(poly, T, offset, bottom=0.45, grid=2.0, wall_step=0.6):
    """Slab whose top follows the terrain T(x, y) + offset, with walls down to top - bottom."""
    parts = []
    x0, y0, x1, y1 = poly.bounds
    tops = []
    for gx in np.arange(math.floor(x0 / grid) * grid, x1, grid):
        for gy in np.arange(math.floor(y0 / grid) * grid, y1, grid):
            cell = Polygon([(gx, gy), (gx + grid, gy), (gx + grid, gy + grid), (gx, gy + grid)])
            if not cell.intersects(poly):
                continue
            piece = cell.intersection(poly)
            for g in getattr(piece, 'geoms', [piece]):
                if isinstance(g, Polygon) and g.area > 1e-6:
                    pts, tri, _ = triangulate(g)
                    if len(tri):
                        z = T(pts[:, 0], pts[:, 1]) + offset
                        tops.append((np.column_stack([pts, z]), tri))
    parts += tops
    # walls along every ring, densified so they follow the terrain
    poly = orient(poly, 1.0)
    for ring in [poly.exterior] + list(poly.interiors):
        line = LineString(ring.coords)
        n = max(3, int(line.length / wall_step))
        pts = np.array([line.interpolate(i * line.length / n).coords[0] for i in range(n)])
        z = T(pts[:, 0], pts[:, 1]) + offset
        top = np.column_stack([pts, z]); bot = np.column_stack([pts, z - bottom])
        V = np.vstack([top, bot]); k = len(pts)
        idx = np.arange(k); nxt = np.roll(idx, -1)
        F = np.vstack([np.column_stack([idx, idx + k, nxt + k]), np.column_stack([idx, nxt + k, nxt])])
        parts.append((V, F))
    return merge(parts)


def drape_strip(line, T, offset, width, step=1.0):
    """Thin strip along a line lying on the terrain (paving joints, painted lines)."""
    L = line.length
    if L < 0.05:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    n = max(1, int(L / step))
    pts = np.array([line.interpolate(i * L / n).coords[0] for i in range(n + 1)])
    d = np.gradient(pts, axis=0); d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-d[:, 1], d[:, 0]]) * width / 2
    left, right = pts + nrm, pts - nrm
    zl, zr = T(left[:, 0], left[:, 1]) + offset, T(right[:, 0], right[:, 1]) + offset
    V = np.vstack([np.column_stack([left, zl]), np.column_stack([right, zr])])
    k = len(pts); idx = np.arange(k - 1)
    F = np.vstack([np.column_stack([idx, idx + k, idx + k + 1]), np.column_stack([idx, idx + k + 1, idx + 1])])
    return V, F


# ------------------------------------------------------------------ park furniture
FRAME_IRON, SLAT, CONCRETE, BLACK = (28, 30, 30), (196, 186, 166), (204, 200, 192), (22, 22, 22)


def worlds_fair_bench(c, a, n, L=2.4):
    """1939 World's Fair bench: cast-iron end frames with the round arm hoop, 6 seat and 3 back slats.
    c = centre at ground (3D), a = bench axis, n = unit vector the seat faces (front)."""
    frames, slats = [], []
    # profile in (d, z): d = 0 at the front edge of the seat, +d toward the back; drawn then mirrored so +d = -n
    hoop = Point(0.27, 0.64).buffer(0.22, 6).difference(Point(0.27, 0.64).buffer(0.195, 6))
    legs = [LineString([(0.14, 0.40), (0.09, 0.24), (0.02, 0.09), (-0.06, 0.02)]).buffer(0.022, 2),           # curved front leg
            LineString([(0.42, 0.40), (0.50, 0.20), (0.60, 0.02)]).buffer(0.022, 2),                         # rear leg
            Polygon([(-0.09, 0.0), (-0.02, 0.0), (-0.02, 0.025), (-0.09, 0.025)]),                           # feet
            Polygon([(0.56, 0.0), (0.64, 0.0), (0.64, 0.025), (0.56, 0.025)]),
            Polygon([(0.02, 0.38), (0.54, 0.38), (0.54, 0.43), (0.02, 0.43)]),                               # seat bearer
            LineString([(0.49, 0.42), (0.58, 0.86)]).buffer(0.022, 2)]                                       # back bearer
    from shapely.ops import unary_union
    prof = unary_union([hoop] + legs)
    # map profile d -> along -n from the front edge (front edge sits 0.3 m in front of c)
    nn = (-n[0], -n[1])
    c0 = np.asarray(c, float) + 0.30 * np.array([n[0], n[1], 0.0])
    for t0, t1 in [(-L / 2, -L / 2 + 0.045), (L / 2 - 0.045, L / 2)]:
        frames.append(extrude_profile(prof, c0, a, nn, t0, t1))
    for k in range(6):
        d0 = 0.03 + k * 0.088
        slats.append(frame_box(c0, a, nn, -L / 2 + 0.02, L / 2 - 0.02, d0, d0 + 0.072, 0.43, 0.462))
    tilt = math.atan2(0.08, 0.44)
    for zc in (0.55, 0.66, 0.77):
        dc = 0.47 + (zc - 0.42) * math.tan(tilt) + 0.035
        V, F = frame_box((0, 0, 0), (1, 0), (0, 1), -L / 2 + 0.02, L / 2 - 0.02, -0.016, 0.016, -0.04, 0.04)
        # tilt about the bench axis, then place
        ca, sa = math.cos(tilt), math.sin(tilt)
        d, z = V[:, 1], V[:, 2]
        d2, z2 = d * ca + z * sa, -d * sa + z * ca
        a3 = np.array([a[0], a[1], 0.0]); n3 = np.array([nn[0], nn[1], 0.0])
        W = c0 + V[:, :1] * a3 + (d2 + dc)[:, None] * n3 + (z2 + zc)[:, None] * np.array([0, 0, 1.0])
        slats.append((W, F))
    return merge(frames), merge(slats)


def backed_bench(c, a, n, L=1.2, seat_h=0.44):
    """Plain slatted bench with a back (game-table benches)."""
    nn = (-n[0], -n[1]); c0 = np.asarray(c, float) + 0.22 * np.array([n[0], n[1], 0.0])
    frames, slats = [], []
    prof = Polygon([(0.0, 0.0), (0.05, 0.0), (0.05, seat_h - 0.03), (0.40, seat_h - 0.03), (0.40, 0.0), (0.45, 0.0), (0.47, 0.85),
                    (0.42, 0.85), (0.40, seat_h + 0.01), (0.0, seat_h + 0.01)])
    for t0, t1 in [(-L / 2 + 0.05, -L / 2 + 0.09), (L / 2 - 0.09, L / 2 - 0.05)]:
        frames.append(extrude_profile(prof, c0, a, nn, t0, t1))
    for k in range(4):
        d0 = 0.01 + k * 0.105
        slats.append(frame_box(c0, a, nn, -L / 2, L / 2, d0, d0 + 0.09, seat_h + 0.01, seat_h + 0.04))
    for z0 in (0.56, 0.70):
        slats.append(frame_box(c0, a, nn, -L / 2, L / 2, 0.43, 0.46, z0, z0 + 0.10))
    return merge(frames), merge(slats)


def game_table(c, a, n):
    """Concrete chess table: pedestal, rounded top, 8 x 8 inlaid board, a backed bench on each side."""
    concrete, dark, light = [], [], []
    cx, cy, cz = c
    concrete.append(revolve([(0.20, 0), (0.20, 0.05), (0.14, 0.10), (0.12, 0.62), (0.18, 0.68)], (cx, cy, cz), 20))
    top = Polygon([(-0.39, -0.39), (0.39, -0.39), (0.39, 0.39), (-0.39, 0.39)]).buffer(0.04, 6)
    pts = np.array(top.exterior.coords)[:-1]
    world = Polygon([(cx + x * a[0] + y * n[0], cy + x * a[1] + y * n[1]) for x, y in pts])
    concrete.append(prism(world, cz + 0.68, cz + 0.76))
    sq = 0.05
    for i in range(8):
        for j in range(8):
            s0, d0 = -0.2 + i * sq, -0.2 + j * sq
            (dark if (i + j) % 2 else light).append(frame_box(c, a, n, s0, s0 + sq, d0, d0 + sq, 0.76, 0.763))
    benches_f, benches_s = [], []
    for side in (-1, 1):
        bc = np.asarray(c, float) + side * 0.72 * np.array([a[0], a[1], 0.0])
        face = (-side * a[0], -side * a[1])
        f, s = backed_bench(bc, n, face, L=1.1)
        benches_f.append(f); benches_s.append(s)
    return merge(concrete), merge(dark), merge(light), merge(benches_f), merge(benches_s)


def parks_lamp(c):
    """NYC Parks cast-iron lamppost with a teardrop globe (height approximate, about 4.3 m)."""
    cx, cy, cz = c
    post = revolve([(0.20, 0.0), (0.20, 0.06), (0.17, 0.10), (0.17, 0.16), (0.13, 0.22), (0.12, 0.30), (0.15, 0.34), (0.11, 0.40),
                    (0.09, 0.60), (0.085, 1.20), (0.11, 1.25), (0.11, 1.32), (0.075, 1.38), (0.062, 3.40), (0.09, 3.45), (0.09, 3.55),
                    (0.05, 3.60)], (cx, cy, cz), 20)
    globe = revolve([(0.05, 3.60), (0.16, 3.72), (0.21, 3.88), (0.19, 4.05), (0.12, 4.17), (0.06, 4.22)], (cx, cy, cz), 20)
    cap = revolve([(0.08, 4.20), (0.09, 4.24), (0.04, 4.30), (0.015, 4.42)], (cx, cy, cz), 12)
    pad = prism(Point(cx, cy).buffer(0.32, 4), cz - 0.05, cz + 0.06)
    return merge([post, cap]), globe, pad


def bollard(c):
    cx, cy, cz = c
    return revolve([(0.055, 0.0), (0.055, 0.66), (0.07, 0.68), (0.07, 0.72), (0.05, 0.74), (0.035, 0.78)], (cx, cy, cz), 12)


def catenary(p0, p1, sag, n=12):
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    t = np.linspace(0, 1, n + 1)
    P = p0 + (p1 - p0) * t[:, None]
    P[:, 2] -= sag * 4 * t * (1 - t)
    return P


def spear_post(c, h=0.95):
    cx, cy, cz = c
    post = frame_box((cx, cy, cz), (1, 0), (0, 1), -0.02, 0.02, -0.02, 0.02, 0.0, h)
    tip = revolve([(0.028, h), (0.03, h + 0.02), (0.0, h + 0.10)], (cx, cy, cz), 4)
    return merge([post, tip])


# ------------------------------------------------------------------ trees
TREE_FORMS = {   # envelope, colour, leaf cluster count factor
    'pin oak': ('pyramidal', (78, 120, 58)), 'northern red oak': ('round', (84, 118, 56)), 'white oak': ('round', (82, 116, 60)),
    "'Regal Prince' Oak": ('columnar', (80, 118, 62)), 'Thornless honeylocust': ('vase', (138, 160, 72)),
    "'Skyline' Thornless honeylocust": ('vase', (138, 160, 72)), 'Callery pear': ('oval', (92, 128, 62)),
    'goldenrain tree': ('round', (110, 138, 60)), 'American basswood': ('oval', (96, 136, 70)), 'littleleaf linden': ('oval', (92, 130, 66)),
    'silver linden': ('oval', (120, 140, 96)), 'Japanese zelkova': ('vase', (96, 132, 64)), 'Japanese tree lilac': ('round', (88, 120, 66)),
    'katsura tree': ('pyramidal', (102, 132, 70)), 'Japanese pagoda tree': ('round', (96, 130, 64)),
    "'Fastigiata' European hornbeam": ('columnar', (88, 124, 62)), 'American elm': ('vase', (90, 126, 60)),
    "'Shawnee Brave' Bald cypress": ('cone', (96, 120, 70)), "'Glauca' blue spruce": ('cone', (92, 116, 120)),
    'blue spruce': ('cone', (92, 116, 120)), 'arborvitae': ('column-conifer', (70, 100, 60)),
}


def envelope(form, t):
    t = min(max(t, 0.0), 1.0)
    if form == 'pyramidal':
        return (1 - t) ** 0.6 * min(1.0, 2.5 * t + 0.4)
    if form == 'round':
        return math.sin(math.pi * (0.08 + 0.84 * t)) ** 0.6
    if form == 'oval':
        return 0.8 * math.sin(math.pi * (0.05 + 0.9 * t)) ** 0.7
    if form == 'vase':
        return (0.35 + 0.65 * t) * math.sin(math.pi * (0.1 + 0.85 * t)) ** 0.35
    if form == 'columnar':
        return 0.42 * math.sin(math.pi * (0.05 + 0.9 * t)) ** 0.5
    return 1 - t


def tree(x, y, z, species, dbh_in, height, crown_d, seed):
    """Procedural tree: tapered trunk, main limbs and leaf clusters inside a species envelope.
    Returns ((V, F) bark, (V, F) foliage, foliage colour)."""
    rng = np.random.default_rng(seed)
    form, colour = TREE_FORMS.get(species, ('round', (86, 124, 62)))
    colour = tuple(int(np.clip(ch * rng.uniform(0.92, 1.08), 0, 255)) for ch in colour)
    R = crown_d / 2
    r_trunk = max(0.05, dbh_in * 0.0254 / 2)
    bark, leaves = [], []
    if form in ('cone', 'column-conifer'):
        base = 0.10 if form == 'cone' else 0.15
        bark.append(revolve([(r_trunk, 0), (r_trunk * 0.6, height * 0.6), (0.02, height * 0.95)], (x, y, z), 10))
        tiers = 5 if form == 'cone' else 4
        rr = R if form == 'cone' else R * 0.45
        for k in range(tiers):
            t0 = base + (1 - base) * k / tiers
            h0, h1 = height * t0, min(height, height * (t0 + 1.6 * (1 - base) / tiers))
            leaves.append(cone(x, y, z + h0, rr * (1 - 0.75 * k / tiers), h1 - h0, 14))
        return merge(bark), merge(leaves), colour
    crown_base = min(max(0.32 * height, 2.2), 4.5)
    trunk_top = crown_base + (height - crown_base) * (0.55 if form in ('pyramidal', 'columnar') else 0.25)
    bark.append(revolve([(r_trunk * 1.25, 0), (r_trunk, 0.4), (r_trunk * 0.8, crown_base), (r_trunk * 0.35, trunk_top)], (x, y, z), 10))
    span = height - crown_base
    n_clusters = int(np.clip(10 + crown_d * 2.2, 14, 40))
    for k in range(n_clusters + 3):
        if k >= n_clusters:   # a few large clusters along the axis fill the core of the crown
            t = 0.3 + 0.2 * (k - n_clusters); env = envelope(form, t) * R; rad, ang = 0.0, 0.0
        else:
            t = rng.uniform(0.06, 0.94)
            env = envelope(form, t) * R
            ang = rng.uniform(0, 2 * math.pi)
            rad = env * math.sqrt(rng.uniform(0.05, 0.8))
        cx_, cy_, cz_ = x + rad * math.cos(ang), y + rad * math.sin(ang), z + crown_base + t * span
        rc = max(0.7, (0.44 + 0.16 * rng.random()) * max(env, R * 0.42))
        V = SPH1[0] * np.array([rc, rc, rc * 0.8]) + np.array([cx_, cy_, cz_])
        V += rng.normal(0, rc * 0.06, V.shape)
        leaves.append((V, SPH1[1]))
        if k < 5 and rad > 0.6:   # a few visible limbs from the trunk to the outer clusters
            start = (x, y, z + crown_base + 0.3 * (cz_ - z - crown_base))
            bark.append(tube([start, (cx_ * 0.6 + x * 0.4, cy_ * 0.6 + y * 0.4, cz_ - rc * 0.6)], max(0.03, r_trunk * 0.35), 6))
    return merge(bark), merge(leaves), colour
