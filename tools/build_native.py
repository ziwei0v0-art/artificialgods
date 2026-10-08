"""Build the in-project native 1.0 candidate without launching it or signing it."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def _make_png_validator(label, *, limits=None):
    # Match the native loader's PNG/alpha/crop checks without installing an image
    # library or opening a window. ImageIO and CoreGraphics are part of macOS.
    import ctypes

    class Point(ctypes.Structure):
        _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]

    class Size(ctypes.Structure):
        _fields_ = [('width', ctypes.c_double), ('height', ctypes.c_double)]

    class Rect(ctypes.Structure):
        _fields_ = [('origin', Point), ('size', Size)]

    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
    imageio = ctypes.CDLL('/System/Library/Frameworks/ImageIO.framework/ImageIO')
    pointer, size_t = ctypes.c_void_p, ctypes.c_size_t

    def bind(library, name, arguments, result=None):
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result
        return function

    data_create = bind(cf, 'CFDataCreate', [pointer, pointer, ctypes.c_long], pointer)
    release = bind(cf, 'CFRelease', [pointer])
    source_create = bind(imageio, 'CGImageSourceCreateWithData', [pointer, pointer], pointer)
    image_create = bind(imageio, 'CGImageSourceCreateImageAtIndex', [pointer, size_t, pointer], pointer)
    image_width = bind(cg, 'CGImageGetWidth', [pointer], size_t)
    image_height = bind(cg, 'CGImageGetHeight', [pointer], size_t)
    image_alpha = bind(cg, 'CGImageGetAlphaInfo', [pointer], ctypes.c_uint32)
    crop_image = bind(cg, 'CGImageCreateWithImageInRect', [pointer, Rect], pointer)
    release_image = bind(cg, 'CGImageRelease', [pointer])
    color_create = bind(cg, 'CGColorSpaceCreateDeviceRGB', [], pointer)
    color_release = bind(cg, 'CGColorSpaceRelease', [pointer])
    context_create = bind(cg, 'CGBitmapContextCreate',
                          [pointer, size_t, size_t, size_t, size_t, pointer, ctypes.c_uint32], pointer)
    context_draw = bind(cg, 'CGContextDrawImage', [pointer, Rect, pointer])
    context_release = bind(cg, 'CGContextRelease', [pointer])

    def validate_png(path, crop):
        if limits is not None and path.stat().st_size > limits[0]:
            raise ValueError(f'{label} PNG exceeds the file size limit')
        data = path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError(f'{label} resource does not contain PNG data')
        if limits is not None:
            if len(data) > limits[0] or len(data) < 24 or data[12:16] != b'IHDR':
                raise ValueError(f'{label} PNG has an invalid or oversized header')
            w, h = int.from_bytes(data[16:20], 'big'), int.from_bytes(data[20:24], 'big')
            if not (0 < w <= limits[1] and 0 < h <= limits[1] and w * h <= limits[2]):
                raise ValueError(f'{label} PNG dimensions exceed the supported limits')
        buffer = ctypes.create_string_buffer(data)
        cfdata = source_ref = image_ref = cropped = color = context = None
        try:
            cfdata = data_create(None, buffer, len(data))
            source_ref = source_create(cfdata, None) if cfdata else None
            image_ref = image_create(source_ref, 0, None) if source_ref else None
            if not image_ref or image_alpha(image_ref) not in (1, 2, 3, 4, 7):
                raise ValueError(f'{label} PNG must decode with an alpha channel')
            width, height = image_width(image_ref), image_height(image_ref)
            if limits is not None and (width > limits[1] or height > limits[1] or width * height > limits[2]):
                raise ValueError(f'{label} PNG dimensions exceed the supported limits')
            if crop is not None:
                x, y, w, h = crop
                if x >= width or y >= height or w > width - x or h > height - y:
                    raise ValueError(f'{label} sourceRect must remain inside its PNG')
                cropped = crop_image(image_ref, Rect(Point(x, y), Size(w, h)))
                if not cropped:
                    raise ValueError(f'{label} PNG crop could not be decoded')
                width, height = w, h
            if not width or not height:
                raise ValueError(f'{label} PNG must have positive dimensions')
            rgba = (ctypes.c_ubyte * (width * height * 4))()
            color = color_create()
            # Premultiplied-last + big-endian 32-bit is explicit RGBA bytes;
            # premultiplication changes color channels, never this alpha byte.
            context = context_create(rgba, width, height, 8, width * 4, color, 1 | (4 << 12))
            if not context:
                raise ValueError(f'{label} PNG could not be decoded to RGBA')
            context_draw(context, Rect(Point(0, 0), Size(width, height)), cropped or image_ref)
            if not any(memoryview(rgba).cast('B')[3::4]):
                raise ValueError(f'{label} PNG crop must contain visible alpha')
        finally:
            if context:
                context_release(context)
            if color:
                color_release(color)
            if cropped:
                release_image(cropped)
            if image_ref:
                release_image(image_ref)
            if source_ref:
                release(source_ref)
            if cfdata:
                release(cfdata)

    return validate_png

def copy_scene_art(source: Path, resources: Path):
    """Validate the complete scene manifest, then stage only its owned PNGs."""
    source = source.resolve()
    target = resources / 'art' / 'scene'
    if not source.exists():
        if target.exists() or target.is_symlink():
            raise ValueError('Scene source is missing but output contains art; refusing stale bundled resources')
        return False  # Only a clean development bundle may use the runtime fallback.
    if not source.is_dir():
        raise ValueError('Scene source must be a directory')

    def resolve_file(name, *, png=False):
        if (not isinstance(name, str) or not name or name in ('.', '..')
                or Path(name).name != name or '\\' in name):
            raise ValueError('Scene resource must be a filename in its own directory')
        try:
            result = (source / name).resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError('Invalid scene resource path') from error
        if not result.is_relative_to(source) or not result.is_file():
            raise ValueError('Scene resource missing or outside its directory')
        if png and (Path(name).suffix.lower() != '.png' or result.suffix.lower() != '.png'):
            raise ValueError('Scene resource must be a PNG')
        return result

    def finite_number(value):
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False

    def validate_rect(value, *, bounds=False):
        if not isinstance(value, list) or len(value) != 4 or not all(finite_number(n) for n in value):
            raise ValueError('Scene rectangles must contain four finite numbers')
        x, y, width, height = value
        if width <= 0 or height <= 0:
            raise ValueError('Scene rectangles must have positive dimensions')
        if bounds:
            # The same design-space canvas used by TianmuView; source pixels are top-left based.
            if x < 55 or y < 130 or x + width > 425 or y + height > 320:
                raise ValueError('Scene layer bounds must be inside the scene canvas')
        elif any(type(n) != int for n in value) or x < 0 or y < 0:
            raise ValueError('Scene sourceRect must use nonnegative integer origins and positive integer sizes')

    def validate_anchor(value):
        if (not isinstance(value, list) or len(value) != 2
                or not all(finite_number(n) and 0 <= n <= 1 for n in value)):
            raise ValueError('Scene incenseAnchor must contain two normalized finite numbers')

    validate_png = _make_png_validator('Scene')

    manifest_file = resolve_file('manifest.json')
    manifest = json.loads(manifest_file.read_text())
    if (not isinstance(manifest, dict) or type(manifest.get('version')) != int
            or manifest['version'] != 1 or manifest.get('sampling') != 'nearest'):
        raise ValueError('Unsupported scene manifest version or sampling')
    layers = manifest.get('layers')
    expected_ids = {'shrine', 'idol', 'incense', 'fruit'}
    if (not isinstance(layers, list) or len(layers) != 4
            or any(not isinstance(layer, dict) or not isinstance(layer.get('id'), str) for layer in layers)
            or {layer['id'] for layer in layers} != expected_ids):
        raise ValueError('Scene requires shrine, idol, incense and fruit exactly once')
    if 'attendantHeight' in manifest:
        height = manifest['attendantHeight']
        if not finite_number(height) or not 0 < height <= 180:
            raise ValueError('Scene attendantHeight must be positive and at most 180')
    if 'incenseAnchor' in manifest:
        validate_anchor(manifest['incenseAnchor'])
    files = {'manifest.json': manifest_file}

    def collect(spec):
        if not isinstance(spec, dict):
            raise ValueError('Invalid scene image specification')
        name = spec.get('file')
        path = resolve_file(name, png=True)
        if 'sourceRect' in spec:
            validate_rect(spec['sourceRect'])
        validate_png(path, spec.get('sourceRect'))
        files[name] = path

    for layer in layers:
        validate_rect(layer.get('bounds'), bounds=True)
        collect(layer)
    if 'fruitVariants' in manifest:
        variants = manifest['fruitVariants']
        if not isinstance(variants, dict) or not set(variants).issubset({'fresh', 'soft', 'ripe'}):
            raise ValueError('Scene fruitVariants may only contain fresh, soft and ripe')
        for spec in variants.values():
            collect(spec)

    required_layers = {'shrine_g1': {'shrine'}, 'shrine_g2': {'shrine', 'idol'},
                       'offering_plate': {'fruit'}, 'incense_burner': {'incense'}, 'bell': {'bell'}}
    appearances = manifest.get('appearances', {})
    if not isinstance(appearances, dict) or not set(appearances).issubset(required_layers):
        raise ValueError('Scene appearances may only name the five supported decorations')
    for item_id, appearance in appearances.items():
        if not isinstance(appearance, dict):
            raise ValueError('Invalid scene appearance specification')
        replacements = appearance.get('layers')
        required = required_layers[item_id]
        if (not isinstance(replacements, list) or len(replacements) != len(required)
                or any(not isinstance(layer, dict) or not isinstance(layer.get('id'), str)
                       for layer in replacements)
                or {layer['id'] for layer in replacements} != required):
            raise ValueError('Scene appearance requires its exact replacement layer set')
        for layer in replacements:
            validate_rect(layer.get('bounds'), bounds=True)
            collect(layer)
        if item_id == 'offering_plate' and 'fruitVariants' not in appearance:
            raise ValueError('Purchased plate requires all three fruit variants')
        if 'fruitVariants' in appearance:
            variants = appearance['fruitVariants']
            if not isinstance(variants, dict) or set(variants) != {'fresh', 'soft', 'ripe'}:
                raise ValueError('Scene appearance fruitVariants must contain fresh, soft and ripe')
            for spec in variants.values():
                collect(spec)
        if item_id == 'incense_burner' and 'incenseAnchor' not in appearance:
            raise ValueError('Purchased incense burner requires an authored incenseAnchor')
        if 'incenseAnchor' in appearance:
            validate_anchor(appearance['incenseAnchor'])

    if target.is_symlink() or target.parent.is_symlink() or (target.exists() and not target.is_dir()):
        raise ValueError('Scene output must be an ordinary directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Copy failures leave the existing output unchanged, while a fresh directory removes stale files.
    with tempfile.TemporaryDirectory(prefix='scene-', dir=target.parent) as directory:
        staged = Path(directory) / 'scene'
        staged.mkdir()
        for name, path in files.items():
            shutil.copy2(path, staged / name)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staged), str(target))
    return True

def _compile_insect_validator(directory: Path):
    """Build only the actual resource loader and a windowless diagnostic entry."""
    main_file = directory / 'main.swift'
    main_file.write_text(r'''
import Foundation
let artwork = InsectArtwork(directory: URL(fileURLWithPath: CommandLine.arguments[1]))
let diagnostic: [String: Any] = [
    "complete": artwork.complete,
    "styles": artwork.availableStyles.map(\.rawValue).sorted(),
    "issues": artwork.issues,
]
let data = try JSONSerialization.data(withJSONObject: diagnostic, options: [.sortedKeys])
print(String(data: data, encoding: .utf8)!)
exit(artwork.complete ? 0 : 1)
''')
    binary = directory / 'validate-insects'
    result = subprocess.run(['swiftc', '-framework', 'AppKit',
                             str(ROOT / 'native/v1/WindowPlacement.swift'),
                             str(ROOT / 'native/v1/InsectArtwork.swift'),
                             str(main_file), '-o', str(binary)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('Insect runtime validator could not compile: ' + result.stderr.strip())
    return binary


def _validate_insect_runtime(source: Path):
    # No NSApplication, Host, game entry point, worker, or save is involved.
    try:
        with tempfile.TemporaryDirectory(prefix='tianmu-insect-validation-') as directory:
            binary = _compile_insect_validator(Path(directory))
            result = subprocess.run([str(binary), str(source)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError('Insect runtime validation could not run') from error
    try:
        diagnostic = json.loads(result.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError('Insect runtime validation returned no usable diagnostic: ' + result.stderr.strip()) from error
    if (result.returncode or not isinstance(diagnostic, dict) or diagnostic.get('complete') is not True
            or diagnostic.get('styles') != ['cute', 'realistic']):
        raise ValueError('Insect runtime validation failed: ' + result.stdout.strip())


def copy_insect_art(source: Path, resources: Path):
    """Require both real styles before staging the manifest and its three PNGs."""
    try:
        source = source.resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError('Insect source is not a valid directory') from error
    if not source.is_dir():
        raise ValueError('Insect source directory is required')
    target = resources / 'art' / 'insects'
    if (resources.is_symlink() or target.parent.is_symlink() or target.is_symlink()
            or (target.exists() and not target.is_dir())):
        raise ValueError('Insect output must be an ordinary directory')

    def resolve_file(name, *, png=False):
        if (not isinstance(name, str) or not name or '\\' in name or Path(name).is_absolute()
                or '..' in Path(name).parts or name in ('.', '..')):
            raise ValueError('Insect resources must use relative paths inside their directory')
        try:
            result = (source / name).resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError('Insect resource path is invalid') from error
        if not result.is_relative_to(source) or not result.is_file():
            raise ValueError('Insect resource is missing or outside its directory')
        if png and (Path(name).suffix.lower() != '.png' or result.suffix.lower() != '.png'):
            raise ValueError('Insect images must be PNG files')
        return result

    def object_keys(value, required, optional=()):
        if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
            raise ValueError('Insect manifest has missing or unsupported fields')

    def finite(value):
        try:
            return type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            return False

    def numbers(value, count):
        if not isinstance(value, list) or len(value) != count or not all(finite(n) for n in value):
            raise ValueError('Insect geometry must contain the required finite numbers')
        return value

    def rgb_palette(value):
        if (not isinstance(value, list) or len(value) != 3
                or any(not isinstance(rgb, list) or len(rgb) != 3
                       or any(type(n) != int or not 0 <= n <= 255 for n in rgb) for rgb in value)):
            raise ValueError('Insect palettes require exactly three integer RGB colors')

    def source_rect(value):
        numbers(value, 4)
        if any(type(n) != int for n in value) or min(value[:2]) < 0 or min(value[2:]) <= 0:
            raise ValueError('Insect sourceRect requires nonnegative integer origins and positive integer sizes')
        return value

    def inside_canvas(rect, canvas):
        x, y, width, height = numbers(rect, 4)
        if (width < 0 or height < 0 or x < -canvas[0] / 2 or y < -canvas[1] / 2
                or x + width > canvas[0] / 2 or y + height > canvas[1] / 2):
            raise ValueError('Insect display bounds must remain inside their canvas')

    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Insect manifest contains duplicate fields')
            result[key] = value
        return result

    manifest_file = resolve_file('manifest.json')
    try:
        manifest = json.loads(manifest_file.read_text(), object_pairs_hook=no_duplicate_keys)
    except (ValueError, UnicodeError) as error:
        raise ValueError('Insect manifest is not valid unambiguous JSON') from error
    object_keys(manifest, ('version', 'sampling', 'styles'))
    if type(manifest['version']) != int or manifest['version'] != 1 or manifest['sampling'] != 'nearest':
        raise ValueError('Insect manifest requires version 1 and nearest sampling')
    object_keys(manifest['styles'], ('cute', 'realistic'))
    files = {'manifest.json': manifest_file}
    validate_png = _make_png_validator('Insect', limits=(32 * 1024 * 1024, 4096, 16777216))

    def collect(name, rect):
        path = resolve_file(name, png=True)
        validate_png(path, source_rect(rect))
        files[name] = path
        return path

    for style_name, expected_kind in (('cute', 'atlas'), ('realistic', 'wingLayers')):
        style = manifest['styles'][style_name]
        common = ('kind', 'canvasSize', 'sampleScale', 'fps', 'frames', 'palette')
        required = (('file', 'displayScale') if style_name == 'cute' else
                    ('body', 'upperWing', 'lowerWing', 'bodyPolygon', 'warmGate', 'lumaRange'))
        object_keys(style, common + required, ('sequence',))
        if style['kind'] != expected_kind:
            raise ValueError('Insect styles must use their own atlas or wingLayers representation')
        canvas = numbers(style['canvasSize'], 2)
        if any(not 0 < size <= 24 or not (size * 2).is_integer() for size in map(float, canvas)):
            raise ValueError('Insect canvas must fit 24 points with integral cache dimensions')
        if type(style['sampleScale']) != int or style['sampleScale'] != 2:
            raise ValueError('Insect sampleScale must be 2')
        if not finite(style['fps']) or not 0 < style['fps'] <= 30:
            raise ValueError('Insect fps must be positive and at most 30')
        sequence = style.get('sequence', [0, 1, 2, 1])
        if (not isinstance(sequence, list) or not 3 <= len(sequence) <= 16
                or any(type(index) != int or index not in (0, 1, 2) for index in sequence)
                or set(sequence) != {0, 1, 2}):
            raise ValueError('Insect sequence must reference all three actual frames')
        frames = style['frames']
        if not isinstance(frames, list) or len(frames) != 3:
            raise ValueError('Insect styles require exactly three actual frames')
        object_keys(style['palette'], ('普通褐色', '中褐色', '深褐色', '白色'))
        for palette in style['palette'].values():
            rgb_palette(palette)

        if style_name == 'cute':
            scale = style['displayScale']
            if not finite(scale) or not 0 < scale <= 4:
                raise ValueError('Insect displayScale must be positive and at most 4')
            for frame in frames:
                object_keys(frame, ('sourceRect', 'anchor', 'bodyRows', 'sourcePalette'))
                rect = source_rect(frame['sourceRect'])
                atlas_path = collect(style['file'], rect)
                width, height = rect[2:]
                anchor = numbers(frame['anchor'], 2)
                if not 0 <= anchor[0] <= width or not 0 <= anchor[1] <= height:
                    raise ValueError('Insect atlas anchor must be inside its crop')
                inside_canvas([-anchor[0] * scale, -anchor[1] * scale, width * scale, height * scale], canvas)
                rows = frame['bodyRows']
                if not isinstance(rows, list) or not rows:
                    raise ValueError('Insect atlas requires an explicit body mask')
                selected = set()
                for row in rows:
                    if (not isinstance(row, list) or len(row) != 3 or any(type(n) != int for n in row)
                            or not 0 <= row[0] < height or not 0 <= row[1] <= row[2] < width):
                        raise ValueError('Insect body mask rows must stay inside the crop')
                    pixels = {(x, row[0]) for x in range(row[1], row[2] + 1)}
                    if selected & pixels:
                        raise ValueError('Insect body mask rows must not overlap')
                    selected.update(pixels)
                rgb_palette(frame['sourcePalette'])
                if len({tuple(rgb) for rgb in frame['sourcePalette']}) != 3:
                    raise ValueError('Insect sourcePalette must contain three distinct colors')
        else:
            paths = {}
            for part_name in ('body', 'upperWing', 'lowerWing'):
                part = style[part_name]
                object_keys(part, ('file', 'sourceRect', 'bounds') + (() if part_name == 'body' else ('pivot',)))
                paths[part_name] = collect(part['file'], part['sourceRect'])
                bounds = numbers(part['bounds'], 4)
                if min(bounds[2:]) <= 0:
                    raise ValueError('Insect part bounds must have positive dimensions')
                inside_canvas(bounds, canvas)
                if part_name != 'body':
                    pivot = numbers(part['pivot'], 2)
                    if not (bounds[0] <= pivot[0] <= bounds[0] + bounds[2]
                            and bounds[1] <= pivot[1] <= bounds[1] + bounds[3]):
                        raise ValueError('Insect wing pivot must be inside its bounds')
            if paths['upperWing'] != paths['lowerWing'] or len({atlas_path, *paths.values()}) != 3:
                raise ValueError('Insect styles require one atlas, one body and one shared wings PNG')
            for frame in frames:
                object_keys(frame, ('upperYScale', 'lowerYScale'))
                for part_name, key in (('upperWing', 'upperYScale'), ('lowerWing', 'lowerYScale')):
                    scale = frame[key]
                    if not finite(scale) or not -1 <= scale <= 1:
                        raise ValueError('Insect wing scales must be finite and between -1 and 1')
                    x, y, width, height = style[part_name]['bounds']
                    pivot_y = style[part_name]['pivot'][1]
                    ends = [pivot_y + (edge - pivot_y) * scale for edge in (y, y + height)]
                    inside_canvas([x, min(ends), width, max(ends) - min(ends)], canvas)
            polygon = style['bodyPolygon']
            if not isinstance(polygon, list) or len(polygon) < 3:
                raise ValueError('Insect bodyPolygon must have at least three distinct vertices')
            width, height = style['body']['sourceRect'][2:]
            for point in polygon:
                x, y = numbers(point, 2)
                if not 0 <= x <= width or not 0 <= y <= height:
                    raise ValueError('Insect bodyPolygon must stay inside the body crop')
            if (len({tuple(point) for point in polygon}) != len(polygon)
                    or sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(polygon, polygon[1:] + polygon[:1])) == 0):
                raise ValueError('Insect bodyPolygon must have distinct vertices and nonzero area')
            gate = style['warmGate']
            object_keys(gate, ('minRed', 'minGreenOverRed', 'minGreenMinusBlue'))
            if (any(type(gate[key]) != int or not 0 <= gate[key] <= 255 for key in ('minRed', 'minGreenMinusBlue'))
                    or not finite(gate['minGreenOverRed']) or not 0 <= gate['minGreenOverRed'] <= 1):
                raise ValueError('Insect warmGate must contain valid RGB thresholds')
            low, high = numbers(style['lumaRange'], 2)
            if not 0 <= low < high <= 255:
                raise ValueError('Insect lumaRange must be increasing within 0 through 255')

    # Actual mask hits, original RGBA format, recoloring, and distinct final
    # sprites are checked by the exact loader used in the product.
    _validate_insect_runtime(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='insects-', dir=target.parent) as directory:
        staged = Path(directory) / 'insects'
        staged.mkdir()
        for name, path in files.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staged), str(target))
    return True

def _validated_bottle_files(source: Path):
    """Read the pinned full PNG and manifest without modifying any output."""
    import zlib

    try:
        source = source.resolve()
    except (OSError, RuntimeError) as error:
        raise ValueError('Bottle source directory is invalid') from error
    if not source.is_dir():
        raise ValueError('Bottle source directory is required')

    def resolve(name, *, png=False):
        if (not isinstance(name, str) or not name or name in ('.', '..')
                or '\\' in name or Path(name).is_absolute() or '..' in Path(name).parts):
            raise ValueError('Bottle resource must be a relative path inside its directory')
        try:
            path = (source / name).resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError('Bottle resource path is invalid') from error
        if not path.is_relative_to(source) or not path.is_file():
            raise ValueError('Bottle resource is missing or outside its directory')
        if png and (path.suffix.lower() != '.png' or Path(name).suffix.lower() != '.png'):
            raise ValueError('Bottle image must be a PNG')
        return path

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Bottle manifest contains duplicate fields')
            result[key] = value
        return result

    manifest_file = resolve('manifest.json')
    if not 0 < manifest_file.stat().st_size <= 1_048_576:
        raise ValueError('Bottle manifest size is invalid')
    try:
        value = json.loads(manifest_file.read_text(), object_pairs_hook=unique)
    except (ValueError, UnicodeError) as error:
        raise ValueError('Bottle manifest must be unambiguous JSON') from error
    if (not isinstance(value, dict)
            or set(value) != {'version', 'sampling', 'file', 'sha256', 'interiorRect'}
            or type(value['version']) != int or value['version'] != 1
            or value['sampling'] != 'nearest'):
        raise ValueError('Bottle manifest version, sampling or fields are invalid')
    digest = value['sha256']
    if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
        raise ValueError('Bottle manifest requires a lowercase SHA-256 value')
    rect = value['interiorRect']
    try:
        valid_rect = (isinstance(rect, list) and len(rect) == 4
                      and all(type(n) in (int, float) and math.isfinite(n) for n in rect)
                      and min(rect[:2]) >= 0 and min(rect[2:]) > 0
                      and rect[0] + rect[2] <= 1 and rect[1] + rect[3] <= 1)
    except OverflowError:
        valid_rect = False
    if not valid_rect:
        raise ValueError('Bottle interiorRect must be normalized inside the full PNG canvas')
    image = resolve(value['file'], png=True)
    if not 0 < image.stat().st_size <= 32 * 1_048_576:
        raise ValueError('Bottle PNG file size is invalid')
    data = image.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('Bottle PNG SHA-256 does not match its manifest')
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Bottle image does not contain PNG data')
    # ImageIO may recover a partial image. Packaging requires every original
    # chunk, its checksum, and the final IEND instead of accepting recovery.
    cursor, chunks = 8, []
    while cursor < len(data):
        if cursor + 12 > len(data):
            raise ValueError('Bottle PNG has an incomplete chunk')
        size = int.from_bytes(data[cursor:cursor + 4], 'big')
        end = cursor + size + 12
        if end > len(data):
            raise ValueError('Bottle PNG has truncated chunk data')
        kind = data[cursor + 4:cursor + 8]
        payload = data[cursor + 8:end - 4]
        crc = int.from_bytes(data[end - 4:end], 'big')
        if zlib.crc32(kind + payload) & 0xffffffff != crc:
            raise ValueError('Bottle PNG chunk checksum is invalid')
        chunks.append(kind)
        cursor = end
        if kind == b'IEND':
            if size != 0 or cursor != len(data):
                raise ValueError('Bottle PNG has invalid data after IEND')
            break
    if (not chunks or chunks[0] != b'IHDR' or chunks.count(b'IHDR') != 1
            or b'IDAT' not in chunks or chunks[-1] != b'IEND' or b'acTL' in chunks):
        raise ValueError('Bottle PNG must be one complete static image')
    _make_png_validator('Bottle', limits=(32 * 1_048_576, 4096, 16_777_216))(image, None)
    return {'manifest.json': manifest_file, value['file']: image}


def copy_bottle_art(source: Path, resources: Path):
    """Stage exactly the verified manifest and byte-identical source PNG."""
    target = resources / 'art' / 'bottle'
    if (resources.is_symlink() or target.parent.is_symlink() or target.is_symlink()
            or (target.exists() and not target.is_dir())):
        raise ValueError('Bottle output must be an ordinary directory')
    files = _validated_bottle_files(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='bottle-', dir=target.parent) as directory:
        staged = Path(directory) / 'bottle'
        staged.mkdir()
        for name, path in files.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staged), str(target))
    return True


def copy_attendant_art(source: Path, resources: Path):
    """Copy only manifest-owned PNGs; reject escaping paths before any writes."""
    source = source.resolve()
    if not source.exists():
        if (resources / 'art' / 'A01').exists():
            raise ValueError('A01 source is missing but output contains art; refusing stale bundled resources')
        return False  # Development builds retain the explicitly temporary fallback.

    def resolve_file(name):
        if not isinstance(name, str) or not name or Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('A01 resource must be a relative path inside its directory')
        result = (source / name).resolve()
        if not result.is_relative_to(source) or not result.is_file():
            raise ValueError('A01 resource missing or outside its directory')
        return result

    manifest_file = resolve_file('manifest.json')
    manifest = json.loads(manifest_file.read_text())
    if manifest.get('version') != 1 or not isinstance(manifest.get('stand'), dict):
        raise ValueError('Unsupported A01 manifest')
    specs = [manifest['stand']]
    if 'walk' in manifest:
        walk = manifest['walk']
        if not isinstance(walk, dict) or not isinstance(walk.get('frames'), list):
            raise ValueError('Invalid A01 walk frames')
        specs.extend(walk['frames'])
    if 'fixedActions' in manifest:
        actions = manifest['fixedActions']
        if not isinstance(actions, dict) or not isinstance(actions.get('catch'), dict):
            raise ValueError('Invalid A01 fixed actions')
        capture = actions['catch']
        for key in ('torsoUnderlay', 'net'):
            if not isinstance(capture.get(key), dict):
                raise ValueError('Missing A01 fixed action resource')
            specs.append(capture[key])
        if 'daily' in actions:
            daily = actions['daily']
            if not isinstance(daily, dict) or not isinstance(daily.get('props'), dict):
                raise ValueError('Invalid A01 daily action resources')
            specs.extend(daily['props'].values())
    files = {'manifest.json': manifest_file}
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError('Invalid A01 frame')
        name = spec.get('file')
        path = resolve_file(name)
        if path.suffix.lower() != '.png':
            raise ValueError('A01 frame must be a PNG')
        files[name] = path
    target = resources / 'art' / 'A01'
    target.parent.mkdir(parents=True, exist_ok=True)
    # Stage first so a validation/copy failure leaves an existing candidate intact.
    with tempfile.TemporaryDirectory(prefix='a01-', dir=target.parent) as directory:
        staged = Path(directory) / 'A01'
        staged.mkdir()
        for name, path in files.items():
            destination = staged / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(staged), str(target))
    return True

def copy_ui_art(source: Path, resources: Path):
    source = source.resolve()
    manifest_path = source / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('version') != 1 or set(manifest.get('assets', {})) != {'divination-vessel', 'timer-dial'}:
        raise ValueError('UI artwork manifest is incomplete')
    files = {'manifest.json': manifest_path}
    validate = _make_png_validator('UI artwork', limits=(8_000_000, 4096, 16_777_216))
    for row in manifest['assets'].values():
        name = row.get('file', '')
        if not isinstance(name, str) or Path(name).name != name or not name.endswith('.png'):
            raise ValueError('UI artwork must be a local PNG')
        path = (source / name).resolve()
        if not path.is_relative_to(source) or not path.is_file():
            raise ValueError('UI artwork missing')
        if hashlib.sha256(path.read_bytes()).hexdigest() != row.get('sha256'):
            raise ValueError('UI artwork hash mismatch')
        crop = row.get('sourceRect')
        if (not isinstance(crop, list) or len(crop) != 4 or
                any(type(value) is not int or value < 0 for value in crop) or not crop[2] or not crop[3]):
            raise ValueError('Invalid UI artwork crop')
        validate(path, crop)
        files[name] = path
    target = resources / 'art' / 'ui'
    if (resources.is_symlink() or target.is_symlink() or target.parent.is_symlink()
            or (target.exists() and not target.is_dir())):
        raise ValueError('UI output must be an ordinary directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ui-', dir=target.parent) as directory:
        staged = Path(directory) / 'ui'
        staged.mkdir()
        for name, path in files.items():
            shutil.copy2(path, staged / name)
        # A partial copy never touches the prior package. Keep it until the
        # complete stage has been installed, so a failed rename can roll back.
        previous = Path(directory) / 'previous'
        if target.exists():
            target.rename(previous)
        try:
            staged.rename(target)
        except OSError:
            if previous.exists():
                previous.rename(target)
            raise


def _validated_brand_files(source: Path):
    """Require the generated production PNG and its intact provenance; no fallback."""
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Brand artwork source directory is missing or unsafe')
    source = source.resolve()

    def read(name, limit):
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError('Brand artwork must use local filenames')
        path = source / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError('Brand artwork resource is missing or unsafe: ' + name)
        return path, path.read_bytes()

    manifest_path, manifest_data = read('manifest.json', 65_536)
    try:
        manifest = json.loads(manifest_data)
        if not isinstance(manifest, dict) or manifest.get('version') != 1:
            raise ValueError('Brand artwork manifest version is unsupported')
        filename = manifest.get('file')
        if not isinstance(filename, str) or not filename.endswith('.png'):
            raise ValueError('Brand artwork must be a PNG')
        png_path, png_data = read(filename, 8_000_000)
        if hashlib.sha256(png_data).hexdigest() != manifest.get('sha256'):
            raise ValueError('Brand artwork hash mismatch')
        size = manifest.get('pixelSize')
        if (not isinstance(size, list) or len(size) != 2
                or any(type(value) is not int for value in size)
                or size[0] != size[1] or not 1024 <= size[0] <= 4096
                or len(png_data) < 24 or png_data[12:16] != b'IHDR'
                or [int.from_bytes(png_data[16:20], 'big'),
                    int.from_bytes(png_data[20:24], 'big')] != size):
            raise ValueError('Brand artwork must match its square production dimensions')
        provenance_name = manifest.get('provenance')
        if provenance_name in ('manifest.json', filename):
            raise ValueError('Brand artwork provenance must be separate')
        provenance_path, provenance_data = read(provenance_name, 65_536)
        provenance = json.loads(provenance_data)
        if (hashlib.sha256(provenance_data).hexdigest() != manifest.get('provenance_sha256')
                or not isinstance(provenance, dict)
                or provenance.get('sha256') != manifest.get('sha256')
                or not provenance.get('tool') or not provenance.get('status')):
            raise ValueError('Brand artwork provenance does not match its PNG')
        prompt_name = manifest.get('prompt')
        if prompt_name in ('manifest.json', filename, provenance_name):
            raise ValueError('Brand artwork prompt must be separate')
        prompt_path, prompt_data = read(prompt_name, 100_000)
        if hashlib.sha256(prompt_data).hexdigest() != manifest.get('prompt_sha256'):
            raise ValueError('Brand artwork prompt hash mismatch')
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError('Brand artwork metadata is invalid') from error
    _make_png_validator('Brand artwork', limits=(8_000_000, 4096, 16_777_216))(png_path, None)
    return {name: path for name, path in [('manifest.json', manifest_path),
            (filename, png_path), (provenance_name, provenance_path), (prompt_name, prompt_path)]}


def build_brand_icon(resources: Path, source: Path = ROOT / 'assets/production/brand'):
    """Resize the validated generated PNG with AppKit, then package all ICNS sizes."""
    files = _validated_brand_files(source)
    manifest = json.loads(files['manifest.json'].read_text())
    resources = Path(resources)
    brand_target = resources / 'art/brand'
    icon_target = resources / 'Tianmu.icns'
    if (resources.is_symlink() or (resources / 'art').is_symlink()
            or brand_target.is_symlink() or icon_target.is_symlink()
            or (brand_target.exists() and not brand_target.is_dir())
            or (icon_target.exists() and not icon_target.is_file())):
        raise ValueError('Brand artwork output must use ordinary paths')
    with tempfile.TemporaryDirectory(prefix='tianmu-icon-') as directory:
        folder = Path(directory)
        iconset = folder / 'Tianmu.iconset'
        iconset.mkdir()
        swift_source = folder / 'main.swift'
        swift_source.write_text(r'''
import AppKit
let input = URL(fileURLWithPath:CommandLine.arguments[1])
let output = URL(fileURLWithPath:CommandLine.arguments[2])
guard let artwork=NSImage(contentsOf:input),
      let cg=artwork.cgImage(forProposedRect:nil,context:nil,hints:nil),
      cg.width == cg.height, cg.width >= 1024 else { fatalError("Production brand PNG did not decode") }
for size in [16,32,128,256,512] {
    for scale in [1,2] {
        let pixels=size*scale
        let bitmap=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:pixels,pixelsHigh:pixels,bitsPerSample:8,samplesPerPixel:4,hasAlpha:true,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current=NSGraphicsContext(bitmapImageRep:bitmap)
        NSGraphicsContext.current!.imageInterpolation = .high
        artwork.draw(in:NSRect(x:0,y:0,width:pixels,height:pixels),from:.zero,operation:.copy,fraction:1)
        NSGraphicsContext.restoreGraphicsState()
        let name="icon_\(size)x\(size)"+(scale == 2 ? "@2x" : "")+".png"
        try bitmap.representation(using:.png,properties:[:])!.write(to:output.appendingPathComponent(name))
    }
}
assert(NSApp == nil,"Icon conversion must not start an application")
''')
        binary = folder / 'render'
        subprocess.run(['swiftc', '-framework', 'AppKit', str(swift_source), '-o', str(binary)], check=True)
        subprocess.run([str(binary), str(files[manifest['file']]), str(iconset)], check=True)
        icon = folder / 'Tianmu.icns'
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(icon)], check=True)
        # All source validation and conversion finish before touching Resources.
        # Stage on the destination filesystem, and restore prior brand files if
        # either final rename fails.
        resources.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix='brand-', dir=resources))
        cleanup_stage = False
        installed_brand = False
        previous_brand, previous_icon = stage / 'previous-brand', stage / 'previous.icns'
        try:
            brand = stage / 'brand'
            brand.mkdir()
            for name, path in files.items():
                shutil.copy2(path, brand / name)
            shutil.copy2(icon, stage / 'Tianmu.icns')
            brand_target.parent.mkdir(exist_ok=True)
            if brand_target.exists():
                brand_target.rename(previous_brand)
            if icon_target.exists():
                icon_target.rename(previous_icon)
            brand.rename(brand_target)
            installed_brand = True
            (stage / 'Tianmu.icns').rename(icon_target)
            cleanup_stage = True
        except BaseException:
            try:
                if installed_brand:
                    shutil.rmtree(brand_target)
                if previous_brand.exists():
                    previous_brand.rename(brand_target)
                if previous_icon.exists():
                    previous_icon.rename(icon_target)
                cleanup_stage = True
            except BaseException as restore_error:
                # A failed restore must leave its old assets recoverable. This
                # directory intentionally survives; the outer temp has no copy.
                raise RuntimeError(f'Brand installation failed; recovery files retained at {stage}') from restore_error
            raise
        finally:
            if cleanup_stage:
                shutil.rmtree(stage)


def bundle_info(minimum_system, qa_save_file=None, *, embed_python=False):
    info = {
        'CFBundleName': '灶神', 'CFBundleDisplayName': '灶神', 'CFBundleExecutable': 'Tianmu',
        'CFBundleIdentifier': 'local.tianmu.garden', 'CFBundlePackageType': 'APPL',
        'CFBundleShortVersionString': '1.0.6', 'CFBundleVersion': '26',
        'CFBundleIconFile': 'Tianmu.icns',
        'LSUIElement': True, 'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': minimum_system,
        'TianmuPythonExecutable': 'Runtime/bin/python3' if embed_python else str(Path(sys.executable).resolve()),
        'TianmuEmbeddedPython': embed_python,
    }
    if qa_save_file is not None:
        info.update(CFBundleName='灶神测试', CFBundleDisplayName='灶神测试',
                    CFBundleIdentifier='local.tianmu.garden.qa',
                    TianmuQASaveFile=str(Path(qa_save_file).resolve()))
    return info


def _validated_python_licenses(source, version, build, architecture):
    """Require this exact distribution's original notices before embedding it."""
    source = Path(source)
    def read(name):
        path = source / name
        if (Path(name).name != name or source.is_symlink() or path.is_symlink()
                or not path.is_file() or not 0 < path.stat().st_size < 200_000):
            raise ValueError('Python license resource is missing or unsafe: ' + name)
        return path.read_bytes()
    files = {'provenance.json': read('provenance.json'), 'PYTHON.json': read('PYTHON.json'),
             'README.md': read('README.md')}
    provenance = json.loads(files['provenance.json'])
    triple = {'arm64': 'aarch64-apple-darwin', 'x86_64': 'x86_64-apple-darwin'}.get(architecture)
    if (provenance.get('python_version') != version or provenance.get('release_tag') != build
            or provenance.get('target_triple') != triple
            or hashlib.sha256(files['PYTHON.json']).hexdigest() != provenance.get('metadata_sha256')):
        raise ValueError('Python license provenance does not match this runtime distribution')
    required = {'LICENSE.cpython.txt', 'LICENSE.bzip2.txt', 'LICENSE.libffi.txt', 'LICENSE.mpdecimal.txt',
                'LICENSE.expat.txt', 'LICENSE.openssl-3.txt', 'LICENSE.liblzma.txt',
                'LICENSE.sqlite.txt', 'LICENSE.libuuid.txt'}
    for row in provenance.get('files', []):
        name = row.get('file', '')
        data = read(name)
        if (name in files or len(data) != row.get('bytes')
                or hashlib.sha256(data).hexdigest() != row.get('sha256')):
            raise ValueError('Python license bytes do not match the official archive: ' + name)
        files[name] = data
    if not required.issubset(files):
        raise ValueError('Python dependency license collection is incomplete')
    return files


