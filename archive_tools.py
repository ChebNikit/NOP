"""Bounded extraction of verified Windows vendor archives."""
import hashlib
from pathlib import Path, PurePosixPath
import subprocess

# 7-Zip Extra 26.05, official x64 standalone console binary; no system PATH lookup.
SEVENZIP = Path(__file__).resolve().parent / '.build-tools' / '7zip-26.05' / '7za.exe'
SEVENZIP_SHA256 = '7ddf0a3bc451e166679296be630d6f0573eb386159c04184761c43020c484291'


def safe_member(name, size, directory=False):
    path = PurePosixPath(name.replace('\\', '/'))
    if path.is_absolute() or '..' in path.parts or any(':' in p for p in path.parts):
        raise RuntimeError('Unsafe archive member: ' + name)
    if not path.parts or any(p.rstrip(' .') != p for p in path.parts):
        raise RuntimeError('Ambiguous Windows archive member: ' + name)
    return max(0, int(size or 0))


def extract_7z(archive: Path, destination: Path):
    import py7zr
    # py7zr can list BCJ2 archives, but cannot decompress their BCJ2 streams.
    # Keep all existing member checks and use native 7-Zip only for extraction.
    with py7zr.SevenZipFile(archive, 'r') as container:
        entries = container.list()
        if len(entries) > 100000:
            raise RuntimeError('Vendor archive has too many members')
        total = 0
        names = set()
        for item in entries:
            total += safe_member(item.filename, item.uncompressed, item.is_directory)
            if getattr(item, 'is_symlink', False):
                raise RuntimeError('Symlink in Windows vendor archive')
            normalized = item.filename.replace('\\', '/').casefold()
            if normalized in names:
                raise RuntimeError('Case-colliding vendor archive members')
            names.add(normalized)
        if total > 12 * 1024**3:
            raise RuntimeError('Vendor archive exceeds 12 GiB')
    try:
        actual = hashlib.sha256(SEVENZIP.read_bytes()).hexdigest()
    except OSError as error:
        raise RuntimeError('Private 7-Zip 26.05 is unavailable: ' + str(SEVENZIP)) from error
    if actual != SEVENZIP_SHA256:
        raise RuntimeError('Private 7-Zip 26.05 SHA-256 mismatch: ' + str(SEVENZIP))
    destination.mkdir(parents=True, exist_ok=True)
    command = [str(SEVENZIP), 'x', '-y', '-bd', '-bsp0', '-sccUTF-8',
               '-o' + str(destination.resolve()), '--', str(archive.resolve())]
    print('Extracting with private 7-Zip 26.05 (BCJ2 enabled)...', flush=True)
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding='utf-8',
            errors='replace', timeout=900,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError('Cannot finish private 7-Zip extraction: ' + str(error)) from error
    if result.returncode != 0:
        raise RuntimeError('7-Zip extraction failed (exit ' + str(result.returncode) + '):\n' + result.stdout[-8000:])
    print('7-Zip extraction and archive CRC checks passed.', flush=True)
