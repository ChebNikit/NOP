"""Reject conflicting multimedia DLL basenames in the same NOP process."""
from pathlib import Path
import hashlib


def check_inprocess_conflicts(root):
    root = Path(root)
    prefixes = ('avcodec', 'avformat', 'avutil', 'avfilter', 'avdevice',
                'swresample', 'swscale', 'libwinpthread', 'libgcc', 'libstdc++')
    qt = {}
    for path in (root / '_internal').rglob('*.dll'):
        name = path.name.casefold()
        if name.startswith(prefixes):
            qt.setdefault(name, []).append(path)
    for path in (root / 'mpv').glob('*.dll'):
        for other in qt.get(path.name.casefold(), []):
            if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(other.read_bytes()).digest():
                raise RuntimeError('In-process multimedia DLL conflict: ' + str(path) + ' / ' + str(other) +
                    '. Use a libmpv build with static media dependencies; do not mix these DLL sets.')
    return 'No conflicting FFmpeg/MinGW DLL basenames between Qt and libmpv'
