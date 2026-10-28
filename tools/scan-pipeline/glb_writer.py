"""Minimal GLB 2.0 writer for coloured meshes (park frame in, glTF Y-up out: x = u, y = z, z = -v)."""
import json, struct
import numpy as np


def _srgb_to_linear(c):
    c = c / 255.0
    return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92


def write_glb(path, groups, generator='court-square-park'):
    """groups: iterable of dict(color=(r, g, b[, a]), V=(n,3), F=(m,3), smooth=bool, name=str, rough=float).
    Groups with the same colour, smoothness and name are merged into one primitive."""
    merged = {}
    for g in groups:
        if len(g['F']) == 0:
            continue
        key = (tuple(g['color']), bool(g.get('smooth')), g.get('name', ''), g.get('rough', 0.9))
        merged.setdefault(key, []).append((np.asarray(g['V'], float), np.asarray(g['F'], int)))
    bin_ = bytearray(); views, accs, mats, meshes, nodes = [], [], [], [], []

    def view(arr, target):
        while len(bin_) % 4:
            bin_.append(0)
        views.append(dict(buffer=0, byteOffset=len(bin_), byteLength=arr.nbytes, target=target)); bin_.extend(arr.tobytes())
        return len(views) - 1

    for (color, smooth, name, rough), parts in merged.items():
        if smooth:
            V, F, off = [], [], 0
            for v, f in parts:
                V.append(v); F.append(f + off); off += len(v)
            V = np.vstack(V); F = np.vstack(F)
            fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
            N = np.zeros_like(V)
            for k in range(3):
                np.add.at(N, F[:, k], fn)
            N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
            idx = F.astype('<u4').ravel()
        else:   # flat shading: one vertex per corner
            T = np.vstack([v[f] for v, f in parts])            # (m, 3, 3)
            fn = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
            fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
            V = T.reshape(-1, 3); N = np.repeat(fn, 3, 0); idx = None
        P = np.column_stack([V[:, 0], V[:, 2], -V[:, 1]]).astype('<f4')
        Nn = np.column_stack([N[:, 0], N[:, 2], -N[:, 1]]).astype('<f4')
        a_p = len(accs); accs.append(dict(bufferView=view(P, 34962), componentType=5126, count=len(P), type='VEC3', min=P.min(0).tolist(), max=P.max(0).tolist()))
        a_n = len(accs); accs.append(dict(bufferView=view(Nn, 34962), componentType=5126, count=len(Nn), type='VEC3'))
        prim = dict(attributes=dict(POSITION=a_p, NORMAL=a_n), material=len(mats), mode=4)
        if idx is not None:
            a_i = len(accs); accs.append(dict(bufferView=view(idx, 34963), componentType=5125, count=len(idx), type='SCALAR'))
            prim['indices'] = a_i
        alpha = color[3] / 255 if len(color) > 3 else 1.0
        mats.append(dict(name=name or 'material', doubleSided=True, alphaMode='BLEND' if alpha < 1 else 'OPAQUE',
                         pbrMetallicRoughness=dict(baseColorFactor=[*(_srgb_to_linear(c) for c in color[:3]), alpha], metallicFactor=0, roughnessFactor=rough)))
        meshes.append(dict(name=name, primitives=[prim])); nodes.append(dict(name=name, mesh=len(meshes) - 1))
    while len(bin_) % 4:
        bin_.append(0)
    gltf = dict(asset=dict(version='2.0', generator=generator), scene=0, scenes=[dict(nodes=list(range(len(nodes))))], nodes=nodes,
                meshes=meshes, materials=mats, accessors=accs, bufferViews=views, buffers=[dict(byteLength=len(bin_))])
    js = json.dumps(gltf, separators=(',', ':')).encode(); js += b' ' * ((4 - len(js) % 4) % 4)
    with open(path, 'wb') as fh:
        fh.write(struct.pack('<III', 0x46546C67, 2, 28 + len(js) + len(bin_)))
        fh.write(struct.pack('<II', len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack('<II', len(bin_), 0x004E4942)); fh.write(bin_)
    return sum(len(F) for parts in merged.values() for _, F in parts)
