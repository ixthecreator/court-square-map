"""LOD3 site model of Court Square Park for Rhino 8, built from the scan measurements and NYC data.

Same park frame as every other file here: meters, x = u along the courthouse edge toward Thomson Ave,
y = v toward Jackson Ave, z up, z = 0 at park grade (NAVD88 5.28 m). Ground levels are flat per surface
type (roads 15 cm below the curb); the real site falls about 0.4 m from Jackson Ave to the courthouse.

Usage: python scripts/build_model.py        (needs rhino3dm, shapely, mapbox_earcut, numpy)
Writes model/court_square_park_LOD3.3dm, model/court_square_park_LOD3_preview.glb and
model/court_square_park_LOD3_web.glb (the website copy, without One Court Square)
"""
import csv, json, math, os, struct, sys
import numpy as np
import rhino3dm as r
import mapbox_earcut as earcut
from shapely.geometry import Polygon, MultiPolygon, LineString, Point, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parkframe import ROOT, polygons_uv, NORTH, EAST, ORIGIN_LL

D = lambda *p: os.path.join(ROOT, *p)
site = json.load(open(D('model', 'site_local.json')))
feat = json.load(open(D('scan', 'features.json')))
lawn_e, ring_e, sym, pad = feat['lawn_oval'], feat['ring_outer'], feat['symmetry'], feat['spray_pad']
GRADE = site['frame']['park_grade_navd88_m']
EXTENT = box(-45, -45, 95, 85)              # streets and ground
BLDG_EXTENT = box(-90, -110, 150, 170)       # buildings (keeps One Court Square in view)

# ------------------------------------------------------------------ record types
prisms, cylinders, meshes, curves, dots = [], [], [], [], []


def prism(layer, geom, z0, z1, color=None, name='', src='model'):
    geom = geom.buffer(0) if not geom.is_valid else geom
    for g in getattr(geom, 'geoms', [geom]):
        if isinstance(g, Polygon) and g.area > 0.0005:
            prisms.append(dict(layer=layer, poly=orient(g, 1.0), z0=z0, z1=z1, color=color, name=name, src=src))


def cylinder(layer, x, y, radius, z0, z1, color=None, name='', src='model'):
    cylinders.append(dict(layer=layer, x=x, y=y, r=radius, z0=z0, z1=z1, color=color, name=name, src=src))


def frame_box(c, a, n, s0, s1, d0, d1):
    """Rectangle in a local frame: c + s*a + d*n."""
    pts = [(c[0] + s * a[0] + d * n[0], c[1] + s * a[1] + d * n[1]) for s, d in [(s0, d0), (s1, d0), (s1, d1), (s0, d1)]]
    return Polygon(pts)


def ellipse(e, grow=0.0, n=144):
    c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
    a, b = e['a'] + grow, e['b'] + grow
    return [(e['cx'] + a * math.cos(t) * c - b * math.sin(t) * s, e['cy'] + a * math.cos(t) * s + b * math.sin(t) * c)
            for t in [2 * math.pi * i / n for i in range(n)]]


def outer_parts(path, key='geometry'):
    out = []
    for f in json.load(open(path))['features']:
        for o, hs in polygons_uv(f[key]):
            p = Polygon(o, hs)
            out.append(p if p.is_valid else p.buffer(0))
    return out


# ------------------------------------------------------------------ ground
park = Polygon(site['park'])
lawn = Polygon(ellipse(lawn_e))
lawn_curb = lawn.buffer(0.2).difference(lawn)
spray = Polygon(pad['hull']).difference(lawn.buffer(0.2))
egg_pts = ellipse(ring_e)
cx, cy = np.mean([p[0] for p in pad['hull'][:-1]]), np.mean([p[1] for p in pad['hull'][:-1]])
w = ring_e.get('path_width_m', 2.4)
for x, y in pad['hull'][:-1]:
    dd = math.hypot(x - cx, y - cy) or 1
    egg_pts.append((x + (x - cx) / dd * w, y + (y - cy) / dd * w))
