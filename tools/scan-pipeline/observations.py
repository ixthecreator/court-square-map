"""Week 1 field counts (Court_Square_Research.pdf) as fitted 3D points for the site's Map and Model tabs.

Counts are means per snapshot (Fri, Sat, Sun; 4:00-4:20 pm, five snapshots a day) at the NE Jackson Ave entrance.
No GPS was recorded, so each counted person gets a fitted spot in the study area: moving people along the entry
path, the ring path and the Jackson sidewalk, standing people at the entrance edge, seated people on bench seats.
Seeded, so every run gives the same points. Park frame as everywhere here: u along the courthouse edge, v toward
Jackson Ave, meters.

  python3 tools/scan-pipeline/observations.py           # writes data/observations.json
  python3 tools/scan-pipeline/observations.py --embed   # and puts it in index.html (srcdoc, id="observations")
"""
import csv, html, json, math, os, random, re, sys
from shapely.geometry import LineString, Point, Polygon, box, shape

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
D = lambda *p: os.path.join(ROOT, *p)
GEO = json.load(open(D('data', 'scan-georef.json')))
LON0, LAT0 = GEO['origin']; MX, MY = GEO['m_per_deg_lon'], GEO['m_per_deg_lat']
B = math.radians(GEO['x_bearing_deg'])


def to_uv(lon, lat):
    e, n = (lon - LON0) * MX, (lat - LAT0) * MY
    return e * math.sin(B) + n * math.cos(B), -e * math.cos(B) + n * math.sin(B)


def to_ll(u, v):
    return LON0 + (u * math.sin(B) - v * math.cos(B)) / MX, LAT0 + (u * math.cos(B) + v * math.sin(B)) / MY


def bearing(a):
    """Park-frame direction (degrees from +u toward +v) -> compass bearing."""
    du, dv = math.cos(math.radians(a)), math.sin(math.radians(a))
    return math.degrees(math.atan2(du * math.sin(B) - dv * math.cos(B), du * math.cos(B) + dv * math.sin(B))) % 360


half_up = lambda x: int(math.floor(x + 0.5))

# ------------------------------------------------------------------ study area and the surfaces people use
STUDY = box(31, 24, 53, 45)                       # NE Jackson Ave entrance, adjacent seating and a short path
NE_PATH = Polygon([(40.9, 34.6), (42.3, 37.6), (41.8, 42.6), (36.8, 42.6), (38.2, 37.8), (38.4, 36.1)])  # build_model.py
BISTRO = box(44.5, 16.4, 53.0, 25.8)                  # bistro plaza, build_model.py
MOUTH, JUNCTION = (39.3, 41.4), (39.65, 35.4)     # entry path at the sidewalk and where it meets the ring
detail = {f['properties']['kind']: f for f in json.load(open(D('data', 'park-detail.geojson')))['features']}
uv_poly = lambda f: Polygon([to_uv(*c) for c in f['geometry']['coordinates'][0]])
LAWN = uv_poly(detail['lawn'])
RING = uv_poly(detail['ring-path'])               # outer edge; the path is 2.4 m wide
ring_mid = RING.buffer(-1.2).exterior.intersection(STUDY)
RING_MID = max(getattr(ring_mid, 'geoms', [ring_mid]), key=lambda g: g.length)
ROUTES = {   # name: (centre line, half width, share of moving people)
    'path': (LineString([(39.3, 42.0), (40.2, 37.7), JUNCTION]), 0.8, 0.5),
    'ring': (RING_MID, 0.7, 0.3),
    'sidewalk': (LineString([(31, 41.6), (42, 41.7), (46, 42.6), (50, 43.6), (52.6, 44.3)]), 0.3, 0.2),
}
BENCHES = []                                      # (u, v, axis degrees, seats)
for r in csv.DictReader(open(D('data', 'modeling', 'scan_objects.csv'))):
    if r['kind'] == 'bench' and STUDY.contains(Point(float(r['x']), float(r['y']))):
        BENCHES.append((float(r['x']), float(r['y']), float(r['heading_deg']), 3 if float(r['length_m']) > 2.2 else 2))
BENCHES.sort(key=lambda b: math.dist(b[:2], MOUTH))


