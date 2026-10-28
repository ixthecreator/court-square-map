"""Fill unscanned parts of the central oval by mirroring the scan across its symmetry axis.

Only the oval ring (lawn, ring path, benches, spray pad) is treated as symmetric; the rest of the
park is not (the oval sits off-centre, game tables W vs bistro area E), so nothing outside the
ring region is mirrored. The unscanned lawn interior is filled with a synthetic flat grass surface.

Writes scan/court_square_scan_completed.ply (property 'source': 0 scan, 1 mirrored, 2 synthetic lawn),
       scan/court_square_scan_fill_only.ply, scan/symmetry.json, scan/ortho_completed.png,
       and adds mirrored benches / tables to scan/features.json (flag mirrored=True).
"""
import json, math, os
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = lambda *p: os.path.join(ROOT, 'scan', *p)
feat = json.load(open(S('features.json')))
feat['objects'] = [o for o in feat['objects'] if not o.get('mirrored')]
lawn, ring = feat['lawn_oval'], feat['ring_outer']


def read_ply(path):
    with open(path, 'rb') as fh:
        hdr = b''
        while not hdr.endswith(b'end_header\n'):
            hdr += fh.read(1)
        return np.frombuffer(fh.read(), dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4'), ('r', 'u1'), ('g', 'u1'), ('b', 'u1')])


rec = read_ply(S('court_square_scan_site.ply'))
P = np.stack([rec['x'], rec['y'], rec['z']], 1).astype(np.float64)
C = np.stack([rec['r'], rec['g'], rec['b']], 1)


def ell_q(x, y, e, grow=0.0):
    c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
    dx, dy = x - e['cx'], y - e['cy']
    return np.sqrt(((dx * c + dy * s) / (e['a'] + grow)) ** 2 + ((-dx * s + dy * c) / (e['b'] + grow)) ** 2)


# the ring region: lawn + path + bench zone, extended south to take in the spray pad and the arcs that close below it
def in_region(x, y):
    south = (y < lawn['cy']) & (np.abs(x - lawn['cx']) < ring['a'] + 0.8) & (y > lawn['cy'] - lawn['b'] - 9.5)
    return (ell_q(x, y, ring, 0.8) <= 1.0) | (south & (ell_q(x, y, ring, 4.5) <= 1.0))


def mirror(xy, cu, phi):
    """Reflect across the line through (cu, lawn cy) whose direction is +V rotated by phi (deg, CCW)."""
    t = math.radians(90 + phi)
    d = np.array([math.cos(t), math.sin(t)])
    p0 = np.array([cu, lawn['cy']])
    r = xy - p0
    return p0 + 2 * (r @ d)[:, None] * d - r


# class raster at 10 cm for scoring: 1 paved, 2 green, 3 raised
G = 0.10
U0, V0, U1, V1 = lawn['cx'] - 22, lawn['cy'] - 26, lawn['cx'] + 22, lawn['cy'] + 20
W, H = int((U1 - U0) / G), int((V1 - V0) / G)


def cls_raster(xy, z, col):
    ix = ((xy[:, 0] - U0) / G).astype(int); iy = ((V1 - xy[:, 1]) / G).astype(int)
    m = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
    ix, iy, z, col = ix[m], iy[m], z[m], col[m].astype(int)
    cell = iy * W + ix
    low = np.full(W * H, np.inf); np.minimum.at(low, cell, z)
    top = np.full(W * H, -np.inf); np.maximum.at(top, cell, np.where(z < 2.5, z, -np.inf))
    gsum = np.zeros((W * H, 3)); n = np.zeros(W * H)
    near = np.abs(z - low[cell]) < 0.1
    np.add.at(gsum, cell[near], col[near]); np.add.at(n, cell[near], 1)
    gc = gsum / np.maximum(n, 1)[:, None]
    out = np.zeros(W * H, np.int8)
    ok = np.isfinite(low)
    out[ok] = 1
    out[ok & (gc[:, 1] > gc[:, 0] + 8) & (gc[:, 1] > gc[:, 2] + 8)] = 2
    out[ok & (top - low > 0.3) & (top > 0.3)] = 3
    return out.reshape(H, W)


reg = in_region(P[:, 0], P[:, 1])
Pr, Cr = P[reg], C[reg]
orig = cls_raster(Pr[:, :2], Pr[:, 2], Cr)

best = None
for cu in np.arange(lawn['cx'] - 3, lawn['cx'] + 3.01, 0.1):
    for phi in np.arange(-6, 6.01, 1.0):
        mir = cls_raster(mirror(Pr[:, :2], cu, phi), Pr[:, 2], Cr)
        both = (orig > 0) & (mir > 0)
        if both.sum() < 2000:
            continue
        agree = ((orig == mir) & both).sum() / both.sum()
        if best is None or agree > best[0]:
            best = (agree, cu, phi, int(both.sum()))
# refine
agree0, cu0, phi0, _ = best
for cu in np.arange(cu0 - 0.15, cu0 + 0.151, 0.05):
    for phi in np.arange(phi0 - 1, phi0 + 1.01, 0.25):
        mir = cls_raster(mirror(Pr[:, :2], cu, phi), Pr[:, 2], Cr)
        both = (orig > 0) & (mir > 0)
        agree = ((orig == mir) & both).sum() / both.sum()
        if agree > best[0]:
            best = (agree, cu, phi, int(both.sum()))
agree, CU, PHI, overlap = best
print(f'symmetry axis: u = {CU:.2f} m at v = {lawn["cy"]:.2f}, tilt {PHI:+.2f} deg; class agreement {agree * 100:.1f}% over {overlap * G * G:.0f} m2 of overlap')

# ---- mirrored fill: mirrored points landing where the original has nothing within ~15 cm ----------
F = 0.05
occ = set(map(tuple, np.floor(P[:, :2] / F).astype(np.int64).tolist()))
Mxy = mirror(Pr[:, :2], CU, PHI)
cells = np.floor(Mxy / F).astype(np.int64)
empty = np.array([all((cx + dx, cy + dy) not in occ for dx in (-2, 0, 2) for dy in (-2, 0, 2)) for cx, cy in cells.tolist()])
keep = empty & in_region(Mxy[:, 0], Mxy[:, 1])
fill_m = np.column_stack([Mxy[keep], Pr[keep, 2]])
fill_mc = Cr[keep]
print('mirrored fill points', len(fill_m))

# ---- synthetic lawn: grid inside the lawn oval wherever scan + mirror left a hole -------------------
occ2 = occ | set(map(tuple, np.floor(fill_m[:, :2] / F).astype(np.int64).tolist()))
edge = (ell_q(P[:, 0], P[:, 1], lawn) > 0.85) & (ell_q(P[:, 0], P[:, 1], lawn) < 1.0) & (np.abs(P[:, 2]) < 0.3)
gz = float(np.median(P[edge, 2])) if edge.any() else 0.0
gu = np.arange(lawn['cx'] - lawn['a'] - 1, lawn['cx'] + lawn['a'] + 1, F)
gv = np.arange(lawn['cy'] - lawn['b'] - 1, lawn['cy'] + lawn['b'] + 1, F)
GU, GV = np.meshgrid(gu, gv)
GU, GV = GU.ravel(), GV.ravel()
ins = ell_q(GU, GV, lawn) < 0.98
hole = np.array([(int(math.floor(u / F)), int(math.floor(v / F))) not in occ2 for u, v in zip(GU[ins], GV[ins])])
lu, lv = GU[ins][hole], GV[ins][hole]
rng = np.random.default_rng(1)
fill_l = np.column_stack([lu, lv, np.full(len(lu), gz) + rng.normal(0, 0.01, len(lu))])
fill_lc = np.clip(np.array([92, 128, 60]) + rng.normal(0, 12, (len(lu), 3)), 0, 255).astype(np.uint8)
print(f'synthetic lawn points {len(fill_l)} at z = {gz:.2f} m')


def write_ply(path, pts, col, src):
    rec = np.zeros(len(pts), dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4'), ('r', 'u1'), ('g', 'u1'), ('b', 'u1'), ('s', 'u1')])
    rec['x'], rec['y'], rec['z'] = pts[:, 0], pts[:, 1], pts[:, 2]
    rec['r'], rec['g'], rec['b'] = col[:, 0], col[:, 1], col[:, 2]
    rec['s'] = src
    with open(path, 'wb') as fh:
        fh.write(('ply\nformat binary_little_endian 1.0\n'
                  'comment Court Square Park scan, park frame, meters, Z-up. source: 0 scan, 1 mirrored, 2 synthetic lawn\n'
                  f'element vertex {len(pts)}\nproperty float x\nproperty float y\nproperty float z\n'
                  'property uchar red\nproperty uchar green\nproperty uchar blue\nproperty uchar source\nend_header\n').encode())
        fh.write(rec.tobytes())


allp = np.concatenate([P, fill_m, fill_l]); allc = np.concatenate([C, fill_mc, fill_lc])
src = np.concatenate([np.zeros(len(P), np.uint8), np.ones(len(fill_m), np.uint8), np.full(len(fill_l), 2, np.uint8)])
write_ply(S('court_square_scan_completed.ply'), allp, allc, src)
write_ply(S('court_square_scan_fill_only.ply'), allp[src > 0], allc[src > 0], src[src > 0])

# ---- completed ortho (same raster as ortho_rgb.png); mirrored points tinted so they read as inferred ---
PX, OU0, OV0, OU1, OV1 = 0.04, -40, -40, 90, 80
OW, OH = int((OU1 - OU0) / PX), int((OV1 - OV0) / PX)
base = np.array(Image.open(S('ortho_rgb.png')).convert('RGB'))
for pts, col, tint in [(fill_l, fill_lc, None), (fill_m, fill_mc, (120, 150, 255))]:
    ix = ((pts[:, 0] - OU0) / PX).astype(int); iy = ((OV1 - pts[:, 1]) / PX).astype(int)
    order = np.argsort(pts[:, 2])
    ix, iy, c = ix[order], iy[order], col[order].astype(float)
    if tint is not None:
        c = c * 0.7 + np.array(tint) * 0.3
    m = (ix >= 0) & (ix < OW) & (iy >= 0) & (iy < OH) & (pts[order, 2] < 2.2)
    blank = (base[iy[m], ix[m]] == 255).all(1)
    base[iy[m][blank], ix[m][blank]] = c[m][blank].astype(np.uint8)
Image.fromarray(base).save(S('ortho_completed.png'))

# ---- mirrored objects ------------------------------------------------------------------------------
objs = [o for o in feat['objects'] if not o.get('mirrored')]
added = []
for o in objs:
    if o['kind'] != 'bench' or not in_region(np.array([o['x']]), np.array([o['y']]))[0]:
        continue
    (mx, my), = mirror(np.array([[o['x'], o['y']]]), CU, PHI)
    if any(q['kind'] == o['kind'] and math.hypot(q['x'] - mx, q['y'] - my) < 1.2 for q in objs + added):
        continue
    hd = (2 * (90 + PHI) - o['heading_deg']) % 180
    added.append(dict(o, x=round(float(mx), 2), y=round(float(my), 2), heading_deg=round(hd, 1), mirrored=True))
feat['objects'] = objs + added
# symmetric spray pad outline: average the scanned top / bottom extents of mirrored column pairs
sp = feat.get('spray_pad')
if sp:
    h = sp['hull'][:-1]; n = len(h) // 2
    bot, top = h[:n], h[n:][::-1]
    xs = np.array([p[0] for p in bot]); lo = np.array([p[1] for p in bot]); hi = np.array([p[1] for p in top])
    d = np.abs(xs - CU)
    dd = np.arange(0, d.max() + 0.25, 0.5)
    prof = []
    for q in dd:
        m = np.abs(d - q) < 0.26
        if m.sum():
            prof.append((q, float(np.median(lo[m])), float(np.median(hi[m]))))
    # a lens tapers toward its tips: top may only drop and bottom only rise moving away from the axis
    # (stops the ring path, which the tips touch, from flaring the outline)
    for i in range(1, len(prof)):
        q, l, u = prof[i]
        prof[i] = (q, max(l, prof[i - 1][1]), min(u, prof[i - 1][2]))
    prof = [p for p in prof if p[2] - p[1] > 0.3]
    # lens = two circular arcs through the tips and the measured top / bottom apex on the axis
    q_tip = prof[-1][0] + 0.25
    v_tip = (prof[-1][1] + prof[-1][2]) / 2
    v_top, v_bot = prof[0][2], prof[0][1]

    def arc(v_apex, n=24):
        # circle through (-q_tip, v_tip), (0, v_apex), (q_tip, v_tip) in axis-relative coords
        h = v_apex - v_tip
        R = (q_tip ** 2 + h ** 2) / (2 * h)
        cy = v_apex - R
        return [(CU + q, cy + math.copysign(math.sqrt(max(R * R - q * q, 0)), R)) for q in np.linspace(-q_tip, q_tip, n)]
    top_arc, bot_arc = arc(v_top), arc(v_bot)
    outline = [(round(x, 2), round(y, 2)) for x, y in bot_arc] + [(round(x, 2), round(y, 2)) for x, y in reversed(top_arc[1:-1])]
    outline.append(outline[0])
    sp.update(hull=outline, u_min=CU - q_tip, u_max=CU + q_tip, v_min=v_bot, v_max=v_top, symmetric=True,
              width_m=2 * q_tip, depth_m=v_top - v_bot, area_m2=round(0.5 * abs(sum(outline[i][0] * outline[i + 1][1] - outline[i + 1][0] * outline[i][1] for i in range(len(outline) - 1))), 1))
    print('spray pad (symmetric): u %.1f..%.1f, v %.1f..%.1f' % (sp['u_min'], sp['u_max'], sp['v_min'], sp['v_max']))
feat['symmetry'] = dict(axis_u=CU, axis_v=lawn['cy'], tilt_deg=PHI, agreement=agree, overlap_m2=overlap * G * G,
                        mirrored_pts=int(len(fill_m)), synthetic_lawn_pts=int(len(fill_l)), lawn_z=gz)
json.dump(feat, open(S('features.json'), 'w'), indent=1)
json.dump(feat['symmetry'], open(S('symmetry.json'), 'w'), indent=1)
print('mirrored objects added:', [(o['kind'], o['x'], o['y']) for o in added])