egg = Polygon(egg_pts).convex_hull
axis_u = sym['axis_u']
south_fan = Polygon([p for p in egg.exterior.coords if p[1] < 7] + [(axis_u - 6.2, 0.0), (axis_u + 6.2, 0.0)]).convex_hull
# connections read off the scan ortho (1 m grid); approximate to ~0.3 m
nw_path = Polygon([(21.6, 33.8), (24.6, 35.9), (28.4, 41.1), (23.6, 41.1), (21.9, 37.5)])
ne_path = Polygon([(40.9, 34.6), (42.3, 37.6), (41.9, 41.1), (37.2, 41.1), (38.2, 37.8), (38.4, 36.1)])
table_plaza = box(14.9, 15.0, 19.5, 27.6)
bistro_plaza = box(44.5, 16.4, 51.2, 25.8)

roadbed = unary_union([p for p in outer_parts(D('data', 'plan2_roadbed.geojson')) if p.intersects(EXTENT)]).intersection(EXTENT)
medians = unary_union([p for p in outer_parts(D('data', 'plan2_median.geojson')) if p.intersects(EXTENT)]).intersection(EXTENT)
bldg_polys = []
for f in json.load(open(D('data', 'buildings.geojson')))['features']:
    pr = f['properties']
    for o, hs in polygons_uv(f['geometry']):
        p = Polygon(o, hs).buffer(0)
        if p.intersects(BLDG_EXTENT):
            bldg_polys.append((p, float(pr.get('height_roof') or 0) * 0.3048, float(pr.get('ground_elevation') or 0) * 0.3048, pr.get('bin')))
buildings_all = unary_union([b[0] for b in bldg_polys])
non_road = EXTENT.difference(roadbed).difference(medians)
# the park block: the piece of non-road ground that holds the park
park_block = max(getattr(non_road, 'geoms', [non_road]), key=lambda g: g.intersection(park).area)
landscape = park_block.intersection(park.union(box(park.bounds[0], 0, park.bounds[2] + 4, park.bounds[3] + 0.3))).difference(buildings_all)

sidewalks = unary_union([p for p in outer_parts(D('data', 'plan2_sidewalk.geojson')) if p.intersects(EXTENT)]).intersection(EXTENT)
sidewalks = sidewalks.difference(landscape).difference(buildings_all)   # drops the pre-2025 paths inside the park
forecourt_box = box(-0.5, -17.8, 51.5, 0.0)
forecourt = sidewalks.intersection(forecourt_box)
sidewalks = sidewalks.difference(forecourt_box)
paving = unary_union([egg, south_fan, nw_path, ne_path, table_plaza, bistro_plaza]).intersection(landscape).difference(lawn.buffer(0.2)).difference(spray)
planting = landscape.difference(paving).difference(lawn.buffer(0.2)).difference(spray)
other = non_road.difference(sidewalks).difference(forecourt).difference(landscape).difference(buildings_all).difference(
    unary_union([egg, south_fan]))

# courthouse stair (approximate: 10 risers of 16.5 cm, 33 cm treads, 9 m wide on the axis)
FACADE_V = -17.4
STAIR_W, RISE, TREAD, N_STEPS = 9.0, 0.165, 0.33, 10
stair_cut = box(axis_u - STAIR_W / 2, FACADE_V, axis_u + STAIR_W / 2, FACADE_V + N_STEPS * TREAD)
forecourt = forecourt.difference(stair_cut)

BOT = -0.40
prism('10_Ground::Roadbed', roadbed, BOT, -0.15, src='NYC planimetric roadbed')
prism('10_Ground::Median', medians, BOT, 0.0, src='NYC planimetric median')
prism('10_Ground::Sidewalk', sidewalks, BOT, 0.0, src='NYC planimetric sidewalk')
prism('10_Ground::Forecourt', forecourt, BOT, 0.0, src='NYC planimetric sidewalk')
prism('10_Ground::Other ground', other, BOT, 0.0, src='lots outside the park block')
prism('10_Ground::Park paving', paving, BOT, 0.0, src='scan')
prism('10_Ground::Planting beds', planting, BOT, 0.05, src='scan')
prism('10_Ground::Lawn', lawn, BOT, 0.03, src='scan')
prism('10_Ground::Lawn curb', lawn_curb, BOT, 0.10, src='scan')
prism('10_Ground::Spray pad', spray, BOT, -0.02, src='scan')
prism('10_Ground::Forecourt', stair_cut, BOT, 0.0, src='approx')
for k in range(1, N_STEPS + 1):
    prism('40_Buildings::Courthouse stair (approx)', box(axis_u - STAIR_W / 2, FACADE_V, axis_u + STAIR_W / 2, FACADE_V + (N_STEPS - k + 1) * TREAD),
          (k - 1) * RISE, k * RISE, name=f'step {k}', src='approx from photos')

