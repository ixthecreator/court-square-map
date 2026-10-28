"""Render plan PNGs: official base plan, and the LiDAR ortho with the base plan on top.

Usage: python3 scripts/render_plans.py [u0 v0 u1 v1]   (crop window in park-frame meters)
"""
import json, math, os, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
site = json.load(open(os.path.join(ROOT, 'model', 'site_local.json')))
PX = 0.04
U0, V0, U1, V1 = -40, -40, 90, 80          # must match register_scan.py raster
crop = [float(c) for c in sys.argv[1:5]] if len(sys.argv) >= 5 else [-22, -30, 72, 62]


def to_px(u, v):
    return ((u - U0) / PX, (V1 - v) / PX)


def font(sz):
    for f in ['/System/Library/Fonts/Helvetica.ttc', '/System/Library/Fonts/Supplemental/Arial.ttf']:
        if os.path.exists(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default()


def draw_base(img, light=False):
    d = ImageDraw.Draw(img, 'RGBA')
    W = lambda w: max(1, int(w))
    for r in site['sidewalks']:
        d.polygon([to_px(*p) for p in r], fill=None if light else (236, 236, 232, 255), outline=(150, 150, 150, 200))
    for b in site['buildings']:
        for r in b['rings']:
            d.polygon([to_px(*p) for p in r], fill=(120, 120, 130, 40) if light else (205, 200, 195, 255), outline=(60, 60, 70, 255))
    for r in site['curbs']:
        d.line([to_px(*p) for p in r], fill=(230, 60, 40, 255), width=W(4))
    d.line([to_px(*p) for p in site['park']], fill=(20, 140, 60, 255), width=W(6))
    for t in site['trees']:
        x, y = to_px(t['x'], t['y'])
        if t['status'] == 'Full':
            r = t['crown_d_m'] / 2 / PX
            d.ellipse([x - r, y - r, x + r, y + r], outline=(30, 120, 40, 220), fill=None if light else (90, 170, 90, 60), width=W(3))
            d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(20, 90, 30, 255))
        else:
            d.line([x - 10, y - 10, x + 10, y + 10], fill=(160, 0, 0, 255), width=4)
            d.line([x - 10, y + 10, x + 10, y - 10], fill=(160, 0, 0, 255), width=4)
    f = font(46)
    for s, u, v in [('JACKSON AVE', 8, 47), ('COURT SQ W', -15, 14), ('THOMSON AVE', 52, 22), ('COURTHOUSE', 14, -24)]:
        d.text(to_px(u, v), s, fill=(40, 40, 40, 255), font=f)
    return d


def furniture(d):
    # scale bar 10 m and north arrow, placed in crop coordinates
    x0, y0 = to_px(crop[0] + 2, crop[1] + 2)
    d.rectangle([x0, y0 - 14, x0 + 5 / PX, y0], fill=(0, 0, 0, 255))
    d.rectangle([x0 + 5 / PX, y0 - 14, x0 + 10 / PX, y0], outline=(0, 0, 0, 255), fill=(255, 255, 255, 255), width=3)
    d.text((x0, y0 - 60), '0      5     10 m', fill=(0, 0, 0, 255), font=font(38))
    cx, cy = to_px(crop[2] - 5, crop[3] - 6)
    a = math.radians(site['frame']['north_cw_from_y'])
    L = 3 / PX
    tip = (cx + L * math.sin(a), cy - L * math.cos(a))
    d.line([cx, cy, *tip], fill=(0, 0, 0, 255), width=6)
    d.polygon([tip, (tip[0] - 25 * math.cos(a) - 30 * math.sin(a), tip[1] - 25 * math.sin(a) + 30 * math.cos(a)),
               (tip[0] + 25 * math.cos(a) - 30 * math.sin(a), tip[1] + 25 * math.sin(a) + 30 * math.cos(a))], fill=(0, 0, 0, 255))
    d.text((tip[0] + 10, tip[1] - 50), 'N', fill=(0, 0, 0, 255), font=font(50))