def seats(b):
    u, v, a, n = b; du, dv = math.cos(math.radians(a)), math.sin(math.radians(a))
    return [(u + du * 0.8 * (k - (n - 1) / 2), v + dv * 0.8 * (k - (n - 1) / 2)) for k in range(n)]


# ------------------------------------------------------------------ placement
def place_day(i, row, rng):
    pts = []
    free = lambda p, gap=0.7: STUDY.contains(Point(p)) and all(math.dist(p, q['uv']) >= gap for q in pts)

    # seated: benches nearest the entrance first, alternating a pair and a single
    n, k, pair = half_up(float(row['seated'])), 0, rng.random() < 0.5
    for b in BENCHES:
        if k >= n:
            break
        s = seats(b); take = min(2 if pair else 1, n - k)
        for p in (s[:2] if take == 2 else [s[len(s) // 2]]):
            pts.append(dict(cat='seated', uv=p, a=b[2], at='bistro bench' if BISTRO.contains(Point(b[:2])) else "World's Fair bench")); k += 1
        pair = not pair
    assert k == n, f"{row['day']}: not enough bench seats for {n}"

    # standing: either side of the entry path mouth first, then at the ring junction
    n = half_up(float(row['standing']))
    for j in range(n):
        for _ in range(400):
            if j < 3:
                side = 1 if j % 2 == 0 else -1
                p = (MOUTH[0] + side * rng.uniform(1.4, 2.3), MOUTH[1] - rng.uniform(0.3, 1.6))
                ok = NE_PATH.buffer(0.2).contains(Point(p))
            else:
                t = rng.uniform(0, 2 * math.pi); r = rng.uniform(1.3, 2.2)
                p = (JUNCTION[0] + r * math.cos(t), JUNCTION[1] + r * math.sin(t))
                ok = not LAWN.buffer(0.2).contains(Point(p))
            if ok and free(p):
                pts.append(dict(cat='standing', uv=p, a=-90.0, at='entrance edge' if j < 3 else 'ring path junction')); break
        else:
            raise RuntimeError(f"{row['day']}: no room for standing person {j}")

    # moving: along the routes; Friday leans toward the station corner (commuters), the weekend splits evenly
    n, toward = half_up(float(row['moving'])), 0.7 if row['day'] == 'Fri' else 0.5
    names = list(ROUTES); quota = [half_up(n * ROUTES[r][2]) for r in names]
    quota[0] += n - sum(quota)
    for name, q in zip(names, quota):
        line, hw, _ = ROUTES[name]
        heads = [True] * half_up(q * toward) + [False] * (q - half_up(q * toward)); rng.shuffle(heads)
        for head in heads:
            for _ in range(600):
                s = rng.uniform(0.04, 0.96) * line.length
                c, c2 = line.interpolate(s), line.interpolate(min(s + 0.5, line.length))
                c0 = line.interpolate(max(s - 0.5, 0))
                tu, tv = c2.x - c0.x, c2.y - c0.y; L = math.hypot(tu, tv) or 1
                tu, tv = tu / L, tv / L
                off = rng.uniform(-hw, hw)
                p = (c.x - tv * off, c.y + tu * off)
                if name == 'path' and not NE_PATH.contains(Point(p)):
                    continue
                if LAWN.buffer(0.15).contains(Point(p)) or not free(p):
                    continue
                # forward = toward the station corner: out along the path, toward the entry on the ring, +u on the sidewalk
                fwd = {'path': tv > 0, 'ring': (JUNCTION[0] - p[0]) * tu + (JUNCTION[1] - p[1]) * tv > 0, 'sidewalk': tu > 0}[name]
                if head != fwd:
                    tu, tv = -tu, -tv
                at = {'path': 'entry path', 'ring': 'ring path', 'sidewalk': 'Jackson Ave sidewalk'}[name]
                pts.append(dict(cat='moving', uv=p, a=math.degrees(math.atan2(tv, tu)), at=at)); break
            else:
                raise RuntimeError(f"{row['day']}: no room on the {name}")
    return pts


def build():
    days = list(csv.DictReader(open(D('data', 'observations', 'counts.csv'), encoding='utf-8')))
    places = list(csv.DictReader(open(D('data', 'observations', 'places.csv'), encoding='utf-8')))
    people, out_days = [], []
    for i, row in enumerate(days):
        pts = place_day(i, row, random.Random(f"court-square-week1-{row['day']}"))
        tally = {c: sum(p['cat'] == c for p in pts) for c in ('moving', 'standing', 'seated')}
        for c in tally:
            assert tally[c] == half_up(float(row[c])), (row['day'], c)
        seen = {}
        for p in sorted(pts, key=lambda p: ('moving', 'standing', 'seated').index(p['cat'])):
            lon, lat = to_ll(*p['uv']); seen[p['cat']] = seen.get(p['cat'], 0) + 1
            people.append(dict(id=f"{row['day'].lower()}-{p['cat'][:3]}{seen[p['cat']]:02d}", day=i, cat=p['cat'],
                               u=round(p['uv'][0], 2), v=round(p['uv'][1], 2), a=round(p['a'], 1), brg=round(bearing(p['a']), 1),
                               lon=round(lon, 8), lat=round(lat, 8), at=p['at']))
        rec = None
        if row['record_time']:
            rec = dict(time=row['record_time'], moving=int(row['record_moving']), standing=int(row['record_standing']),
                       seated=int(row['record_seated']), behavior=row['behavior'])
        out_days.append(dict(day=row['day'], date=row['date'], question=row['question'], temp_f=int(row['temp_f']),
                             feels_f=int(row['feels_f']), wind_mph=int(row['wind_mph']), sky=row['sky'], note=row['weather_note'],
                             mean=dict(moving=float(row['moving']), standing=float(row['standing']), seated=float(row['seated'])),
                             points=tally, record=rec))
    for d, row in zip(out_days, days):
        pts = [p for p in people if p['day'] == days.index(row)]
        for a in pts:
            gap = min((math.dist((a['u'], a['v']), (b['u'], b['v'])) for b in pts if b is not a), default=9)
            assert gap >= 0.69, (a['id'], gap)
            assert STUDY.contains(Point(a['u'], a['v'])), a['id']
            if a['cat'] == 'seated':
                assert any(math.dist((a['u'], a['v']), s) < 0.02 for b in BENCHES for s in seats(b)), a['id']
    plate = [(31, 24), (50.5, 24), (53, 26.5), (53, 45), (33.5, 45), (31, 42.5)]   # study area with two cut corners
    area = [[round(c, 8) for c in to_ll(u, v)] for u, v in plate]
    pl = []
    for p in places:
        lon, lat = to_ll(float(p['u']), float(p['v']))
        pl.append(dict(id=p['id'], kind=p['kind'], title=p['title'], note=p['note'], u=float(p['u']), v=float(p['v']),
                       z=float(p['z']), lon=round(lon, 8), lat=round(lat, 8)))
    return dict(
        meta=dict(title='Passing & pausing', source='Week 1 Observational Research (Court_Square_Research.pdf, pp. 5-12)',
                  window='4:00-4:20 pm, five snapshots a day', counts='mean people per snapshot; points are the means rounded',
                  positions='fitted by category into the study area; no GPS was recorded', bearing_u_deg=GEO['x_bearing_deg']),
        area=dict(uv=[list(p) for p in plate], ll=area, centre=[42, 34.5]),
        days=out_days, people=people, places=pl)


def embed(obs):
    path = D('index.html'); page = open(path, encoding='utf-8').read()
    m = re.search(r'srcdoc="([^"]*)"', page); doc = html.unescape(m.group(1))
    block = '<script type="application/json" id="observations">' + json.dumps(obs, ensure_ascii=False, separators=(',', ':')) + '</script>'
    old = re.search(r'<script type="application/json" id="observations">.*?</script>', doc, re.S)
    if old:
        doc = doc[:old.start()] + block + doc[old.end():]
    else:
        i = doc.index('</script>', doc.index('id="park-detail"')) + len('</script>')
        doc = doc[:i] + '\n  ' + block + doc[i:]
    open(path, 'w', encoding='utf-8').write(page[:m.start(1)] + html.escape(doc, quote=True) + page[m.end(1):])


if __name__ == '__main__':
    obs = build()
    json.dump(obs, open(D('data', 'observations.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    for d in obs['days']:
        print(f"{d['day']} {d['date']}: mean {d['mean']} -> points {d['points']}")
    print(f"{len(obs['people'])} people, {len(obs['places'])} places, {len(BENCHES)} benches in the study area")
    if '--embed' in sys.argv:
        embed(obs); print('embedded in index.html')
