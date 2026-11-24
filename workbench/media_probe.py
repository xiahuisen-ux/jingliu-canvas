"""Install the small macOS media probe into the app runtime if it is missing."""
import base64
import hashlib
import io
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

PACKAGES = {
    'arm64': ('darwin-arm64', '5.0.1', 'vwNCNjokH8hfkbl6m95zICHwkSzhEvDC3GVBcUp5HX8+4wsX10SP3B+bGur7XUzTIZ4cQpgJmEIAx6TUwRepMg=='),
    'x86_64': ('darwin-x64', '5.1.0', 'J+YGscZMpQclFg31O4cfVRGmDpkVsQ2fZujoUdMAAYcP0NtqpC49Hs3SWJpBdsGB4VeqOt5TTm1vSZQzs1NkhA=='),
}

def main():
    target = Path(sys.prefix) / 'bin' / 'ffprobe'
    if os.environ.get('JINGLIU_FFPROBE') or shutil.which('ffprobe') or target.is_file():
        return
    package, version, digest = PACKAGES[platform.machine()]
    url = f'https://registry.npmjs.org/@ffprobe-installer/{package}/-/{package}-{version}.tgz'
    data = subprocess.check_output(['curl','-fsSL','--retry','2','--max-time','180',url])
    if hashlib.sha512(data).digest() != base64.b64decode(digest):
        raise ValueError('FFprobe 下载校验失败')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        member = archive.getmember('package/ffprobe')
        if not member.isfile():
            raise ValueError('FFprobe 文件格式错误')
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as tmp:
            shutil.copyfileobj(archive.extractfile(member),tmp)
    candidate=Path(tmp.name)
    try:
        candidate.chmod(0o755)
        subprocess.run([candidate,'-version'],check=True,stdout=subprocess.DEVNULL)
        candidate.replace(target)
    finally:
        candidate.unlink(missing_ok=True)

if __name__ == '__main__':
    main()
