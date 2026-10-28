"""Export the as-built park layout and the scan georeference for the court-square-map website.

Usage: python3 scripts/export_web.py ../court-square-map
Writes <site>/data/park-detail.geojson and <site>/data/scan-georef.json
"""
import csv, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.abspath(sys.argv[1])
os.makedirs(os.path.join(SITE, 'data'), exist_ok=True)
feat = json.load(open(os.path.join(ROOT, 'scan', 'features.json')))
site = json.load(open(os.path.join(ROOT, 'model', 'site_local.json')))

LAT0, LON0 = 40.74636, -73.94345
_phi = math.radians(LAT0)
MLAT = 111132.954 - 559.822 * math.cos(2 * _phi) + 1.175 * math.cos(4 * _phi)
MLON = 111412.84 * math.cos(_phi) - 93.5 * math.cos(3 * _phi)
B = math.radians(site['frame']['x_bearing'])
E_LL = json.load(open(os.path.join(ROOT, 'data', 'parks_property_Q267.geojson')))['features'][0]['geometry']['coordinates'][0][0][4]


def ll(u, v):
    east, north = u * math.sin(B) - v * math.cos(B), u * math.cos(B) + v * math.sin(B)
    return [round(E_LL[0] + east / MLON, 8), round(E_LL[1] + north / MLAT, 8)]


def ring(pts):
    r = [ll(u, v) for u, v in pts]
    if r[0] != r[-1]:
        r.append(r[0])
    return r


def ellipse(e, grow=0.0, n=72):
    c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
    a, b = e['a'] + grow, e['b'] + grow
    return [(e['cx'] + a * math.cos(t) * c - b * math.sin(t) * s, e['cy'] + a * math.cos(t) * s + b * math.sin(t) * c)
            for t in [2 * math.pi * i / n for i in range(n + 1)]]


def rect(o):
    hd = math.radians(o['heading_deg']); c, s = math.cos(hd), math.sin(hd)
    hl, hw = o['length_m'] / 2, o['width_m'] / 2
    return [(o['x'] + dx * c - dy * s, o['y'] + dx * s + dy * c) for dx, dy in [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw), (-hl, -hw)]]


out = []
add = lambda kind, geom, **p: out.append(dict(type='Feature', properties=dict(kind=kind, **p), geometry=geom))
poly = lambda pts: dict(type='Polygon', coordinates=[ring(pts)])

def hull(pts):
    pts = sorted(set((round(x, 3), round(y, 3)) for x, y in pts))
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for q in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], q) <= 0: lo.pop()
        lo.append(q)
    for q in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], q) <= 0: hi.pop()
        hi.append(q)
    return lo[:-1] + hi[:-1] + [lo[0]]


# the ring path wraps round the spray pad at its south end: hull of the ring ellipse and the pad grown by the path width
ring_pts = ellipse(feat['ring_outer'])
if feat.get('spray_pad'):
    pad = feat['spray_pad']['hull'][:-1]
    cx, cy = sum(p[0] for p in pad) / len(pad), sum(p[1] for p in pad) / len(pad)
    w = feat['ring_outer'].get('path_width_m', 2.4)
    for x, y in pad:
        d = math.hypot(x - cx, y - cy) or 1
        ring_pts.append((x + (x - cx) / d * w, y + (y - cy) / d * w))
add('ring-path', poly(hull(ring_pts)), label='Ring path', source='scan')
# paved plazas read off the scan ortho (approximate rectangles)
add('plaza', poly([(14.9, 15.0), (18.6, 15.0), (18.6, 27.6), (14.9, 27.6)]), label='Game-table plaza', source='scan', approximate=True)
add('plaza', poly([(45.2, 16.4), (51.2, 16.4), (51.2, 25.8), (45.2, 25.8)]), label='Bistro area', source='scan', approximate=True)
if feat.get('spray_pad'):
    add('spray-pad', poly(feat['spray_pad']['hull']), label='Spray pad', source='scan')
add('lawn', poly(ellipse(feat['lawn_oval'])), label='Central lawn', source='scan')
for o in feat['objects']:
    if o['kind'] == 'bench' and o['x'] < 44:     # ring benches; the bistro-edge bars are not benches
        add('bench', poly(rect(o)), label='1939 World\'s Fair bench', source='mirrored' if o.get('mirrored') else 'scan')
    elif o['kind'] == 'game table + seats':
        add('game-table', poly(rect(o)), label='Game table with benches', source='scan')
    elif o['kind'] == 'pole (lamp / sign)' and 0 <= o['x'] <= 49 and 0 <= o['y'] <= 41.1:
        add('pole', dict(type='Point', coordinates=ll(o['x'], o['y'])), label='Lamp / sign pole', source='scan')
REMOVED = {(25.245, 8.117), (27.246, 31.901), (35.768, 31.372)}   # blue spruces gone with the 2025 rebuild
for t in csv.DictReader(open(os.path.join(ROOT, 'model', 'trees.csv'))):
    x, y = float(t['x_m']), float(t['y_m'])
    if t['in_park'] != 'True' or t['status'] != 'Full' or (round(x, 3), round(y, 3)) in REMOVED:
        continue
    add('tree', dict(type='Point', coordinates=ll(x, y)), label=t['species'], dbh_in=float(t['dbh_in']),
        crown_m=float(t['crown_d_m_est']), source='NYC Forestry')
sym = feat['symmetry']
t = math.radians(90 + sym['tilt_deg'])
add('axis', dict(type='LineString', coordinates=[ll(sym['axis_u'] - 21 * math.cos(t), sym['axis_v'] - 21 * math.sin(t)),
                                                 ll(sym['axis_u'] + 17 * math.cos(t), sym['axis_v'] + 17 * math.sin(t))]),
    label='Symmetry axis', source='scan')

json.dump(dict(type='FeatureCollection', name='court-square-park-as-built-2026-10-28',
               note='As-built layout measured from the 2026-10-28 LiDAR scan; trees from NYC Forestry (crown diameter estimated from DBH).',
               features=out), open(os.path.join(SITE, 'data', 'park-detail.geojson'), 'w'), separators=(',', ':'))
georef = dict(origin=[E_LL[0], E_LL[1]], x_bearing_deg=site['frame']['x_bearing'], m_per_deg_lon=MLON, m_per_deg_lat=MLAT,
              grade_navd88_m=site['frame']['park_grade_navd88_m'],
              note='glTF x = park u, y = height above grade, z = -park v. east = u sin(b) - v cos(b); north = u cos(b) + v sin(b)')
json.dump(georef, open(os.path.join(SITE, 'data', 'scan-georef.json'), 'w'), indent=1)
print(len(out), 'features;', {k: sum(f['properties']['kind'] == k for f in out) for k in sorted({f['properties']['kind'] for f in out})})
print('check: corner D ->', ll(0, 41.09), '(NYC Parks: -73.94382646, 40.74641934)')
