"""Measure the as-built park from the registered scan.

- fits the central lawn oval (inner edge of the ring path) and the ring's outer edge
- finds raised objects (benches, tables, poles/trunks) as connected components
- checks scan trunks against the NYC Forestry tree points
Writes scan/features.json and scan/debug_classes.png
"""
import csv, json, math, os
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = lambda *p: os.path.join(ROOT, 'scan', *p)
site = json.load(open(os.path.join(ROOT, 'model', 'site_local.json')))

with open(S('court_square_scan_site.ply'), 'rb') as fh:
    hdr = b''
    while not hdr.endswith(b'end_header\n'):
        hdr += fh.read(1)
    rec = np.frombuffer(fh.read(), dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4'), ('r', 'u1'), ('g', 'u1'), ('b', 'u1')])
X, Y, Z = rec['x'].astype(float), rec['y'].astype(float), rec['z'].astype(float)
RGB = np.stack([rec['r'], rec['g'], rec['b']], 1).astype(int)

PX = 0.05
U0, V0, U1, V1 = -10, -12, 62, 52
W, H = int((U1 - U0) / PX), int((V1 - V0) / PX)
ix = ((X - U0) / PX).astype(int); iy = ((V1 - Y) / PX).astype(int)
ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
ix, iy, Xo, Yo, Zo, Co = ix[ok], iy[ok], X[ok], Y[ok], Z[ok], RGB[ok]
cell = iy * W + ix

# per-cell ground (lowest) and top (highest under 2.5 m)
low = np.full(W * H, np.inf); np.minimum.at(low, cell, Zo)
under = Zo < 2.5
top = np.full(W * H, -np.inf); np.maximum.at(top, cell[under], Zo[under])
low, top = low.reshape(H, W), top.reshape(H, W)
scanned = np.isfinite(low)

# ground colour: mean RGB of points within 10 cm of the cell's lowest point
g = np.abs(Zo - low.ravel()[cell]) < 0.10
csum = np.zeros((W * H, 3)); np.add.at(csum, cell[g], Co[g]); cnt = np.bincount(cell[g], minlength=W * H)
gcol = (csum / np.maximum(cnt, 1)[:, None]).reshape(H, W, 3)
r_, g_, b_ = gcol[..., 0], gcol[..., 1], gcol[..., 2]
green = scanned & (g_ > r_ + 8) & (g_ > b_ + 8)
paved = scanned & ~green & (np.abs(low) < 0.25) & (np.max(gcol, -1) - np.min(gcol, -1) < 40)


def to_uv(px, py):
    return U0 + (px + 0.5) * PX, V1 - (py + 0.5) * PX


def to_px(u, v):
    return int((u - U0) / PX), int((V1 - v) / PX)


def fit_ellipse(pts):
    x, y = pts[:, 0], pts[:, 1]
    D = np.stack([x * x, x * y, y * y, x, y, np.ones_like(x)], 1)
    _, _, Vt = np.linalg.svd(D, full_matrices=False)
    A, B, C, Dd, E, F = Vt[-1]
    den = B * B - 4 * A * C
    cx = (2 * C * Dd - B * E) / den; cy = (2 * A * E - B * Dd) / den
    th = 0.5 * math.atan2(B, A - C)
    num = 2 * (A * E * E + C * Dd * Dd - B * Dd * E + den * F)
    s = math.sqrt((A - C) ** 2 + B * B)
    a = -math.sqrt(num * (A + C + s)) / den; b = -math.sqrt(num * (A + C - s)) / den
    return dict(cx=cx, cy=cy, a=abs(a), b=abs(b), theta_deg=math.degrees(th))


def ellipse_pts(e, n=96):
    t = np.linspace(0, 2 * math.pi, n + 1); c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
    return [(round(e['cx'] + e['a'] * math.cos(q) * c - e['b'] * math.sin(q) * s, 3),
             round(e['cy'] + e['a'] * math.cos(q) * s + e['b'] * math.sin(q) * c, 3)) for q in t]


def ring_edges(c0, rmin, rmax):
    inner, outer = [], []
    for ang in np.radians(np.arange(0, 360, 2)):
        prof = []
        for r in np.arange(rmin, rmax, PX):
            px, py = to_px(c0[0] + r * math.cos(ang), c0[1] + r * math.sin(ang))
            prof.append((r, paved[py, px] if 0 <= px < W and 0 <= py < H else False))
        rs = [r for r, p in prof if p]
        if not rs:
            continue
        r_in = rs[0]
        # first paved run starting at r_in
        r_out = r_in
        for r, p in prof:
            if r < r_in:
                continue
            if not p and r - r_out > 0.3:
                break
            if p:
                r_out = r
        inner.append((c0[0] + r_in * math.cos(ang), c0[1] + r_in * math.sin(ang), math.degrees(ang)))
        outer.append((c0[0] + r_out * math.cos(ang), c0[1] + r_out * math.sin(ang), math.degrees(ang)))
    return np.array(inner), np.array(outer)


def robust_ellipse(p, iters=4):
    keep = np.ones(len(p), bool)
    for _ in range(iters):
        e = fit_ellipse(p[keep, :2])
        c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
        dx, dy = p[:, 0] - e['cx'], p[:, 1] - e['cy']
        q = np.sqrt(((dx * c + dy * s) / e['a']) ** 2 + ((-dx * s + dy * c) / e['b']) ** 2)
        res = np.abs(q - 1) * (e['a'] + e['b']) / 2
        keep = res < max(0.25, np.percentile(res, 75))
    e['rms_m'] = float(np.sqrt(np.mean(res[keep] ** 2))); e['n'] = int(keep.sum())
    return e, keep


c0 = (31.0, 23.5)
inner, outer = ring_edges(c0, 5.0, 16.0)
lawn, kin = robust_ellipse(inner)
c1 = (lawn['cx'], lawn['cy'])
inner, outer = ring_edges(c1, 5.0, 16.0)
lawn, kin = robust_ellipse(inner)
# ring path width where the paved band is a plain path (N and E arcs; W has the game-table plaza, S the spray pad)
wd = np.hypot(*(outer[:, :2] - inner[:, :2]).T)
sector = ((inner[:, 2] > -30) & (inner[:, 2] < 140)) | (inner[:, 2] > 330)
plain = kin & sector & (wd > 0.8) & (wd < 4.0)
path_w = float(np.median(wd[plain])) if plain.any() else 2.0
ring = dict(lawn, a=lawn['a'] + path_w, b=lawn['b'] + path_w, path_width_m=path_w)
print('lawn oval', {k: round(v, 2) for k, v in lawn.items()})
print('ring path width (N/E arcs) m', round(path_w, 2), 'p25-p75', np.percentile(wd[plain], [25, 75]).round(2) if plain.any() else '-')

# ---- raised objects ------------------------------------------------------------
rel = np.where(scanned & np.isfinite(top), top - np.where(np.isfinite(low), low, 0), 0)
obj_mask = (rel > 0.30) & (top > 0.30)
lbl = np.zeros((H, W), np.int32); n = 0
for sy, sx in zip(*np.where(obj_mask)):
    if lbl[sy, sx]:
        continue
    n += 1; stack = [(sy, sx)]; lbl[sy, sx] = n
    while stack:
        y, x = stack.pop()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < H and 0 <= xx < W and obj_mask[yy, xx] and not lbl[yy, xx]:
                    lbl[yy, xx] = n; stack.append((yy, xx))
objs = []
park = np.array(site['park'])
for k in range(1, n + 1):
    yy, xx = np.where(lbl == k)
    if len(yy) < 6:
        continue
    pts = np.array([to_uv(x, y) for x, y in zip(xx, yy)])
    c = pts.mean(0)
    cov = np.cov((pts - c).T) if len(pts) > 2 else np.eye(2) * 1e-4
    w, v = np.linalg.eigh(cov)
    ax = v[:, 1]; proj = (pts - c) @ ax; proj2 = (pts - c) @ v[:, 0]
    L, Wd = proj.max() - proj.min() + PX, proj2.max() - proj2.min() + PX
    h = float(np.max(top[yy, xx]))
    area = len(yy) * PX * PX
    if L > 6 or area > 8:
        kind = 'vegetation / mass'
    elif L < 0.7 and h > 1.6:
        kind = 'pole or trunk'
    elif 1.4 <= L <= 2.6 and Wd <= 1.0 and h <= 1.2:
        kind = 'bench'
    elif 1.2 <= area <= 2.8 and 1.4 <= L <= 2.4 and Wd >= 1.1 and 0.7 <= h <= 1.1:
        kind = 'game table + seats'
    elif area < 0.3 and h <= 1.2:
        kind = 'small object (bin / bollard / fixture)'
    elif h <= 1.2:
        kind = 'low object'
    else:
        kind = 'tall object'
    objs.append(dict(x=round(c[0], 2), y=round(c[1], 2), length_m=round(L, 2), width_m=round(Wd, 2), height_m=round(h, 2),
                     heading_deg=round(math.degrees(math.atan2(ax[1], ax[0])) % 180, 1), footprint_m2=round(area, 2), kind=kind))
objs = [o for o in objs if o['kind'] != 'vegetation / mass']

# trunks vs forestry points
trunk_pts = (Zo > 1.0) & (Zo < 1.8)
alive = [t for t in site['trees'] if t['status'] == 'Full']
offs = []
for o in objs:
    if o['kind'] != 'pole or trunk':
        continue
    d = [(math.hypot(t['x'] - o['x'], t['y'] - o['y']), t) for t in alive]
    dmin, t = min(d, key=lambda q: q[0])
    o['nearest_db_tree_m'] = round(dmin, 2)
    if dmin < 2.0:
        o['kind'] = 'tree trunk'; o['species_db'] = t['species']
        offs.append((t['x'] - o['x'], t['y'] - o['y']))
    else:
        o['kind'] = 'pole (lamp / sign)'
offs = np.array(offs) if offs else np.zeros((0, 2))
print('objects', {k: sum(o['kind'] == k for o in objs) for k in set(o['kind'] for o in objs)})
if len(offs):
    print('trunk -> forestry offset mean', offs.mean(0).round(2), 'median dist', np.median(np.hypot(*offs.T)).round(2), 'n', len(offs))

# spray pad: pale blue-gray paved cells just south of the lawn, outside the lawn oval
blue = paved & (b_ > r_ + 6) & (b_ > g_ - 2)
sy, sx = np.where(blue)
sp = np.array([to_uv(x, y) for x, y in zip(sx, sy)]) if len(sx) else np.zeros((0, 2))
spray = None
if len(sp):
    c, s = math.cos(math.radians(lawn['theta_deg'])), math.sin(math.radians(lawn['theta_deg']))
    dx, dy = sp[:, 0] - lawn['cx'], sp[:, 1] - lawn['cy']
    q = np.sqrt(((dx * c + dy * s) / lawn['a']) ** 2 + ((-dx * s + dy * c) / lawn['b']) ** 2)
    sp = sp[(q > 1.0) & (dy < -lawn['b'] * 0.55) & (np.abs(dx) < lawn['a'] * 0.62) & (dy > -lawn['b'] - 7)]
if len(sp) > 50:
    # outline from per-column extents (0.5 m columns), which keeps the lens shape a convex hull would lose
    cols = {}
    for x, y in sp:
        cols.setdefault(int(math.floor(x / 0.5)), []).append(y)
    prof = sorted((k * 0.5 + 0.25, np.percentile(v, 5), np.percentile(v, 95)) for k, v in cols.items() if len(v) >= 40)
    hull = [(round(x, 2), round(lo_, 2)) for x, lo_, hi_ in prof] + [(round(x, 2), round(hi_, 2)) for x, lo_, hi_ in reversed(prof)]
    hull.append(hull[0])
    spray = dict(hull=hull, u_min=float(sp[:, 0].min()), u_max=float(sp[:, 0].max()), v_min=float(sp[:, 1].min()),
                 v_max=float(sp[:, 1].max()), area_m2=round(len(sp) * PX * PX, 1))
    print('spray pad', {k: round(v, 2) for k, v in spray.items() if k != 'hull'})

feat = dict(lawn_oval=lawn, ring_outer=ring, lawn_pts=ellipse_pts(lawn), ring_pts=ellipse_pts(ring), spray_pad=spray,
            objects=objs, trunk_offset_mean=offs.mean(0).tolist() if len(offs) else None)
json.dump(feat, open(S('features.json'), 'w'), indent=1)

# DXF / CSV export happens in export_features.py, after symmetrize_scan.py

# debug raster: paved / green / edges
dbg = np.full((H, W, 3), 255, np.uint8)
dbg[paved] = (190, 190, 190); dbg[green] = (120, 200, 120); dbg[blue & paved] = (150, 180, 230); dbg[obj_mask] = (230, 120, 40)
for p in inner[kin]:
    x, y = to_px(p[0], p[1]); dbg[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = (200, 0, 0)
for p in outer[plain]:
    x, y = to_px(p[0], p[1]); dbg[max(0, y - 1):y + 2, max(0, x - 1):x + 2] = (0, 0, 200)
Image.fromarray(dbg).save(S('debug_classes.png'))
