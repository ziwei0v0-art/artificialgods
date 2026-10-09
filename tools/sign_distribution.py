"""Seal a fresh copy of a native app, without launching or notarizing it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile


MACH_O_MAGIC = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
                b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
                b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca',
                b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise ValueError(result.stderr.strip() or result.stdout.strip()
                         or 'Command failed: ' + arguments[0])
    return result.stdout + result.stderr


def sha256(path):
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def developer_identity(requested):
    """Select only one exact, valid Developer ID Application identity; no fallback."""
    if not (requested.startswith('Developer ID Application: ')
            or re.fullmatch(r'[0-9a-fA-F]{40}', requested)):
        raise ValueError('An exact Developer ID Application identity name or SHA-1 is required')
    listing = run(['/usr/bin/security', 'find-identity', '-v', '-p', 'codesigning'])
    identities = re.findall(r'^\s*\d+\)\s+([0-9A-Fa-f]{40})\s+"(Developer ID Application: [^"]+)"',
                            listing, re.MULTILINE)
    matches = {(fingerprint.upper(), name) for fingerprint, name in identities
               if requested == name or requested.upper() == fingerprint.upper()}
    if len(matches) != 1:
        raise ValueError('Developer ID Application identity is missing or ambiguous; '
                         'no signing was performed and no ad-hoc fallback is allowed')
    return next(iter(matches))


def inspect_input(app, output):
    if app.is_symlink() or not app.is_dir() or app.suffix != '.app':
        raise ValueError('Input must be an ordinary .app directory')
    app = app.resolve()
    if output.is_symlink() or output.exists():
        raise ValueError('Output already exists; choose a new .app path')
    output = output.resolve()
    if output.suffix != '.app':
        raise ValueError('Output must name a new .app directory')
    if output.is_relative_to(app):
        raise ValueError('Output must not be inside the input app')
    binaries = []
    for path in sorted(app.rglob('*')):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            # An absolute link would still point at the original after copying.
            try:
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError) as error:
                raise ValueError('Input contains a broken or cyclic symlink') from error
            if (Path(os.readlink(path)).is_absolute() or not resolved.is_relative_to(app)
                    or not resolved.is_file()):
                raise ValueError('Input symlink must be relative and target a file inside the app')
        elif stat.S_ISDIR(mode):
            if path.suffix in {'.app', '.framework', '.xpc', '.appex', '.bundle'}:
                raise ValueError('Nested code bundles need a separate signing plan: ' + str(path))
        elif stat.S_ISREG(mode):
            with path.open('rb') as stream:
                if stream.read(4) in MACH_O_MAGIC:
                    binaries.append(path.relative_to(app))
        else:
            raise ValueError('Input contains an unsupported file type: ' + str(path))
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    executable = info.get('CFBundleExecutable') if isinstance(info, dict) else None
    if (not isinstance(executable, str) or not executable
            or Path(executable).name != executable or executable in ('.', '..')):
        raise ValueError('Input must declare a plain CFBundleExecutable filename')
    main = Path('Contents/MacOS') / executable
    if main not in binaries:
        raise ValueError('CFBundleExecutable must be a regular Mach-O file')
    return app, output, main, binaries


def sign_copy(app, output, *, identity=None):
    if sys.platform != 'darwin':
        raise ValueError('Signing requires macOS')
    app, output, main, binaries = inspect_input(Path(app), Path(output))
    fingerprint, name = developer_identity(identity) if identity is not None else ('-', 'ad-hoc')
    options = ['--options', 'runtime', '--timestamp'] if identity is not None else ['--timestamp=none']
    before = {path: sha256(app / path) for path in binaries}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.sign-distribution-', dir=output.parent) as temporary:
        staged = Path(temporary) / output.name
        shutil.copytree(app, staged, symlinks=True)
        # Python's executable, dylibs and .so modules are all signed before the
        # outer resource envelope. Never use --deep for signing.
        for relative in sorted((p for p in binaries if p != main),
                               key=lambda p: (-len(p.parts), str(p))):
            run(['/usr/bin/codesign', '--force', '--sign', fingerprint, *options,
                 str(staged / relative)])
        run(['/usr/bin/codesign', '--force', '--sign', fingerprint, *options, str(staged)])
        rows = []
        for relative in sorted(binaries):
            path = staged / relative
            run(['/usr/bin/codesign', '--verify', '--strict', str(path)])
            details = run(['/usr/bin/codesign', '--display', '--verbose=4', str(path)])
            if identity is not None:
                if (f'Authority={name}\n' not in details or 'Timestamp=' not in details
                        or '(runtime)' not in details):
                    raise ValueError('Developer ID signature lacks expected authority, timestamp or runtime')
            elif 'Signature=adhoc' not in details:
                raise ValueError('Expected an explicit ad-hoc signature')
            rows.append({'path': str(relative), 'inputSHA256': before[relative],
                         'signedSHA256': sha256(path)})
        run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(staged)])
        seal = staged / 'Contents/_CodeSignature/CodeResources'
        if not seal.is_file():
            raise ValueError('Signed app is missing its resource envelope')
        # copytree creates the destination exclusively. Even if it appears after
        # preflight, it is never overwritten. Only a fully verified app is copied.
        shutil.copytree(staged, output, symlinks=True)
    run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(output)])
    return {'formatVersion': 1, 'mode': 'developer-id' if identity is not None else 'ad-hoc',
            'input': str(app), 'output': str(output), 'identity': name,
            'identitySHA1': fingerprint if identity is not None else None,
            'machO': rows, 'resourceSealSHA256': sha256(output / 'Contents/_CodeSignature/CodeResources'),
            'codesignVerification': 'passed', 'notarization': 'not-performed',
            'gatekeeper': 'not-assessed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True, help='input app; preserved unchanged')
    parser.add_argument('--output', type=Path, required=True, help='new signed copy; must not exist')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--ad-hoc', action='store_true', help='local resource seal; not Gatekeeper trust')
    mode.add_argument('--identity', help='exact Developer ID Application name or certificate SHA-1')
    args = parser.parse_args()
    try:
        report = sign_copy(args.app, args.output, identity=args.identity)
    except (ValueError, OSError, plistlib.InvalidFileException, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'Signing failed: {error}\nNo success report was produced.\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