# ------------------------------------------------------------------ furniture
FRAME, WOOD, CONCRETE, BLACK, GLASS = (32, 32, 32), (196, 154, 108), (205, 202, 195), (25, 25, 25), (170, 200, 215)
lawn_c = (lawn_e['cx'], lawn_e['cy'])


def bench(o, layer):
    L = min(max(o['length_m'], 2.3), 2.5)
    h = math.radians(o['heading_deg']); a = (math.cos(h), math.sin(h)); n = (-a[1], a[0])
    c = (o['x'], o['y'])
    if (lawn_c[0] - c[0]) * n[0] + (lawn_c[1] - c[1]) * n[1] < 0:   # front faces the lawn
        n = (-n[0], -n[1])
    src = 'mirrored' if o.get('mirrored') else 'scan'
    for s0, s1 in [(-L / 2, -L / 2 + 0.05), (L / 2 - 0.05, L / 2)]:
        for d0, d1, z0, z1 in [(0.22, 0.29, 0, 0.43), (-0.30, -0.23, 0, 0.86), (-0.25, 0.30, 0.60, 0.64), (-0.25, 0.29, 0.38, 0.42)]:
            prism(layer, frame_box(c, a, n, s0, s1, d0, d1), z0, z1, FRAME, 'bench frame', src)
    for k in range(5):
        d1 = 0.29 - k * 0.095
        prism(layer, frame_box(c, a, n, -L / 2 + 0.05, L / 2 - 0.05, d1 - 0.075, d1), 0.42, 0.45, WOOD, 'seat slat', src)
    for z0, z1 in [(0.52, 0.60), (0.63, 0.71), (0.74, 0.82)]:
        prism(layer, frame_box(c, a, n, -L / 2 + 0.05, L / 2 - 0.05, -0.27, -0.24), z0, z1, WOOD, 'back slat', src)


def game_table(o):
    h = math.radians(o['heading_deg']); a = (math.cos(h), math.sin(h)); n = (-a[1], a[0]); c = (o['x'], o['y'])
    lay = '20_Furniture::Game tables'
    prism(lay, frame_box(c, a, n, -0.15, 0.15, -0.15, 0.15), 0, 0.68, CONCRETE, 'pedestal', 'scan')
    prism(lay, frame_box(c, a, n, -0.43, 0.43, -0.43, 0.43), 0.68, 0.76, CONCRETE, 'table top', 'scan')
    prism(lay, frame_box(c, a, n, -0.24, 0.24, -0.24, 0.24), 0.76, 0.765, (40, 110, 70), 'checkerboard', 'scan')
    for side in (-1, 1):   # benches on both sides along the long axis, backs on the outside
        s_in, s_out = side * 0.62, side * 1.02
        lo, hi = min(s_in, s_out), max(s_in, s_out)
        prism(lay, frame_box(c, a, n, lo, hi, -0.6, 0.6), 0.42, 0.46, WOOD, 'bench seat', 'scan')
        bk = (side * 0.98, side * 1.02)
        prism(lay, frame_box(c, a, n, min(bk), max(bk), -0.6, 0.6), 0.46, 0.85, WOOD, 'bench back', 'scan')
        for d in (-0.5, 0.5):
            prism(lay, frame_box(c, a, n, lo + 0.05, hi - 0.05, d - 0.03, d + 0.03), 0, 0.42, FRAME, 'bench leg', 'scan')


