"""Register the ARKit scan into the park frame (see build_site.py) and export it.

Step 1: rigid 2D fit of camera positions to GPS fixes (coarse, GPS is ~14 m here).
Step 2: ICP of scanned curb/step edges against NYC planimetric curb lines.
Writes scan/registration.json, scan/court_square_scan_site.ply (Z-up, meters, park frame),
       scan/ortho_rgb.png, scan/ortho_height.png (4 cm/px, same extent as plans/site_base_plan.png).
"""
import json, math, os
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = lambda *p: os.path.join(ROOT, 'scan', *p)
site = json.load(open(os.path.join(ROOT, 'model', 'site_local.json')))

LAT0, LON0 = 40.74636, -73.94345
_phi = math.radians(LAT0)
MLAT = 111132.954 - 559.822 * math.cos(2 * _phi) + 1.175 * math.cos(4 * _phi)
MLON = 111412.84 * math.cos(_phi) - 93.5 * math.cos(3 * _phi)
_t = math.radians(site['frame']['x_bearing'])
UX, UY, VX, VY = math.sin(_t), math.cos(_t), -math.cos(_t), math.sin(_t)
park = np.array(site['park'])
_E = None
# corner E (origin) is park[4] == (0, 0); recover its offset from the original lon/lat file
_ll = json.load(open(os.path.join(ROOT, 'data', 'parks_property_Q267.geojson')))['features'][0]['geometry']['coordinates'][0][0][4]
EX, EY = (_ll[0] - LON0) * MLON, (_ll[1] - LAT0) * MLAT


def uv(lon, lat):
    x, y = (lon - LON0) * MLON - EX, (lat - LAT0) * MLAT - EY
    return np.stack([x * UX + y * UY, x * VX + y * VY], -1)


def fit_rigid(a, b, w=None):
    w = np.ones(len(a)) if w is None else w
    ca, cb = (a * w[:, None]).sum(0) / w.sum(), (b * w[:, None]).sum(0) / w.sum()
    A, B = a - ca, b - cb
    s = (w * (A[:, 0] * B[:, 1] - A[:, 1] * B[:, 0])).sum()
    c = (w * (A * B).sum(1)).sum()
    th = math.atan2(s, c)
    R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    return R, cb - R @ ca, th


traj = json.load(open(S('trajectory.json')))
cam = np.array([[f['T'][0][3], f['T'][1][3], f['T'][2][3]] for f in traj])
a = np.stack([cam[:, 0], -cam[:, 2]], 1)              # ARKit top view (x, -z)
b = uv(np.array([f['lon'] for f in traj]), np.array([f['lat'] for f in traj]))
keep = np.ones(len(a), bool)
for it in range(6):
    R, T, th = fit_rigid(a[keep], b[keep])
    res = np.linalg.norm((a @ R.T + T) - b, axis=1)
    keep = res < max(4.0, np.percentile(res, 70))
print(f'GPS fit: rot {math.degrees(th):.2f} deg, median residual {np.median(res):.1f} m')

cloud = np.load(S('arkit_cloud.npz'))
P, C = cloud['points'].astype(np.float64), cloud['colors']
hist, edges = np.histogram(P[:, 1], bins=np.arange(P[:, 1].min(), P[:, 1].max() + 0.05, 0.05))
ground_y = edges[np.argmax(hist)] + 0.025
print('ARKit ground level y =', round(ground_y, 2))
xy_arkit = np.stack([P[:, 0], -P[:, 2]], 1)
Hgt = P[:, 1] - ground_y

PX = 0.04
U0, V0, U1, V1 = -40, -40, 90, 80     # raster extent in park frame (m)
W, H = int((U1 - U0) / PX), int((V1 - V0) / PX)


def raster(xy, h, rgb=None):
    ix = ((xy[:, 0] - U0) / PX).astype(int); iy = ((V1 - xy[:, 1]) / PX).astype(int)
    m = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H) & (h < 2.2)
    ix, iy, hh = ix[m], iy[m], h[m]
    order = np.argsort(hh)                       # later (higher) points overwrite lower ones
    top = np.full((H, W), np.nan, np.float32); top[iy[order], ix[order]] = hh[order]
    low = np.full((H, W), np.nan, np.float32); low[iy[order[::-1]], ix[order[::-1]]] = hh[order[::-1]]
    img = None
    if rgb is not None:
        img = np.full((H, W, 3), 255, np.uint8); img[iy[order], ix[order]] = rgb[m][order]
    return top, low, img


