"""Split a GLB into byte-exact parts for GitHub (which rejects files over 100 MB) and write scan/manifest.json.

The site fetches the parts, joins them, checks the SHA-256 of the result against the manifest and hands the
original GLB to model-viewer, so nothing is re-encoded or compressed.

Usage:
  python3 tools/split_scan.py path/to/scan.glb --name court-square-park-2026-10-28.glb \
      --title "Court Square Park field scan" --captured 2026-10-28 [--part-mb 40] [--georef data/scan-georef.json]
"""
import argparse, hashlib, json, os, struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'scan')

ap = argparse.ArgumentParser()
ap.add_argument('glb')
ap.add_argument('--name', required=True, help='file name the site shows and attaches notes to')
ap.add_argument('--title', default='Field scan')
ap.add_argument('--captured', default='')
ap.add_argument('--device', default='')
ap.add_argument('--part-mb', type=float, default=40)
ap.add_argument('--georef', help='JSON with origin [lon, lat], x_bearing_deg, m_per_deg_lon, m_per_deg_lat for the scan frame')
args = ap.parse_args()

data = open(args.glb, 'rb').read()
if data[:4] != b'glTF' or struct.unpack('<I', data[4:8])[0] != 2 or struct.unpack('<I', data[8:12])[0] != len(data):
    raise SystemExit('not a complete GLB 2.0 file')
jlen = struct.unpack('<I', data[12:16])[0]
gltf = json.loads(data[20:20 + jlen])
tris = sum(gltf['accessors'][p['indices']]['count'] // 3 for m in gltf['meshes'] for p in m['primitives'])
verts = sum(gltf['accessors'][p['attributes']['POSITION']]['count'] for m in gltf['meshes'] for p in m['primitives'])

os.makedirs(OUT, exist_ok=True)
for f in os.listdir(OUT):
    if f.startswith(args.name + '.part'):
        os.remove(os.path.join(OUT, f))
size = int(args.part_mb * 1024 * 1024)
parts = []
for i in range(0, len(data), size):
    chunk = data[i:i + size]
    fn = f'{args.name}.part{len(parts):03d}'
    open(os.path.join(OUT, fn), 'wb').write(chunk)
    parts.append(dict(path=fn, bytes=len(chunk), sha256=hashlib.sha256(chunk).hexdigest()))

manifest = dict(version=1, name=args.name, title=args.title, captured=args.captured, device=args.device,
                bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), triangles=tris, vertices=verts,
                materials=[m.get('name', '') for m in gltf.get('materials', [])], frame=gltf['asset'].get('extras', {}).get('frame', ''),
                georef=json.load(open(args.georef)) if args.georef else None, parts=parts)
json.dump(manifest, open(os.path.join(OUT, 'manifest.json'), 'w'), indent=1)
print(f"{args.name}: {len(data) / 1e6:.1f} MB -> {len(parts)} parts, {tris:,} triangles, {verts:,} vertices")
