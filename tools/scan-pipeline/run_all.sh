#!/bin/zsh
# Rebuild everything. Usage: zsh scripts/run_all.sh ~/Downloads/keyframes path/to/court-square-map
set -e
cd "$(dirname "$0")/.."
python3 -I scripts/build_site.py          # NYC open data -> model/ (DXF, OBJ, CSV, site_local.json)
python3 -I scripts/scan_to_cloud.py "$1"  # LiDAR keyframes -> scan/arkit_cloud.npz
python3 -I scripts/register_scan.py       # GPS + curb ICP -> scan/court_square_scan_site.ply, orthos
python3 -I scripts/analyze_scan.py        # lawn oval, ring path, spray pad, objects -> scan/features.json
python3 -I scripts/symmetrize_scan.py     # mirror-fill the oval ring -> scan/court_square_scan_completed.ply
python3 -I scripts/export_features.py     # features -> model/court_square_scan_features.dxf, scan_objects.csv
python3 -I scripts/render_plans.py        # plans/*.png
# 3D mesh (needs: pip install open3d) and website exports
python scripts/scan_to_mesh.py "$1"       # TSDF 2 cm -> scan/court_square_scan_mesh.ply
python scripts/mesh_to_glb.py             # -> scan/court_square_scan.glb, scan/court_square_scan_completed.glb
python3 -I scripts/export_web.py "$2"     # -> <site>/data/park-detail.geojson, <site>/data/scan-georef.json
# Rhino 8 model (needs: pip install rhino3dm shapely mapbox-earcut)
python scripts/clean_scan.py              # vehicles and specks removed -> scan/court_square_scan_clean.ply
python scripts/build_model.py             # LOD3 -> model/court_square_park_LOD3.3dm (+ _preview.glb)
python scripts/build_scan_3dm.py          # scan -> model/court_square_scan.3dm
