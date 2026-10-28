"""Write the cleaned scan as a Rhino 8 file in the same frame as court_square_park_LOD3.3dm.

Layers: Scan::Observed (cleaned)  - scanned surfaces, vehicles and specks removed (clean_scan.py), full resolution
        Scan::Inferred            - oval ring mirrored across the symmetry axis + flat lawn fill (from mesh_to_glb.py)
Vertex colour is the camera colour (sRGB).

Usage: python scripts/build_scan_3dm.py     (needs rhino3dm, open3d)
"""
import json, os, struct, sys
import numpy as np
import open3d as o3d
import rhino3dm as r

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parkframe import ROOT, NORTH, EAST, ORIGIN_LL

S = lambda *p: os.path.join(ROOT, 'scan', *p)
GRADE = json.load(open(os.path.join(ROOT, 'model', 'site_local.json')))['frame']['park_grade_navd88_m']
AXIS_U = json.load(open(S('features.json')))['symmetry']['axis_u']


def glb_nodes(path, names):
    """Read named nodes of our own uncompressed GLB back into park-frame (u, v, h) arrays + sRGB colours."""
    b = open(path, 'rb').read()
    jl = struct.unpack('<I', b[12:16])[0]
    js = json.loads(b[20:20 + jl]); bin0 = 20 + jl + 8
    def acc(i, dtype, width):
        a = js['accessors'][i]; v = js['bufferViews'][a['bufferView']]
        return np.frombuffer(b, dtype, a['count'] * width, bin0 + v['byteOffset']).reshape(a['count'], width) if width > 1 else \
               np.frombuffer(b, dtype, a['count'], bin0 + v['byteOffset'])
    out = {}
    for node in js['nodes']:
        if node['name'] not in names:
            continue
        p = js['meshes'][node['mesh']]['primitives'][0]
        P = acc(p['attributes']['POSITION'], '<f4', 3).astype(np.float64)
        C = acc(p['attributes']['COLOR_0'], '<u2', 4)[:, :3] / 65535.0
        F = acc(p['indices'], '<u4', 1).reshape(-1, 3)
        srgb = np.where(C <= 0.0031308, C * 12.92, 1.055 * C ** (1 / 2.4) - 0.055)
        out[node['name']] = (np.column_stack([P[:, 0], -P[:, 2], P[:, 1]]), F, np.round(srgb * 255).astype(np.uint8))
    return out


def rhino_mesh(V, F, C):
    m = r.Mesh()
    for x, y, z in V.tolist():
        m.Vertices.Add(x, y, z)
    for a, b_, c in F.tolist():
        m.Faces.AddFace(a, b_, c)
    for cr, cg, cb in C.tolist():
        m.VertexColors.Add(cr, cg, cb)
    m.Normals.ComputeNormals()
    return m


f = r.File3dm()
f.Settings.ModelUnitSystem = r.UnitSystem.Meters
f.Settings.ModelAbsoluteTolerance = 0.001
ea = f.Settings.EarthAnchorPoint
ea.EarthBasepointLatitude, ea.EarthBasepointLongitude, ea.EarthBasepointElevation = ORIGIN_LL[1], ORIGIN_LL[0], GRADE
ea.ModelBasePoint = r.Point3d(0, 0, 0); ea.ModelNorth = r.Vector3d(NORTH[0], NORTH[1], 0); ea.ModelEast = r.Vector3d(EAST[0], EAST[1], 0)
f.Settings.EarthAnchorPoint = ea
parent = r.Layer(); parent.Name = 'Scan'; parent.Color = (120, 120, 120, 255)
pi = f.Layers.Add(parent)
idx = {}
for name, col in [('Observed (cleaned)', (150, 150, 150)), ('Inferred', (120, 150, 255))]:
    L = r.Layer(); L.Name = name; L.Color = (*col, 255); L.ParentLayerId = f.Layers.FindIndex(pi).Id
    idx[name] = f.Layers.Add(L)


def add(mesh, layer, name, src):
    at = r.ObjectAttributes(); at.LayerIndex = idx[layer]; at.Name = name; at.SetUserString('source', src)
    f.Objects.AddMesh(mesh, at)


clean = o3d.io.read_triangle_mesh(S('court_square_scan_clean.ply'))
V, F = np.asarray(clean.vertices), np.asarray(clean.triangles)
C = np.round(np.asarray(clean.vertex_colors) * 255).astype(np.uint8)
add(rhino_mesh(V, F, C), 'Observed (cleaned)', 'LiDAR scan 2026-10-28', 'TSDF 2 cm, vehicles and specks removed')
print(f'observed: {len(V):,} vertices {len(F):,} triangles')
for name, (Vi, Fi, Ci) in glb_nodes(S('court_square_scan_completed.glb'), {'mirrored', 'lawn_fill'}).items():
    add(rhino_mesh(Vi, Fi, Ci), 'Inferred', name, 'mirrored across x = %.2f m' % AXIS_U if name == 'mirrored' else 'flat fill at measured lawn height')
    print(f'{name}: {len(Vi):,} vertices {len(Fi):,} triangles')
f.Write(os.path.join(ROOT, 'model', 'court_square_scan.3dm'), 8)
print('written', os.path.getsize(os.path.join(ROOT, 'model', 'court_square_scan.3dm')) / 1e6, 'MB')