def curb_edges(xy):
    """Scan cells where the ground steps 8-30 cm within 12 cm: curbs, lawn edges, steps."""
    top, low, _ = raster(xy, Hgt)
    g = np.where(np.isnan(low), np.nan, low)
    gx = np.abs(np.roll(g, -3, 1) - np.roll(g, 3, 1)); gy = np.abs(np.roll(g, -3, 0) - np.roll(g, 3, 0))
    step = np.fmax(gx, gy)
    iy, ix = np.where((step > 0.08) & (step < 0.30) & (g < 0.5))
    return np.stack([U0 + (ix + 0.5) * PX, V1 - (iy + 0.5) * PX], 1)


def densify(lines, d=0.1):
    out = []
    for l in lines:
        for (x1, y1), (x2, y2) in zip(l[:-1], l[1:]):
            n = max(1, int(math.hypot(x2 - x1, y2 - y1) / d))
            out.extend((x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n))
    return np.array(out)


ref = densify(site['curbs'])
grid = {}
for i, (x, y) in enumerate(ref):
    grid.setdefault((int(x // 1), int(y // 1)), []).append(i)


def nearest(p):
    best = np.full(len(p), np.inf); idx = np.zeros(len(p), int)
    for j, (x, y) in enumerate(p):
        gx, gy = int(x // 1), int(y // 1)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for i in grid.get((gx + dx, gy + dy), ()):
                    d = (ref[i, 0] - x) ** 2 + (ref[i, 1] - y) ** 2
                    if d < best[j]:
                        best[j], idx[j] = d, i
    return np.sqrt(best), idx


R0, T0 = R, T
edge_a = curb_edges(xy_arkit @ R0.T + T0)
edge_a = (edge_a - T0) @ R0          # back to ARKit top view so we can refit R, T directly
rng = np.random.default_rng(0)
if len(edge_a) > 6000:
    edge_a = edge_a[rng.choice(len(edge_a), 6000, replace=False)]
thresh = 3.0
for it in range(40):
    q = edge_a @ R.T + T
    d, idx = nearest(q)
    m = d < thresh
    if m.sum() < 50:
        break
    R, T, th = fit_rigid(edge_a[m], ref[idx[m]])
    thresh = max(0.4, thresh * 0.9)
q = edge_a @ R.T + T
d, _ = nearest(q)
inl = d < 0.5
print(f'ICP: rot {math.degrees(th):.2f} deg, shift from GPS fit {np.linalg.norm(T - T0):.2f} m, '
      f'{inl.mean() * 100:.0f}% edge pts within 0.5 m, median {np.median(d[inl]):.2f} m')

xy = xy_arkit @ R.T + T
Z = Hgt
park_grade = site['frame']['park_grade_navd88_m']
reg = dict(R=R.tolist(), T=T.tolist(), rot_deg=math.degrees(th), arkit_ground_y=float(ground_y),
           park_grade_navd88_m=park_grade, icp_inlier_frac=float(inl.mean()), icp_median_m=float(np.median(d[inl])),
           note='site_xy = R @ (arkit_x, -arkit_z) + T ; site_z = arkit_y - arkit_ground_y')
json.dump(reg, open(S('registration.json'), 'w'), indent=1)

camxy = a @ R.T + T
json.dump(dict(xy=camxy[::5].round(2).tolist(), keys=[f['key'] for f in traj[::5]]), open(S('trajectory_site.json'), 'w'))

top, low, img = raster(xy, Z, C)
Image.fromarray(img).save(S('ortho_rgb.png'))
hn = np.nan_to_num(np.clip((top + 0.3) / 2.5, 0, 1), nan=1.0)
cm = (np.stack([hn, 1 - np.abs(hn - 0.5) * 2, 1 - hn], -1) * 255).astype(np.uint8)
cm[np.isnan(top)] = 255
Image.fromarray(cm).save(S('ortho_height.png'))

with open(S('court_square_scan_site.ply'), 'wb') as fh:
    fh.write(('ply\nformat binary_little_endian 1.0\ncomment Court Square Park iPhone LiDAR scan 2026-10-28, park frame, meters, Z-up, z=0 park grade\n'
              f'element vertex {len(xy)}\nproperty float x\nproperty float y\nproperty float z\n'
              'property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n').encode())
    rec = np.zeros(len(xy), dtype=[('x', '<f4'), ('y', '<f4'), ('z', '<f4'), ('r', 'u1'), ('g', 'u1'), ('b', 'u1')])
    rec['x'], rec['y'], rec['z'] = xy[:, 0], xy[:, 1], Z
    rec['r'], rec['g'], rec['b'] = C[:, 0], C[:, 1], C[:, 2]
    fh.write(rec.tobytes())
print('wrote', len(xy), 'points; raster', W, 'x', H)