def copy_embedded_python(resources: Path):
    """Copy the current relocatable CPython; reject dependencies outside the app/system.

    This does not download, install, rewrite Mach-O files, or invoke codesign.
    A framework/Homebrew build with absolute private dependencies fails closed.
    """
    if platform.system() != 'Darwin':
        raise ValueError('Embedded Python packaging requires macOS')
    probe = subprocess.run([sys.executable, '-I', '-B', '-c',
                            'import json,platform,sys,sysconfig; print(json.dumps({'
                            '"executable":sys.executable,"prefix":sys.base_prefix,'
                            '"stdlib":sysconfig.get_path("stdlib"),"version":platform.python_version(),'
                            '"architecture":platform.machine(),"implementation":sys.implementation.name}))'],
                           check=True, capture_output=True, text=True, timeout=20)
    source = json.loads(probe.stdout)
    prefix = Path(source['prefix']).resolve()
    executable = Path(source['executable']).resolve()
    stdlib = Path(source['stdlib']).resolve()
    if (source['implementation'] != 'cpython' or source['architecture'] != platform.machine()
            or not executable.is_relative_to(prefix) or not stdlib.is_relative_to(prefix)
            or stdlib.parent != prefix / 'lib' or executable.parent != prefix / 'bin'):
        raise ValueError('Python must be a same-architecture standalone bin/lib distribution')
    license_file = stdlib / 'LICENSE.txt'
    if not license_file.is_file() or license_file.stat().st_size < 1000:
        raise ValueError('The Python distribution must include its original LICENSE.txt')
    build_file = prefix / 'BUILD'
    build = build_file.read_text().strip() if build_file.is_file() else None
    licenses = _validated_python_licenses(ROOT / 'tools/python_runtime_licenses',
                                         source['version'], build, source['architecture'])
    provenance = json.loads(licenses['provenance.json'])
    binary_name = 'bin/python' + '.'.join(source['version'].split('.')[:2])
    verified = next((row for row in provenance.get('runtime_verification', {}).get('binaries', [])
                     if row.get('file') == binary_name and row.get('byte_identical') is True), {})
    executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    if executable_hash != verified.get('official_sha256'):
        raise ValueError('Python executable does not match the verified official runtime archive')
    resources = Path(resources)
    target = resources / 'Runtime'
    if resources.is_symlink() or target.exists() or target.is_symlink():
        raise ValueError('Embedded runtime requires a fresh ordinary Resources/Runtime directory')
    resources.mkdir(parents=True, exist_ok=True)
    excluded = {'__pycache__', 'site-packages', 'test', 'tests', 'ensurepip', 'idlelib',
                'tkinter', 'turtledemo', 'turtle.py', 'venv', 'config-' + stdlib.name[6:] + '-darwin'}

    def ignored(directory, names):
        return [name for name in names if name in excluded or name.startswith('_tkinter.')
                or name.endswith(('.pyc', '.pyo'))]

    # Inspect only files selected for copying. Local pip/user packages never enter the app.
    def check_tree(directory):
        for child in directory.iterdir():
            if child.name in ignored(directory, [child.name]):
                continue
            resolved = child.resolve(strict=True)
            if not resolved.is_relative_to(stdlib) or (child.is_symlink() and child.is_dir()):
                raise ValueError('Python standard library contains an unsafe symbolic link')
            if child.is_dir():
                check_tree(child)
            elif not child.is_file():
                raise ValueError('Python standard library contains an unsupported file type')

    check_tree(stdlib)
    magic = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf',
             b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
             b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
    with tempfile.TemporaryDirectory(prefix='embedded-python-', dir=resources) as temporary:
        staged = Path(temporary) / 'Runtime'
        (staged / 'bin').mkdir(parents=True)
        shutil.copy2(executable, staged / 'bin/python3')
        shutil.copytree(stdlib, staged / 'lib' / stdlib.name, ignore=ignored)
        shutil.copy2(license_file, staged / 'LICENSE.txt')
        if build_file.is_file():
            shutil.copy2(build_file, staged / 'BUILD')
        (staged / 'licenses').mkdir()
        for name, data in licenses.items():
            (staged / 'licenses' / name).write_bytes(data)
        dependency_rows = []
        processed = set()
        pending = []
        for path in staged.rglob('*'):
            if path.is_file():
                with path.open('rb') as stream:
                    if stream.read(4) in magic:
                        pending.append(path)
        while pending:
            binary = pending.pop()
            if binary in processed:
                continue
            processed.add(binary)
            loaded = subprocess.run(['/usr/bin/otool', '-L', str(binary)], check=True,
                                    capture_output=True, text=True, timeout=20).stdout
            commands = subprocess.run(['/usr/bin/otool', '-l', str(binary)], check=True,
                                      capture_output=True, text=True, timeout=20).stdout
            rpaths = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset \d+\)', commands)

            def expand(value):
                if value.startswith('@loader_path/'):
                    return binary.parent / value[len('@loader_path/'):]
                if value.startswith('@executable_path/'):
                    return staged / 'bin' / value[len('@executable_path/'):]
                raise ValueError('Python runtime has an unsupported or absolute private load path: ' + value)

            for rpath in rpaths:
                if not expand(rpath).resolve().is_relative_to(staged.resolve()):
                    raise ValueError('Python runtime rpath escapes its bundled directory')
            dependencies = [line.strip().split(' (compatibility version', 1)[0]
                            for line in loaded.splitlines()[1:] if '(compatibility version' in line]
            for dependency in dependencies:
                if dependency.startswith(('/usr/lib/', '/System/Library/')):
                    continue
                if dependency.startswith('@rpath/'):
                    candidates = [expand(path) / dependency[len('@rpath/'):] for path in rpaths]
                    # The executable's rpath is inherited by dependent modules in a standalone runtime.
                    candidates.append(staged / 'lib' / dependency[len('@rpath/'):])
                else:
                    candidates = [expand(dependency)]
                resolved = None
                for candidate in candidates:
                    candidate = candidate.resolve()
                    if not candidate.is_relative_to(staged.resolve()):
                        raise ValueError('Python runtime dependency escapes its bundled directory')
                    original = (prefix / candidate.relative_to(staged)).resolve()
                    if not original.is_relative_to(prefix):
                        raise ValueError('Python runtime dependency symlink escapes its source distribution')
                    if candidate.is_file() or original.is_file():
                        resolved = candidate
                        if not candidate.is_file():
                            candidate.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(original, candidate)
                            pending.append(candidate)
                        break
                if resolved is None:
                    raise ValueError('Python runtime dependency is missing: ' + dependency)
            dependency_rows.append({'path': str(binary.relative_to(staged)),
                                    'dependencies': dependencies, 'rpaths': rpaths})
        smoke = subprocess.run([str(staged / 'bin/python3'), '-I', '-B', '-c',
                                'import ctypes,json,ssl,sqlite3,bz2,lzma,zlib,zoneinfo,sys; '
                                'print(json.dumps({"prefix":sys.prefix,"paths":sys.path}))'],
                               env={'PATH': '/nonexistent', 'LC_CTYPE': 'UTF-8'},
                               check=True, capture_output=True, text=True, timeout=20)
        checked = json.loads(smoke.stdout)
        if (Path(checked['prefix']).resolve() != staged.resolve()
                or any(not Path(path).resolve().is_relative_to(staged.resolve()) for path in checked['paths'])):
            raise ValueError('Copied Python searches outside its bundled standard library')
        metadata = {'formatVersion': 1, 'selfContained': True, 'version': source['version'],
                    'architecture': source['architecture'], 'distributionBuild': build,
                    'executable': 'bin/python3', 'sourceExecutableSHA256': executable_hash,
                    'officialExecutableVerified': True,
                    'codesignInvoked': False, 'machO': sorted(dependency_rows, key=lambda row: row['path']),
                    'excluded': sorted(excluded | {'_tkinter.*', '*.pyc', '*.pyo'}),
                    'files': [{'path': str(path.relative_to(staged)), 'bytes': path.stat().st_size,
                               'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                              for path in sorted(staged.rglob('*')) if path.is_file()]}
        (staged / 'runtime-manifest.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
        shutil.move(str(staged), str(target))
    return metadata


def _desktop_motion_smoke(module_text):
    """Execute the same system JavaScriptCore engine as the native host, without UI."""
    import ctypes
    pointer = ctypes.c_void_p
    js = ctypes.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore')

    def bind(name, arguments, result=None):
        function = getattr(js,name)
        function.argtypes, function.restype = arguments,result
        return function

    create = bind('JSGlobalContextCreate',[pointer],pointer)
    release = bind('JSGlobalContextRelease',[pointer])
    string = bind('JSStringCreateWithUTF8CString',[ctypes.c_char_p],pointer)
    free_string = bind('JSStringRelease',[pointer])
    evaluate = bind('JSEvaluateScript',[pointer,pointer,pointer,pointer,ctypes.c_int,ctypes.POINTER(pointer)],pointer)
    boolean = bind('JSValueToBoolean',[pointer,pointer],ctypes.c_bool)
    smoke = r'''
;(() => {
  const api = globalThis.TianmuFlyMotion;
  if (!api || typeof api.step !== 'function' || typeof api.reset !== 'function') return false;
  api.reset();
  const input = {time:1,screens:[{id:'build-check',x:0,y:0,w:1200,h:800}],icons:[],
    pointer:{enabled:false},suppressThreat:false,
    rows:[{id:'build-check-adult',seed:'12345',x:600,y:400,sex:'f'}]};
  let result = api.step(input);
  for (let frame=1; frame<=3; frame++) {
    input.time=1+frame/60; result=api.step(input);
    if (!Array.isArray(result) || result.length!==1 || result[0].id!=='build-check-adult' ||
        result[0].screenID!=='build-check' ||
        !['x','y','vx','vy','heading','animationTime','simulationTime'].every(key=>Number.isFinite(result[0][key])) ||
        !['flying','crawling','resting'].includes(result[0].activity) || result[0].simulationTime<=0) return false;
  }
  api.reset(); input.rows=[];
  result=api.step(input);
  return Array.isArray(result) && result.length===0;
})()
'''
    context = script = None
    try:
        context = create(None)
        if not context:
            raise ValueError('Desktop motion JavaScriptCore context could not be created')
        script = string((module_text+'\n'+smoke).encode('utf-8'))
        exception = pointer()
        value = evaluate(context,script,None,None,1,ctypes.byref(exception))
        if exception.value or not value or not boolean(context,value):
            raise ValueError('Desktop motion step/reset API failed the JavaScriptCore build check')
    finally:
        if script: free_string(script)
        if context: release(context)


def _validated_desktop_motion_files(source: Path):
    """Check pinned provenance, all 62 original functions, and the executable adapter."""
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Desktop motion source directory is required')
    source = source.resolve()
    names = ('desktop-motion.js','source-manifest.json','NOTICE.md',
             'upstream/renderer/overlay.js','upstream/package.json','upstream/README.md')
    files = {}
    for name in names:
        path = source/name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError(f'Desktop motion required resource is missing or unsafe: {name}')
        data = path.read_bytes()
        if not data or len(data) > 2_000_000:
            raise ValueError(f'Desktop motion resource is empty or oversized: {name}')
        files[name] = data
    try:
        manifest = json.loads(files['source-manifest.json'])
        module = files['desktop-motion.js'].decode('utf-8')
        original = files['upstream/renderer/overlay.js'].decode('utf-8')
    except (ValueError,UnicodeError) as error:
        raise ValueError('Desktop motion source or manifest cannot be decoded') from error
    commit = '9c6130681c1a112c3c7faaafbad6d335cc0a1c36'
    source_hash = 'dcfe5153feff4b5bfd47ad5fdde63cf5da337cbf286bb41ba0cb0562c7f2ac95'
    if (not isinstance(manifest,dict) or manifest.get('commit') != commit or
            manifest.get('repository') != 'https://github.com/pyd021226/fly-paradise' or
            manifest.get('package_license') != 'MIT' or
            hashlib.sha256(files['upstream/renderer/overlay.js']).hexdigest() != source_hash):
        raise ValueError('Desktop motion pinned source provenance does not match')
    rows = manifest.get('files')
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
        raise ValueError('Desktop motion source manifest has no valid file list')
    records = {row.get('path'):row for row in rows if isinstance(row.get('path'),str)}
    if len(records) != len(rows):
        raise ValueError('Desktop motion source manifest has duplicate or invalid paths')
    for name in names[3:]:
        record = records.get(name,{})
        if record.get('bytes') != len(files[name]) or record.get('sha256') != hashlib.sha256(files[name]).hexdigest():
            raise ValueError(f'Desktop motion source hash mismatch: {name}')
    function = re.compile(r'^function (\w+)\([^\n]*\) \{(?:[^\n]*\}|.*?^\})',re.M|re.S)
    functions = {match[1]:match[0] for match in function.finditer(original)}
    needed, todo = set(), ['spawnFly','stepFly']
    while todo:
        name = todo.pop()
        if name in needed: continue
        if name not in functions:
            raise ValueError(f'Desktop motion original function is missing: {name}')
        needed.add(name)
        todo.extend(other for other in functions if other not in needed and re.search(r'\b'+other+r'\s*\(',functions[name]))
    start, end = '// BEGIN UPSTREAM FUNCTIONS','// END UPSTREAM FUNCTIONS'
    if len(needed) != 62 or module.count(start) != 1 or module.count(end) != 1 or '\x00' in module:
        raise ValueError('Desktop motion original 62-function boundary is incomplete')
    section = module.split(start,1)[1].split(end,1)[0]
    adapted = list(function.finditer(section))
    if (len(adapted) != 62 or {match[1] for match in adapted} != needed or
            any(match[0] != functions[match[1]] for match in adapted)):
        raise ValueError('Desktop motion original function bodies have changed or are missing')
    constants = original[original.index('const FLY_HIT'):original.index('\nfunction mateMs')].strip()
    if constants not in module:
        raise ValueError('Desktop motion original constants are incomplete')
    _desktop_motion_smoke(module)
    return {name:hashlib.sha256(data).hexdigest() for name,data in files.items()}


def _validate_bundled_desktop_motion(source: Path, expected):
    actual = _validated_desktop_motion_files(source)
    if actual != expected:
        raise ValueError('Desktop motion bundled resources differ from the validated source')


def build_timer_core(backend):
    # Build from the exact sources copied into this package. Runtime must be
    # able to load the same content-addressed library without a compiler or
    # write access to the application bundle.
    result = subprocess.run([sys.executable, '-B', '-c',
                             'from tianmu_mvp.duration import ensure_native_library; '
                             'print(ensure_native_library())'],
                            cwd=backend, check=True, capture_output=True, text=True, timeout=45)
    library = Path(result.stdout.strip())
    if library.parent != backend / 'build' or not library.is_file() or library.stat().st_size == 0:
        raise ValueError('计时核心未完整打入应用，已停止构建')
    return library


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--qa-save-file', type=Path, help='将专用测试包的默认启动也绑定到隔离存档')
    parser.add_argument('--embed-python', action='store_true', help='内置当前独立 Python 运行时，使当前 Mac 的本地包可搬移')
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit('打包需要 Python 3.10 或更新版本；请使用 python3.12，避免生成无法启动数据服务的候选。')
    # This package is for the current Mac. A Swift toolchain's inferred target
    # can be newer than the installed product version, causing LaunchServices
    # to reject an otherwise runnable binary. Pin both Mach-O and app metadata.
    minimum_system = platform.mac_ver()[0]
    architecture = platform.machine()
    if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', minimum_system) or architecture not in ('arm64', 'x86_64'):
        raise SystemExit('无法确认当前 Mac 的系统版本与架构，已停止打包')
    swift_target = f'{architecture}-apple-macosx{minimum_system}'
    target = args.output.resolve()
    if target.suffix != '.app':
        raise SystemExit('输出须是 .app 目录')
    contents = target / 'Contents'
    previous_info = contents / 'Info.plist'
    if previous_info.exists():
        previous = plistlib.loads(previous_info.read_bytes())
        if previous.get('CFBundleShortVersionString') == '0.9.8':
            raise SystemExit('0.9.8 已撤回且须保留，不能覆盖；请选择新的输出目录')
    insect_source = ROOT / 'assets' / 'production' / 'insects'
    bottle_source = ROOT / 'assets' / 'production' / 'bottle'
    if not insect_source.is_dir():
        raise ValueError('Insect source directory is required')
    # Fail on a missing or corrupt required bottle before creating a candidate.
    _validated_bottle_files(bottle_source)
    _validated_brand_files(ROOT / 'assets/production/brand')
    motion_files = _validated_desktop_motion_files(ROOT / 'third_party/fly-paradise')
    copy_insect_art(insect_source, contents / 'Resources')
    copy_bottle_art(bottle_source, contents / 'Resources')
    copy_ui_art(ROOT / 'assets/production/ui', contents / 'Resources')
    build_brand_icon(contents / 'Resources')
    binary = contents / 'MacOS' / 'Tianmu'
    binary.parent.mkdir(parents=True, exist_ok=True)
    backend = contents / 'Resources' / 'backend'
    backend.mkdir(parents=True, exist_ok=True)
    copy_attendant_art(ROOT / 'assets' / 'production' / 'A01', contents / 'Resources')
    copy_scene_art(ROOT / 'assets' / 'production' / 'scene', contents / 'Resources')
    for name in ('LICENSE', 'ASSET-LICENSES.md'):
        shutil.copy2(ROOT / name, contents / 'Resources' / name)
    shutil.copytree(ROOT / 'tianmu_mvp', backend / 'tianmu_mvp', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', 'ui.py', 'drawing.py', 'native_overlay.py'))
    # Vendored originals are read-only. A previously built candidate inherits
    # that mode, so allow replacing only its generated dependency copies.
    dependency_target = backend / 'third_party'
    if dependency_target.is_dir():
        for bundled in dependency_target.rglob('*'):
            if bundled.is_file() and not bundled.is_symlink():
                bundled.chmod(bundled.stat().st_mode | 0o200)
    shutil.copytree(ROOT / 'third_party', dependency_target, dirs_exist_ok=True)
    _validate_bundled_desktop_motion(dependency_target / 'fly-paradise', motion_files)
    build_timer_core(backend)
    if args.embed_python:
        copy_embedded_python(contents / 'Resources')
    elif (contents / 'Resources/Runtime').exists():
        raise ValueError('Output already contains an embedded runtime; use a fresh output directory')
    with tempfile.TemporaryDirectory() as temporary:
        # Reuse only the verified scene/input classes, never the old Host or Tk bridge.
        scene = (ROOT / 'native' / 'OverlayHost.swift').read_text().split('final class Host:')[0]
        scene_file = Path(temporary) / 'DesktopScene.swift'
        scene_file.write_text(scene)
        subprocess.run(['swiftc', '-O', '-whole-module-optimization', '-target', swift_target, '-framework', 'AppKit', '-framework', 'SwiftUI',
                        str(scene_file), str(ROOT / 'native' / 'v1' / 'Presentation.swift'), str(ROOT / 'native' / 'v1' / 'WindowPlacement.swift'), str(ROOT / 'native' / 'v1' / 'InsectArtwork.swift'), str(ROOT / 'native' / 'v1' / 'DesktopInsects.swift'), str(ROOT / 'native' / 'v1' / 'TimerControls.swift'), str(ROOT / 'native/v1/BrandArtwork.swift'), str(ROOT / 'native/v1/WeatherAtmosphere.swift'), str(ROOT / 'native/v1/LeisureViews.swift'), str(ROOT / 'native' / 'v1' / 'main.swift'), '-o', str(binary)], check=True)
    (contents / 'Info.plist').write_bytes(plistlib.dumps(bundle_info(minimum_system,args.qa_save_file,
                                                                embed_python=args.embed_python)))
    print(target)

if __name__ == '__main__':
    main()
