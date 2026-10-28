"""Remove transient objects and specks from the fused scan mesh.

- anything standing on the roadbed (parked cars, traffic): more than 25 cm above the local road surface,
  or more than 45 cm within 35 cm of the curb line, where the curb itself stands
- pieces left floating over the road (car remnants) and connected pieces under 300 triangles

Usage: python scripts/clean_scan.py      (needs open3d, shapely)
Writes scan/court_square_scan_clean.ply and prints what was removed.
"""
import json, os, sys
import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw
from shapely.geometry import Polygon
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parkframe import ROOT, polygons_uv

S = lambda *p: os.path.join(ROOT, 'scan', *p)
mesh = o3d.io.read_triangle_mesh(S('court_square_scan_mesh.ply'))
V = np.asarray(mesh.vertices); F = np.asarray(mesh.triangles)
cent = V[F].mean(1)

# rasterise the NYC roadbed at 5 cm
PX, U0, V0, U1, V1 = 0.05, -20, -20, 70, 60
W, H = int((U1 - U0) / PX), int((V1 - V0) / PX)
to_px = lambda p: ((p[0] - U0) / PX, (V1 - p[1]) / PX)
# roadbed interior (35 cm in from the curb line) and the curb band itself are judged separately:
# curb tops stand at most ~30 cm above the road, while cars parked against the curb show up almost
# entirely inside that band, because the scanner only saw the side facing the sidewalk
roadbed = unary_union([Polygon(o, h) for f in json.load(open(os.path.join(ROOT, 'data', 'plan2_roadbed.geojson')))['features']
                       for o, h in polygons_uv(f['geometry'])])


def mask(geom):
    img = Image.new('L', (W, H), 0); d = ImageDraw.Draw(img)
    for poly in getattr(geom, 'geoms', [geom]):
        d.polygon([to_px(p) for p in poly.exterior.coords], fill=1)
        for h in poly.interiors:
            d.polygon([to_px(p) for p in h.coords], fill=0)
    return np.asarray(img, bool)


inner_mask, full_mask = mask(roadbed.buffer(-0.35)), mask(roadbed)
ix = ((cent[:, 0] - U0) / PX).astype(int); iy = ((V1 - cent[:, 1]) / PX).astype(int)
ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
on_road = np.zeros(len(F), bool); on_road[ok] = inner_mask[iy[ok], ix[ok]]
on_band = np.zeros(len(F), bool); on_band[ok] = full_mask[iy[ok], ix[ok]] & ~inner_mask[iy[ok], ix[ok]]

# local road surface: 5th percentile of road heights in a 7.5 m window (the scan drifts a few dm in height
# across the site, so one global road level would cut real pavement on the low side)
CELL = 2.5
cu, cv = np.floor(cent[:, 0] / CELL).astype(int), np.floor(cent[:, 1] / CELL).astype(int)
cells = {}
near_road = on_road | on_band
for a, b, z in zip(cu[near_road], cv[near_road], cent[near_road, 2]):
    cells.setdefault((a, b), []).append(z)
low = {k: np.percentile(v, 5) for k, v in cells.items() if len(v) >= 20}
def ground(a, b):
    near = [low[(a + i, b + j)] for i in (-1, 0, 1) for j in (-1, 0, 1) if (a + i, b + j) in low]
    return min(near) if near else None
gmap = {}
standing = np.zeros(len(F), bool)
for i in np.where(near_road)[0]:
    k = (cu[i], cv[i])
    if k not in gmap: gmap[k] = ground(*k)
    g = gmap[k]
    standing[i] = g is not None and cent[i, 2] > g + (0.25 if on_road[i] else 0.45)
road_z = float(np.median([v for v in low.values()])) if low else -0.15
print(f'road surface z (median of local levels) = {road_z:.2f} m; {on_road.sum():,} triangles on the roadbed + {on_band.sum():,} in the curb band, {standing.sum():,} standing on them (vehicles)')
mesh.remove_triangles_by_mask(standing)
mesh.remove_unreferenced_vertices()

# pieces left over the road once those bodies are gone (sills, bumpers): separate pieces that lie on the
# roadbed (+30 cm), are under 50k triangles and sit more than 30 cm above the road around them
V = np.asarray(mesh.vertices); F = np.asarray(mesh.triangles); cent = V[F].mean(1)
zone_mask = mask(roadbed.buffer(0.3))
ix = ((cent[:, 0] - U0) / PX).astype(int); iy = ((V1 - cent[:, 1]) / PX).astype(int)
ok = (ix >= 0) & (ix < W) & (iy >= 0) & (iy < H)
in_zone = np.zeros(len(F), bool); in_zone[ok] = zone_mask[iy[ok], ix[ok]]
labels, counts, _ = mesh.cluster_connected_triangles()
labels = np.asarray(labels)
floating = np.zeros(len(F), bool)
for comp in np.unique(labels[in_zone]):
    members = np.where(labels == comp)[0]
    if len(members) >= 50000 or in_zone[members].mean() < 0.8:
        continue
    cx, cy = cent[members, 0].mean(), cent[members, 1].mean()
    around = in_zone & (np.abs(cent[:, 0] - cx) < 4) & (np.abs(cent[:, 1] - cy) < 4)
    g = np.percentile(cent[around, 2], 5) if around.sum() > 10 else road_z
    if np.median(cent[members, 2]) > g + 0.30:
        floating[members] = True
print(f'{floating.sum():,} more triangles in {len(np.unique(labels[floating]))} pieces left over the road')
mesh.remove_triangles_by_mask(floating)
mesh.remove_unreferenced_vertices()

labels, counts, _ = mesh.cluster_connected_triangles()
labels, counts = np.asarray(labels), np.asarray(counts)
small = counts[labels] < 300
print(f'{small.sum():,} triangles in {(counts < 300).sum():,} pieces under 300 triangles')
mesh.remove_triangles_by_mask(small)
mesh.remove_unreferenced_vertices()
mesh.compute_vertex_normals()
o3d.io.write_triangle_mesh(S('court_square_scan_clean.ply'), mesh)
print('clean mesh', f'{len(mesh.vertices):,} vertices', f'{len(mesh.triangles):,} triangles', 'road_z', round(road_z, 3))
json.dump(dict(road_z=road_z), open(S('clean_scan.json'), 'w'))
