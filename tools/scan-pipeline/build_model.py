"""Detailed site model of Court Square Park for Rhino 8, built from the scan measurements and NYC data.

Park frame as everywhere here: meters, x = u along the courthouse edge toward Thomson Ave, y = v toward Jackson Ave,
z up, z = 0 at park grade (NAVD88 5.28 m).

- terrain: thin-plate spline through NYC ground spot elevations (roadbed points raised 15 cm to curb level)
- ground surfaces draped on the terrain; roadbed 15 cm below the curb; granite curb band, planting edge band, tree pits
- paving joints: 0.61 m pavers around the park and on the forecourt, 5 ft flags elsewhere, radial saw cuts on the ring path
- furniture from the scan positions: World's Fair benches, chess tables, chain-and-bollard lawn fence, spear-top rail fence,
  Parks lamppost, sign, bus shelter, spray-pad drain
- species-based procedural trees (NYC Forestry points, crowns estimated from DBH)
- buildings: NYC 3D Building Model (2014 survey, LOD1/2 hybrid) where the building predates 2015, otherwise the current
  footprint extruded to its recorded roof height (glass, with floor bands)
- the courthouse facade, entrance and roofs at LOD3 from photos on top of its survey massing (scripts/courthouse.py)

Usage: python scripts/build_model.py   (needs rhino3dm, shapely, mapbox_earcut, scipy, pyogrio, pyproj)
Writes model/court_square_park_LOD3.3dm, model/court_square_park_LOD3_preview.glb,
       model/court_square_park_LOD3_web.glb (the website copy, quantized to half the size) and
       model/court_square_park_LOD3_web.buildings.json (footprint prisms the website uses to fade buildings that block the view)
"""
import csv, json, math, os, sys
import numpy as np
import rhino3dm as r
import pyogrio, pyproj
from scipy.interpolate import RBFInterpolator
from shapely import wkb, contains_xy
from shapely.geometry import Polygon, LineString, MultiLineString, Point, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parkframe import ROOT, polygons_uv, uv, NORTH, EAST, ORIGIN_LL
import model_parts as mp
import courthouse
from glb_writer import write_glb

D = lambda *p: os.path.join(ROOT, *p)
site = json.load(open(D('model', 'site_local.json')))
feat = json.load(open(D('scan', 'features.json')))
lawn_e, ring_e, sym, pad = feat['lawn_oval'], feat['ring_outer'], feat['symmetry'], feat['spray_pad']
GRADE = site['frame']['park_grade_navd88_m']
EXTENT = box(-45, -45, 95, 85)              # streets and ground
BLDG_EXTENT = box(-90, -110, 150, 170)       # buildings
objs, curves, dots = [], [], []             # objs: dict(layer, V, F, color, smooth, name, src)


def add(layer, VF, color, name='', src='', smooth=False, rough=0.9):
    V, F = np.asarray(VF[0], float), np.asarray(VF[1], int)
    if len(F):   # drop zero-area triangles (revolve tips, slivers from clipping): Rhino flags them as invalid
        area = np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
        F = F[area > 1e-9]
    if len(F):
        objs.append(dict(layer=layer, V=np.asarray(V, float), F=np.asarray(F, int), color=tuple(color), smooth=smooth, name=name, src=src, rough=rough))


def parts(path):
    out = []
    for f in json.load(open(path))['features']:
        for o, hs in polygons_uv(f['geometry']):
            p = Polygon(o, hs)
            out.append(p if p.is_valid else p.buffer(0))
    return out


def polys(g):
    return [p for p in getattr(g, 'geoms', [g]) if isinstance(p, Polygon) and p.area > 0.02]


# ------------------------------------------------------------------ terrain
roadbed = unary_union([p for p in parts(D('data', 'plan2_roadbed.geojson')) if p.intersects(EXTENT)]).intersection(EXTENT)
footprints = []
for f in json.load(open(D('data', 'buildings2.geojson')))['features']:
    pr = f['properties']
    for o, hs in polygons_uv(f['geometry']):
        p = Polygon(o, hs).buffer(0)
        if p.intersects(BLDG_EXTENT) and p.area > 1:
            footprints.append(dict(poly=p, bin=str(pr.get('bin')), year=int(pr.get('construction_year') or 0),
                                   h=float(pr.get('height_roof') or 0) * 0.3048, ground=float(pr.get('ground_elevation') or 0) * 0.3048))
buildings_all = unary_union([b['poly'] for b in footprints])
gx, gy, gz = [], [], []
road_all = unary_union(parts(D('data', 'plan2_roadbed.geojson')))
for f in json.load(open(D('data', 'plan2_elevation_points.geojson')))['features']:
    if f['properties'].get('feat_code') != '3000':       # 3020 points are roof heights
        continue
    x, y = uv(*f['geometry']['coordinates'])
    if contains_xy(buildings_all, x, y):
        continue
    z = float(f['properties']['elevation']) * 0.3048
    gx.append(x); gy.append(y); gz.append(z + (0.15 if contains_xy(road_all, x, y) else 0.0) - GRADE)