def crop_box():
    a, b = to_px(crop[0], crop[3]); c, e = to_px(crop[2], crop[1])
    return tuple(int(x) for x in (a, b, c, e))


W, H = int((U1 - U0) / PX), int((V1 - V0) / PX)
os.makedirs(os.path.join(ROOT, 'plans'), exist_ok=True)

base = Image.new('RGB', (W, H), (250, 250, 247))
d = draw_base(base)
furniture(d)
base.crop(crop_box()).save(os.path.join(ROOT, 'plans', 'site_base_plan.png'))

ortho_p = os.path.join(ROOT, 'scan', 'ortho_rgb.png')
if os.path.exists(ortho_p):
    ov = Image.open(ortho_p).convert('RGB')
    d = draw_base(ov, light=True)
    tr = json.load(open(os.path.join(ROOT, 'scan', 'trajectory_site.json')))['xy']
    d.line([to_px(*p) for p in tr], fill=(40, 90, 255, 160), width=3)
    furniture(d)
    ov.crop(crop_box()).save(os.path.join(ROOT, 'plans', 'scan_overlay.png'))
    Image.open(ortho_p).crop(crop_box()).save(os.path.join(ROOT, 'plans', 'scan_ortho_rgb.png'))
    Image.open(os.path.join(ROOT, 'scan', 'ortho_height.png')).crop(crop_box()).save(os.path.join(ROOT, 'plans', 'scan_ortho_height.png'))
