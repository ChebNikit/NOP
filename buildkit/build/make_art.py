"""Generates the installer artwork and the application icon from the icon embedded in NOP itself.

Design: NOP player theme 1 ("Classic"): #0d0f14 background, #11151e panels, #2a3242 borders, #ff426d accent.
Dark panel, rounded N tile in a bordered card, large NOP wordmark, NikOmniPlayer subtitle, version line.
Nothing is copied from third-party kits; the mark comes from NOP's own source (_NOP_APP_ICON_PNGS)."""
from __future__ import annotations

import ast
import base64
import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Colours taken from the player's first theme ("classic", STYLE table in NOP_1_2.py).
BACKGROUND = (13, 15, 20)      # #0d0f14  window
CARD = (17, 21, 30)            # #11151e  inputs / cards
CARD_EDGE = (42, 50, 66)       # #2a3242  borders
TILE = (20, 22, 29)
TILE_EDGE = (42, 50, 66)
TEXT = (240, 243, 250)         # #f0f3fa  titles
MUTED = (142, 152, 171)        # #8e98ab  secondary text
ACCENT = (255, 66, 109)        # #ff426d  accent

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuil.ttf", r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
FONT_LIGHT = (r"C:\Windows\Fonts\segoeuil.ttf", r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

FONT_BOLD = (r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeui.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")

WIZARD_SIZES = ((164, 314), (192, 386), (246, 459), (328, 628))      # Inno modern style, 100%..200% DPI
SMALL_SIZES = ((55, 58), (64, 68), (83, 80), (110, 106))


def load_icon_layers(source: Path) -> dict[int, Image.Image]:
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_NOP_APP_ICON_PNGS" for t in node.targets):
            layers = {}
            for encoded in ast.literal_eval(node.value):
                image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")
                layers[image.width] = image
            if layers:
                return layers
    raise RuntimeError("The application icon (_NOP_APP_ICON_PNGS) was not found in the NOP source.")


def _font(candidates, size):
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _tile(layers: dict[int, Image.Image], size: int) -> Image.Image:
    base = layers[max(layers)]
    return base.resize((size, size), Image.LANCZOS)


def make_wizard(layers, width, height, version: str) -> Image.Image:
    scale = width / 164
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    tile = int(round(84 * scale))
    pad = int(round(10 * scale))
    cx = width // 2
    top = int(height * 0.25)
    # bordered card behind the icon, like the player's panels (radius 12, 1px border)
    card = (cx - tile // 2 - pad, top - pad, cx + tile // 2 + pad, top + tile + pad)
    draw.rounded_rectangle(card, radius=int(round(14 * scale)), fill=CARD, outline=CARD_EDGE,
                           width=max(1, int(round(scale))))
    icon = _tile(layers, tile)  # the application icon already is the rounded dark tile
    image.paste(icon, (cx - icon.width // 2, top), icon)
    title_font = _font(FONT_BOLD, int(36 * scale))
    sub_font = _font(FONT_CANDIDATES, int(13 * scale))
    foot_font = _font(FONT_CANDIDATES, max(8, int(10.5 * scale)))
    y = top + tile + pad + int(22 * scale)
    draw.text((cx, y), "NOP", font=title_font, fill=TEXT, anchor="mt")
    y += int(52 * scale)
    draw.text((cx, y), "NikOmniPlayer", font=sub_font, fill=MUTED, anchor="mt")
    # short accent bar under the name, same pink as the player's main button
    bar_w, bar_h = int(28 * scale), max(2, int(3 * scale))
    bar_y = y + int(24 * scale)
    draw.rounded_rectangle((cx - bar_w // 2, bar_y, cx + bar_w // 2, bar_y + bar_h), radius=bar_h // 2, fill=ACCENT)
    draw.text((cx, height - int(26 * scale)), f"{version}  /  Windows x64", font=foot_font, fill=MUTED, anchor="mm")
    draw.rectangle((0, height - max(2, int(2 * scale)), width, height), fill=ACCENT)
    return image


def make_small(layers, width, height) -> Image.Image:
    image = Image.new("RGB", (width, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    side = int(min(width, height) * 0.86)
    left, top = (width - side) // 2, (height - side) // 2
    icon = _tile(layers, side)
    image.paste(icon, (left, top), icon)
    return image


def build_all(source: Path, output: Path, version: str) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    layers = load_icon_layers(source)
    wizard = []
    for width, height in WIZARD_SIZES:
        path = output / f"wizard_{width}x{height}.bmp"
        make_wizard(layers, width, height, version).save(path, "BMP")
        wizard.append(path.name)
    small = []
    for width, height in SMALL_SIZES:
        path = output / f"small_{width}x{height}.bmp"
        make_small(layers, width, height).save(path, "BMP")
        small.append(path.name)
    sizes = [(s, s) for s in sorted(layers) if s <= 256]
    layers[256].save(output / "nop.ico", format="ICO", sizes=sizes, append_images=[layers[s] for s in sorted(layers) if s != 256])
    make_wizard(layers, 656, 1256, version).save(output / "wizard_preview.png")
    return {"wizard": wizard, "small": small, "icon": "nop.ico"}


if __name__ == "__main__":
    print(build_all(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] if len(sys.argv) > 3 else "1.2"))
