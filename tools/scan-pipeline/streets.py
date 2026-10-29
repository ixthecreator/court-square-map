"""Street detail around the park from NYC open data (park frame: x = u, y = v, z up, meters).

- crosswalks: high-visibility bars between pairs of curb ramps facing each other across the roadbed (DOT pedestrian ramps)
- lane markings from the street centerline (CSCL): double yellow on two-way streets, dashed white between travel lanes
  that run the same way, white parking-lane lines on two-way streets; all stop short of intersections and crosswalks
- traffic signals at the corners of intersections in DOT's signal data (leading pedestrian intervals); pole and head
  positions are approximate
- street lights on the city poles in the small-cell pole registry (not every light pole is listed there)
- DSNY litter baskets and DOT parking meters at their recorded positions
"""
import json, math, os
import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.ops import unary_union
import model_parts as mp

WHITE, YELLOW, POLE, SIGNAL = (236, 236, 228), (232, 188, 58), (52, 60, 56), (30, 32, 30)
PAINT = 0.006            # paint sits this far above the roadbed


def _polys(g):
    return [p for p in getattr(g, 'geoms', [g]) if isinstance(p, Polygon) and p.area > 1e-4]


def _lines(g):
    return [l for l in getattr(g, 'geoms', [g]) if isinstance(l, LineString) and l.length > 0.2]


def paint(poly, T, z_off):
    """Flat marking on the terrain: the polygon triangulated, each corner at T + z_off (markings are small)."""
    parts = []
    for p in _polys(poly):
        pts, tri, _ = mp.triangulate(p)
        if len(tri):
            parts.append((np.column_stack([pts, T(pts[:, 0], pts[:, 1]) + z_off]), tri))
    return mp.merge(parts)


def _ramps(path, uv, area):
    pts = [uv(*f['geometry']['coordinates']) for f in json.load(open(path))['features']]
    return [p for p in pts if area.contains(Point(p))]


def crosswalk_lines(ramps, roadbed):
    """Pairs of ramps that face each other across the roadbed. Each ramp keeps its shortest crossing, plus a second one
    in a clearly different direction (corner ramps serve two crossings); a pair counts when both ends choose it."""
    near = [Point(p).distance(roadbed) < 3.0 for p in ramps]
    picks = []
    for i, p in enumerate(ramps):
        cands = []
        for j, q in enumerate(ramps):
            if i == j or not (near[i] and near[j]):
                continue
            d = math.dist(p, q)
            if not 5.0 < d < 32.0:
                continue
            seg = LineString([p, q])
            if seg.intersection(roadbed).length / d < 0.6:
                continue
            cands.append((d, j, math.atan2(q[1] - p[1], q[0] - p[0])))
        cands.sort()
        mine = cands[:1]
        for c in cands[1:]:
            ang = abs((c[2] - mine[0][2] + math.pi) % (2 * math.pi) - math.pi)
            if ang > math.radians(50) and c[0] < mine[0][0] * 1.6:
                mine.append(c); break
        picks.append({j for _, j, _ in mine})
    return [LineString([ramps[i], ramps[j]]) for i in range(len(ramps)) for j in picks[i] if i < j and i in picks[j]]


def crosswalk_bars(line, roadbed, width=3.0, bar=0.6, gap=0.6):
    """NYC high-visibility crosswalk: bars parallel to traffic, 0.6 m wide with 0.6 m gaps, across a 3 m wide walk."""
    (x0, y0), (x1, y1) = line.coords[0], line.coords[-1]
    L = line.length; a = np.array([x1 - x0, y1 - y0]) / L; n = np.array([-a[1], a[0]])
    bars = []
    for s in np.arange(0.3, L - 0.3, bar + gap):
        c = np.array([x0, y0]) + a * s
        q = [c - n * width / 2, c - n * width / 2 + a * bar, c + n * width / 2 + a * bar, c + n * width / 2]
        bars.append(Polygon([tuple(v) for v in q]))
    return unary_union(bars).intersection(roadbed)


def _centerlines(path, uv, area):
    out = []
    for f in json.load(open(path))['features']:
        g, p = f['geometry'], f['properties']
        if p.get('rw_type') not in ('1', 1):
            continue
        for coords in (g['coordinates'] if g['type'] == 'MultiLineString' else [g['coordinates']]):
            line = LineString([uv(*c) for c in coords])
            if line.intersects(area):
                out.append(dict(line=line, dir=p.get('trafdir'), travel=int(p.get('number_travel_lanes') or 0),
                                park=int(p.get('number_park_lanes') or 0), width=float(p.get('streetwidth') or 0) * 0.3048,
                                name=p.get('stname_label') or ''))
    return out


