"""Generate the app favicon (logo #8: donut chart) as a PNG, using Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Rounded square in the accent blue.
pad = S * 0.055
d.rounded_rectangle([pad, pad, S - pad, S - pad], radius=int(S * 0.22), fill=(74, 144, 217, 255))

# Donut: a faint full ring + a brighter highlighted segment (matches the SVG logo).
cx = cy = S / 2
r = S * 0.25
w = int(S * 0.135)
bbox = [cx - r, cy - r, cx + r, cy + r]
d.arc(bbox, 0, 360, fill=(165, 200, 236, 255), width=w)    # full ring (white ~50% over blue)
d.arc(bbox, -90, 150, fill=(255, 255, 255, 255), width=w)  # 2/3 (240deg) white segment from the top

out = Path(__file__).resolve().parents[1] / "app" / "favicon.png"
img.save(out)
print("wrote", out)