feat_p = os.path.join(ROOT, 'scan', 'features.json')
comp_p = os.path.join(ROOT, 'scan', 'ortho_completed.png')
if os.path.exists(feat_p) and os.path.exists(comp_p):
    feat = json.load(open(feat_p))
    im = Image.open(comp_p).convert('RGB')
    im = Image.blend(im, Image.new('RGB', im.size, (255, 255, 255)), 0.35)
    d = draw_base(im, light=True)
    d.line([to_px(*p) for p in feat['lawn_pts']], fill=(0, 150, 60, 255), width=6)
    lw, rg = feat['lawn_oval'], feat['ring_outer']
    c, s = math.cos(math.radians(rg['theta_deg'])), math.sin(math.radians(rg['theta_deg']))
    ring_pts = [(rg['cx'] + rg['a'] * math.cos(t) * c - rg['b'] * math.sin(t) * s,
                 rg['cy'] + rg['a'] * math.cos(t) * s + rg['b'] * math.sin(t) * c) for t in [i * math.pi / 48 for i in range(97)]]
    d.line([to_px(*p) for p in ring_pts], fill=(90, 90, 90, 255), width=4)
    if feat.get('spray_pad'):
        d.polygon([to_px(*p) for p in feat['spray_pad']['hull']], outline=(30, 110, 230, 255), fill=(80, 150, 255, 60), width=5)
    sym = feat.get('symmetry')
    if sym:
        t = math.radians(90 + sym['tilt_deg'])
        a0 = (sym['axis_u'] - 20 * math.cos(t), sym['axis_v'] - 20 * math.sin(t)); a1 = (sym['axis_u'] + 16 * math.cos(t), sym['axis_v'] + 16 * math.sin(t))
        for k in range(0, 36, 2):
            p = (a0[0] + (a1[0] - a0[0]) * k / 36, a0[1] + (a1[1] - a0[1]) * k / 36)
            q = (a0[0] + (a1[0] - a0[0]) * (k + 1) / 36, a0[1] + (a1[1] - a0[1]) * (k + 1) / 36)
            d.line([to_px(*p), to_px(*q)], fill=(200, 0, 160, 255), width=4)
    colors = {'bench': (150, 75, 20), 'game table + seats': (120, 40, 160), 'pole (lamp / sign)': (230, 160, 0),
              'tree trunk': (20, 90, 30), 'tall object': (90, 90, 90), 'low object': (120, 120, 120)}
    for o in feat['objects']:
        col = colors.get(o['kind'])
        if not col:
            continue
        hd = math.radians(o['heading_deg']); c, s = math.cos(hd), math.sin(hd)
        hl, hw = max(o['length_m'], 0.3) / 2, max(o['width_m'], 0.3) / 2
        pts = [to_px(o['x'] + dx * c - dy * s, o['y'] + dx * s + dy * c) for dx, dy in [(-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw)]]
        if o.get('mirrored'):
            d.polygon(pts, outline=col + (255,), fill=(255, 255, 255, 200), width=4)
        else:
            d.polygon(pts, fill=col + (255,))
    f = font(40)
    notes = [('Central lawn  ~%.0f x %.0f m' % (2 * lw['a'], 2 * lw['b']), lw['cx'] - 8.5, lw['cy'] + 3), ('ring path ~%.1f m wide' % rg.get('path_width_m', 2.4), lw['cx'] - 7.5, lw['cy'] + 0.6),
             ('Spray pad', (feat['spray_pad']['u_min'] + feat['spray_pad']['u_max']) / 2 - 3.5, feat['spray_pad']['v_min'] - 0.6) if feat.get('spray_pad') else None,
             ('Game tables', 11.5, 27.5), ('Bistro area', 44.5, 27.6),
             ('Symmetry axis', sym['axis_u'] + 0.6, sym['axis_v'] + 16.6) if sym else None, ('Bus shelter', 46, 44.5)]
    for n in notes:
        if n:
            x, y = to_px(n[1], n[2])
            d.text((x, y), n[0], fill=(20, 20, 20, 255), font=f, stroke_width=4, stroke_fill=(255, 255, 255, 255))
    furniture(d)
    legend = [((0, 150, 60), 'lawn edge (scan fit)'), ((90, 90, 90), 'ring path outer edge'), ((30, 110, 230), 'spray pad (scan)'),
              ((150, 75, 20), 'bench: solid = scanned'), ((150, 75, 20), 'bench: outline = mirrored', True), ((120, 40, 160), 'game table + seats'),
              ((230, 160, 0), 'lamp / sign pole'), ((20, 90, 30), 'tree (NYC Forestry point,'), (None, '  canopy circle = estimate)'),
              ((160, 0, 0), 'removed tree / stump (x)'), ((230, 60, 40), 'curb (NYC planimetrics)'), ((20, 140, 60), 'park property line'),
              ((200, 0, 160), 'symmetry axis (dashed)'), ((150, 170, 230), 'blue tint = mirrored fill'), ((140, 180, 110), 'flat green = synthetic lawn')]
    body = im.crop(crop_box())
    panel = 1000
    out = Image.new('RGB', (body.width + panel, body.height), (255, 255, 255))
    out.paste(body, (0, 0))
    d2 = ImageDraw.Draw(out)
    lx, ly = body.width + 50, 60
    d2.text((lx, ly), 'Court Square Park', fill=(0, 0, 0), font=font(60))
    d2.text((lx, ly + 75), 'as-built 2026-10-28 (iPhone LiDAR)', fill=(60, 60, 60), font=font(36))
    d2.text((lx, ly + 120), 'park frame, meters; origin = Court Sq W', fill=(60, 60, 60), font=font(36))
    d2.text((lx, ly + 165), 'x courthouse-side park corner', fill=(60, 60, 60), font=font(36))
    ly += 260
    for i, item in enumerate(legend):
        col, txt = item[0], item[1]
        y = ly + i * 58
        if col and len(item) > 2:
            d2.rectangle([lx, y + 8, lx + 70, y + 40], outline=col, fill=(255, 255, 255), width=5)
        elif col:
            d2.rectangle([lx, y + 8, lx + 70, y + 40], fill=col)
        d2.text((lx + 95, y), txt, fill=(0, 0, 0), font=font(38))
    out.save(os.path.join(ROOT, 'plans', 'annotated_plan.png'))
    Image.open(comp_p).crop(crop_box()).save(os.path.join(ROOT, 'plans', 'scan_ortho_completed.png'))
print('crop', crop, crop_box())
