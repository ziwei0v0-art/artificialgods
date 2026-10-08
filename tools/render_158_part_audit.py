"""Read-only source-pixel audit; diagnostic masks, never production art.

Pillow only. No AppKit, window, service, worker, or save access.
"""
from pathlib import Path
import hashlib
import json

from PIL import Image, ImageChops, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'assets/production/A01/stand-pixel-20261001.png'
OUT = ROOT / 'evidence/1.0/158-part-audit'
SOURCE_RECT = (318, 356, 807, 1334)
FONT = ImageFont.load_default(size=17)
SMALL = ImageFont.load_default(size=13)
LIGHT = (239, 240, 242, 255)
DARK = (35, 46, 58, 255)
# Deliberately approximate study masks. Source-coordinate polygons are annotated
# and must not be mistaken for final separated arm artwork.
MASKS = {
    'viewer-left': [(200, 568), (216, 574), (232, 600), (254, 621),
        (265, 650), (265, 712), (258, 748), (243, 784), (218, 804),
        (216, 835), (204, 850), (174, 843), (155, 810), (135, 788),
        (110, 775), (95, 754), (104, 733), (123, 710), (150, 680),
        (170, 637), (186, 600)],
    'viewer-right': [(340, 603), (354, 612), (370, 639), (386, 668),
        (413, 695), (442, 722), (455, 747), (443, 770), (428, 786),
        (403, 799), (383, 789), (376, 754), (365, 720), (356, 690),
        (350, 651)],
}


def panel(source, background, title):
    result = Image.new('RGBA', (source.width + 32, source.height + 60), background)
    result.alpha_composite(source, (16, 44))
    ink = (240, 243, 247, 255) if background == DARK else (35, 39, 46, 255)
    ImageDraw.Draw(result).text((16, 14), title, font=FONT, fill=ink)
    return result


def board(images):
    result = Image.new('RGBA', (sum(im.width for im in images), max(im.height for im in images)), LIGHT)
    x = 0
    for im in images:
        result.alpha_composite(im, (x, 0))
        x += im.width
    return result


def detached_study(source, polygon, dx, dy):
    mask = Image.new('L', source.size, 0)
    ImageDraw.Draw(mask).polygon(polygon, fill=255)
    # Keep the white front hair/collar in place; this is only a diagnostic
    # safeguard, not a production segmentation algorithm.
    light_protection = source.convert('RGB').convert('L').point(lambda value: 255 if value > 155 else 0)
    mask = ImageChops.subtract(mask, light_protection)
    extracted = source.copy()
    extracted.putalpha(ImageChops.multiply(source.getchannel('A'), mask))
    base = source.copy()
    base.putalpha(ImageChops.multiply(source.getchannel('A'), ImageChops.invert(mask)))
    moved = Image.new('RGBA', source.size)
    moved.alpha_composite(extracted, (dx, dy))
    result = Image.alpha_composite(base, moved)
    vacated = ImageChops.subtract(source.getchannel('A'), result.getchannel('A')).point(lambda v: 255 if v > 16 else 0)
    marked = result.copy()
    tint = Image.new('RGBA', source.size, (218, 35, 136, 0))
    tint.putalpha(vacated.point(lambda value: 190 if value else 0))
    marked.alpha_composite(tint)
    return extracted, result, marked, sum(value > 0 for value in vacated.getdata())


def main():
    original_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    source = Image.open(SOURCE).convert('RGBA').crop(SOURCE_RECT)
    assert source.size == (489, 978)
    OUT.mkdir(parents=True, exist_ok=True)
    board([panel(source, LIGHT, 'Accepted source crop / light'),
           panel(source, DARK, 'Accepted source crop / dark')]).save(OUT / '01-source-alpha-reference.png')
    upper = source.crop((60, 530, 489, 890)).resize((858, 720), Image.Resampling.NEAREST)
    grid = panel(upper, LIGHT, 'Source-coordinate guide: x60..489, y530..890 (2x)')
    draw = ImageDraw.Draw(grid)
    for x in range(100, 489, 50):
        px = 16 + (x - 60) * 2
        draw.line((px, 44, px, 764), fill=(40, 110, 170, 90))
        draw.text((px + 2, 48), str(x), font=SMALL, fill=(20, 80, 135))
    for y in range(550, 890, 50):
        py = 44 + (y - 530) * 2
        draw.line((16, py, 874, py), fill=(40, 110, 170, 90))
        draw.text((20, py + 2), str(y), font=SMALL, fill=(20, 80, 135))
    grid.save(OUT / '02-upper-body-coordinate-guide.png')
    mask_map = source.copy()
    painter = ImageDraw.Draw(mask_map)
    for name, polygon in MASKS.items():
        painter.line(polygon + [polygon[0]], fill=(0, 170, 225, 255), width=3)
    panel(mask_map, LIGHT, 'Approximate sleeve-mask boundaries / NOT accepted').save(OUT / '03-mask-boundaries.png')
    audit_rows = []
    for name, dx, dy in [('viewer-left', 44, -70), ('viewer-right', -35, -65)]:
        detached, moved, marked, count = detached_study(source, MASKS[name], dx, dy)
        # Upper body only, at source scale: a comparison artifact, not a new asset.
        box = (60, 530, 489, 890)
        images = [panel(source.crop(box), LIGHT, 'Original'),
                  panel(detached.crop(box), DARK, 'Rough extraction'),
                  panel(moved.crop(box), LIGHT, 'Moved pixels / no fill'),
                  panel(marked.crop(box), LIGHT, 'Magenta: vacated source area')]
        board(images).save(OUT / ('04-' + name + '-separation-study.png'))
        audit_rows.append({'name': name, 'polygon': MASKS[name], 'diagnostic_translation': [dx, dy],
                           'vacated_source_pixel_count': count,
                           'note': 'Vacated area includes former exterior sleeve silhouette; it is NOT an exact underpaint request.'})
    small = []
    for name, dx, dy in [('viewer-left', 44, -70), ('viewer-right', -35, -65)]:
        _, moved, _, _ = detached_study(source, MASKS[name], dx, dy)
        for height in (128, 64):
            scaled = moved.resize((round(moved.width * height / moved.height), height), Image.Resampling.NEAREST)
            small.append(panel(scaled, DARK, name + ' / ' + str(height)))
    board(small).save(OUT / '05-unfilled-study-small.png')
    manifest = {'source': str(SOURCE), 'source_sha256': original_hash,
                'source_rect_xywh': [318, 356, 489, 978],
                'status': 'DIAGNOSTIC ONLY; masks are hypotheses, not accepted production separations',
                'no_windows_workers_or_saves': True,
                'mask_studies': audit_rows,
                'warning': 'Diagnostic light-protection threshold and hand-drawn masks are not validated production segmentation.'}
    (OUT / 'audit.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == original_hash
    print('SOURCE_UNCHANGED; diagnostic alpha composites written; no window/worker/save')


if __name__ == '__main__':
    main()
