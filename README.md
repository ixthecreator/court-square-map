# Court Square Park / Long Island City

A fullscreen, interactive map of Long Island City and a local 3D scan viewer for Court Square Park. The map uses real NYC building footprints, roof heights and street geometry. The park stays highlighted in red and is reserved for field-scanned detail.

**Website:** https://ixthecreator.github.io/court-square-map/

## Use

- Drag to pan; Shift + drag to orbit. Scroll or use + / − to zoom.
- Select **LIC** for the full study area or **Park** for the park close-up.
- Move the height slider between flat footprints and the recorded roof heights.
- Select the red park or **Scan** to open the scan viewer.
- Use the pin button to add an observation inside the park. In a loaded scan, choose **Add note** and click a solid model surface.

Camera preferences, height settings and up to 12 observation drafts are stored in the browser on this device. Clearing browser storage removes them. Imported model files remain local to the current session and are not uploaded or saved by this site.

## Import a scan

Choose **Scan → Import scan** and select a self-contained `.glb` file, up to 100 MB. The viewer requires embedded geometry and PNG/JPEG textures. Draco, KTX/Basis and Meshopt compression, external resources, `.gltf` bundles and ZIP archives are not accepted by this version. Convert a glTF bundle to an uncompressed, embedded GLB before importing.

The city map and scan viewer use separate coordinate systems. Surface notes stay attached to the selected scan filename; the model is not georeferenced onto the city map. No actual field scan is bundled yet.

## Data

Coverage follows the union of the 2020 NYC NTA areas **Long Island City–Hunters Point** and **Queensbridge–Ravenswood–Dutch Kills**, approximately 5.14 km². This is an explicit study-area definition, not a claim that LIC has one universally agreed boundary.

The embedded data snapshot contains **3,699 building footprints** and **1,213 street segments**, retrieved October 28, 2026. See [DATA_SOURCES.md](DATA_SOURCES.md) for sources, height interpretation and limitations.

## Run and publish

This is a static website. Serve the directory over HTTP, for example:

```sh
python -m http.server 8000
```

Open `http://localhost:8000`. No build step or API key is required. Internet access is needed to load the pinned D3 and model-viewer libraries and the icon runtime from their CDNs.

GitHub Pages publishes the repository root on **`codex/github-pages`**. `.nojekyll` enables direct static-file publishing.

Modern browsers with Canvas 2D, WebGL, and `DecompressionStream` are required. Large scans may need cropping or simplification before import on a phone.
