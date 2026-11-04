"""Verify the complete supplied kit before native extraction or packaging."""
import hashlib,json
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent

def verify():
    manifest=json.loads((ROOT/'kit-manifest.json').read_text('utf-8'))
    if manifest.get('schema')!=1 or not manifest.get('files'):
        raise RuntimeError('The complete R12 kit manifest is missing or invalid')
    for relative,expected in manifest['files'].items():
        p=PurePosixPath(relative)
        if p.is_absolute() or '..' in p.parts or any(':' in x for x in p.parts):
            raise RuntimeError('Unsafe kit manifest path')
        path=ROOT.joinpath(*p.parts)
        if not path.is_file():raise RuntimeError('Incomplete BuildKit: missing '+relative)
        with path.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
        if actual!=expected:raise RuntimeError('BuildKit file SHA-256 mismatch: '+relative)
    print('Complete BuildKit file hashes verified:',len(manifest['files']),flush=True)
if __name__=='__main__':verify()
