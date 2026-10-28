"""Park frame helpers shared by clean_scan.py and build_model.py (same frame as build_site.py).

u (x) runs along the courthouse edge toward Thomson Ave (true bearing 62.4 deg), v (y) toward Jackson Ave,
origin at the park corner where Court Square West meets the courthouse forecourt. Meters.
"""
import json, math, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAT0, LON0 = 40.74636, -73.94345
_phi = math.radians(LAT0)
MLAT = 111132.954 - 559.822 * math.cos(2 * _phi) + 1.175 * math.cos(4 * _phi)
MLON = 111412.84 * math.cos(_phi) - 93.5 * math.cos(3 * _phi)
BEARING = 62.4
_t = math.radians(BEARING)
UX, UY, VX, VY = math.sin(_t), math.cos(_t), -math.cos(_t), math.sin(_t)
ORIGIN_LL = json.load(open(os.path.join(ROOT, 'data', 'parks_property_Q267.geojson')))['features'][0]['geometry']['coordinates'][0][0][4]
_EX, _EY = (ORIGIN_LL[0] - LON0) * MLON, (ORIGIN_LL[1] - LAT0) * MLAT
NORTH = (UY, VY)   # unit vector of true north in (u, v)
EAST = (UX, VX)    # unit vector of true east in (u, v)


def uv(lon, lat):
    x, y = (lon - LON0) * MLON - _EX, (lat - LAT0) * MLAT - _EY
    return (x * UX + y * UY, x * VX + y * VY)


def polygons_uv(geom):
    """GeoJSON (Multi)Polygon -> list of (outer, [holes]) in park coordinates."""
    t, c = geom['type'], geom['coordinates']
    polys = [c] if t == 'Polygon' else c if t == 'MultiPolygon' else []
    return [([uv(*p) for p in poly[0]], [[uv(*p) for p in r] for r in poly[1:]]) for poly in polys]