_rbf = RBFInterpolator(np.column_stack([gx, gy]), np.array(gz), kernel='thin_plate_spline', smoothing=3.0)
# sample once on a 1 m grid and interpolate bilinearly (fast, and keeps far extrapolation tame)
_GX = np.arange(-100, 161, 1.0); _GY = np.arange(-120, 181, 1.0)
_GRID = _rbf(np.column_stack([np.repeat(_GX, len(_GY)), np.tile(_GY, len(_GX))])).reshape(len(_GX), len(_GY))


def T(x, y):
    x = np.clip(np.atleast_1d(np.asarray(x, float)), _GX[0], _GX[-1] - 1e-6); y = np.clip(np.atleast_1d(np.asarray(y, float)), _GY[0], _GY[-1] - 1e-6)
    i = ((x - _GX[0]) // 1).astype(int); j = ((y - _GY[0]) // 1).astype(int)
    fx, fy = x - _GX[i], y - _GY[j]
    return (_GRID[i, j] * (1 - fx) * (1 - fy) + _GRID[i + 1, j] * fx * (1 - fy) + _GRID[i, j + 1] * (1 - fx) * fy + _GRID[i + 1, j + 1] * fx * fy)


Tp = lambda x, y: float(T(x, y)[0])
park = Polygon(site['park'])
print(f'terrain from {len(gz)} ground spot elevations; park centre {Tp(31, 22):+.2f} m, Jackson edge {Tp(31, 41):+.2f}, '
      f'courthouse edge {Tp(31, 0):+.2f}, Thomson road {Tp(60, 12) - 0.15:+.2f}')

# ------------------------------------------------------------------ zones (same layout as the scan-based plan)
def ellipse(e, grow=0.0, n=144):
    c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
    a, b = e['a'] + grow, e['b'] + grow
    return [(e['cx'] + a * math.cos(t) * c - b * math.sin(t) * s, e['cy'] + a * math.cos(t) * s + b * math.sin(t) * c)
            for t in [2 * math.pi * i / n for i in range(n)]]


lawn = Polygon(ellipse(lawn_e)); lawn_c = (lawn_e['cx'], lawn_e['cy'])
lawn_curb = lawn.buffer(0.2).difference(lawn)
spray = Polygon(pad['hull']).difference(lawn.buffer(0.2))
egg_pts = ellipse(ring_e)
pcx, pcy = np.mean([p[0] for p in pad['hull'][:-1]]), np.mean([p[1] for p in pad['hull'][:-1]])
w = ring_e.get('path_width_m', 2.4)
for x, y in pad['hull'][:-1]:
    dd = math.hypot(x - pcx, y - pcy) or 1
    egg_pts.append((x + (x - pcx) / dd * w, y + (y - pcy) / dd * w))
egg = Polygon(egg_pts).convex_hull
axis_u = sym['axis_u']
south_fan = Polygon([p for p in egg.exterior.coords if p[1] < 7] + [(axis_u - 6.2, 0.0), (axis_u + 6.2, 0.0)]).convex_hull
# entrances run on to the sidewalk; the landscape clip trims them at the sidewalk's inner edge
nw_path = Polygon([(21.6, 33.8), (24.6, 35.9), (29.4, 42.6), (23.4, 42.6), (21.9, 37.5)])
ne_path = Polygon([(40.9, 34.6), (42.3, 37.6), (41.8, 42.6), (36.8, 42.6), (38.2, 37.8), (38.4, 36.1)])
table_plaza = box(14.9, 15.0, 19.5, 27.6)
bistro_plaza = box(44.5, 16.4, 53.0, 25.8)    # opens onto the Thomson Ave sidewalk
medians = unary_union([p for p in parts(D('data', 'plan2_median.geojson')) if p.intersects(EXTENT)]).intersection(EXTENT)
non_road = EXTENT.difference(roadbed).difference(medians)
park_block = max(getattr(non_road, 'geoms', [non_road]), key=lambda g: g.intersection(park).area)
sidewalks = unary_union([p for p in parts(D('data', 'plan2_sidewalk.geojson')) if p.intersects(EXTENT)]).intersection(EXTENT)
# NYC's sidewalk layer still holds the pre-2025 park paths: drop those, keep every real sidewalk outside the park
sidewalks = sidewalks.difference(park).difference(buildings_all)
# park landscape: the property plus the strip between it and the Thomson / Jackson sidewalks
landscape = park_block.intersection(park.union(box(park.bounds[0], 0, park.bounds[2] + 4, park.bounds[3] + 0.3))).difference(sidewalks).difference(buildings_all)
FACADE_V, STAIR_W, RISE, TREAD, N_STEPS = -16.8, 9.0, 0.165, 0.33, 10   # stair foot; the landing runs back to the facade
forecourt = sidewalks.intersection(box(-0.5, -17.8, 51.5, 0.0))
sidewalks = sidewalks.difference(box(-0.5, -17.8, 51.5, 0.0))
stair_cut = box(axis_u - STAIR_W / 2, FACADE_V, axis_u + STAIR_W / 2, FACADE_V + N_STEPS * TREAD)
forecourt = forecourt.difference(stair_cut)
paving = unary_union([egg, south_fan, nw_path, ne_path, table_plaza, bistro_plaza]).intersection(landscape).difference(lawn.buffer(0.2)).difference(spray)
planting = landscape.difference(paving).difference(lawn.buffer(0.2)).difference(spray)
other = non_road.difference(sidewalks).difference(forecourt).difference(landscape).difference(buildings_all).difference(unary_union([egg, south_fan]))

# street trees get pits in the sidewalk; granite curb band along the roadbed; concrete band where planting meets the sidewalk
REMOVED = {(25.245, 8.117), (27.246, 31.901), (35.768, 31.372)}
trees = [t for t in csv.DictReader(open(D('model', 'trees.csv'))) if t['status'] == 'Full'
         and (round(float(t['x_m']), 3), round(float(t['y_m']), 3)) not in REMOVED and EXTENT.contains(Point(float(t['x_m']), float(t['y_m'])))]
pits = unary_union([box(float(t['x_m']) - 0.75, float(t['y_m']) - 0.75, float(t['x_m']) + 0.75, float(t['y_m']) + 0.75)
                    for t in trees if sidewalks.contains(Point(float(t['x_m']), float(t['y_m'])))]).intersection(sidewalks)
curb_band = sidewalks.intersection(roadbed.buffer(0.18)).difference(pits)
edge_band = sidewalks.union(forecourt).intersection(planting.buffer(0.42)).difference(pits).difference(curb_band)
sidewalks = sidewalks.difference(pits).difference(curb_band).difference(edge_band)
forecourt = forecourt.difference(edge_band)
pavers_zone = park_block.buffer(0.5)        # pigmented 2 ft pavers around the park, 5 ft flags elsewhere

GROUND = [  # layer, geometry, offset, colour, grid
    ('10_Ground::Roadbed', roadbed, -0.15, (70, 73, 78), 3.0),
    ('10_Ground::Median', medians, 0.0, (150, 150, 145), 2.0),
    ('10_Ground::Sidewalk', sidewalks, 0.0, (206, 204, 196), 2.0),
    ('10_Ground::Curb stone', curb_band, 0.0, (178, 178, 176), 1.0),
    ('10_Ground::Planting edge band', edge_band, 0.01, (192, 192, 186), 1.0),
    ('10_Ground::Tree pits', pits, -0.04, (92, 72, 54), 1.0),
    ('10_Ground::Forecourt', forecourt, 0.0, (214, 208, 196), 2.0),
    ('10_Ground::Other ground', other, 0.0, (170, 170, 165), 3.0),
    ('10_Ground::Park paving', paving, 0.0, (176, 178, 176), 1.5),
    ('10_Ground::Planting beds', planting, 0.05, (112, 126, 70), 1.5),
    ('10_Ground::Lawn', lawn, 0.03, (96, 148, 78), 1.5),
    ('10_Ground::Lawn curb', lawn_curb, 0.10, (236, 236, 230), 0.8),
    ('10_Ground::Spray pad', spray, -0.02, (160, 182, 198), 1.0),
]
for layer, geom, off, col, grid in GROUND:
    for k, p in enumerate(polys(geom)):
        add(layer, mp.drape(p, T, off, grid=grid), col, f'{layer.split("::")[-1]} {k + 1}', 'draped on NYC spot-elevation terrain')


# paving joints
def grid_lines(geom, spacing):
    x0, y0, x1, y1 = geom.bounds
    lines = [LineString([(x, y0 - 1), (x, y1 + 1)]) for x in np.arange(math.floor(x0 / spacing) * spacing, x1 + spacing, spacing)]
    lines += [LineString([(x0 - 1, y), (x1 + 1, y)]) for y in np.arange(math.floor(y0 / spacing) * spacing, y1 + spacing, spacing)]
    return MultiLineString(lines).intersection(geom)


def add_joints(lines, offset, color):
    pieces = [g for g in getattr(lines, 'geoms', [lines]) if isinstance(g, LineString) and g.length > 0.05]
    add('10_Ground::Paving joints', mp.merge([mp.drape_strip(g, T, offset + 0.004, 0.012) for g in pieces]), color, 'joints', 'paver / saw-cut joints', smooth=True)


add_joints(grid_lines(sidewalks.intersection(pavers_zone), 0.61), 0.0, (150, 148, 142))
add_joints(grid_lines(sidewalks.difference(pavers_zone), 1.524), 0.0, (150, 148, 142))
add_joints(grid_lines(forecourt, 0.61), 0.0, (160, 152, 140))
add_joints(grid_lines(unary_union([table_plaza, bistro_plaza]).intersection(paving), 1.5), 0.0, (140, 142, 140))
ring_ang = np.linspace(0, 2 * math.pi, int(2 * math.pi * (lawn_e['a'] + 1.2) / 2.5), endpoint=False)
add_joints(MultiLineString([LineString([lawn_c, (lawn_c[0] + 30 * math.cos(t), lawn_c[1] + 30 * math.sin(t))]) for t in ring_ang]).intersection(
    paving.intersection(egg.union(south_fan))), 0.0, (140, 142, 140))

# courthouse stair (approximate: 10 risers of 16.5 cm on 33 cm treads, 9 m wide on the axis)
z_stair = Tp(axis_u, FACADE_V + 1.6)
add('40_Buildings::Courthouse stair (approx)', mp.prism(stair_cut, z_stair - 0.4, z_stair), (214, 208, 196), 'stair base', 'approx from photos')
for k in range(1, N_STEPS + 1):
    add('40_Buildings::Courthouse stair (approx)', mp.prism(box(axis_u - STAIR_W / 2, FACADE_V, axis_u + STAIR_W / 2, FACADE_V + (N_STEPS - k + 1) * TREAD),
        z_stair + (k - 1) * RISE, z_stair + k * RISE), (220, 214, 204), f'step {k}', 'approx from photos')


# ------------------------------------------------------------------ furniture
def at(x, y, off=0.0):
    return (x, y, Tp(x, y) + off)


for o in feat['objects']:
    if o['kind'] == 'bench' and o['x'] < 44:
        h = math.radians(o['heading_deg']); a = (math.cos(h), math.sin(h)); n = (-a[1], a[0])
        if (lawn_c[0] - o['x']) * n[0] + (lawn_c[1] - o['y']) * n[1] < 0:
            n = (-n[0], -n[1])
        lay = '20_Furniture::Benches (mirrored)' if o.get('mirrored') else '20_Furniture::Benches (scanned)'
        fr, sl = mp.worlds_fair_bench(at(o['x'], o['y']), a, n, L=min(max(o['length_m'], 2.3), 2.5))
        src = 'mirrored across the symmetry axis' if o.get('mirrored') else 'scan position'
        add(lay, fr, mp.FRAME_IRON, "World's Fair bench frame", src); add(lay, sl, mp.SLAT, "World's Fair bench slats", src)
    elif o['kind'] == 'game table + seats':
        h = math.radians(o['heading_deg']); a = (math.cos(h), math.sin(h)); n = (-a[1], a[0])
        con, dk, lt, bf, bs = mp.game_table(at(o['x'], o['y']), a, n)
        lay = '20_Furniture::Game tables'
        add(lay, con, mp.CONCRETE, 'table', 'scan position'); add(lay, dk, (36, 104, 66), 'board dark squares'); add(lay, lt, (236, 232, 220), 'board light squares')
        add(lay, bf, mp.FRAME_IRON, 'bench frames'); add(lay, bs, (150, 112, 82), 'bench slats')

edge = LineString(ellipse(lawn_e, grow=0.35, n=720) + [ellipse(lawn_e, grow=0.35, n=720)[0]])
found = [o for o in feat['objects'] if o['kind'].startswith('small object') and edge.distance(Point(o['x'], o['y'])) < 0.35]
pos = sorted(edge.project(Point(o['x'], o['y'])) for o in found)
gaps = np.diff(pos) if len(pos) > 2 else np.array([2.4])
spacing = float(np.median(gaps[(gaps > 0.8) & (gaps < 4)])) if ((gaps > 0.8) & (gaps < 4)).any() else 2.4
spray_side = spray.buffer(1.0)
n_b = int(round(edge.length / spacing))
bollards = [(p.x, p.y) for p in (edge.interpolate(k * edge.length / n_b) for k in range(n_b)) if not spray_side.contains(p)]
add('20_Furniture::Lawn fence', mp.merge([mp.bollard(at(x, y, 0.03)) for x, y in bollards]), mp.BLACK, 'bollards', 'scan spacing', smooth=True)
chain = []
for (x0, y0), (x1, y1) in zip(bollards, bollards[1:] + bollards[:1]):
    if math.hypot(x1 - x0, y1 - y0) < spacing * 1.6:
        p = mp.catenary(at(x0, y0, 0.03 + 0.66), at(x1, y1, 0.03 + 0.66), 0.10)
        chain.append(mp.tube(p, 0.007, 6))
        curves.append(dict(layer='20_Furniture::Lawn fence', pts=[tuple(q) for q in p]))
add('20_Furniture::Lawn fence', mp.merge(chain), mp.BLACK, 'chain', 'catenary between bollards', smooth=True)

fence_lines = planting.boundary.intersection(unary_union([sidewalks, forecourt, edge_band, curb_band]).buffer(0.5))
posts, rails = [], []
for g in getattr(fence_lines, 'geoms', [fence_lines]):
    if not isinstance(g, LineString) or g.length < 1.0:
        continue
    n_p = max(1, int(round(g.length / 1.8)))
    for k in range(n_p + 1):
        p = g.interpolate(k * g.length / n_p)
        posts.append(mp.spear_post(at(p.x, p.y, 0.05)))
    samples = [g.interpolate(t) for t in np.linspace(0, g.length, max(2, int(g.length / 0.8) + 1))]
    for hgt in (0.86, 0.40):
        rails.append(mp.tube([at(q.x, q.y, 0.05 + hgt) for q in samples], 0.014, 8))
add('20_Furniture::Perimeter fence', mp.merge(posts), mp.BLACK, 'fence posts', 'style from the scan keyframes')
add('20_Furniture::Perimeter fence', mp.merge(rails), mp.BLACK, 'fence rails', 'style from the scan keyframes', smooth=True)

lamp = next((o for o in feat['objects'] if o['kind'].startswith('pole') and 0 < o['x'] < 48 and 0 < o['y'] < 41), None)
if lamp:
    post, globe, padp = mp.parks_lamp(at(lamp['x'], lamp['y'], 0.05))
    add('20_Furniture::Lamps (approx height)', post, mp.BLACK, 'lamppost', 'scan position, height approx', smooth=True)
    add('20_Furniture::Lamps (approx height)', globe, (242, 240, 228), 'globe', smooth=True)
    add('20_Furniture::Lamps (approx height)', padp, mp.CONCRETE, 'lamp pad')
sign = min((o for o in feat['objects'] if o['kind'] == 'tall object'), key=lambda o: math.hypot(o['x'] - 31.9, o['y'] - 39.4))
c = at(sign['x'], sign['y'], 0.05)
add('20_Furniture::Signs', mp.merge([mp.frame_box(c, (1, 0), (0, 1), s - 0.04, s + 0.04, -0.04, 0.04, -0.05, 1.70) for s in (-0.6, 0.6)]),
    (120, 92, 60), 'sign posts', 'scan')
add('20_Furniture::Signs', mp.frame_box(c, (1, 0), (0, 1), -0.66, 0.66, -0.02, 0.02, 0.45, 1.65), (28, 72, 48), 'Parks sign panel', 'scan')
cshel = at(48.3, 42.3)
shelter = [mp.frame_box(cshel, (1, 0), (0, 1), -2.1, 2.1, -0.82, 0.82, 2.45, 2.58)]
shelter += [mp.frame_box(cshel, (1, 0), (0, 1), s, s + 0.07, d, d + 0.07, 0, 2.45) for s in (-2.1, 2.03) for d in (-0.82, 0.75)]
add('20_Furniture::Bus shelter (approx)', mp.merge(shelter), (60, 62, 64), 'shelter frame', 'NYC standard size, approx')
glass = [mp.frame_box(cshel, (1, 0), (0, 1), -2.03, 2.03, 0.76, 0.785, 0.15, 2.42)] + \
        [mp.frame_box(cshel, (1, 0), (0, 1), s, s + 0.025, -0.75, 0.75, 0.15, 2.42) for s in (-2.08, 2.055)]
add('20_Furniture::Bus shelter (approx)', mp.merge(glass), (180, 205, 220, 110), 'shelter glass')
add('20_Furniture::Spray pad', mp.revolve([(0.25, 0.0), (0.25, 0.012), (0.0, 0.012)], at(axis_u, pcy, -0.02), 24), (60, 62, 66), 'drain', 'scan', smooth=True)

# ------------------------------------------------------------------ trees
for i, t in enumerate(trees):
    x, y = float(t['x_m']), float(t['y_m'])
    off = 0.05 if planting.contains(Point(x, y)) else -0.04 if pits.contains(Point(x, y)) else 0.0
    bark, leaves, col = mp.tree(x, y, Tp(x, y) + off, t['species'], float(t['dbh_in'] or 4), float(t['height_m_est']), float(t['crown_d_m_est']), seed=1000 + i)
    if off == 0.05:   # mulch ring at the trunk
        ring = Point(x, y).buffer(float(np.clip(0.5 + float(t['dbh_in'] or 4) * 0.03, 0.7, 1.4)), 12).intersection(planting)
        for p in polys(ring):
            add('10_Ground::Mulch rings', mp.drape(p, T, 0.065, bottom=0.05, grid=1.5), (86, 68, 50), 'mulch ring', 'around park trees')
    lay = '30_Trees::Park trees' if t['in_park'] == 'True' else '30_Trees::Street trees'
    nm = f"{t['species']} DBH {float(t['dbh_in'] or 0):.0f} in"
    add(lay, bark, (96, 76, 58), nm + ' trunk', 'NYC Forestry; form from species, size from DBH', smooth=True)
    add(lay, leaves, col, nm + ' crown', 'NYC Forestry; crown estimated from DBH', smooth=True)

# ------------------------------------------------------------------ buildings
gdb = D('data', 'nyc3d', 'DA_WISE_Multipatch', 'DA10_3D_Buildings_Multipatch.gdb')
to2263 = pyproj.Transformer.from_crs('EPSG:4326', 'EPSG:2263', always_xy=True)
to4326 = pyproj.Transformer.from_crs('EPSG:2263', 'EPSG:4326', always_xy=True)
bx = [to2263.transform(-73.9500, 40.7420), to2263.transform(-73.9370, 40.7510)]
meta, fid, g3, fld = pyogrio.raw.read(gdb, bbox=(bx[0][0], bx[0][1], bx[1][0], bx[1][1]))
model3d = {}
for b_, g in zip(fld[0], g3):
    model3d.setdefault(str(b_), []).append(g)


def lod2_faces(blobs):
    """Multipatch faces -> list of ((V, F), is_roof, z_min) in park coordinates."""
    out = []
    for blob in blobs:
        geom = wkb.loads(blob)
        for face in getattr(geom, 'geoms', [geom]):
            rings = [np.array(face.exterior.coords)] + [np.array(h.coords) for h in face.interiors]
            allp = np.vstack(rings)
            lon, lat = to4326.transform(allp[:, 0], allp[:, 1])
            P = np.column_stack([np.array([uv(a_, b_) for a_, b_ in zip(lon, lat)]), allp[:, 2] * 0.3048 - GRADE])
            ring0 = P[:len(rings[0])]; c0 = ring0.mean(0)
            nrm = sum(np.cross(ring0[i] - c0, ring0[i + 1] - c0) for i in range(len(ring0) - 1))
            if np.linalg.norm(nrm) < 1e-9:
                continue
            nrm = nrm / np.linalg.norm(nrm)
            ax = np.cross(nrm, [0, 0, 1.0]) if abs(nrm[2]) < 0.9 else np.cross(nrm, [1.0, 0, 0]); ax /= np.linalg.norm(ax); ay = np.cross(nrm, ax)
            q = np.column_stack([(P - c0) @ ax, (P - c0) @ ay])
            k, prs = 0, []
            for rr in rings:
                prs.append([tuple(v) for v in q[k:k + len(rr)]]); k += len(rr)
            p2 = Polygon(prs[0], prs[1:])
            if not p2.is_valid:
                p2 = p2.buffer(0)
            for piece in polys(p2):
                pts2, tri, _ = mp.triangulate(piece)
                if not len(tri):
                    continue
                W = c0 + pts2[:, :1] * ax + pts2[:, 1:2] * ay
                if np.dot(np.cross(W[tri[:, 1]] - W[tri[:, 0]], W[tri[:, 2]] - W[tri[:, 0]]).sum(0), nrm) < 0:
                    tri = tri[:, [0, 2, 1]]
                out.append([W, tri, nrm])
    if not out:
        return []
    # multipatch rings are not consistently wound. Horizontal faces at the building's base face down and every other
    # horizontal face up; a wall faces the side where a probe just off it is outside the volume under the roofs
    zb = min(W[:, 2].min() for W, _, _ in out)
    roofs_xy = []
    for i, (W, tri, nrm) in enumerate(out):
        if abs(nrm[2]) > 0.5:
            want = -1.0 if W[:, 2].max() < zb + 0.3 else 1.0
            if nrm[2] * want < 0:
                out[i] = [W, tri[:, [0, 2, 1]], -nrm]
            if want > 0:
                roofs_xy.append((unary_union([Polygon(W[t][:, :2]) for t in tri if Polygon(W[t][:, :2]).area > 1e-6]), W[:, 2].max()))
    centre = np.vstack([W for W, _, _ in out]).mean(0)
    res = []
    for W, tri, nrm in out:
        if abs(nrm[2]) <= 0.5:
            c = W.mean(0); pr = c + 0.3 * nrm
            under = [z for poly, z in roofs_xy if poly.contains(Point(pr[0], pr[1]))]
            inside = bool(under) and max(under) > pr[2]
            if inside or (not roofs_xy and np.dot(nrm, c - centre) < 0):
                nrm = -nrm; tri = tri[:, [0, 2, 1]]
        res.append(((W, tri), nrm[2] > 0.5, W[:, 2].min(), W[:, 2].max(), nrm[2]))
    return res


n_lod2 = n_lod1 = 0
bldg_plan = {}                               # BIN -> plan polygon, for the website's fade test
z_entry = z_stair + N_STEPS * RISE
gaps = []
GLASS_TOWER, BANDS = (128, 150, 164), (206, 210, 212)
for b in footprints:
    if b['h'] <= 0:
        continue
    court = b['bin'] == '4000698'
    name = f"BIN {b['bin']}"
    if b['year'] < 2015 and b['bin'] in model3d:
        faces = lod2_faces(model3d[b['bin']])
        if not faces:
            continue
        bottom = unary_union([Polygon(W[t][:, :2]) for (W, tri), roof, z0, z1, nz in faces if nz < -0.5 for t in tri if Polygon(W[t][:, :2]).area > 1e-6])
        # the current footprint can run past the 2014 walls: fill narrow strips like that with ground
        gap = b['poly'].difference(bottom.buffer(0.02)).intersection(EXTENT)
        gaps += [(g, court) for g in polys(gap) if g.buffer(-1.0).is_empty]
        bldg_plan[b['bin']] = bottom if not bottom.is_empty else b['poly']
        if court:
            massing, cparts = courthouse.build(faces, axis_u, FACADE_V, z_entry)
            lay = '40_Buildings::Courthouse (LOD2)'
            add(lay, mp.merge(massing['walls']), courthouse.BRICK, name + ' walls', 'NYC 3D Building Model (2014)')
            add(lay, mp.merge(massing['roofs']), (150, 144, 138), name + ' roofs', 'NYC 3D Building Model (2014)')
            for part, col, vf, smooth in cparts:
                roofpart = part in ('copper roof', 'mansard roof')
                add('40_Buildings::Courthouse roofs (approx)' if roofpart else '40_Buildings::Courthouse facade (approx)', vf, col,
                    name + ' ' + part, 'from photos (Wikimedia Commons 2018-2026), on the 2014 survey massing', smooth=smooth,
                    rough=0.3 if part == 'windows' else 0.55 if part == 'copper roof' else 0.9)
        else:
            wall = [vf for vf, roof, z0, z1, nz in faces if not roof]
            roof = [vf for vf, roof, z0, z1, nz in faces if roof]
            glass = b['bin'] == '4307108'          # One Court Square: green glass curtain wall
            shade = 204 + int(b['bin'][-2:]) % 5 * 4
            col_w = (98, 140, 134) if glass else (shade, shade - 2, shade - 6)
            add('40_Buildings::Context (LOD2, 2014 survey)', mp.merge(wall), col_w, name + ' walls', 'NYC 3D Building Model (2014)', rough=0.35 if glass else 0.9)
            add('40_Buildings::Context (LOD2, 2014 survey)', mp.merge(roof), (190, 190, 196), name + ' roofs', 'NYC 3D Building Model (2014)')
        n_lod2 += 1
    else:
        z0 = b['ground'] - GRADE
        zb = min(float(T(*np.array(b['poly'].exterior.coords).T).min()), z0) - 0.3
        for p in polys(b['poly']):
            p = orient(p, 1.0)
            add('40_Buildings::Context (LOD1, built 2015 or later)', mp.prism(p, zb, z0 + b['h']), GLASS_TOWER, name,
                f'NYC footprint extruded to roof {b["h"]:.1f} m (year {b["year"]})', rough=0.35)
            edge = Polygon(p.exterior.coords).buffer(0.06, join_style=2).difference(Polygon(p.exterior.coords))
            if b['h'] > 12:   # floor slabs every 3.2 m, so the glass towers read at their scale
                add('40_Buildings::Context (LOD1, built 2015 or later)',
                    mp.merge([mp.prism(edge, z, z + 0.4) for z in np.arange(z0 + 4.4, z0 + b['h'] - 1.0, 3.2)]), BANDS, name + ' floor bands',
                    'generic 3.2 m storeys, not surveyed')
        bldg_plan[b['bin']] = b['poly']
        n_lod1 += 1
for g, court in gaps:
    add('10_Ground::Footprint gaps', mp.drape(g, T, 0.0, grid=1.5), (214, 208, 196) if court else (206, 204, 196), 'ground between footprint and 2014 walls',
        'NYC footprint minus the 2014 survey walls')
print(f'buildings: {n_lod2} LOD2 from the 2014 model, {n_lod1} extruded (built 2015+ or missing from it)')


# ------------------------------------------------------------------ reference curves + labels
def ring_curve(layer, pts, z):
    curves.append(dict(layer=layer, pts=[(x, y, z) for x, y in pts] + [(pts[0][0], pts[0][1], z)]))


ring_curve('00_Reference::Property line', [(x, y) for x, y in list(park.exterior.coords)[:-1]], 0.3)
for g in [lawn, egg, spray, paving, planting]:
    for part in polys(g):
        ring_curve('00_Reference::Zone outlines (flat, z 0.3)', list(part.exterior.coords)[:-1], 0.3)
t = math.radians(90 + sym['tilt_deg'])
curves.append(dict(layer='00_Reference::Symmetry axis', pts=[(axis_u - 22 * math.cos(t), sym['axis_v'] - 22 * math.sin(t), 0.35),
                                                           (axis_u + 18 * math.cos(t), sym['axis_v'] + 18 * math.sin(t), 0.35)]))
nx, ny = NORTH; base = (-35.0, 70.0)
curves.append(dict(layer='00_Reference::North arrow', pts=[(base[0], base[1], 1), (base[0] + 8 * nx, base[1] + 8 * ny, 1),
                                                         (base[0] + 8 * nx - 1.5 * (nx + ny * .5), base[1] + 8 * ny - 1.5 * (ny - nx * .5), 1)]))
dots.append(dict(layer='00_Reference::North arrow', text='N (true)', x=base[0] + 9 * nx, y=base[1] + 9 * ny, z=1))
for x, y, z in zip(gx, gy, gz):
    if EXTENT.contains(Point(x, y)):
        dots.append(dict(layer='00_Reference::Spot elevations (NAVD88)', text=f'{z + GRADE:.2f}', x=x, y=y, z=z))
for text, x, y in [('Central lawn', *lawn_c), ('Spray pad', axis_u, 8.2), ('Game tables', 17.2, 28.6), ('Bistro area', 48.0, 21.0),
                   ('Jackson Ave', 20, 50), ('Thomson Ave', 63, 25), ('Court Sq W', -8, 20), ('Long Island City Courthouse', 31, -30)]:
    dots.append(dict(layer='90_Annotation', text=text, x=x, y=y, z=Tp(x, y) + 1.5))

LAYERS = {'00_Reference': (90, 90, 90), '10_Ground': (150, 150, 150), '20_Furniture': (60, 60, 60), '30_Trees': (70, 120, 60),
          '40_Buildings': (200, 200, 205), '90_Annotation': (0, 0, 0)}
for o in objs:
    LAYERS.setdefault(o['layer'], o['color'][:3])
for c_ in curves + dots:
    LAYERS.setdefault(c_['layer'], (60, 60, 60))


# ------------------------------------------------------------------ write .3dm (meshes, curves, dots)
def write_3dm(path):
    f = r.File3dm()
    f.Settings.ModelUnitSystem = r.UnitSystem.Meters
    f.Settings.ModelAbsoluteTolerance = 0.001
    ea = f.Settings.EarthAnchorPoint
    ea.EarthBasepointLatitude, ea.EarthBasepointLongitude, ea.EarthBasepointElevation = ORIGIN_LL[1], ORIGIN_LL[0], GRADE
    ea.ModelBasePoint = r.Point3d(0, 0, 0); ea.ModelNorth = r.Vector3d(NORTH[0], NORTH[1], 0); ea.ModelEast = r.Vector3d(EAST[0], EAST[1], 0)
    ea.Name = 'Court Square Park, park frame origin (Court Sq W x courthouse forecourt corner)'
    f.Settings.EarthAnchorPoint = ea
    index = {}
    for full in sorted(LAYERS, key=lambda s: (s.count('::'), s)):
        col = LAYERS[full]
        lay = r.Layer(); lay.Name = full.split('::')[-1]; lay.Color = (*col[:3], 255)
        if '::' in full:
            lay.ParentLayerId = f.Layers.FindIndex(index[full.rsplit('::', 1)[0]]).Id
        index[full] = f.Layers.Add(lay)

    def attrs(layer, color=None, name='', src=''):
        at = r.ObjectAttributes(); at.LayerIndex = index[layer]; at.Name = name
        if color:
            at.ObjectColor = (*color[:3], 255); at.ColorSource = r.ObjectColorSource.ColorFromObject
        if src:
            at.SetUserString('source', src)
        return at

    for o in objs:
        V, F = o['V'], o['F']
        if not o['smooth']:          # unweld so hard edges render crisp
            V = V[F].reshape(-1, 3); F = np.arange(len(V)).reshape(-1, 3)
        m = r.Mesh()
        for x, y, z in V.tolist():
            m.Vertices.Add(x, y, z)
        for a_, b_, c_ in F.tolist():
            m.Faces.AddFace(a_, b_, c_)
        m.Normals.ComputeNormals()
        f.Objects.AddMesh(m, attrs(o['layer'], o['color'], o['name'], o['src']))
    for c_ in curves:
        pl = r.Point3dList()
        for x, y, z in c_['pts']:
            pl.Add(float(x), float(y), float(z))
        f.Objects.AddCurve(r.PolylineCurve(pl), attrs(c_['layer']))
    for d in dots:
        f.Objects.AddTextDot(d['text'], r.Point3d(float(d['x']), float(d['y']), float(d['z'])), attrs(d['layer']))
    f.Write(path, 8)


write_3dm(D('model', 'court_square_park_LOD3.3dm'))
# buildings keep their own materials (bldg:<BIN> ...) so a viewer can fade one building at a time
bin_of = lambda o: o['name'].split()[1] if o['name'].startswith('BIN ') else None
groups = [dict(V=o['V'], F=o['F'], color=o['color'], smooth=o['smooth'], rough=o['rough'],
               name=(f"bldg:{bin_of(o)} " if bin_of(o) else '') + o['layer'].split('::')[-1]
               + (' facade bands' if o['name'].endswith('floor bands') else '')) for o in objs]
tri_all = write_glb(D('model', 'court_square_park_LOD3_preview.glb'), groups, 'court-square-park scripts/build_model.py')
tri_web = write_glb(D('model', 'court_square_park_LOD3_web.glb'), groups, 'court-square-park scripts/build_model.py (website copy)', quantize=True)
fade = {}
for o in objs:
    k = bin_of(o)
    if k in bldg_plan:
        z = o['V'][:, 2]; lo, hi = fade.get(k, (z.min(), z.max()))
        fade[k] = (min(lo, z.min()), max(hi, z.max()))
rings = lambda g: [[[round(x, 2), round(-y, 2)] for x, y in list(p.exterior.coords)[:-1]] for p in polys(g)]
json.dump(dict(frame='glTF: x = u, y = up, z = -v (metres)', buildings={k: dict(rings=rings(bldg_plan[k]), y0=round(float(lo), 2), y1=round(float(hi), 2))
                                                                          for k, (lo, hi) in fade.items()}),
          open(D('model', 'court_square_park_LOD3_web.buildings.json'), 'w'), separators=(',', ':'))
from collections import Counter
cnt = Counter(o['layer'] for o in objs)
for k in sorted(cnt):
    print(f'{cnt[k]:5d}  {k}')
print('objects', len(objs), '| triangles preview', tri_all, 'web', tri_web, '| bollards', len(bollards), 'spacing', round(spacing, 2))
for fn in ('court_square_park_LOD3.3dm', 'court_square_park_LOD3_preview.glb', 'court_square_park_LOD3_web.glb', 'court_square_park_LOD3_web.buildings.json'):
    print(f'{fn}: {os.path.getsize(D("model", fn)) / 1e6:.1f} MB')
