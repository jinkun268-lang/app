#!/usr/bin/python3 -I
"""Restricted entry point for the GitHub Actions deploy key."""
import filecmp
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

INBOX = Path('/opt/citrus-app/downloads')
LIVE = Path('/opt/citrus-runtime/rootfs/opt/citrus-app/downloads')


def publish_apk():
    latest = INBOX / 'citrus-collect-latest.apk'
    if latest.is_symlink() or not latest.is_file():
        raise ValueError('Missing latest APK upload')
    versions = sorted(
        (p for p in INBOX.glob('citrus-collect-v*.apk')
         if re.fullmatch(r'citrus-collect-v[0-9A-Za-z][0-9A-Za-z._-]*\.apk', p.name)
         and not p.is_symlink() and p.is_file()),
        key=lambda p: p.stat().st_mtime_ns, reverse=True)
    version = next((p for p in versions if filecmp.cmp(str(p), str(latest), shallow=False)), None)
    if version is None:
        raise ValueError('Latest APK does not match a completed version upload')
    with tempfile.TemporaryDirectory(prefix='.publish-', dir=str(LIVE)) as tmp:
        candidate = Path(tmp) / 'version.apk'
        shutil.copyfile(str(version), str(candidate))
        with zipfile.ZipFile(str(candidate)) as apk:
            if not {'AndroidManifest.xml','classes.dex'}.issubset(apk.namelist()):
                raise ValueError('Incomplete Android package')
        candidate.chmod(0o644)
        current = Path(tmp) / 'latest.apk'
        os.link(str(candidate), str(current))
        os.replace(str(candidate), str(LIVE / version.name))
        os.replace(str(current), str(LIVE / latest.name))
    print('Published {} and latest APK ({} bytes).'.format(version.name, latest.stat().st_size))
    latest.unlink()
    version.unlink()


if __name__ == '__main__':
    cmd = os.environ.get('SSH_ORIGINAL_COMMAND','')
    if cmd in ('internal-sftp', '/usr/libexec/openssh/sftp-server', '/usr/lib/openssh/sftp-server'):
        os.execl('/usr/libexec/openssh/sftp-server','sftp-server')
    if cmd.strip() == 'ls -lh /opt/citrus-app/downloads/ | tail -3':
        publish_apk()
    else:
        match = re.fullmatch(r'sudo /opt/citrus-app/publish\.sh (/tmp/release-([a-f0-9]{12})\.tar\.gz) \2\s*&& rm -f \1 /tmp/publish\.sh\.new', cmd.strip())
        if not match:
            raise SystemExit('Unsupported CI operation')
        package, tag = match.groups()
        subprocess.run(['sudo','-n','/opt/citrus-app/publish.sh',package,tag],check=True)
        for name in (package, '/tmp/publish.sh.new'):
            if os.path.lexists(name):
                os.unlink(name)
