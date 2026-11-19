#!/usr/bin/python3 -I
"""Run the repository's original production publisher inside the ECS Ubuntu root."""
import contextlib
import fcntl
import io
import json
import os
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path('/opt/citrus-runtime/rootfs')
APP = ROOT / 'opt/citrus-app'
STAGE = Path('/root/cache/citrus-publish')
REPO = 'jinkun268-lang/app'
API = 'https://api.github.com/repos/' + REPO
LIVE_DB = 'citrus_app'
BACKUPS = '/var/backups/citrus-app'


def github_json(url):
    with urllib.request.urlopen(url, timeout=25) as response:
        return json.load(response)


def main_commit(short):
    sha = github_json(API + '/commits/' + short)['sha']
    if not re.fullmatch('[a-f0-9]{40}', sha) or not sha.startswith(short):
        raise ValueError('Release commit mismatch')
    comparison = github_json(API + '/compare/' + sha + '...main')
    if comparison['status'] not in ('identical', 'ahead'):
        raise ValueError('Release commit is outside production main history')
    return sha


@contextlib.contextmanager
def upload(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != pwd.getpwnam('deploy').pw_uid:
            raise ValueError('Expected a regular CI upload')
        yield f


def release_bundle(work, sha, tag, uploaded):
    # Privileged release logic comes from the selected repository commit. CI supplies
    # only the built, publicly served frontend and a matching copy of the publisher.
    archive = work / 'source.tar.gz'
    with urllib.request.urlopen('https://codeload.github.com/' + REPO + '/tar.gz/' + sha, timeout=60) as src, archive.open('wb') as f:
        shutil.copyfileobj(src, f)
    paths = set()
    script = None
    frontend = set()
    with tarfile.open(str(work / ('release-' + tag + '.tar.gz')), 'w:gz') as out:
        for code, stream in ((True, archive.open('rb')), (False, uploaded)):
            with stream, tarfile.open(fileobj=stream, mode='r|gz') as source:
                for item in source:
                    path = PurePosixPath(item.name)
                    if path.is_absolute() or '..' in path.parts:
                        raise ValueError('Unsafe archive path')
                    parts = path.parts[1:] if code else path.parts
                    if not parts or item.isdir():
                        continue
                    name = '/'.join(parts)
                    asset = name.startswith('admin/dist/')
                    if code == asset:
                        continue
                    if not item.isreg() or name in paths:
                        raise ValueError('Unsupported or duplicate release member')
                    paths.add(name)
                    target = tarfile.TarInfo(name)
                    target.size = item.size
                    target.mode = 0o755 if code and item.mode & 0o111 else 0o644
                    target.mtime = item.mtime
                    with source.extractfile(item) as data:
                        if code and name == 'deploy/publish.sh':
                            script = data.read()
                            out.addfile(target, io.BytesIO(script))
                        else:
                            out.addfile(target, data)
                    if asset:
                        frontend.add(name)
    if 'admin/dist/index.html' not in frontend or not any(n.startswith('admin/dist/assets/') for n in frontend):
        raise ValueError('Missing compiled admin frontend')
    if not script or 'server/app/main.py' not in paths or 'deploy/nginx/render.py' not in paths:
        raise ValueError('Incomplete repository release')
    with upload('/tmp/publish.sh.new') as f:
        if f.read(len(script) + 1) != script:
            raise ValueError('Publisher upload differs from the repository commit')
    (work / 'publish.sh.new').write_bytes(script)


def signed_release(work, tag, archive_path):
    name = 'release-' + tag + '.tar.gz'
    try:
        with upload(str(archive_path) + '.sig') as f:
            signature = f.read(16385)
    except FileNotFoundError:
        return False
    if not signature or len(signature) > 16384:
        raise ValueError('Invalid release signature')
    (work / (name + '.sig')).write_bytes(signature)
    with upload(archive_path) as src, (work / name).open('xb') as dest:
        shutil.copyfileobj(src, dest)
    verify = ['systemd-run', '--quiet', '--wait', '--pipe', '-p', 'RootDirectory=' + str(ROOT),
              '-p', 'MountAPIVFS=yes', '-p', 'BindReadOnlyPaths=' + str(work) + ':/tmp',
              '/usr/bin/ssh-keygen', '-Y', 'verify', '-f', '/opt/citrus-app/host-tools/allowed-signers',
              '-I', 'github-actions', '-n', 'citrus-release-' + tag, '-s', '/tmp/' + name + '.sig']
    with (work / name).open('rb') as package:
        subprocess.run(verify, stdin=package, check=True)
    publisher = None
    with tarfile.open(str(work / name), 'r:gz') as archive:
        for item in archive:
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or not (item.isdir() or item.isreg()):
                raise ValueError('Unsupported release archive member')
            if path.as_posix() == 'deploy/publish.sh':
                with archive.extractfile(item) as script:
                    publisher = script.read()
    if not publisher:
        raise ValueError('Missing publisher in signed release')
    with upload('/tmp/publish.sh.new') as script:
        if script.read(len(publisher) + 1) != publisher:
            raise ValueError('Publisher differs from signed release')
    (work / 'publish.sh.new').write_bytes(publisher)
    print('Verified the CI-uploaded archive locally.', flush=True)
    return True


def guest(work, command):
    args = ['systemd-run', '--quiet', '--wait', '--pipe',
            '-p', 'RootDirectory=' + str(ROOT), '-p', 'MountAPIVFS=yes',
            '-p', 'BindPaths=' + str(work) + ':/tmp',
            '-p', 'BindPaths=' + BACKUPS, '-p', 'BindReadOnlyPaths=/run/systemd/system',
            '-p', 'BindPaths=/run/systemd/private',
            '/usr/bin/env', 'SYSTEMD_IGNORE_CHROOT=1', 'SYSTEMD_OFFLINE=0',
            'PATH=/opt/citrus-app/host-tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'DB_NAME=' + LIVE_DB]
    subprocess.run(args + command, check=True)


def publish(tag, upload_path):
    if not re.fullmatch('[a-f0-9]{12}', tag) or str(upload_path) != '/tmp/release-' + tag + '.tar.gz':
        raise ValueError('Expected matching CI commit and archive path')
    STAGE.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(STAGE)) as temp:
        work = Path(temp)
        if not signed_release(work, tag, upload_path):
            # Compatibility for already deployed, unsigned versions of the workflow.
            sha = main_commit(tag)
            with upload(upload_path) as f:
                release_bundle(work, sha, tag, f)
        current = os.readlink(str(APP / 'current'))
        if current == '/opt/citrus-app/releases/' + tag:
            # The old publisher reuses the tag directory. Keep a runnable previous
            # version when Actions retries the same commit.
            releases = APP / 'releases'
            safe = Path(tempfile.mkdtemp(prefix=tag + '-previous-', dir=str(releases)))
            subprocess.run(['cp', '-a', '--link', str(releases / tag) + '/.', str(safe)], check=True)
            safe.chmod(0o755)
            link = APP / ('.current-retry-' + safe.name)
            link.symlink_to('/opt/citrus-app/releases/' + safe.name)
            os.replace(str(link), str(APP / 'current'))
            try:
                guest(work, ['/opt/citrus-app/render-gateway.sh'])
                subprocess.run(['systemctl', 'reload-or-restart', 'citrus-app', 'citrus-inference'], check=True)
            except BaseException:
                link.symlink_to(current)
                os.replace(str(link), str(APP / 'current'))
                guest(work, ['/opt/citrus-app/render-gateway.sh'])
                subprocess.run(['systemctl', 'reload-or-restart', 'citrus-app', 'citrus-inference'], check=True)
                raise
        guest(work, ['/bin/bash', '/opt/citrus-app/publish.sh', str(upload_path), tag])


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('Expected an Actions archive and commit')
    with open('/opt/citrus-app/.publish.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        publish(sys.argv[2], sys.argv[1])