def _intersections(segs):
    """Zones where streets meet: centerline end points shared by two or more street names (or three or more segments)."""
    ends = []
    for s in segs:
        for c in (s['line'].coords[0], s['line'].coords[-1]):
            ends.append((c, s))
    zones = []
    for c, s in ends:
        meet = [t for d, t in ends if math.dist(c, d) < 1.0]
        if len(meet) >= 3 or len({t['name'] for t in meet}) >= 2:
            r = 0.5 * max(t['width'] for t in meet) + 1.5
            zones.append(Point(c).buffer(r, 12))
    return unary_union(zones) if zones else Polygon()


def _offset(line, d):
    try:
        g = line.offset_curve(d)
    except Exception:
        return []
    return _lines(g)


def _dashes(line, dash=3.0, gap=9.0):
    out, s = [], 0.0
    while s < line.length:
        e = min(s + dash, line.length)
        seg = LineString([line.interpolate(t).coords[0] for t in np.linspace(s, e, 3)])
        if seg.length > 0.3:
            out.append(seg)
        s += dash + gap
    return out


def lane_lines(segs, keep):
    """-> (yellow lines, white lines) as LineStrings clipped to `keep`."""
    yellow, white = [], []
    for s in segs:
        L, W = s['line'], s['width']
        if s['dir'] == 'TW':
            for d in (-0.1, 0.1):
                yellow += _offset(L, d)
            per = max(1, s['travel'] // 2)
            for k in range(1, per):
                for sg in (-1, 1):
                    for l in _offset(L, sg * 3.3 * k):
                        white += _dashes(l)
            if s['park'] and W > 0:
                for sg in (-1, 1):
                    white += _offset(L, sg * (W / 2 - 2.4))
        elif s['dir'] in ('FT', 'TF') and s['travel'] > 1 and W > 0:
            lane = (W - 2.4 * s['park']) / s['travel']
            first = -W / 2 + (2.4 if s['park'] else 0)       # parking side unknown: lanes laid out from one curb
            for k in range(1, s['travel']):
                for l in _offset(L, first + lane * k):
                    white += _dashes(l)
    clip = lambda ls: [g for l in ls for g in _lines(l.intersection(keep))]
    return clip(yellow), clip(white)


def street_light(c, toward):
    """NYC octagonal pole (about 9 m) with a davit arm and cobra-head luminaire, arm pointing at the street."""
    x, y, z = c; a = np.array(toward, float); a /= np.linalg.norm(a) or 1
    pole = mp.revolve([(0.13, 0), (0.12, 0.6), (0.09, 8.6), (0.07, 9.0)], (x, y, z), 8)
    arm_pts = [(x, y, z + 8.4)] + [(x + a[0] * r, y + a[1] * r, z + 8.4 + 0.6 * math.sin(math.pi * r / 4.8)) for r in np.linspace(0.4, 2.4, 6)]
    arm = mp.tube(arm_pts, 0.045, 6)
    hx, hy = x + a[0] * 2.6, y + a[1] * 2.6
    head = mp.frame_box((hx, hy, z + 8.55), a, (-a[1], a[0]), -0.45, 0.35, -0.2, 0.2, -0.12, 0.05)
    base = mp.revolve([(0.22, 0), (0.22, 0.5), (0.13, 0.6)], (x, y, z), 8)
    return mp.merge([pole, arm, base]), head


def signal_pole(c, toward):
    """Pedestrian/traffic signal pole: 4.5 m post, a vehicle head facing the street and a pedestrian head."""
    x, y, z = c; a = np.array(toward, float); a /= np.linalg.norm(a) or 1; n = (-a[1], a[0])
    post = mp.revolve([(0.1, 0), (0.09, 4.5)], (x, y, z), 8)
    veh = mp.frame_box((x, y, z), a, n, 0.12, 0.42, -0.17, 0.17, 3.1, 4.2)
    ped = mp.frame_box((x, y, z), n, (-a[0], -a[1]), 0.12, 0.47, -0.17, 0.17, 2.4, 2.8)
    return post, mp.merge([veh, ped])


def litter_basket(c, kind):
    x, y, z = c
    if 'Wire' in kind:      # DSNY wire basket
        return mp.revolve([(0.0, 0), (0.24, 0.02), (0.29, 0.85), (0.3, 0.88), (0.0, 0.88)], (x, y, z), 12), (40, 92, 60)
    return mp.revolve([(0.0, 0), (0.3, 0.0), (0.3, 1.0), (0.33, 1.05), (0.2, 1.12), (0.0, 1.12)], (x, y, z), 12), (34, 36, 36)


def parking_meter(c, toward):
    x, y, z = c; a = np.array(toward, float); a /= np.linalg.norm(a) or 1
    return mp.merge([mp.frame_box((x, y, z), a, (-a[1], a[0]), -0.06, 0.06, -0.06, 0.06, 0, 1.1),
                     mp.frame_box((x, y, z), a, (-a[1], a[0]), -0.15, 0.15, -0.12, 0.12, 1.1, 1.75)])


def build(data_dir, uv, T, area, roadbed, medians, sidewalks):
    """-> list of (layer, name, colour, (V, F), smooth, source)."""
    D = lambda f: os.path.join(data_dir, f)
    out = []
    road_z = -0.15 + PAINT
    toward_road = lambda p: (lambda q: (q.x - p[0], q.y - p[1]))(roadbed.boundary.interpolate(roadbed.boundary.project(Point(p))))

    ramps = _ramps(D('street_ramps.geojson'), uv, area.buffer(8))
    cross = crosswalk_lines(ramps, roadbed)
    bars = unary_union([crosswalk_bars(l, roadbed) for l in cross]) if cross else Polygon()
    out.append(('50_Street::Crosswalks', 'crosswalk bars', WHITE, paint(bars, T, road_z), False,
                f'{len(cross)} crossings between facing DOT pedestrian ramps'))
    walk_zone = unary_union([l.buffer(2.5, cap_style=2) for l in cross]) if cross else Polygon()

    segs = _centerlines(D('street_centerlines.geojson'), uv, area)
    keep = roadbed.buffer(-0.4).difference(medians.buffer(0.3)).difference(_intersections(segs)).difference(walk_zone).intersection(area)
    yellow, white = lane_lines(segs, keep)
    strip = lambda ls, w: mp.merge([mp.drape_strip(l, T, road_z, w) for l in ls])
    out.append(('50_Street::Lane markings', 'double yellow', YELLOW, strip(yellow, 0.1), False, 'NYC street centerline: two-way segments'))
    out.append(('50_Street::Lane markings', 'lane and parking lines', WHITE, strip(white, 0.1), False, 'NYC street centerline: travel and parking lanes'))

    # traffic signals: one pole per sidewalk corner near each signalised intersection
    posts, heads = [], []
    for f in json.load(open(D('street_lpi.json'))):
        c = uv(*f['the_geom']['coordinates'])
        if not area.contains(Point(c)):
            continue
        corner = [p for p in ramps if math.dist(p, c) < 28 and sidewalks.buffer(0.5).contains(Point(p))]
        groups = []
        for p in corner:
            for g in groups:
                if math.dist(p, g[0]) < 5:
                    g.append(p); break
            else:
                groups.append([p])
        for g in groups:
            m = np.mean(g, axis=0); t = toward_road(m); tn = np.hypot(*t) or 1
            spot = (m[0] - t[0] / tn * 1.2, m[1] - t[1] / tn * 1.2)
            if not sidewalks.contains(Point(spot)):
                continue
            p_, h_ = signal_pole((spot[0], spot[1], float(T(*spot)[0])), t)
            posts.append(p_); heads.append(h_)
    out.append(('50_Street::Traffic signals (approx)', 'signal poles', POLE, mp.merge(posts), True, 'DOT signalised intersections; corners from ramp positions'))
    out.append(('50_Street::Traffic signals (approx)', 'signal heads', SIGNAL, mp.merge(heads), False, 'DOT signalised intersections'))

    # street lights on registered city poles
    poles, lights = [], []
    for x in json.load(open(D('street_poles.json'))):
        if x.get('pole_type') != 'CITY':
            continue
        p = uv(float(x['longitude']), float(x['latitude']))
        if not area.contains(Point(p)):
            continue
        pl, hd = street_light((p[0], p[1], float(T(*p)[0])), toward_road(p))
        poles.append(pl); lights.append(hd)
    out.append(('50_Street::Street lights', 'light poles', POLE, mp.merge(poles), True, 'city poles in the DOT small-cell pole registry'))
    out.append(('50_Street::Street lights', 'luminaires', (200, 202, 196), mp.merge(lights), False, 'cobra-head luminaire, generic'))

    by_col = {}
    for x in json.load(open(D('street_litter_baskets.json'))):
        p = uv(float(x['longitude']), float(x['latitude']))
        if area.contains(Point(p)):
            vf, col = litter_basket((p[0], p[1], float(T(*p)[0])), x.get('baskettype') or '')
            by_col.setdefault(col, []).append(vf)
    for col, parts in by_col.items():
        out.append(('50_Street::Litter baskets', 'litter baskets', col, mp.merge(parts), True, 'DSNY litter basket inventory'))
    meters = []
    for x in json.load(open(D('street_meters.json'))):
        p = uv(float(x['long']), float(x['lat']))
        if area.contains(Point(p)):
            meters.append(parking_meter((p[0], p[1], float(T(*p)[0])), toward_road(p)))
    out.append(('50_Street::Parking meters', 'muni-meters', (70, 74, 78), mp.merge(meters), False, 'DOT parking meter locations'))
    stats = dict(crossings=len(cross), signals=len(posts), lights=len(poles), baskets=sum(len(v) for v in by_col.values()), meters=len(meters),
                 yellow=round(sum(l.length for l in yellow)), white=round(sum(l.length for l in white)))
    return out, stats
