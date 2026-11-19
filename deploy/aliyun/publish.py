#!/usr/bin/python3 -I
"""Deploy an Actions release into the Citrus Ubuntu RootDirectory on the ECS host."""
import fcntl
import filecmp
import json
import os
import pwd
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path, PurePosixPath

GUEST = Path('/opt/citrus-runtime/rootfs')
APP = GUEST / 'opt/citrus-app'
RELEASES = APP / 'releases'
ACTIVE = APP / 'current'
BACKUPS = Path('/var/backups/citrus-app')
SOCKET = '/run/citrus-inference/inference.sock'


def guest_path(path):
    return '/' + str(path.relative_to(GUEST))


def switch(link):
    temp = APP / '.current.publish-next'
    if temp.is_symlink():
        temp.unlink()
    temp.symlink_to(link)
    os.replace(str(temp), str(ACTIVE))


def unpack(upload, release):
    with tarfile.open(fileobj=upload, mode='r|gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or '.api-env' in name.parts:
                raise ValueError('Invalid release path')
            path = release.joinpath(*name.parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isreg() and name.parts:
                path.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, path.open('xb') as dest:
                    shutil.copyfileobj(source, dest)
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise ValueError('Release contains an unsupported file type')
    for filename in ('server/app/main.py', 'server/requirements.txt', 'admin/dist/index.html'):
        if not (release / filename).is_file():
            raise ValueError('Incomplete release: ' + filename)


def prepare_environment(release, previous):
    requirements = release / 'server/requirements.txt'
    if filecmp.cmp(str(requirements), str(previous / 'server/requirements.txt'), shallow=False):
        return os.readlink(str(previous / '.api-env'))
    envs = APP / 'release-envs'
    envs.mkdir(exist_ok=True)
    env = Path(tempfile.mkdtemp(prefix='api-', dir=str(envs)))
    builder = pwd.getpwnam('citrusbuild')
    os.chown(str(env), builder.pw_uid, builder.pw_gid)
    env.chmod(0o755)
    venv = guest_path(env)
    ctx = ['systemd-run', '--quiet', '--wait', '--pipe', '-p', 'RootDirectory=' + str(GUEST),
           '-p', 'User=citrusbuild', '-p', 'Group=citrusbuild', '-p', 'MountAPIVFS=yes',
           '-p', 'PrivateTmp=yes', '-p', 'NoNewPrivileges=yes', '-p', 'ProtectSystem=strict',
           '-p', 'ReadWritePaths=+' + venv, '/usr/bin/env', 'HOME=/nonexistent',
           'PYTHONNOUSERSITE=1', 'PIP_NO_CACHE_DIR=1']
    subprocess.run(ctx + ['/usr/bin/python3', '-m', 'venv', venv], check=True)
    subprocess.run(ctx + [venv + '/bin/python', '-m', 'pip', 'install', '-r', guest_path(requirements)], check=True)
    subprocess.run(ctx + [venv + '/bin/python', '-m', 'pip', 'check'], check=True)
    return venv


def backup_database(tag, stamp):
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    env = (GUEST / 'etc/citrus-app/app.env').read_text().splitlines()
    urls = [line.partition('=')[2] for line in env if line.startswith('APP_DATABASE_URL=')]
    if len(urls) != 1 or urls[0].rsplit('/', 1)[-1] != 'citrus_production':
        raise RuntimeError('Live database does not match the deployment backup target')
    name = BACKUPS / ('pre-' + tag + '-' + stamp + '.dump')
    with tempfile.NamedTemporaryFile(dir=str(BACKUPS), delete=False) as f:
        pending = Path(f.name)
        try:
            subprocess.run(['chroot', '--userspec=citruspg:citruspg', str(GUEST),
                            '/usr/bin/pg_dump', '-Fc', '-h', '/var/lib/postgresql/citrus-socket',
                            'citrus_production'], stdout=f, check=True)
            if f.tell() < 5:
                raise RuntimeError('Empty database dump')
        except BaseException:
            pending.unlink()
            raise
    os.replace(str(pending), str(name))
    print('Backed up citrus_production: ' + name.name, flush=True)


def restart_and_check():
    subprocess.run(['systemctl', 'restart', 'citrus-inference', 'citrus-app'], check=True)
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen('http://127.0.0.1:18081/api/v1/health/ready', timeout=3) as r:
                if r.status != 200:
                    raise ValueError('API not ready')
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(3)
                probe.connect(SOCKET)
                probe.sendall(b'{"op":"health"}\n')
                with probe.makefile('rb') as f:
                    health = json.loads(f.readline(16384))
                if all(health.get(k) for k in ('ok', 'ready', 'classifier', 'detector')):
                    return
        except (OSError, ValueError):
            pass
        time.sleep(1)
    raise RuntimeError('API or inference service did not become ready')


def publish(archive, tag):
    previous_link = os.readlink(str(ACTIVE))
    if not re.fullmatch(r'/opt/citrus-app/releases/[A-Za-z0-9_-]+', previous_link):
        raise ValueError('Unexpected current release target')
    previous = GUEST / previous_link.lstrip('/')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    release = Path(tempfile.mkdtemp(prefix=tag + '-' + stamp + '-', dir=str(RELEASES)))
    release.chmod(0o755)
    with os.fdopen(os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        attr = os.fstat(f.fileno())
        if not stat.S_ISREG(attr.st_mode) or attr.st_uid != pwd.getpwnam('deploy').pw_uid:
            raise ValueError('Release upload has unexpected owner or type')
        unpack(f, release)
    (release / '.api-env').symlink_to(prepare_environment(release, previous))
    backup_database(tag, stamp)
    switch(guest_path(release))
    try:
        restart_and_check()
    except BaseException:
        switch(previous_link)
        print("Release failed; restored " + previous.name, flush=True)
        restart_and_check()
        raise
    print('Published {} to {}. API, gateway and both models ready.'.format(tag, release.name), flush=True)
    # Retain the current and previous managed releases even if the system clock changes.
    active_set = {release, previous}
    owned = sorted((p for p in RELEASES.iterdir() if re.fullmatch(r'[a-f0-9]{12}-\d{8}T\d{6}Z-[a-z0-9_]+', p.name)
                    and p.is_dir() and not p.is_symlink()), key=lambda p:p.stat().st_mtime, reverse=True)
    for retired in owned[5:]:
        if retired not in active_set:
            shutil.rmtree(str(retired))
    for retired in sorted(BACKUPS.glob('pre-*-*.dump'), key=lambda p:p.stat().st_mtime, reverse=True)[10:]:
        if retired.is_file() and not retired.is_symlink():
            retired.unlink()


if __name__ == '__main__':
    if len(sys.argv) != 3 or not re.fullmatch(r'[a-f0-9]{12}', sys.argv[2]) or sys.argv[1] != '/tmp/release-' + sys.argv[2] + '.tar.gz':
        sys.exit('Expected /tmp/release-<12-hex-commit>.tar.gz and matching commit')
    with open('/opt/citrus-app/.publish.lock','a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        publish(sys.argv[1], sys.argv[2])