for o in feat['objects']:
    if o['kind'] == 'bench' and o['x'] < 44:
        bench(o, '20_Furniture::Benches (mirrored)' if o.get('mirrored') else '20_Furniture::Benches (scanned)')
    elif o['kind'] == 'game table + seats':
        game_table(o)

# chain-and-bollard fence on the lawn edge: bollards from the scan where found, evenly filled elsewhere
edge = LineString(ellipse(lawn_e, grow=0.35, n=720) + [ellipse(lawn_e, grow=0.35, n=720)[0]])
found = [o for o in feat['objects'] if o['kind'].startswith('small object') and edge.distance(Point(o['x'], o['y'])) < 0.35]
pos = sorted(edge.project(Point(o['x'], o['y'])) for o in found)
gaps = np.diff(pos) if len(pos) > 2 else np.array([2.4])
spacing = float(np.median(gaps[(gaps > 0.8) & (gaps < 4)])) if ((gaps > 0.8) & (gaps < 4)).any() else 2.4
spray_side = spray.buffer(1.0)
n_b = int(round(edge.length / spacing))
bollards = []
for k in range(n_b):
    p = edge.interpolate(k * edge.length / n_b)
    if not spray_side.contains(p):
        bollards.append((p.x, p.y))
for x, y in bollards:
    cylinder('20_Furniture::Lawn fence bollards', x, y, 0.05, 0.03, 0.78, BLACK, 'bollard', 'scan spacing')
for (x0, y0), (x1, y1) in zip(bollards, bollards[1:] + bollards[:1]):
    if math.hypot(x1 - x0, y1 - y0) < spacing * 1.6:
        curves.append(dict(layer='20_Furniture::Lawn fence chain', pts=[(x0, y0, 0.62), ((x0 + x1) / 2, (y0 + y1) / 2, 0.54), (x1, y1, 0.62)]))

# perimeter hoop fence where planting meets a sidewalk
fence_lines = planting.boundary.intersection(sidewalks.union(forecourt).buffer(0.15))
for g in getattr(fence_lines, 'geoms', [fence_lines]):
    if not isinstance(g, LineString) or g.length < 1.0:
        continue
    for t in np.arange(0, g.length + 0.01, 1.5):
        p = g.interpolate(min(t, g.length))
        prism('20_Furniture::Perimeter fence', box(p.x - 0.02, p.y - 0.02, p.x + 0.02, p.y + 0.02), 0.05, 0.95, BLACK, 'fence post', 'photos')
    for z0 in (0.88, 0.35):
        prism('20_Furniture::Perimeter fence', g.buffer(0.015, cap_style='flat'), z0, z0 + 0.03, BLACK, 'fence rail', 'photos')

lamp = next((o for o in feat['objects'] if o['kind'].startswith('pole') and 0 < o['x'] < 48 and 0 < o['y'] < 41), None)
if lamp:
    for rr, z0, z1, nm in [(0.15, 0, 0.6, 'lamp base'), (0.065, 0.6, 3.6, 'lamp shaft'), (0.22, 3.6, 4.2, 'lantern'), (0.26, 4.2, 4.3, 'lantern cap')]:
        cylinder('20_Furniture::Lamps (approx height)', lamp['x'], lamp['y'], rr, z0, z1, BLACK, nm, 'scan position')
sign = min((o for o in feat['objects'] if o['kind'] == 'tall object'), key=lambda o: math.hypot(o['x'] - 31.9, o['y'] - 39.4))
c, a = (sign['x'], sign['y']), (1.0, 0.0); n = (0.0, 1.0)
for s in (-0.6, 0.6):
    prism('20_Furniture::Signs', frame_box(c, a, n, s - 0.04, s + 0.04, -0.04, 0.04), 0, 1.65, (30, 70, 45), 'sign post', 'scan')
