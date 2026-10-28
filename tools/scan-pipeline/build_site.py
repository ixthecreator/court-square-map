"""Build a modeling base for Court Square Park (LIC, Queens) from NYC open data.

Local frame (meters), aligned to the park like the NYC Parks design plan:
  origin = park corner at Court Square West x courthouse forecourt
  +X     = along the courthouse edge toward Thomson Ave (true bearing 62.4 deg)
  +Y     = toward Jackson Ave (true bearing 332.4 deg)
  Z      = elevation in meters, NAVD88 (NYC data is in feet)
True north in this frame points 27.6 deg clockwise from +Y.

Run from the court-square-park folder:  python3 scripts/build_site.py
"""
import csv, json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, 'data', *p)
OUT = os.path.join(ROOT, 'model')
os.makedirs(OUT, exist_ok=True)
FT = 0.3048

LAT0, LON0 = 40.74636, -73.94345
_phi = math.radians(LAT0)
MLAT = 111132.954 - 559.822 * math.cos(2 * _phi) + 1.175 * math.cos(4 * _phi)
MLON = 111412.84 * math.cos(_phi) - 93.5 * math.cos(3 * _phi)
BEARING_X = 62.4
_t = math.radians(BEARING_X)
UX, UY = math.sin(_t), math.cos(_t)
VX, VY = -UY, UX

park_ll = json.load(open(D('parks_property_Q267.geojson')))['features'][0]['geometry']['coordinates'][0][0]
_E = park_ll[4]
EX, EY = (_E[0] - LON0) * MLON, (_E[1] - LAT0) * MLAT


def uv(lon, lat):
    x, y = (lon - LON0) * MLON - EX, (lat - LAT0) * MLAT - EY
    return (round(x * UX + y * UY, 3), round(x * VX + y * VY, 3))


def inside(pt, poly):
    x, y = pt
    c = False
    for i in range(len(poly) - 1):
        (x1, y1), (x2, y2) = poly[i], poly[i + 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def rings(geom):
    t, c = geom['type'], geom['coordinates']
    if t == 'Polygon':
        return [[uv(*p) for p in r] for r in c]
    if t == 'MultiPolygon':
        return [[uv(*p) for p in r] for poly in c for r in poly]
    if t == 'LineString':
        return [[uv(*p) for p in c]]
    if t == 'MultiLineString':
        return [[uv(*p) for p in l] for l in c]
    return []


def area(r):
    return abs(sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))) / 2


PARK = [uv(*p) for p in park_ll]
CLIP = (-90, -110, 150, 170)  # u0, v0, u1, v1 window kept for context


def in_clip(r):
    return any(CLIP[0] <= u <= CLIP[2] and CLIP[1] <= v <= CLIP[3] for u, v in r)


# ---- buildings -------------------------------------------------------------
KNOWN = {
    '4000698': 'Long Island City Courthouse (1874-76, rebuilt 1904-08)',
    '4307108': 'One Court Square (Citigroup Building)',
    '4539937': 'One Court Square podium / plaza building',
    '4619672': 'New tower NE of Thomson Ave',
    '4623812': 'Tower, Thomson Ave / Court Sq East',
    '4620870': 'Tower, Thomson Ave',
}
buildings = []
for f in json.load(open(D('buildings.geojson')))['features']:
    pr = f['properties']
    rs = [r for r in rings(f['geometry']) if in_clip(r)]
    if not rs:
        continue
    h = float(pr.get('height_roof') or 0) * FT
    g = float(pr.get('ground_elevation') or 0) * FT
    buildings.append(dict(bin=pr.get('bin'), name=KNOWN.get(pr.get('bin'), ''), year=pr.get('construction_year'),
                          height_m=round(h, 2), ground_m=round(g, 2), rings=rs))

# ---- trees -----------------------------------------------------------------
def crown_d(dbh_in):
    # rough open-grown estimate for modeling only: crown diameter (m) from DBH (in)
    return round(max(2.0, (1.5 * dbh_in + 5) * FT), 1)


def height_est(dbh_in):
    return round(min(24.0, 3.0 + 0.75 * dbh_in), 1)


