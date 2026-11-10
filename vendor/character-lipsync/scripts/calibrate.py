"""Calibration helpers for finding the lip-line corners of each pose.

1) Grid view (read coordinates off it):
   python3 calibrate.py grid pose.png --out grid.png [--box x0 y0 x1 y1] [--step 50]
   Draws a labelled pixel grid over the image (or over a zoomed box) so a vision model or
   a human can read the exact coordinates of the two mouth corners.

2) Check view (verify lips + preview openings):
   python3 calibrate.py check pose.png --lips x0 y0 x1 y1 --out check.png [--hmax-ratio 0.186]
   Row 1: crop with red circles on the corners you supplied (must sit exactly on the ends
   of the dark line between the lips).  Row 2: mouth opened at 0, 33, 66, 100 % of hmax.
"""
import argparse, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mouth import open_mouth


def on_white(im):
    bg = Image.new('RGBA', im.size, (255, 255, 255, 255)); bg.alpha_composite(im.convert('RGBA'))
    return bg.convert('RGB')


def grid(a):
    im = Image.open(a.image).convert('RGBA')
    x0, y0, x1, y1 = a.box or (0, 0, im.width, im.height)
    crop = on_white(im.crop((x0, y0, x1, y1)))
    z = max(1, int(900 / max(crop.size)))            # zoom small boxes
    crop = crop.resize((crop.width * z, crop.height * z), Image.NEAREST)
    d = ImageDraw.Draw(crop); f = ImageFont.load_default()
    st = a.step
    for gx in range((x0 // st) * st, x1 + 1, st):
        if gx < x0: continue
        X = (gx - x0) * z
        d.line([(X, 0), (X, crop.height)], fill=(255, 0, 0) if gx % (st * 2) == 0 else (255, 150, 150), width=1)
        d.text((X + 2, 2), str(gx), fill=(200, 0, 0), font=f)
    for gy in range((y0 // st) * st, y1 + 1, st):
        if gy < y0: continue
        Y = (gy - y0) * z
        d.line([(0, Y), (crop.width, Y)], fill=(0, 0, 255) if gy % (st * 2) == 0 else (150, 150, 255), width=1)
        d.text((2, Y + 2), str(gy), fill=(0, 0, 200), font=f)
    crop.save(a.out); print('saved', a.out, 'zoom', z)


def check(a):
    img = np.array(Image.open(a.image).convert('RGBA'))
    x0, y0, x1, y1 = a.lips
    lips = ((x0, y0), (x1, y1))
    W = x1 - x0; cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    r = int(W * 1.05)
    box = (cx - r, cy - r, cx + r, cy + r)
    hmax = W * a.hmax_ratio
    tiles = []
    t0 = on_white(Image.fromarray(img).crop(box)); d = ImageDraw.Draw(t0)
    for (x, y) in lips:
        X, Y = x - box[0], y - box[1]
        d.ellipse((X - 5, Y - 5, X + 5, Y + 5), outline=(255, 0, 0), width=2)
    tiles.append(t0)
    for frac in (0, 0.33, 0.66, 1.0):
        tiles.append(on_white(Image.fromarray(open_mouth(img, lips, hmax * frac)).crop(box)))
    s = 2 * r
    sheet = Image.new('RGB', (s * 5, s), 'white')
    for i, t in enumerate(tiles): sheet.paste(t, (i * s, 0))
    sheet.save(a.out); print('saved', a.out, 'lip width', W, 'hmax px', round(hmax, 1))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); sp = p.add_subparsers(dest='cmd', required=True)
    g = sp.add_parser('grid'); g.add_argument('image'); g.add_argument('--out', required=True)
    g.add_argument('--box', type=int, nargs=4); g.add_argument('--step', type=int, default=50)
    c = sp.add_parser('check'); c.add_argument('image'); c.add_argument('--out', required=True)
    c.add_argument('--lips', type=int, nargs=4, required=True); c.add_argument('--hmax-ratio', type=float, default=0.186)
    a = p.parse_args(); grid(a) if a.cmd == 'grid' else check(a)