prism('20_Furniture::Signs', frame_box(c, a, n, -0.65, 0.65, -0.02, 0.02), 0.45, 1.65, (30, 70, 45), 'park sign', 'scan')
# bus shelter on Jackson Ave near Thomson (partly scanned; size from NYC standard shelters)
c, a, n = (48.3, 42.3), (1.0, 0.0), (0.0, 1.0)
prism('20_Furniture::Bus shelter (approx)', frame_box(c, a, n, -2.1, 2.1, -0.8, 0.8), 2.45, 2.55, FRAME, 'roof', 'approx')
prism('20_Furniture::Bus shelter (approx)', frame_box(c, a, n, -2.1, 2.1, 0.75, 0.78), 0.1, 2.45, GLASS, 'back glass', 'approx')
for s in (-2.1, 2.07):
    prism('20_Furniture::Bus shelter (approx)', frame_box(c, a, n, s, s + 0.03, -0.1, 0.78), 0.1, 2.45, GLASS, 'end glass', 'approx')
    for d in (-0.8, 0.72):
        prism('20_Furniture::Bus shelter (approx)', frame_box(c, a, n, s, s + 0.06, d, d + 0.06), 0, 2.45, FRAME, 'post', 'approx')

# ------------------------------------------------------------------ trees
def icosphere(sub=2):
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
            a_, b_, c_ = mid(i, j), mid(j, k), mid(k, i)
            F2 += [(i, a_, c_), (j, b_, a_), (k, c_, b_), (a_, b_, c_)]
        F = F2
    return np.array(V), np.array(F)


SPH_V, SPH_F = icosphere(2)
REMOVED = {(25.245, 8.117), (27.246, 31.901), (35.768, 31.372)}
for t in csv.DictReader(open(D('model', 'trees.csv'))):
    x, y = float(t['x_m']), float(t['y_m'])
    if t['status'] != 'Full' or (round(x, 3), round(y, 3)) in REMOVED or not EXTENT.contains(Point(x, y)):
        continue
    dbh = float(t['dbh_in'] or 0); H = float(t['height_m_est']); crown = float(t['crown_d_m_est'])
    base = min(max(0.35 * H, 2.2), 4.0)
    cylinder('30_Trees::Trunks', x, y, max(0.06, dbh * 0.0254 / 2), 0.0, base + (H - base) * 0.35, (92, 70, 50), t['species'], 'NYC Forestry')
    rz = (H - base) / 2
    V = SPH_V * np.array([crown / 2, crown / 2, rz]) + np.array([x, y, base + rz])
    meshes.append(dict(layer='30_Trees::Crowns (park)' if t['in_park'] == 'True' else '30_Trees::Crowns (street)', V=V, F=SPH_F,
                       name=f"{t['species']} DBH {dbh:.0f} in", src='NYC Forestry; crown estimated from DBH'))

# ------------------------------------------------------------------ buildings
for p, hgt, ground, bin_ in bldg_polys:
    if hgt <= 0:
        continue
    lay = '40_Buildings::Courthouse' if bin_ == '4000698' else '40_Buildings::Context'
    z0 = ground - GRADE
    prism(lay, p, min(z0, 0.0), z0 + hgt, name=f'BIN {bin_}', src=f'NYC building footprints, roof {hgt:.1f} m')

# ------------------------------------------------------------------ reference curves + labels
def ring_curve(layer, pts, z=0.0):
    curves.append(dict(layer=layer, pts=[(x, y, z) for x, y in pts] + [(pts[0][0], pts[0][1], z)]))


ring_curve('00_Reference::Property line', list(park.exterior.coords)[:-1], 0.12)
for g, nm in [(lawn, 'lawn'), (egg, 'ring path'), (spray, 'spray pad'), (paving, 'paving'), (planting, 'planting')]:
    for part in getattr(g, 'geoms', [g]):
        ring_curve('00_Reference::Zone outlines', list(part.exterior.coords)[:-1], 0.13)
t = math.radians(90 + sym['tilt_deg'])
curves.append(dict(layer='00_Reference::Symmetry axis', pts=[(axis_u - 22 * math.cos(t), sym['axis_v'] - 22 * math.sin(t), 0.14),
                                                           (axis_u + 18 * math.cos(t), sym['axis_v'] + 18 * math.sin(t), 0.14)]))
nx, ny = NORTH
base = (-35.0, 70.0)
curves.append(dict(layer='00_Reference::North arrow', pts=[(base[0], base[1], 0.2), (base[0] + 8 * nx, base[1] + 8 * ny, 0.2),
                                                         (base[0] + 8 * nx - 1.5 * (nx + ny * .5), base[1] + 8 * ny - 1.5 * (ny - nx * .5), 0.2)]))
