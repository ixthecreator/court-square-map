# Geographic data and interpretation

Snapshot retrieved **October 28, 2026**. Coordinates use WGS84 longitude and latitude and are projected locally with D3's Mercator projection.

## Official NYC sources

| Dataset | Used for |
| --- | --- |
| [NYC BUILDING, Office of Technology and Innovation](https://data.cityofnewyork.us/City-Government/BUILDING/5zhs-2jue) | Building footprints and roof heights |
| [NYC Centerline / CSCL](https://data.cityofnewyork.us/City-Government/Centerline/inkn-q76z) | Street geometry and recorded paved widths |
| [NYC Parks Properties](https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve) | Court Square Park, property Q267 |
| [2020 Neighborhood Tabulation Areas, NYC Department of City Planning, version 26b](https://data.cityofnewyork.us/City-Government/2020-Neighborhood-Tabulation-Areas-NTAs-/9nt8-h7nd) | Study-area boundary |
| [Forestry Tree Points, NYC Parks](https://data.cityofnewyork.us/Environment/Forestry-Tree-Points/hn5i-inap) | Trees in and around the park (species, DBH) |
| [NYC Planimetric Database](https://data.cityofnewyork.us/browse?q=planimetric): Curbs, Sidewalk, Roadbed, Median, Elevation Points | Scan registration and the modeling kit |

## Coverage

The union of **QN0201 Long Island City–Hunters Point** and **QN0105 Queensbridge–Ravenswood–Dutch Kills** defines the approximately **5.139 km²** study area. Its bounding box is approximately `[-73.962620, 40.737900, -73.924157, 40.771271]`. This statistical extent does not imply a single universally accepted neighborhood boundary.

The map includes **3,699 building footprints** and **1,213 street segments**. Buildings intersecting the study area retain their entire footprints; streets are clipped to the boundary. No synthetic buildings are added. Coordinate rounding is to seven decimal places; two resulting geometry validity issues were repaired during preparation.

Court Square Park's official polygon has center `[-73.943459, 40.746356]` and recorded area **0.492 acres**. Its interior shows the as-built layout described under *Court Square Park field scan* below.

## Heights and simplification

- `HEIGHT_ROOF` is relative to local ground, not sea level. Original feet are converted to metres using `0.3048`. Ground elevation is not subtracted. See the [official building footprint metadata](https://github.com/CityOfNewYork/nyc-geo-metadata/blob/main/Metadata/Metadata_BuildingFootprints.md).
- Nine buildings have missing or zero roof heights and remain flat. The maximum recorded height in the snapshot is 242.01 metres. Some records describe buildings under construction.
- The slider multiplies displayed heights from zero to the recorded values. This is a visual control, not a change to the source data.
- Buildings are footprint extrusions, without reconstructed facades, roof details or terrain. Distant buildings may use simpler display detail.
- Street widths come from recorded paved-width values in feet, converted to metres. Missing widths receive a symbolic display width. See the [Geosupport User Programming Guide](https://www.nyc.gov/assets/planning/download/pdf/data-maps/open-data/upg.pdf?r=16b), page 276.
- All streets are displayed on one plane. Source level codes are ordinal identifiers, not heights in metres; elevated roads and rail infrastructure are not reconstructed.
- Boundary edges describe the selected coverage, including inland edges. The background is not an authoritative water mask.

## Court Square Park field scan

**Capture.** iPhone 16 Pro LiDAR, October 28, 2026, about 19 minutes walking the ring path, perimeter and sidewalks: 3,385 keyframes with depth (256 × 192), depth confidence, RGB (1024 × 768), ARKit poses and GPS. It was recorded as one ARKit tracking session with no relocalization breaks.

**Mesh.** Only high-confidence depth up to 3.5 m was used. It was fused into a truncated signed distance field (2 cm voxels, 8 cm truncation, at least two observations per surface) and extracted with marching cubes. Vertex colour is sampled from the full-resolution frames. Parked cars were then removed in three passes:
- On the NYC roadbed, anything more than 25 cm above the local road surface (5th percentile over 7.5 m).
- Within 35 cm of the curb line, where the curb itself stands, anything more than 45 cm above it. The scanner saw only the sidewalk side of parked cars, so most of them fell in that band.
- Leftover separate pieces under 50,000 triangles that lie on the roadbed and sit more than 30 cm above the road around them.

Floating pieces under 300 triangles anywhere were also removed. Nothing else was simplified. The GLB stores sRGB colour as 16-bit linear values (glTF convention), so the 8-bit camera colour is preserved exactly.

**Registration.** A rigid fit of the camera path to its GPS fixes (median residual 1.2 m) placed the scan. An ICP fit of scanned curb and step edges to NYC planimetric curbs then corrected it by 0.84 m. As a check, five scanned tree trunks sit a median 1.2 m from their NYC Forestry points. Heights are relative to park grade (NAVD88 ≈ 5.28 m from planimetric spot elevations).

**Inferred surfaces.** The oval (lawn, ring path, benches, spray pad) is mirror-symmetric about an axis at x ≈ 31.7 m, which lines up with the courthouse entrance. The axis was found by maximizing agreement between the scan and its mirror image (89.5% of 272 m² of overlap). Mirrored triangles fill only places the scan did not reach inside the oval. The unscanned lawn interior is a flat surface at the measured lawn height. All of these surfaces use the `inferred` material.

**Park layer.** `data/park-detail.geojson` holds the measured lawn oval (≈ 22.8 × 21.9 m), ring path (≈ 2.4 m wide), spray pad (15.5 × 5.7 m), 14 benches (8 scanned, 6 mirrored), 4 game tables, the game-table and bistro plazas (approximate rectangles) and one pole. It also holds 23 NYC Forestry trees with crowns estimated from DBH. Three blue spruces still listed in the Forestry data stood where the new lawn and spray pad are; they are not on the scan and are omitted.

**Limits.** The scan is a field record, not a survey. The western planting beds, most of the courthouse forecourt and part of the Jackson Avenue sidewalk were not scanned. Tree canopies above about 3 m are not captured. Crown sizes are estimates. Vehicles on the roadbed were removed; anything else present during the scan, on sidewalks or in the park, remains.

## LOD3 site model

`data/modeling/court_square_park_LOD3.3dm` is rebuilt from the measurements above by `tools/scan-pipeline/build_model.py`.

**Ground.** Ground surfaces are flat by type: roadbed −0.15 m; sidewalks, forecourt and park paving 0; planting +0.05 m; lawn +0.03 m; spray pad −0.02 m. The 15 cm difference forms the curb. The real site falls about 0.4 m from Jackson Avenue to the courthouse (NYC spot elevations are on a reference layer).

**Layout sources.**
- Park paving combines the ring path, the plazas, the south entrance and the two Jackson Avenue paths, all read off the scan ortho to about ±0.3 m.
- Sidewalks come from NYC planimetrics, with the pre-2025 park paths still in that dataset removed.
- Benches, tables and bollards sit at their scanned positions; mirrored benches are on their own layer.

**Estimated.** The courthouse stair (10 risers, 9 m wide, from photos), the lamp height and the bus shelter size are estimates and are marked approx. Tree crowns are estimated from DBH. Buildings are footprint extrusions to recorded roof height.

Google Maps, Apple Maps and game interfaces informed the visual direction. Geographic geometry comes from the NYC datasets above; no Google or Apple map geometry is included.

The snapshot is not a current-condition field survey. Refer to the original publishers for data definitions, updates and applicable terms.
