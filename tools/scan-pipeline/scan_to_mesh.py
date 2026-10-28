"""TSDF-fuse the LiDAR keyframes into a vertex-coloured mesh in the park frame (Z-up, meters).

Needs Open3D (pip install open3d). Uses the poses from the export plus scan/registration.json,
so the mesh lands on the same coordinates as the DXF / PLY files.

Usage:  python scripts/scan_to_mesh.py ~/Downloads/keyframes
Writes  scan/court_square_scan_mesh.ply
"""
import json, os, sys
import numpy as np
import open3d as o3d
from PIL import Image

KF = os.path.expanduser(sys.argv[1])
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = lambda *p: os.path.join(ROOT, 'scan', *p)

VOXEL = 0.02          # m (no decimation afterwards: the mesh keeps every TSDF triangle)
TRUNC = 0.08          # m, TSDF truncation
MAX_DEPTH = 3.5       # m
BOX = (-12, -14, -1.0, 64, 54, 3.0)   # u0 v0 z0 u1 v1 z1 kept around the park

reg = json.load(open(S('registration.json')))
R, T, gy = np.array(reg['R']), np.array(reg['T']), reg['arkit_ground_y']
# ARKit world (x, y up, z) -> park frame (u, v, h):  (u, v) = R @ (x, -z) + T,  h = y - ground_y
M = np.array([[R[0, 0], 0, -R[0, 1], T[0]],
              [R[1, 0], 0, -R[1, 1], T[1]],
              [0, 1, 0, -gy],
              [0, 0, 0, 1]])
FLIP = np.diag([1, -1, -1, 1])        # ARKit camera (y up, z back) -> OpenCV camera (y down, z forward)

traj = json.load(open(S('trajectory.json')))
# tensor VoxelBlockGrid (the legacy ScalableTSDFVolume integrates nothing in the open3d 0.20 macOS wheel)
o3c = o3d.core
dev = o3c.Device('CPU:0')
vbg = o3d.t.geometry.VoxelBlockGrid(attr_names=('tsdf', 'weight', 'color'),
                                    attr_dtypes=(o3c.float32, o3c.float32, o3c.float32),
                                    attr_channels=((1), (1), (3)), voxel_size=VOXEL, block_resolution=8,
                                    block_count=240000, device=dev)

for i, fr in enumerate(traj):
    k = fr['key']
    depth = np.asarray(Image.open(os.path.join(KF, 'depth', k + '.png'))).astype(np.uint16)
    conf = np.asarray(Image.open(os.path.join(KF, 'confidence', k + '.png')))
    depth = np.where(conf == 255, depth, 0).astype(np.uint16)
    h, w = depth.shape
    if (depth > 0).sum() < 500:
        continue
    color = np.asarray(Image.open(os.path.join(KF, 'images', k + '.jpg')).convert('RGB'))   # full-res colour
    s = w / fr['w']
    K = o3c.Tensor([[fr['fx'] * s, 0, (fr['cx'] + 0.5) * s - 0.5], [0, fr['fy'] * s, (fr['cy'] + 0.5) * s - 0.5], [0, 0, 1]], o3c.float64)
    Kc = o3c.Tensor([[fr['fx'], 0, fr['cx']], [0, fr['fy'], fr['cy']], [0, 0, 1]], o3c.float64)
    c2w = np.vstack([np.array(fr['T']), [0, 0, 0, 1]])
    E = o3c.Tensor(np.linalg.inv(M @ c2w @ FLIP), o3c.float64)
    D = o3d.t.geometry.Image(o3c.Tensor(np.ascontiguousarray(depth)))
    Cimg = o3d.t.geometry.Image(o3c.Tensor(np.ascontiguousarray(color)))
    try:
        coords = vbg.compute_unique_block_coordinates(D, K, E, 1000.0, MAX_DEPTH, TRUNC / VOXEL)
        vbg.integrate(coords, D, Cimg, K, Kc, E, 1000.0, MAX_DEPTH, TRUNC / VOXEL)
    except RuntimeError as e:      # frame whose depth touches no block
        print('skip', k, str(e)[:80])
        continue
    if i % 300 == 0:
        print(f'{i}/{len(traj)} frames, {vbg.hashmap().size()} blocks', flush=True)

tm = vbg.extract_triangle_mesh(weight_threshold=2.0)
mesh = tm.to_legacy()
col = np.asarray(mesh.vertex_colors)
if len(col) and col.max() > 1.0:
    mesh.vertex_colors = o3d.utility.Vector3dVector(np.clip(col / 255.0, 0, 1))
print('raw mesh', len(mesh.vertices), 'verts', len(mesh.triangles), 'tris', flush=True)
mesh = mesh.crop(o3d.geometry.AxisAlignedBoundingBox(BOX[:3], BOX[3:]))
mesh.remove_degenerate_triangles(); mesh.remove_duplicated_vertices(); mesh.remove_unreferenced_vertices()
labels, counts, _ = mesh.cluster_connected_triangles()
labels, counts = np.asarray(labels), np.asarray(counts)
mesh.remove_triangles_by_mask(counts[labels] < 100)   # drop floating specks only
mesh.remove_unreferenced_vertices()
mesh.compute_vertex_normals()
o3d.io.write_triangle_mesh(S('court_square_scan_mesh.ply'), mesh)
print('final mesh', len(mesh.vertices), 'verts', len(mesh.triangles), 'tris')
