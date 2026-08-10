"""Brand asset generator for the Culligan (Azure) integration.

    python generate.py                 # contact sheet into ./preview for review
    python generate.py --final tank    # write the PNGs into the integration's
                                       # brand/ folder, ready to ship

The art is original: a stylized front view of a cabinet-style water softener -
the tall brine cabinet with its valve head, control display and a water-drop
motif. It is deliberately NOT an imitation of Culligan's own logo or trade
dress; the wordmark is plain text identifying which devices the integration
supports (nominative use), not a reproduction of their branding.

Home Assistant 2026.3+ serves these from custom_components/culligan_azure/brand/
via the Brands Proxy API - local brand images take priority over the brands CDN
with no configuration, and home-assistant/brands stopped accepting
custom-integration PRs in Feb 2026. On older HA versions the folder is inert, so
shipping it is safe either way.

Pillow only. Everything is drawn at 4x and downsampled, which is what keeps the
curves and the thin highlight lines clean at 256px.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "preview")
SHIP = os.path.join(
    os.path.dirname(HERE), "custom_components", "culligan_azure", "brand"
)

# ---------------------------------------------------------------- palette
# The real unit is charcoal, not silver: a narrow resin tank with the valve
# head on top, beside a wider brine tank.
TANK_LIT = (104, 110, 118)     # cylinder highlight, lit from the left
TANK_MID = (72, 78, 86)
TANK_DARK = (38, 42, 48)       # cylinder edges, in shadow
BRINE_LIT = (92, 98, 106)      # brine tank reads slightly flatter than the
BRINE_MID = (62, 68, 75)       # resin tank - larger radius, less curvature
BRINE_DARK = (32, 36, 41)
HEAD_TOP = (222, 226, 232)     # valve head casting, pale grey
HEAD_BOT = (168, 175, 184)
HEAD_EDGE = (132, 140, 150)
SCREEN_TOP = (58, 150, 226)    # control display blue
SCREEN_BOT = (24, 86, 158)
COLLAR = (46, 52, 60)          # collar where the head meets the tank
WHITE = (255, 255, 255)
INK = (28, 34, 44)             # wordmark on light backgrounds


def vgrad(size, top, bot):
    """Vertical linear gradient as an RGBA image."""
    w, h = size
    img = Image.new("RGBA", (1, h))
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = (
            int(top[0] + (bot[0] - top[0]) * t),
            int(top[1] + (bot[1] - top[1]) * t),
            int(top[2] + (bot[2] - top[2]) * t),
            255,
        )
    return img.resize((w, h), Image.NEAREST)


def rounded_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius, 255)
    return m


def paste_rounded_grad(base, box, radius, top, bot):
    x0, y0, x1, y1 = box
    size = (x1 - x0, y1 - y0)
    if size[0] <= 0 or size[1] <= 0:
        return
    base.paste(vgrad(size, top, bot), (x0, y0), rounded_mask(size, radius))


def hgrad(size, left, mid, right):
    """Horizontal three-stop gradient - this is what makes a flat rectangle
    read as a cylinder. A vertical gradient alone looks like a slab."""
    w, h = size
    img = Image.new("RGBA", (w, 1))
    px = img.load()
    for x in range(w):
        t = x / max(1, w - 1)
        if t < 0.5:
            u = t / 0.5
            a, b = left, mid
        else:
            u = (t - 0.5) / 0.5
            a, b = mid, right
        px[x, 0] = (
            int(a[0] + (b[0] - a[0]) * u),
            int(a[1] + (b[1] - a[1]) * u),
            int(a[2] + (b[2] - a[2]) * u),
            255,
        )
    return img.resize((w, h), Image.NEAREST)


def paste_cylinder(base, box, radius, lit, mid, dark):
    """A vertical cylinder: rounded rect filled with a horizontal gradient."""
    x0, y0, x1, y1 = box
    size = (x1 - x0, y1 - y0)
    if size[0] <= 0 or size[1] <= 0:
        return
    base.paste(hgrad(size, dark, lit, mid), (x0, y0), rounded_mask(size, radius))


def draw_device(canvas_w, canvas_h, variant="tank"):
    """Draw the softener centered on a transparent canvas.

    Layout matches the real hardware: a NARROW resin tank on the left carrying
    the valve head and its display, standing beside a WIDER brine tank. Getting
    this wrong (one cabinet, or the head centred over both) is what makes these
    icons unrecognisable.
    """
    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    base_y = int(canvas_h * 0.92)          # both tanks stand on this line
    gap = int(canvas_w * 0.025)

    # Resin tank: narrow and tall, topped by the valve head.
    res_w = int(canvas_w * 0.30)
    res_top = int(canvas_h * 0.30)
    res_x0 = int(canvas_w * 0.10)
    res_r = res_w // 2                     # fully round top = cylinder

    # Brine tank: wider, and its shoulder sits lower than the resin tank's.
    brine_w = int(canvas_w * 0.42)
    brine_top = int(canvas_h * 0.38)
    brine_x0 = res_x0 + res_w + gap
    brine_r = int(brine_w * 0.22)

    head_w = int(res_w * 1.30)
    head_h = int(canvas_h * 0.15)
    head_x0 = res_x0 + (res_w - head_w) // 2
    head_y0 = res_top - head_h + int(head_h * 0.30)
    head_r = int(head_h * 0.30)

    # Contact shadow under both tanks so they sit on a surface.
    sh = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse(
        [res_x0 - int(canvas_w * 0.03), base_y - int(canvas_h * 0.025),
         brine_x0 + brine_w + int(canvas_w * 0.03), base_y + int(canvas_h * 0.040)],
        fill=(0, 0, 0, 70),
    )
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(canvas_h * 0.016)))

    # Brine tank first, so the resin tank and head overlap in front of it.
    paste_cylinder(img, (brine_x0, brine_top, brine_x0 + brine_w, base_y),
                   brine_r, BRINE_LIT, BRINE_MID, BRINE_DARK)
    # Lid seam near the top of the brine tank.
    seam = brine_top + int((base_y - brine_top) * 0.13)
    d.line([(brine_x0 + int(brine_w * 0.10), seam),
            (brine_x0 + brine_w - int(brine_w * 0.10), seam)],
           fill=BRINE_DARK, width=max(1, canvas_w // 240))

    # Resin tank.
    paste_cylinder(img, (res_x0, res_top, res_x0 + res_w, base_y),
                   res_r, TANK_LIT, TANK_MID, TANK_DARK)

    # Collar where the head bolts onto the tank.
    collar_h = max(3, int(canvas_h * 0.022))
    d.rounded_rectangle(
        [res_x0 - int(res_w * 0.04), res_top - collar_h // 2,
         res_x0 + res_w + int(res_w * 0.04), res_top + collar_h],
        collar_h // 2, fill=COLLAR,
    )

    # Valve head.
    paste_rounded_grad(img, (head_x0, head_y0, head_x0 + head_w, head_y0 + head_h),
                       head_r, HEAD_TOP, HEAD_BOT)
    d.rounded_rectangle([head_x0, head_y0, head_x0 + head_w, head_y0 + head_h],
                        head_r, outline=HEAD_EDGE, width=max(1, canvas_w // 300))

    # Blue control display on the head face.
    sw = int(head_w * 0.52)
    sh_ = int(head_h * 0.44)
    sx0 = head_x0 + (head_w - sw) // 2
    sy0 = head_y0 + int(head_h * 0.24)
    paste_rounded_grad(img, (sx0, sy0, sx0 + sw, sy0 + sh_),
                       max(2, sh_ // 4), SCREEN_TOP, SCREEN_BOT)

    # Two readout bars, so it reads as a display rather than a blue sticker.
    bar_h = max(2, sh_ // 6)
    for i, frac in enumerate((0.66, 0.42)):
        y = sy0 + int(sh_ * (0.26 + i * 0.36))
        d.rounded_rectangle(
            [sx0 + int(sw * 0.15), y,
             sx0 + int(sw * 0.15) + int(sw * 0.70 * frac), y + bar_h],
            bar_h // 2, fill=(255, 255, 255, 225),
        )

    # Bypass valve stub on the left of the head, as on the real unit.
    stub_w = int(head_w * 0.16)
    stub_h = int(head_h * 0.34)
    d.rounded_rectangle(
        [head_x0 - stub_w // 2, head_y0 + int(head_h * 0.22),
         head_x0 + stub_w // 2, head_y0 + int(head_h * 0.22) + stub_h],
        stub_w // 3, fill=SCREEN_BOT,
    )
    return img


def make_icon(variant, master=2048):
    """Square icon: the device, generously padded."""
    img = Image.new("RGBA", (master, master), (0, 0, 0, 0))
    img.alpha_composite(draw_device(master, master, variant))
    return img


def _font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_logo(variant, dark=False, master_h=1024):
    """Wide logo: device on the left, plain wordmark to its right.

    The wordmark is plain text naming the supported hardware, not a
    reproduction of Culligan's own logotype.
    """
    w = int(master_h * (1003 / 256))
    img = Image.new("RGBA", (w, master_h), (0, 0, 0, 0))

    dev = draw_device(int(master_h * 0.94), int(master_h * 0.94), variant)
    img.alpha_composite(dev, (int(master_h * 0.06), int(master_h * 0.03)))

    d = ImageDraw.Draw(img)
    color = WHITE if dark else INK
    f = _font(int(master_h * 0.40))
    tx = int(master_h * 1.06)
    ty = int(master_h * 0.30)
    d.text((tx, ty), "Culligan", font=f, fill=color)

    fs = _font(int(master_h * 0.155))
    d.text((tx + 4, ty + int(master_h * 0.46)), "water softener",
           font=fs, fill=(color[0], color[1], color[2], 190))
    return img


def trim(img, pad=0):
    bbox = img.getbbox()
    if not bbox:
        return img
    x0, y0, x1, y1 = bbox
    x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
    x1, y1 = min(img.width, x1 + pad), min(img.height, y1 + pad)
    return img.crop((x0, y0, x1, y1))


def _fit(img, size):
    """Downsample onto an exact canvas, preserving aspect and centering."""
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    src = trim(img)
    scale = min(size[0] / src.width, size[1] / src.height)
    new = src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))),
                     Image.LANCZOS)
    out.alpha_composite(new, ((size[0] - new.width) // 2, (size[1] - new.height) // 2))
    return out


def write_final(variant):
    os.makedirs(SHIP, exist_ok=True)
    icon = make_icon(variant)
    logo = make_logo(variant, dark=False)
    dlogo = make_logo(variant, dark=True)

    # HA expects square icons and 1003x256 logos, with @2x at exactly double.
    targets = [
        (icon, "icon.png", (256, 256)),
        (icon, "icon@2x.png", (512, 512)),
        (logo, "logo.png", (1003, 256)),
        (logo, "logo@2x.png", (2006, 512)),
        (dlogo, "dark_logo.png", (1003, 256)),
        (dlogo, "dark_logo@2x.png", (2006, 512)),
    ]
    for src, name, size in targets:
        out = _fit(src, size)
        path = os.path.join(SHIP, name)
        out.save(path, "PNG", optimize=True)
        print(f"  {name:<18} {out.size[0]}x{out.size[1]}  {out.mode}")


def contact_sheet():
    """Render every shipped asset once, light and dark, for eyeballing.

    The dark logo is drawn on an actual dark panel - a white wordmark on a
    white sheet is invisible, which is exactly the mistake the dark variant
    exists to prevent.
    """
    os.makedirs(OUT, exist_ok=True)
    icon = _fit(make_icon("tank"), (256, 256))
    logo = _fit(make_logo("tank"), (1003, 256))
    dlogo = _fit(make_logo("tank", dark=True), (1003, 256))

    # Lay rows out by measured height rather than by eye - hardcoded offsets
    # are how the dark logo ended up overlapping the light one.
    pad, gap, label_h = 40, 34, 30
    rows = [
        ("icon.png  256x256   (light / dark)", 256),
        ("logo.png  1003x256", 256),
        ("dark_logo.png  1003x256  (shown on a dark panel)", 256),
    ]
    width = pad * 2 + 1003
    height = pad * 2 + sum(label_h + h + gap for _, h in rows) - gap

    sheet = Image.new("RGBA", (width, height), (246, 247, 249, 255))
    d = ImageDraw.Draw(sheet)
    label = _font(20)

    y = pad
    # Row 1: icon on light, and again on dark so a dark-on-dark icon is caught.
    d.text((pad, y), rows[0][0], font=label, fill=(90, 96, 106))
    y += label_h
    sheet.alpha_composite(icon, (pad, y))
    dark_panel = Image.new("RGBA", (256, 256), (24, 26, 30, 255))
    dark_panel.alpha_composite(icon)
    sheet.alpha_composite(dark_panel, (pad + 256 + 40, y))
    y += 256 + gap

    # Row 2: light logo.
    d.text((pad, y), rows[1][0], font=label, fill=(90, 96, 106))
    y += label_h
    sheet.alpha_composite(logo, (pad, y))
    y += 256 + gap

    # Row 3: dark logo on an actual dark panel - a white wordmark on a white
    # sheet is invisible, which is the whole reason the variant exists.
    d.text((pad, y), rows[2][0], font=label, fill=(90, 96, 106))
    y += label_h
    panel = Image.new("RGBA", (1003, 256), (24, 26, 30, 255))
    panel.alpha_composite(dlogo)
    sheet.alpha_composite(panel, (pad, y))

    p = os.path.join(OUT, "contact.png")
    sheet.convert("RGB").save(p, "PNG")
    print(f"  wrote {p}  ({width}x{height})")


if __name__ == "__main__":
    if "--final" in sys.argv:
        i = sys.argv.index("--final")
        variant = sys.argv[i + 1] if len(sys.argv) > i + 1 else "tank"
        write_final(variant)
    else:
        contact_sheet()
