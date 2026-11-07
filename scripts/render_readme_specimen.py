"""Render the fictional passport data page used in the README example.

All data is the ICAO Doc 9303 specimen for Utopia (UTO), a state that does not
exist. The portrait is a drawn silhouette and no issuer artwork is copied.
Pillow's bundled font keeps the output identical across platforms.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUTPUT = Path('docs/images/specimen-passport.png')
WIDTH, HEIGHT = 1500, 1056  # TD3 data page aspect ratio (125 x 88 mm)
MRZ = ('P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<',
       'L898902C36UTO7408122F1204159ZE184226B<<<<<10')
# (label, value, x, y) for the visual inspection zone; values sit under labels.
# Short labels such as "Sex" stay right of their row: the extractor treats a
# short region left of a label as a bilingual prefix.
FIELDS = (
    ('Type', 'P', 430, 150), ('Code', 'UTO', 560, 150), ('Passport No.', 'L898902C3', 760, 150),
    ('Surname', 'ERIKSSON', 430, 250),
    ('Given names', 'ANNA MARIA', 430, 350),
    ('Nationality', 'UTOPIAN', 430, 450), ('Personal No.', 'ZE184226B', 900, 450),
    ('Date of birth', '12 AUG 1974', 430, 550), ('Sex', 'F', 900, 550),
    ('Place of birth', 'ZENITH', 430, 650), ('Authority', 'PASSPORT OFFICE', 900, 650),
    ('Date of issue', '16 APR 2007', 430, 750), ('Date of expiry', '15 APR 2012', 900, 750),
)


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def render() -> Image.Image:
    page = Image.new('RGB', (WIDTH, HEIGHT), (236, 241, 234))
    draw = ImageDraw.Draw(page)
    # Faint background rule lines, standing in for security printing.
    for y in range(0, HEIGHT, 14):
        draw.line([(0, y), (WIDTH, y + 40)], fill=(226, 233, 225), width=1)
    draw.rectangle([0, 0, WIDTH, 110], fill=(40, 70, 92))
    draw.text((60, 30), 'UTOPIA', font=font(46), fill=(255, 255, 255))
    draw.text((WIDTH - 60, 30), 'PASSPORT', font=font(46), fill=(255, 255, 255), anchor='ra')

    # Portrait placeholder: a drawn silhouette, not a photo.
    draw.rectangle([70, 160, 370, 540], fill=(214, 220, 216), outline=(150, 160, 158), width=2)
    draw.ellipse([155, 220, 285, 360], fill=(168, 178, 176))
    draw.chord([105, 380, 335, 640], 180, 360, fill=(168, 178, 176))
    draw.rectangle([70, 540, 370, 541], fill=(150, 160, 158))

    for label, value, x, y in FIELDS:
        draw.text((x, y), label, font=font(22), fill=(80, 92, 98))
        draw.text((x, y + 30), value, font=font(34), fill=(15, 18, 22))

    # Machine readable zone, one fixed-width cell per character.
    draw.rectangle([0, 880, WIDTH, HEIGHT], fill=(250, 250, 247))
    step = (WIDTH - 120) / len(MRZ[0])
    for row, line in enumerate(MRZ):
        for i, char in enumerate(line):
            draw.text((60 + (i + 0.5) * step, 905 + row * 66), char, font=font(40),
                      fill=(10, 10, 10), anchor='ma')

    # Watermark over the portrait and a plain banner, per CONTRIBUTING.md.
    stamp = Image.new('RGBA', (520, 120), (0, 0, 0, 0))
    ImageDraw.Draw(stamp).text((260, 60), 'SPECIMEN', font=font(84), fill=(200, 30, 30, 150), anchor='mm')
    stamp = stamp.rotate(28, Image.Resampling.BICUBIC, expand=True)
    page.paste(stamp, (220 - stamp.width // 2, 400 - stamp.height // 2), stamp)
    draw.text((70, 590), 'SPECIMEN', font=font(30), fill=(190, 30, 30))
    draw.text((70, 630), 'NOT A REAL ID', font=font(30), fill=(190, 30, 30))
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Place the page on a darker surface so it reads like a capture and the
    # preprocessor finds a document boundary.
    page = render()
    mask = Image.new('L', page.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, WIDTH - 1, HEIGHT - 1], 36, fill=255)
    capture = Image.new('RGB', (WIDTH + 140, HEIGHT + 140), (58, 62, 66))
    capture.paste(page, (70, 70), mask)
    capture.save(args.output, optimize=True)
    print(args.output)


if __name__ == '__main__':
    main()
