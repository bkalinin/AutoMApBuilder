"""Create a reproducible Unity package containing only this tool's authored assets."""
import gzip
import hashlib
import io
from pathlib import Path
import tarfile
import uuid

root = Path(__file__).resolve().parent
asset_root = root / 'Assets/CarXMapValidator'
paths = sorted([asset_root] + [p for p in asset_root.rglob('*') if p.suffix != '.meta'])
entries = {}
for path in paths:
    relative = path.relative_to(root).as_posix()
    guid = uuid.uuid5(uuid.NAMESPACE_URL, 'carx-map-validator/' + relative).hex
    if path.is_dir():
        meta = f'fileFormatVersion: 2\nguid: {guid}\nfolderAsset: yes\nDefaultImporter:\n  externalObjects: {{}}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n'
    elif path.suffix == '.cs':
        meta = f'fileFormatVersion: 2\nguid: {guid}\nMonoImporter:\n  externalObjects: {{}}\n  serializedVersion: 2\n  defaultReferences: []\n  executionOrder: 0\n  icon: {{instanceID: 0}}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n'
    else:
        meta = f'fileFormatVersion: 2\nguid: {guid}\nDefaultImporter:\n  externalObjects: {{}}\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n'
    meta_bytes = meta.encode()
    Path(str(path) + '.meta').write_bytes(meta_bytes)
    entries[guid + '/pathname'] = relative.encode()
    entries[guid + '/asset.meta'] = meta_bytes
    if path.is_file(): entries[guid + '/asset'] = path.read_bytes()

target = root / 'dist/CarXMapValidator-4.0.0.unitypackage'
target.parent.mkdir(exist_ok=True)
with target.open('wb') as file, gzip.GzipFile(filename='', mode='wb', fileobj=file, mtime=0) as compressed:
    with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(entries.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
with tarfile.open(target, 'r:gz') as archive:
    actual = {m.name: archive.extractfile(m).read() for m in archive.getmembers()}
assert actual == entries
print(f'Package verified: {len(paths)} assets/folders, {target.stat().st_size} bytes')
print('SHA256:', hashlib.sha256(target.read_bytes()).hexdigest())
