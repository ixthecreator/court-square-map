"""Export scan/features.json (after symmetrize_scan.py) to DXF and CSV.

Writes model/court_square_scan_features.dxf (same frame as court_square_site_base.dxf) and model/scan_objects.csv.
Mirrored items go on *_MIRRORED layers so they can be toggled.
"""
import csv, json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
feat = json.load(open(os.path.join(ROOT, 'scan', 'features.json')))

L = []
a = lambda *kv: L.extend(str(x) for x in kv)
a(0, 'SECTION', 2, 'HEADER', 9, '$INSUNITS', 70, 6, 0, 'ENDSEC', 0, 'SECTION', 2, 'ENTITIES')


def poly(layer, pts, closed=True):
    a(0, 'POLYLINE', 8, layer, 66, 1, 70, 1 if closed else 0, 10, 0, 20, 0, 30, 0)
    for x, y in (pts[:-1] if closed and tuple(pts[0]) == tuple(pts[-1]) else pts):
        a(0, 'VERTEX', 8, layer, 10, round(x, 3), 20, round(y, 3), 30, 0)
    a(0, 'SEQEND', 8, layer)


def ellipse(e, n=96):
    c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
    return [(e['cx'] + e['a'] * math.cos(t) * c - e['b'] * math.sin(t) * s,
             e['cy'] + e['a'] * math.cos(t) * s + e['b'] * math.sin(t) * c) for t in [2 * math.pi * i / n for i in range(n + 1)]]


def layer_name(kind):
    return 'SCAN_' + ''.join(ch if ch.isalnum() else '_' for ch in kind.upper()).strip('_').replace('__', '_')


poly('SCAN_LAWN_OVAL', ellipse(feat['lawn_oval']))
poly('SCAN_RING_PATH_OUTER', ellipse(feat['ring_outer']))
if feat.get('spray_pad'):
    poly('SCAN_SPRAY_PAD', feat['spray_pad']['hull'])
sym = feat.get('symmetry')
if sym:
    t = math.radians(90 + sym['tilt_deg'])
    poly('SCAN_SYMMETRY_AXIS', [(sym['axis_u'] - 22 * math.cos(t), sym['axis_v'] - 22 * math.sin(t)),
                                (sym['axis_u'] + 18 * math.cos(t), sym['axis_v'] + 18 * math.sin(t))], closed=False)
for o in feat['objects']:
    hd = math.radians(o['heading_deg']); c, s = math.cos(hd), math.sin(hd)
    hl, hw = max(o['length_m'], 0.2) / 2, max(o['width_m'], 0.2) / 2
    corners = [(o['x'] + dx * c - dy * s, o['y'] + dx * s + dy * c) for dx, dy in [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw), (-hl, -hw)]]
    poly(layer_name(o['kind']) + ('_MIRRORED' if o.get('mirrored') else ''), corners)
a(0, 'ENDSEC', 0, 'EOF')
open(os.path.join(ROOT, 'model', 'court_square_scan_features.dxf'), 'w').write('\n'.join(L) + '\n')

with open(os.path.join(ROOT, 'model', 'scan_objects.csv'), 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=['kind', 'mirrored', 'x', 'y', 'length_m', 'width_m', 'height_m', 'heading_deg',
                                       'footprint_m2', 'nearest_db_tree_m', 'species_db'], extrasaction='ignore')
    w.writeheader()
    for o in sorted(feat['objects'], key=lambda o: (o['kind'], bool(o.get('mirrored')), o['x'])):
        w.writerow(dict(o, mirrored=bool(o.get('mirrored'))))
print('exported', len(feat['objects']), 'objects')
