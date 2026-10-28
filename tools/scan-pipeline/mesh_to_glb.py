"""Write the scan mesh as GLB for the court-square-map Scan tab (model-viewer 4.4.0) and for Blender.

Two files in scan/:
  court_square_scan.glb            scanned surfaces only
  court_square_scan_completed.glb  + oval ring mirrored across the symmetry axis + flat fill for the unscanned lawn
                                   (separate nodes: scan / mirrored / lawn_fill)
glTF is Y-up: x = park u, y = height, z = -park v (meters, same origin as the DXF files).
Plain uncompressed GLB 2.0, everything embedded, unlit vertex colours (KHR_materials_unlit).\nMaterial 'scan' = observed surfaces, material 'inferred' = mirrored fill + lawn fill (so a viewer can hide it).

Usage: python scripts/mesh_to_glb.py   (needs open3d to read the PLY)
"""
import json, math, os, struct
import numpy as np
import open3d as o3d

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = lambda *p: os.path.join(ROOT, 'scan', *p)
feat = json.load(open(S('features.json')))
lawn, ring, sym = feat['lawn_oval'], feat['ring_outer'], feat['symmetry']

m = o3d.io.read_triangle_mesh(S('court_square_scan_mesh.ply'))
V = np.asarray(m.vertices, dtype=np.float64)
F = np.asarray(m.triangles, dtype=np.int64)
C = np.asarray(m.vertex_colors, dtype=np.float64)


def ell_q(x, y, e, grow=0.0):
    c, s = math.cos(math.radians(e['theta_deg'])), math.sin(math.radians(e['theta_deg']))
    dx, dy = x - e['cx'], y - e['cy']
    return np.sqrt(((dx * c + dy * s) / (e['a'] + grow)) ** 2 + ((-dx * s + dy * c) / (e['b'] + grow)) ** 2)


def in_region(x, y):   # same ring region as symmetrize_scan.py
    south = (y < lawn['cy']) & (np.abs(x - lawn['cx']) < ring['a'] + 0.8) & (y > lawn['cy'] - lawn['b'] - 9.5)
    return (ell_q(x, y, ring, 0.8) <= 1.0) | (south & (ell_q(x, y, ring, 4.5) <= 1.0))


t = math.radians(90 + sym['tilt_deg'])
d = np.array([math.cos(t), math.sin(t)]); p0 = np.array([sym['axis_u'], sym['axis_v']])


def mirror(xy):
    r = xy - p0
    return p0 + 2 * (r @ d)[:, None] * d - r


G = 0.10
def cells(xy):
    return set(map(tuple, np.floor(xy / G).astype(np.int64).tolist()))


def dilate(cs, n=1):
    return {(x + i, y + j) for x, y in cs for i in range(-n, n + 1) for j in range(-n, n + 1)}


covered = dilate(cells(V[:, :2]))

# mirrored triangles: from the ring region, landing where the scan has nothing
cent = V[F].mean(1)
src = in_region(cent[:, 0], cent[:, 1])
Fm = F[src]
used = np.unique(Fm)
remap = -np.ones(len(V), np.int64); remap[used] = np.arange(len(used))
Vm = V[used].copy(); Vm[:, :2] = mirror(Vm[:, :2]); Cm = C[used]
Fm = remap[Fm][:, [0, 2, 1]]                         # reflection flips winding
cm = Vm[Fm].mean(1)
key = np.floor(cm[:, :2] / G).astype(np.int64)
keep = np.array([(a, b) not in covered for a, b in key.tolist()], dtype=bool) & in_region(cm[:, 0], cm[:, 1])
Fm = Fm[keep]
used = np.unique(Fm); remap = -np.ones(len(Vm), np.int64); remap[used] = np.arange(len(used))
Vm, Cm, Fm = Vm[used], Cm[used], remap[Fm]
print('mirrored', len(Fm), 'tris')

# lawn fill: 20 cm grid quads inside the lawn oval where neither scan nor mirror reached
covered2 = covered | dilate(cells(Vm[:, :2]))
edge = (ell_q(V[:, 0], V[:, 1], lawn) > 0.8) & (ell_q(V[:, 0], V[:, 1], lawn) < 1.0) & (V[:, 2] < 0.25)
grassy = edge & (C[:, 1] > C[:, 0]) & (C[:, 1] > C[:, 2])
gcol = np.median(C[grassy], 0) if grassy.sum() > 50 else np.array([0.36, 0.5, 0.24])
gz = float(np.median(V[edge, 2])) if edge.any() else 0.0
L = 0.20
us = np.arange(lawn['cx'] - lawn['a'] - 1, lawn['cx'] + lawn['a'] + 1, L)
vs = np.arange(lawn['cy'] - lawn['b'] - 1, lawn['cy'] + lawn['b'] + 1, L)
quads = []
for u in us:
    for v in vs:
        cx, cy = u + L / 2, v + L / 2
        if ell_q(np.array([cx]), np.array([cy]), lawn)[0] > 0.995:
            continue
        if any((int(math.floor((cx + ox) / G)), int(math.floor((cy + oy) / G))) in covered2 for ox in (-0.05, 0.05) for oy in (-0.05, 0.05)):
            continue
        quads.append((u, v))
