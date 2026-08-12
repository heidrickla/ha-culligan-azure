# Brand asset generator

The integration's icon/logo PNGs live in
[`custom_components/culligan_azure/brand/`](../custom_components/culligan_azure/brand/),
where Home Assistant 2026.3+'s Brands Proxy API serves them directly — local
brand images take priority over the brands CDN with no configuration, so no
home-assistant/brands submission is needed (that repo stopped accepting
custom-integration PRs in Feb 2026). On older HA versions the folder is simply
inert.

`icon.png` and `icon@2x.png` are also copied here at the repository root.
HACS's publishing requirements ask for "a `brand` directory in your repository
with at least an `icon.png` file", and the wording does not say whether that
means the repo root or the integration directory. The integration copy is the
one Home Assistant's Brands Proxy serves; this copy exists so the HACS
requirement is unambiguously met either way. Regenerate both together.

This directory otherwise holds only the tooling. The art is **original**: a stylized front
view of a cabinet-style water softener — the tall brine cabinet with its valve
head, control display and a water-drop motif — drawn programmatically by
[generate.py](generate.py) (Pillow only, rendered at 4x and downsampled).

`dark_logo*.png` are the dark-theme variants (white wordmark). Those exist
because a dark wordmark disappears against a dark theme, which is easy to miss
when every preview is on a white page — so the contact sheet deliberately renders
the icon and dark logo on a dark panel.

## Trademark note

The art does **not** reproduce Culligan's logo or trade dress. The wordmark is
plain text naming the hardware the integration supports (nominative use), not an
imitation of their branding. If Culligan ever objects, regenerating with a
different wordmark is a one-line change here.

## Regenerating

```bash
python generate.py                 # contact sheet into ./preview for review
python generate.py --final tank    # write the shipped PNGs
```

Review the contact sheet before shipping. `preview/` is gitignored.

## Shipped assets

| File | Size |
|---|---|
| `icon.png` | 256x256 |
| `icon@2x.png` | 512x512 |
| `logo.png` | 1003x256 |
| `logo@2x.png` | 2006x512 |
| `dark_logo.png` | 1003x256 |
| `dark_logo@2x.png` | 2006x512 |

All RGBA, `@2x` exactly double. `generate.py --final` enforces these dimensions,
so re-running it cannot drift out of spec.