dots.append(dict(layer='00_Reference::North arrow', text='N (true)', x=base[0] + 9 * nx, y=base[1] + 9 * ny, z=0.2))
for x, y, m, ft in site['elev']:
    if EXTENT.contains(Point(x, y)):
        dots.append(dict(layer='00_Reference::Spot elevations (NAVD88)', text=f'{m:.2f}', x=x, y=y, z=m - GRADE))
for text, x, y in [('Central lawn', lawn_c[0], lawn_c[1]), ('Spray pad', axis_u, 8.2), ('Game tables', 17.2, 28.6), ('Bistro area', 48.0, 21.0),
                   ('Jackson Ave', 20, 50), ('Thomson Ave', 63, 25), ('Court Sq W', -8, 20), ('Long Island City Courthouse', 31, -30)]:
    dots.append(dict(layer='90_Annotation', text=text, x=x, y=y, z=1.0))

LAYERS = {
    '00_Reference': (90, 90, 90), '00_Reference::Property line': (0, 160, 0), '00_Reference::Zone outlines': (120, 120, 120),
    '00_Reference::Symmetry axis': (200, 0, 160), '00_Reference::North arrow': (0, 0, 0), '00_Reference::Spot elevations (NAVD88)': (140, 80, 20),
    '10_Ground': (150, 150, 150), '10_Ground::Roadbed': (72, 75, 80), '10_Ground::Median': (110, 140, 105), '10_Ground::Sidewalk': (200, 198, 190),
    '10_Ground::Forecourt': (212, 206, 196), '10_Ground::Other ground': (165, 165, 160), '10_Ground::Park paving': (188, 188, 183),
    '10_Ground::Planting beds': (92, 98, 64), '10_Ground::Lawn': (98, 152, 82), '10_Ground::Lawn curb': (236, 236, 230), '10_Ground::Spray pad': (150, 176, 196),
    '20_Furniture': (60, 60, 60), '20_Furniture::Benches (scanned)': WOOD, '20_Furniture::Benches (mirrored)': (220, 180, 120),
    '20_Furniture::Game tables': CONCRETE, '20_Furniture::Lawn fence bollards': BLACK, '20_Furniture::Lawn fence chain': (60, 60, 60),
    '20_Furniture::Perimeter fence': BLACK, '20_Furniture::Lamps (approx height)': BLACK, '20_Furniture::Signs': (30, 70, 45),
    '20_Furniture::Bus shelter (approx)': GLASS,
    '30_Trees': (70, 120, 60), '30_Trees::Trunks': (92, 70, 50), '30_Trees::Crowns (park)': (88, 140, 70), '30_Trees::Crowns (street)': (110, 150, 90),
    '40_Buildings': (200, 200, 205), '40_Buildings::Courthouse': (196, 120, 96), '40_Buildings::Context': (205, 205, 210),
    '40_Buildings::Courthouse stair (approx)': (220, 214, 204),
    '90_Annotation': (0, 0, 0),
}

