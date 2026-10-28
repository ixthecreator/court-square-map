# Geographic data and interpretation

Snapshot retrieved **October 28, 2026**. Coordinates use WGS84 longitude and latitude and are projected locally with D3's Mercator projection.

## Official NYC sources

| Dataset | Used for |
| --- | --- |
| [NYC BUILDING, Office of Technology and Innovation](https://data.cityofnewyork.us/City-Government/BUILDING/5zhs-2jue) | Building footprints and roof heights |
| [NYC Centerline / CSCL](https://data.cityofnewyork.us/City-Government/Centerline/inkn-q76z) | Street geometry and recorded paved widths |
| [NYC Parks Properties](https://data.cityofnewyork.us/Recreation/Parks-Properties/enfh-gkve) | Court Square Park, property Q267 |
| [2020 Neighborhood Tabulation Areas, NYC Department of City Planning, version 26b](https://data.cityofnewyork.us/City-Government/2020-Neighborhood-Tabulation-Areas-NTAs-/9nt8-h7nd) | Study-area boundary |

## Coverage

The union of **QN0201 Long Island City–Hunters Point** and **QN0105 Queensbridge–Ravenswood–Dutch Kills** defines the approximately **5.139 km²** study area. Its bounding box is approximately `[-73.962620, 40.737900, -73.924157, 40.771271]`. This statistical extent does not imply a single universally accepted neighborhood boundary.

The map includes **3,699 building footprints** and **1,213 street segments**. Buildings intersecting the study area retain their entire footprints; streets are clipped to the boundary. No synthetic buildings are added. Coordinate rounding is to seven decimal places; two resulting geometry validity issues were repaired during preparation.

Court Square Park's official polygon has center `[-73.943459, 40.746356]` and recorded area **0.492 acres**. The interior remains empty for future field-scanned detail.

## Heights and simplification

- `HEIGHT_ROOF` is relative to local ground, not sea level. Original feet are converted to metres using `0.3048`. Ground elevation is not subtracted. See the [official building footprint metadata](https://github.com/CityOfNewYork/nyc-geo-metadata/blob/main/Metadata/Metadata_BuildingFootprints.md).
- Nine buildings have missing or zero roof heights and remain flat. The maximum recorded height in the snapshot is 242.01 metres. Some records describe buildings under construction.
- The slider multiplies displayed heights from zero to the recorded values. This is a visual control, not a change to the source data.
- Buildings are footprint extrusions, without reconstructed facades, roof details or terrain. Distant buildings may use simpler display detail.
- Street widths come from recorded paved-width values in feet, converted to metres. Missing widths receive a symbolic display width. See the [Geosupport User Programming Guide](https://www.nyc.gov/assets/planning/download/pdf/data-maps/open-data/upg.pdf?r=16b), page 276.
- All streets are displayed on one plane. Source level codes are ordinal identifiers, not heights in metres; elevated roads and rail infrastructure are not reconstructed.
- Boundary edges describe the selected coverage, including inland edges. The background is not an authoritative water mask.

Google Maps, Apple Maps and game interfaces informed the visual direction. Geographic geometry comes from the NYC datasets above; no Google or Apple map geometry is included.

The snapshot is not a current-condition field survey. Refer to the original publishers for data definitions, updates and applicable terms.