rng = np.random.default_rng(3)
Vl = np.array([(u + du, v + dv, gz) for u, v in quads for du, dv in ((0, 0), (L, 0), (L, L), (0, L))]).reshape(-1, 3)
Fl = np.array([(4 * i, 4 * i + 1, 4 * i + 2, 4 * i, 4 * i + 2, 4 * i + 3) for i in range(len(quads))]).reshape(-1, 3)
Cl = np.clip(np.repeat(gcol[None], len(Vl), 0) * rng.normal(1, 0.06, (len(Vl), 1)), 0, 1)
print('lawn fill', len(Fl), 'tris at z', round(gz, 3))


def srgb_to_linear(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def write_glb(path, parts):
    """parts: list of (name, V (park u,v,h), F, C sRGB 0..1, material index: 0 scan, 1 inferred)."""
    bin_ = bytearray(); views, accs, meshes, nodes = [], [], [], []

    def add_view(data, target):
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=len(data), target=target))
        bin_.extend(data)
        return len(views) - 1

    for name, Vp, Fp, Cp, mat in parts:
        if not len(Fp):
            continue
        pos = np.column_stack([Vp[:, 0], Vp[:, 2], -Vp[:, 1]]).astype('<f4')
        col = np.column_stack([srgb_to_linear(np.clip(Cp, 0, 1)), np.ones(len(Cp))])
        col = np.round(col * 65535).astype('<u2')
        idx = Fp.astype('<u4').ravel()
        a_pos = len(accs); accs.append(dict(bufferView=add_view(pos.tobytes(), 34962), componentType=5126, count=len(pos), type='VEC3',
                                            min=pos.min(0).tolist(), max=pos.max(0).tolist()))
        a_col = len(accs); accs.append(dict(bufferView=add_view(col.tobytes(), 34962), componentType=5123, normalized=True, count=len(col), type='VEC4'))
        a_idx = len(accs); accs.append(dict(bufferView=add_view(idx.tobytes(), 34963), componentType=5125, count=len(idx), type='SCALAR'))
        meshes.append(dict(name=name, primitives=[dict(attributes=dict(POSITION=a_pos, COLOR_0=a_col), indices=a_idx, material=mat, mode=4)]))
        nodes.append(dict(name=name, mesh=len(meshes) - 1))
    while len(bin_) % 4:
        bin_.append(0)
    gltf = dict(asset=dict(version='2.0', generator='court-square-park scripts/mesh_to_glb.py',
                           extras=dict(frame='park frame: x = u (toward Thomson Ave), y = up, z = -v (v toward Jackson Ave), meters; '
                                             'true north is 27.6 deg clockwise from +v')),
                scene=0, scenes=[dict(nodes=list(range(len(nodes))))], nodes=nodes, meshes=meshes,
                materials=[dict(name=n, doubleSided=True,
                                pbrMetallicRoughness=dict(baseColorFactor=[1, 1, 1, 1], metallicFactor=0, roughnessFactor=1),
                                extensions=dict(KHR_materials_unlit={})) for n in ('scan', 'inferred')],
                extensionsUsed=['KHR_materials_unlit'],
                accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    js = json.dumps(gltf, separators=(',', ':')).encode()
    js += b' ' * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_)
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<III', 0x46546C67, 2, total))
        fh.write(struct.pack('<II', len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack('<II', len(bin_), 0x004E4942)); fh.write(bin_)
    print(os.path.basename(path), f'{total / 1e6:.1f} MB', sum(len(p[2]) for p in parts), 'tris', sum(len(p[1]) for p in parts), 'verts')


write_glb(S('court_square_scan.glb'), [('scan', V, F, C, 0)])
write_glb(S('court_square_scan_completed.glb'), [('scan', V, F, C, 0), ('mirrored', Vm, Fm, Cm, 1), ('lawn_fill', Vl, Fl, Cl, 1)])
