#!/bin/zsh
# Download the NYC Open Data layers the pipeline uses into ./data (run from the working folder).
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p data && cd data
API=https://data.cityofnewyork.us/resource
box() { python3 -c "import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1]))" "within_box($1,40.7478,-73.9455,40.7450,-73.9418)"; }
curl -s -o parks_property_Q267.geojson "$API/enfh-gkve.geojson?gispropnum=Q267"
curl -s -o buildings.geojson "$API/5zhs-2jue.geojson?\$where=$(box the_geom)&\$limit=500"
curl -s -o trees_forestry.json "$API/hn5i-inap.json?\$where=$(python3 -c "import urllib.parse;print(urllib.parse.quote('within_box(location,40.7472,-73.9445,40.7455,-73.9425)'))")&\$limit=500"
for pair in 52n9-sdep:sidewalk 5xvt-8cbk:curbs i36f-5ih7:roadbed 9uxf-ng6q:elevation_points ees7-4ufv:median; do
  curl -s -o "plan_${pair##*:}.geojson" "$API/${pair%%:*}.geojson?\$where=$(box the_geom)&\$limit=2000"
done
# the model needs whole street polygons around the block, so these use an intersects query
AREA=$(python3 -c "import urllib.parse;print(urllib.parse.quote(\"intersects(the_geom, 'POLYGON((-73.9478 40.7438, -73.9392 40.7438, -73.9392 40.7492, -73.9478 40.7492, -73.9478 40.7438))')\"))")
for pair in i36f-5ih7:roadbed 52n9-sdep:sidewalk ees7-4ufv:median 5xvt-8cbk:curbs; do
  curl -s -o "plan2_${pair##*:}.geojson" "$API/${pair%%:*}.geojson?\$where=$AREA&\$limit=5000"
done
# current footprints (with construction year) and ground spot elevations for the detailed model
curl -s -o buildings2.geojson "$API/5zhs-2jue.geojson?\$where=$AREA&\$limit=5000"
curl -s -o plan2_elevation_points.geojson "$API/9uxf-ng6q.geojson?\$where=$AREA&\$limit=5000"
# NYC 3D Building Model, delivery area 10 only (fetched by byte range from the city-wide zip)
python3 -I "$HERE/fetch_nyc3d.py" nyc3d DA10
ls -la
