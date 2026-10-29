"""Parks rules sign texture from a field photo: straighten the panel, take the sky glare off, write a JPEG for the model.

The photo (IMG_5373, iPhone 16 Pro at 35 mm equivalent, 2026-10-28 11:54, facing the courthouse from the Jackson Ave side)
stays out of the repo because it carries GPS. Convert it first:  sips -s format jpeg IMG_5373.HEIC --out IMG_5373.jpg

- the four panel corners were picked on the full-resolution photo
- the panel's width/height comes from the corners and the camera's focal length (plane-to-image homography),
  so it is measured, not assumed; the edges come out 90.4 deg apart, which checks the focal length
- glare: the dark panel is flattened to its least-lit level using a smooth field fitted to background pixels only
  (text, rules and the leaf logo are masked out), then levels map panel to charcoal and lettering to off-white

Usage: python scripts/sign_texture.py IMG_5373.jpg   (needs opencv-python)
Writes photos/court_square_park_sign.jpg (2048 px wide, no EXIF) and prints the panel's width/height ratio.
"""
import os, sys
import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parkframe import ROOT

CORNERS = [(49, 970), (5577, 803), (5498, 4055), (205, 4010)]   # TL TR BR BL, pixels in the 5712 x 4284 photo
FOCAL_35MM = 35
OUT_W = 2048
# text blocks and rules on the straightened panel (fractions of width, height): logo column, English/Spanish, icons, Chinese,
# part number, the rule between the middle and right columns, the rule above the icons
TEXT = [(0, 0, 0.335, 1), (0.355, 0.05, 0.63, 0.82), (0.355, 0.86, 0.63, 0.99), (0.685, 0.04, 0.95, 0.43), (0.955, 0.93, 1, 1),
        (0.656, 0, 0.668, 1), (0.33, 0.845, 0.67, 0.865)]


def panel_aspect(corners, w, h, f35):
    """Width/height of the rectangle seen at these corners, for a camera with this 35 mm equivalent focal length."""
    f = f35 / np.hypot(36, 24) * np.hypot(w, h)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1]])
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]), np.float32(corners))
    G = np.linalg.inv(K) @ H
    r1, r2 = G[:, 0], G[:, 1]
    return np.linalg.norm(r1) / np.linalg.norm(r2), float(np.degrees(np.arccos(r1 @ r2 / np.linalg.norm(r1) / np.linalg.norm(r2))))


def norm_blur(x, m, sigma):
    """Gaussian average of x over the pixels where m is set (normalized convolution)."""
    num = cv2.GaussianBlur(x * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    return num / np.maximum(den, 1e-3)


def main(src):
    im = cv2.imread(src, cv2.IMREAD_COLOR)
    h, w = im.shape[:2]
    aspect, corner = panel_aspect(CORNERS, w, h, FOCAL_35MM)
    # straighten at full resolution, trim a hair off the edges (post wood and background), then scale down
    fw = int(round(np.mean([CORNERS[1][0] - CORNERS[0][0], CORNERS[2][0] - CORNERS[3][0]])))
    fh = int(round(fw / aspect))
    M = cv2.getPerspectiveTransform(np.float32(CORNERS), np.float32([[0, 0], [fw, 0], [fw, fh], [0, fh]]))
    flat = cv2.warpPerspective(im, M, (fw, fh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    t = int(fw * 0.003)
    flat = flat[t:fh - t, t:fw - t]
    oh = int(round(OUT_W / aspect))
    flat = cv2.resize(flat, (OUT_W, oh), interpolation=cv2.INTER_AREA)

    lab = cv2.cvtColor(flat, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[..., 0]
    # lettering, rules and logo: brighter than their surroundings, or bright outright (the big leaf)
    ink = (L > cv2.GaussianBlur(L, (0, 0), 12) + 14) | (L > 150)
    ink = cv2.dilate(ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    m = (~ink).astype(np.float32)
    near, wide = norm_blur(L, m, 8), norm_blur(L, m, 40)       # inside the big leaf there is no panel nearby: use the wide field
    k = np.clip(cv2.GaussianBlur(m, (0, 0), 8) / 0.3, 0, 1)
    bg = k * near + (1 - k) * wide
    floor = np.percentile(bg, 5)
    d = L - bg                                                 # lettering stands well above the panel; scratches lit by the sky
    g = np.maximum(bg - floor, 0)                              # are fainter, but brighter where the glare is strong,
    text = np.zeros_like(L)                                    # so the cut-off rises with the glare: gently inside the text
    H_, W_ = L.shape                                           # blocks (thin strokes), steeply on the empty panel
    for x0, y0, x1, y1 in TEXT:
        text[int(y0 * H_):int(y1 * H_), int(x0 * W_):int(x1 * W_)] = 1
    rise = 2.0 - 1.6 * cv2.GaussianBlur(text, (0, 0), 6)
    t0, t1 = 18 + rise * g, 55 + rise * g
    gate = np.clip((d - t0) / (t1 - t0), 0, 1); gate = gate * gate * (3 - 2 * gate)
    L = floor + 0.12 * (bg - floor) + d * gate                 # flat panel (a trace of the glare kept), lettering kept
    lo = floor
    hi = np.percentile(L[ink & (d > 60)], 90)
    y = np.clip((L - lo) / (hi - lo), 0, 1) ** 0.9            # panel -> charcoal, lettering -> off-white
    L = 40 + y * (238 - 40)
    L = L + 0.5 * (L - cv2.GaussianBlur(L, (0, 0), 1.2))      # light unsharp mask
    lab[..., 0] = np.clip(L, 0, 255)
    lab[..., 1:] = 128 + (lab[..., 1:] - 128) * 0.25         # sky tint off, a trace of the panel's colour left
    out = cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)
    dst = os.path.join(ROOT, 'photos', 'court_square_park_sign.jpg')
    cv2.imwrite(dst, out, [cv2.IMWRITE_JPEG_QUALITY, 88, cv2.IMWRITE_JPEG_PROGRESSIVE, 1])
    print(f'panel width/height {aspect:.3f} (edges {corner:.1f} deg apart) -> {dst} {OUT_W}x{oh}, {os.path.getsize(dst) / 1e3:.0f} kB')


if __name__ == '__main__':
    main(sys.argv[1])