# ------------------------------------------------------------------ write .3dm
def write_3dm(path):
    f = r.File3dm()
    f.Settings.ModelUnitSystem = r.UnitSystem.Meters
    f.Settings.ModelAbsoluteTolerance = 0.001
    ea = f.Settings.EarthAnchorPoint
    ea.EarthBasepointLatitude, ea.EarthBasepointLongitude, ea.EarthBasepointElevation = ORIGIN_LL[1], ORIGIN_LL[0], GRADE
    ea.ModelBasePoint = r.Point3d(0, 0, 0)
    ea.ModelNorth = r.Vector3d(NORTH[0], NORTH[1], 0)
    ea.ModelEast = r.Vector3d(EAST[0], EAST[1], 0)
    ea.Name = 'Court Square Park, park frame origin (Court Sq W x courthouse forecourt corner)'
    f.Settings.EarthAnchorPoint = ea
    index = {}
    global bad
    bad = []
    for full, col in LAYERS.items():
        lay = r.Layer(); lay.Name = full.split('::')[-1]; lay.Color = (*col, 255)
        if '::' in full:
            lay.ParentLayerId = f.Layers.FindIndex(index[full.rsplit('::', 1)[0]]).Id
        mat = r.Material(); mat.Name = full.replace('::', ' - '); mat.DiffuseColor = (*col, 255)
        lay.RenderMaterialIndex = f.Materials.Add(mat)
        index[full] = f.Layers.Add(lay)

    def attrs(layer, color=None, name='', src=''):
        at = r.ObjectAttributes(); at.LayerIndex = index[layer]; at.Name = name
        if color:
            at.ObjectColor = (*color, 255); at.ColorSource = r.ObjectColorSource.ColorFromObject
        if src:
            at.SetUserString('source', src)
        return at

    for p in prisms:
        ext = list(p['poly'].exterior.coords)[:-1]
        if len(ext) < 3:
            continue
        pl = r.Point3dList()
        for x, y in ext + [ext[0]]:
            pl.Add(x, y, p['z0'])
        e = r.Extrusion.Create(r.PolylineCurve(pl), p['z1'] - p['z0'], True)
        if e is None:
            bad.append(p['layer']); continue
        bb = e.GetBoundingBox()
        if abs(bb.Min.Z - p['z0']) > 1e-4 or abs(bb.Max.Z - p['z1']) > 1e-4:
            bad.append(p['layer'] + ' (z range)'); continue
        ox, oy = ext[0]
        for hole in p['poly'].interiors:
            hp = r.Point3dList()
            pts = list(hole.coords)
            for x, y in pts:
                hp.Add(x - ox, y - oy, 0)
            e.AddInnerProfile(r.PolylineCurve(hp))
        f.Objects.AddExtrusion(e, attrs(p['layer'], p['color'], p['name'], p['src']))
    for c in cylinders:
        circ = r.Circle(r.Point3d(c['x'], c['y'], c['z0']), c['r'])   # world-XY circle at the base
        e = r.Extrusion.CreateCylinderExtrusion(r.Cylinder(circ, c['z1'] - c['z0']), True, True)
        f.Objects.AddExtrusion(e, attrs(c['layer'], c['color'], c['name'], c['src']))
    for m in meshes:
        mesh = r.Mesh()
        for x, y, z in m['V']:
            mesh.Vertices.Add(float(x), float(y), float(z))
        for a_, b_, c_ in m['F']:
            mesh.Faces.AddFace(int(a_), int(b_), int(c_))
        mesh.Normals.ComputeNormals() if hasattr(mesh.Normals, 'ComputeNormals') else None
        f.Objects.AddMesh(mesh, attrs(m['layer'], None, m['name'], m['src']))
    for c in curves:
        pl = r.Point3dList()
        for x, y, z in c['pts']:
            pl.Add(x, y, z)
        f.Objects.AddCurve(r.PolylineCurve(pl), attrs(c['layer']))
    for d in dots:
        f.Objects.AddTextDot(d['text'], r.Point3d(d['x'], d['y'], d['z']), attrs(d['layer']))
    f.Write(path, 8)
    return f


# ------------------------------------------------------------------ write preview GLB (Y-up)
def tri_prism(poly, z0, z1):
    rings = [list(poly.exterior.coords)[:-1]] + [list(h.coords)[:-1] for h in poly.interiors]
    flat = np.array([p for ring in rings for p in ring], dtype=np.float64)
    ends = np.cumsum([len(ring) for ring in rings]).astype(np.uint32)
    idx = earcut.triangulate_float64(flat, ends).reshape(-1, 3)
    tris = []
    for a_, b_, c_ in idx:
        pa, pb, pc = flat[a_], flat[b_], flat[c_]
        cross = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
        if cross < 0:
            pb, pc = pc, pb
        tris.append([(pa[0], pa[1], z1), (pb[0], pb[1], z1), (pc[0], pc[1], z1)])
        tris.append([(pa[0], pa[1], z0), (pc[0], pc[1], z0), (pb[0], pb[1], z0)])
    for ring in rings:
        for i in range(len(ring)):
            (x0, y0), (x1, y1) = ring[i], ring[(i + 1) % len(ring)]
            tris.append([(x0, y0, z0), (x1, y1, z0), (x1, y1, z1)])
            tris.append([(x0, y0, z0), (x1, y1, z1), (x0, y0, z1)])
    return tris


