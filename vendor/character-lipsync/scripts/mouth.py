"""2D cartoon mouth-opening warp for a single static character image.

open_mouth(img_rgba, lips, h) -> RGBA numpy array with the mouth opened by h pixels.

lips = ((x0, y0), (x1, y1)): left and right CORNERS of the dark line between the lips,
in source-image pixels. Everything else is derived from the lip width, so the same
code works for any resolution.

How it works:
 1. Displacement warp: pixels BELOW the lip line (lower lip, chin, beard) slide down by
    up to h px. The shift is 1.0 right under the line, fades to 0 about 0.95 lip-widths
    below, and fades sideways with a cosine window, so the jaw drops softly and the
    mouth corners stay pinned.
 2. A dark cavity (lens shape) is painted between the upper lip line and the shifted
    lower lip, then a tongue (lower half-ellipse), an upper-teeth strip, and a dark
    outline in the character's line-art colour.
"""
import numpy as np
import cv2

CAVITY = (58, 22, 26)      # mouth interior (dark maroon)
TONGUE = (196, 92, 92)
TEETH = (248, 244, 236)
OUTLINE = (25, 12, 12)


def open_mouth(img, lips, h, curve=None, cavity=CAVITY, tongue=TONGUE, teeth=TEETH, outline=OUTLINE):
    if h < 1:
        return img
    (x0, y0), (x1, y1) = lips
    W = float(x1 - x0)
    k = W / 145.0                      # all constants were tuned on a 145 px wide mouth
    cx = (x0 + x1) / 2.0
    slope = (y1 - y0) / (x1 - x0)
    # линия губ на cartoon-иллюстрациях изогнута: y = c0 + c1*dx + c2*dx^2
    c0, c1, c2 = curve if curve is not None else ((y0 + y1) / 2.0, slope, 0.0)

    # work only on a window around the mouth (fast)
    X0 = int(max(0, x0 - 40 * k)); X1 = int(min(img.shape[1], x1 + 40 * k))
    Y0 = int(max(0, min(y0, y1) - 30 * k)); Y1 = int(min(img.shape[0], max(y0, y1) + 160 * k))
    sub = img[Y0:Y1, X0:X1].copy()
    hh, ww = sub.shape[:2]

    xs, ys = np.meshgrid(np.arange(ww, dtype=np.float32) + X0, np.arange(hh, dtype=np.float32) + Y0)
    dxs = xs - cx
    yl = c0 + c1 * dxs + c2 * dxs * dxs                 # lip line y at each column
    u = (xs - cx) / (W / 2)                             # -1..1 across the mouth
    wx = np.clip(np.cos(np.clip(u, -1.25, 1.25) * np.pi / 2.5), 0, 1) ** 1.5
    v = ys - yl                                         # distance below the lip line
    near, fall = 25 * k, 115 * k
    wy = np.where(v < 0, 0, np.where(v < near, 1, np.clip(1 - (v - near) / fall, 0, 1)))
    wy = wy * wy * (3 - 2 * wy)                         # smoothstep
    dy = h * wx * wy
    out = cv2.remap(sub, xs - X0, (ys - dy) - Y0, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    # cavity polygon
    top, bot = [], []
    for xx in np.linspace(x0 + 10 * k, x1 - 10 * k, 40):
        uu = (xx - cx) / (W / 2)
        w = max(0.0, np.cos(uu * np.pi / 2.5)) ** 1.5
        ddx = xx - cx
        yy = c0 + c1 * ddx + c2 * ddx * ddx
        ex = h * 0.94 * w
        top.append((xx - X0, yy - Y0 - 0.18 * ex + 1))
        bot.append((xx - X0, yy - Y0 + ex * 0.9))
    poly = np.array(top + bot[::-1], np.float32)
    P = lambda p: np.round(p * 4).astype(np.int32)     # sub-pixel (shift=2)

    mask = np.zeros((hh, ww), np.uint8)
    cv2.fillPoly(mask, [P(poly)], 255, cv2.LINE_AA, shift=2)
    tmask = np.zeros((hh, ww), np.uint8)
    tc = (int(cx - X0), int(c0 - Y0 + h * 0.85))
    cv2.ellipse(tmask, tc, (int(W * 0.27), max(2, int(h * 0.38))), float(np.degrees(np.arctan(slope))),
                180, 360, 255, -1, cv2.LINE_AA)
    temask = np.zeros((hh, ww), np.uint8)
    tp = poly[:40].copy(); bp = tp.copy(); bp[:, 1] += min(h * 0.28, 9 * k)
    cv2.fillPoly(temask, [P(np.concatenate([tp[6:34], bp[6:34][::-1]]))], 255, cv2.LINE_AA, shift=2)
    olmask = np.zeros((hh, ww), np.uint8)
    cv2.polylines(olmask, [P(poly)], True, 255, max(2, int(round(3 * k))), cv2.LINE_AA, shift=2)

    out = out.astype(np.float32)
    m = mask.astype(np.float32) / 255
    def paint(alpha, col):
        out[..., :3] = out[..., :3] * (1 - alpha[..., None]) + np.array(col, np.float32) * alpha[..., None]
    paint(m, cavity)
    paint(tmask / 255.0 * m, tongue)
    paint(temask / 255.0 * m, teeth)
    paint(olmask / 255.0 * 0.85, outline)
    res = img.copy()
    res[Y0:Y1, X0:X1] = np.clip(out, 0, 255).astype(np.uint8)
    return res
