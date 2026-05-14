"""Генерация обложки 640×360 для регистрации Mini App в BotFather."""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "miniapp" / "casino-cover.png"


def _try_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def main():
    W, H = 640, 360
    img = Image.new("RGB", (W, H), (10, 10, 14))
    draw = ImageDraw.Draw(img)

    # Лёгкий градиент сверху → центр.
    for y in range(H):
        t = y / H
        # тёмно-фиолетовый → почти чёрный
        r = int(20 + (10 - 20) * t)
        g = int(15 + (10 - 15) * t)
        b = int(40 + (14 - 40) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Декоративные точки/«монеты».
    coin_color = (200, 170, 50)
    coin_color_dim = (90, 75, 30)
    spots = [
        (60, 80, 18), (575, 95, 14), (110, 280, 16), (520, 270, 20),
        (40, 200, 10), (590, 200, 8), (200, 60, 8), (450, 310, 10),
    ]
    for x, y, r in spots:
        draw.ellipse([x - r, y - r, x + r, y + r], outline=coin_color, width=2)
        draw.ellipse([x - r + 5, y - r + 5, x + r - 5, y + r - 5], fill=coin_color_dim)

    # Основной заголовок.
    title_font = _try_font(78)
    subtitle_font = _try_font(28)

    title = "XYLOZ"
    subtitle = "CASINO"
    hint = "bets · markets · leaderboard"

    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]
    title_x = (W - title_w) // 2
    title_y = (H - title_h) // 2 - 30

    # Тень.
    draw.text((title_x + 3, title_y + 3), title, font=title_font, fill=(0, 0, 0))
    draw.text((title_x, title_y), title, font=title_font, fill=(245, 230, 180))

    sub_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    sub_w = sub_bbox[2] - sub_bbox[0]
    sub_x = (W - sub_w) // 2
    sub_y = title_y + title_h + 14
    draw.text((sub_x, sub_y), subtitle, font=subtitle_font, fill=(200, 170, 90))

    hint_font = _try_font(16)
    hint_bbox = draw.textbbox((0, 0), hint, font=hint_font)
    hint_w = hint_bbox[2] - hint_bbox[0]
    hint_x = (W - hint_w) // 2
    hint_y = sub_y + 50
    draw.text((hint_x, hint_y), hint, font=hint_font, fill=(140, 140, 160))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT_PATH, "PNG", optimize=True)
    print(f"saved: {OUT_PATH} ({OUT_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