trees = []
for t in json.load(open(D('trees_forestry.json'))):
    lon, lat = t['location']['coordinates']
    p = uv(lon, lat)
    if not (CLIP[0] <= p[0] <= CLIP[2] and CLIP[1] <= p[1] <= CLIP[3]):
        continue
    dbh = float(t['dbh']) if t.get('dbh') else 0.0
    sp = t.get('genusspecies', '')
    trees.append(dict(x=p[0], y=p[1], dbh_in=dbh, status=t.get('tpstructure'),
                      species_latin=sp.split(' - ')[0], species=sp.split(' - ')[-1],
                      in_park=inside(p, PARK), crown_d_m=crown_d(dbh), height_est_m=height_est(dbh),
                      updated=(t.get('updateddate') or '')[:10]))
# drop duplicates of the same spot: keep the living record
seen = {}
for t in trees:
    k = (round(t['x'], 1), round(t['y'], 1))
    if k not in seen or (t['status'] == 'Full' and seen[k]['status'] != 'Full'):
        seen[k] = t
trees = sorted(seen.values(), key=lambda t: (not t['in_park'], t['x']))
alive = [t for t in trees if t['status'] == 'Full']

# ---- planimetrics ----------------------------------------------------------
def layer(fn, key=None):
    out = []
    for f in json.load(open(D(fn)))['features']:
        for r in rings(f['geometry']):
            if in_clip(r):
                out.append(r)
    return out

curbs = layer('plan_curbs.geojson')
sidewalks = layer('plan_sidewalk.geojson')
roadbed = layer('plan_roadbed.geojson')
medians = layer('plan_median.geojson')
elev = []
for f in json.load(open(D('plan_elevation_points.geojson')))['features']:
    p = uv(*f['geometry']['coordinates'])
    if CLIP[0] <= p[0] <= CLIP[2] and CLIP[1] <= p[1] <= CLIP[3] and f['properties'].get('elevation'):
        e = float(f['properties']['elevation'])
        if 0 < e < 100:  # ground spot heights only (feet)
            elev.append((p[0], p[1], round(e * FT, 2), e))

# ---- write CSV -------------------------------------------------------------
with open(os.path.join(OUT, 'trees.csv'), 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['x_m', 'y_m', 'in_park', 'status', 'species', 'species_latin', 'dbh_in', 'crown_d_m_est', 'height_m_est', 'record_updated'])
    for t in trees:
        w.writerow([t['x'], t['y'], t['in_park'], t['status'], t['species'], t['species_latin'], t['dbh_in'], t['crown_d_m'], t['height_est_m'], t['updated']])
with open(os.path.join(OUT, 'buildings.csv'), 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['bin', 'name', 'year', 'roof_height_m', 'ground_elev_m', 'footprint_m2', 'centroid_x', 'centroid_y'])
    for b in sorted(buildings, key=lambda b: -b['height_m']):
        r = b['rings'][0]
        w.writerow([b['bin'], b['name'], b['year'], b['height_m'], b['ground_m'], round(area(r)),
                    round(sum(p[0] for p in r) / len(r), 1), round(sum(p[1] for p in r) / len(r), 1)])