def write_glb(path, exclude=()):
    groups = {}
    def add(key, tris):
        groups.setdefault(key, []).extend(tris)
    for p in prisms:
        if p['name'] in exclude:
            continue
        add(p['color'] or LAYERS[p['layer']], tri_prism(p['poly'], p['z0'], p['z1']))
    for c in cylinders:
        add(c['color'] or LAYERS[c['layer']], tri_prism(Point(c['x'], c['y']).buffer(c['r'], 8), c['z0'], c['z1']))
    for m in meshes:
        add(LAYERS[m['layer']], [[tuple(m['V'][i]) for i in face] for face in m['F']])
    bin_ = bytearray(); views, accs, mats, prims = [], [], [], []
    for k, (color, tris) in enumerate(groups.items()):
        T = np.array(tris, dtype=np.float64)                    # (n, 3, 3) in park frame
        P = np.stack([T[..., 0], T[..., 2], -T[..., 1]], -1).reshape(-1, 3).astype('<f4')
        e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
        nrm = np.cross(e1, e2); nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
        N = np.repeat(np.stack([nrm[:, 0], nrm[:, 2], -nrm[:, 1]], -1), 3, 0).astype('<f4')
        for arr, target in [(P, 34962), (N, 34962)]:
            while len(bin_) % 4: bin_.append(0)
            views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=arr.nbytes, target=target)); bin_.extend(arr.tobytes())
        accs.append(dict(bufferView=len(views) - 2, componentType=5126, count=len(P), type='VEC3', min=P.min(0).tolist(), max=P.max(0).tolist()))
        accs.append(dict(bufferView=len(views) - 1, componentType=5126, count=len(N), type='VEC3'))
        lin = [((c / 255 + 0.055) / 1.055) ** 2.4 for c in color]
        mats.append(dict(pbrMetallicRoughness=dict(baseColorFactor=[*lin, 0.55 if color == GLASS else 1.0], metallicFactor=0, roughnessFactor=0.9),
                         alphaMode='BLEND' if color == GLASS else 'OPAQUE', doubleSided=True))
        prims.append(dict(attributes=dict(POSITION=len(accs) - 2, NORMAL=len(accs) - 1), material=k))
    while len(bin_) % 4: bin_.append(0)
    gltf = dict(asset=dict(version='2.0', generator='court-square-park scripts/build_model.py'), scene=0, scenes=[dict(nodes=[0])],
                nodes=[dict(name='Court Square Park LOD3', mesh=0)], meshes=[dict(primitives=prims)], materials=mats,
                accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    js = json.dumps(gltf, separators=(',', ':')).encode(); js += b' ' * ((4 - len(js) % 4) % 4)
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<III', 0x46546C67, 2, 28 + len(js) + len(bin_)))
        fh.write(struct.pack('<II', len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack('<II', len(bin_), 0x004E4942)); fh.write(bin_)


bad = []
f = write_3dm(D('model', 'court_square_park_LOD3.3dm'))
print('extrusions that failed:', len(bad), sorted(set(bad))[:10])
write_glb(D('model', 'court_square_park_LOD3_preview.glb'))
# website copy: One Court Square (193 m) sits between the default camera and the park, so it is left out
write_glb(D('model', 'court_square_park_LOD3_web.glb'), exclude={'BIN 4307108'})
from collections import Counter
cnt = Counter(p['layer'] for p in prisms) + Counter(c['layer'] for c in cylinders) + Counter(m['layer'] for m in meshes) + Counter(c['layer'] for c in curves)
for k in sorted(cnt):
    print(f'{cnt[k]:5d}  {k}')
print('bollards', len(bollards), 'spacing', round(spacing, 2), '| areas m2: paving', round(paving.area, 1), 'planting', round(planting.area, 1),
      'lawn', round(lawn.area, 1), 'spray', round(spray.area, 1), 'forecourt', round(forecourt.area, 1))
