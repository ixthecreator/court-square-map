"""Turn the iPhone LiDAR keyframe export into a colored point cloud in ARKit world space.

Usage:  python3 scripts/scan_to_cloud.py ~/Downloads/keyframes
Writes  scan/arkit_cloud.npz (points, colors), scan/trajectory.json (poses + GPS)
"""
import json, math, os, sys
import numpy as np
from PIL import Image

KF = os.path.expanduser(sys.argv[1])
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scan')
os.makedirs(OUT, exist_ok=True)

FRAME_STEP = 2      # use every Nth keyframe for points
PIX_STEP = 2        # sample every Nth depth pixel
MAX_DEPTH = 4.0     # m, LiDAR gets noisy beyond this
VOXEL = 0.03        # m

keys = sorted(f[:-5] for f in os.listdir(os.path.join(KF, 'cameras')) if f.endswith('.json'))
traj = []
for k in keys:
    c = json.load(open(os.path.join(KF, 'cameras', k + '.json')))
    T = [[c[f't_{r}{q}'] for q in range(4)] for r in range(3)]
    loc = json.load(open(os.path.join(KF, 'location', k + '.json')))
    L = loc['location']
    traj.append(dict(key=k, T=T, fx=c['fx'], fy=c['fy'], cx=c['cx'], cy=c['cy'], w=c['width'], h=c['height'],
                     lat=L['latitude'], lon=L['longitude'], alt=L['altitude'], hacc=L['horizontalAccuracy'],
                     heading=loc.get('heading', {}).get('trueHeading'), mapping=c.get('world_mapping_status'),
                     blur=c.get('blur_score'), time=c['exif']['DateTimeOriginal'] if 'exif' in c else None))
json.dump(traj, open(os.path.join(OUT, 'trajectory.json'), 'w'))

pts_all, col_all = [], []
vox = {}
for i, fr in enumerate(traj[::FRAME_STEP]):
    k = fr['key']
    depth = np.asarray(Image.open(os.path.join(KF, 'depth', k + '.png')), dtype=np.float32) / 1000.0
    conf = np.asarray(Image.open(os.path.join(KF, 'confidence', k + '.png')))
    img = np.asarray(Image.open(os.path.join(KF, 'images', k + '.jpg')).convert('RGB'))
    dh, dw = depth.shape
    s = fr['w'] / dw
    v, u = np.mgrid[0:dh:PIX_STEP, 0:dw:PIX_STEP]
    d = depth[v, u]
    m = (conf[v, u] == 255) & (d > 0.2) & (d < MAX_DEPTH)
    u, v, d = u[m], v[m], d[m]
    # ARKit camera: x right, y up, looking down -z
    X = (u * s + s / 2 - fr['cx']) / fr['fx'] * d
    Y = -(v * s + s / 2 - fr['cy']) / fr['fy'] * d
    Z = -d
    T = np.array(fr['T'])
    P = (T[:, :3] @ np.vstack([X, Y, Z])).T + T[:, 3]
    C = img[np.clip((v * s + s / 2).astype(int), 0, fr['h'] - 1), np.clip((u * s + s / 2).astype(int), 0, fr['w'] - 1)]
    pts_all.append(P.astype(np.float32)); col_all.append(C)
    if len(pts_all) >= 100 or i == len(traj[::FRAME_STEP]) - 1:
        P = np.concatenate(pts_all); C = np.concatenate(col_all)
        q = np.floor(P / VOXEL).astype(np.int64)
        key = (q[:, 0] + 2**20) * 2**42 + (q[:, 1] + 2**20) * 2**21 + (q[:, 2] + 2**20)
        _, idx = np.unique(key, return_index=True)
        for kk, p, c in zip(key[idx].tolist(), P[idx], C[idx]):
            if kk not in vox:
                vox[kk] = (p, c)
        pts_all, col_all = [], []
        print(f'{(i + 1) * FRAME_STEP}/{len(traj)} frames, {len(vox)} voxels', flush=True)

P = np.array([v[0] for v in vox.values()], dtype=np.float32)
C = np.array([v[1] for v in vox.values()], dtype=np.uint8)
np.savez_compressed(os.path.join(OUT, 'arkit_cloud.npz'), points=P, colors=C)
print('points', len(P), 'bbox', P.min(0).round(2), P.max(0).round(2))