# ---- write DXF (R12, meters) -----------------------------------------------
def dxf(path):
    L = []
    a = lambda *kv: L.extend(str(x) for x in kv)
    a(0, 'SECTION', 2, 'HEADER', 9, '$INSUNITS', 70, 6, 0, 'ENDSEC', 0, 'SECTION', 2, 'ENTITIES')

    def poly(layer, pts, z=0.0, closed=True):
        a(0, 'POLYLINE', 8, layer, 66, 1, 70, 1 if closed else 0, 10, 0, 20, 0, 30, z)
        for x, y in (pts[:-1] if closed and pts[0] == pts[-1] else pts):
            a(0, 'VERTEX', 8, layer, 10, x, 20, y, 30, z)
        a(0, 'SEQEND', 8, layer)

    def circle(layer, x, y, r):
        a(0, 'CIRCLE', 8, layer, 10, x, 20, y, 30, 0, 40, r)

    def text(layer, x, y, s, h=1.0):
        a(0, 'TEXT', 8, layer, 10, x, 20, y, 30, 0, 40, h, 1, s)

    poly('PARK_BOUNDARY', PARK)
    for b in buildings:
        for r in b['rings']:
            poly('BUILDINGS', r)
        if b['name']:
            r = b['rings'][0]
            text('LABELS', sum(p[0] for p in r) / len(r), sum(p[1] for p in r) / len(r), f"{b['name']} {b['height_m']}m", 1.5)
    for r in curbs:
        poly('CURB', r, closed=False)
    for r in sidewalks:
        poly('SIDEWALK', r)
    for r in roadbed:
        poly('ROADBED', r)
    for r in medians:
        poly('MEDIAN', r)
    for t in trees:
        lay = ('TREES_PARK' if t['in_park'] else 'TREES_STREET') + ('' if t['status'] == 'Full' else '_REMOVED')
        circle(lay, t['x'], t['y'], 0.15)
        if t['status'] == 'Full':
            circle(lay + '_CANOPY', t['x'], t['y'], t['crown_d_m'] / 2)
    for x, y, m, ft in elev:
        a(0, 'POINT', 8, 'SPOT_ELEV', 10, x, 20, y, 30, m)
        text('SPOT_ELEV', x + 0.3, y + 0.3, f'{m:.2f}', 0.5)
    for s, x, y, rot in [('JACKSON AVE', 10, 52, 0), ('THOMSON AVE', 60, 10, 0), ('COURT SQ W', -14, 10, 0), ('COURTHOUSE', 18, -30, 0)]:
        text('LABELS', x, y, s, 2.0)
    a(0, 'ENDSEC', 0, 'EOF')
    open(path, 'w').write('\n'.join(L) + '\n')

dxf(os.path.join(OUT, 'court_square_site_base.dxf'))

# ---- write OBJ massing (Y-up, meters; ground at 0 = park mean grade) ---------
park_z = [m for x, y, m, ft in elev if inside((x, y), PARK)]
Z0 = round(sum(park_z) / len(park_z), 2) if park_z else 4.5


def obj(path):
    V, F, lines = [], [], []
    def add_prism(name, ring, z0, z1):
        pts = ring[:-1] if ring[0] == ring[-1] else ring
        base = len(V)
        for x, y in pts:
            V.append((x, z0, -y))
        for x, y in pts:
            V.append((x, z1, -y))
        n = len(pts)
        lines.append(f'o {name}')
        lines.extend(f'v {x:.3f} {y:.3f} {z:.3f}' for x, y, z in V[base:])
        lines.append('f ' + ' '.join(str(base + n + i + 1) for i in range(n)))
        lines.append('f ' + ' '.join(str(base + i + 1) for i in reversed(range(n))))
        for i in range(n):
            j = (i + 1) % n
            lines.append(f'f {base+i+1} {base+j+1} {base+n+j+1} {base+n+i+1}')
    for b in buildings:
        if b['height_m'] <= 0:
            continue
        add_prism(f"bldg_{b['bin']}", b['rings'][0], b['ground_m'] - Z0, b['ground_m'] - Z0 + b['height_m'])
    add_prism('park_ground', PARK, -0.15, 0.0)
    open(path, 'w').write('# Court Square Park massing. Y-up, meters. y=0 is park grade (NAVD88 %.2f m)\n' % Z0 + '\n'.join(lines) + '\n')

obj(os.path.join(OUT, 'court_square_massing.obj'))

# ---- JSON for the reference page --------------------------------------------
json.dump(dict(frame=dict(origin='Court Sq W x courthouse corner of park', x_bearing=BEARING_X, north_cw_from_y=27.6, park_grade_navd88_m=Z0),
               park=PARK, buildings=buildings, trees=trees, curbs=curbs, sidewalks=sidewalks, medians=medians,
               elev=elev),
          open(os.path.join(OUT, 'site_local.json'), 'w'))

print('park grade NAVD88 m', Z0, '| buildings', len(buildings), '| trees', len(trees), 'alive', len(alive),
      'in park alive', sum(t['in_park'] for t in alive), '| curbs', len(curbs), 'sidewalks', len(sidewalks), 'elev', len(elev))
