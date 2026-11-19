#!/usr/bin/python3 -I
"""Adapt the old publisher's Ubuntu paths and service manager to this ECS."""
import contextlib
import fcntl
import hashlib
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
TRUSTED = Path('/opt/citrus-app/release-reference')
REPO = 'jinkun268-lang/app'
API = 'https://api.github.com/repos/' + REPO
PUBLISHER = 'deploy/publish.sh'
RENDERER = 'deploy/nginx/render.py'
REQUIREMENTS = 'server/requirements.txt'
PRIVILEGED = {PUBLISHER, RENDERER, REQUIREMENTS}


@contextlib.contextmanager
def upload(path):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(str(path), flags), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != int(os.environ.get('SUDO_UID', os.getuid())):
            raise ValueError('Expected a regular file owned by the publishing account')
        yield stream


def archive_name(value):
    name = PurePosixPath(value)
    if name.is_absolute() or '..' in name.parts:
        raise ValueError('Archive path leaves the release directory')
    return name.as_posix()


def add_stream(source, out, seen, fields, take, strip_prefix=False):
    """Copy release members without restoring creator IDs, devices or set-id modes."""
    with tarfile.open(fileobj=source, mode='r|gz') as archive:
        for item in archive:
            name = archive_name(item.name)
            if strip_prefix:
                name = '/'.join(PurePosixPath(name).parts[1:])
            if not name or name == '.' or not take(name):
                continue
            if name in seen:
                raise ValueError('Duplicate archive member')
            target = tarfile.TarInfo(name)
            target.mtime = item.mtime
            if item.isdir():
                target.type = tarfile.DIRTYPE
                target.mode = 0o755
                out.addfile(target)
            elif item.isreg():
                target.size = item.size
                target.mode = 0o755 if item.mode & 0o111 else 0o644
                with archive.extractfile(item) as data:
                    if name in PRIVILEGED:
                        fields[name] = data.read()
                        out.addfile(target, io.BytesIO(fields[name]))
                    else:
                        out.addfile(target, data)
            elif item.issym():
                target.type = tarfile.SYMTYPE
                target.linkname = item.linkname
                target.mode = 0o777
                out.addfile(target)
            elif item.islnk():
                target.type = tarfile.LNKTYPE
                dest = archive_name(item.linkname)
                target.linkname = '/'.join(PurePosixPath(dest).parts[1:]) if strip_prefix else dest
                out.addfile(target)
            else:
                raise ValueError('Unsupported special file in release')
            seen[name] = target


def check_links(members):
    links = {name: item.linkname for name, item in members.items() if item.issym()}
    for name, item in members.items():
        if any(not members[str(parent)].isdir() for parent in PurePosixPath(name).parents if str(parent) in members):
            raise ValueError('Archive writes below a non-directory')
        if item.issym() and (not item.linkname or PurePosixPath(item.linkname).is_absolute()):
            raise ValueError('Expected a relative release symlink')
        if item.islnk() and (item.linkname not in members or not members[item.linkname].isreg()):
            raise ValueError('Hardlink target must be a regular member of this release')
    for name, value in links.items():
        parts = list(PurePosixPath(name).parent.parts)
        pending = list(PurePosixPath(value).parts)
        expanded = 0
        while pending:
            step = pending.pop(0)
            if step == '/':
                raise ValueError('Absolute release symlink')
            if step == '..':
                if not parts:
                    raise ValueError('Release symlink escapes package')
                parts.pop()
            else:
                parts.append(step)
                where = '/'.join(parts)
                if where in links:
                    expanded += 1
                    if expanded > 40:
                        raise ValueError('Cyclic release symlink')
                    parts.pop()
                    pending = list(PurePosixPath(links[where]).parts) + pending


def github_json(endpoint):
    with urllib.request.urlopen(API + endpoint, timeout=30) as response:
        return json.load(response)


def upstream_release(tag, original, work, name):
    # Only changes to code executed with service-management privileges, or a
    # dependency install, need an independent source for those privileges.
    if not re.fullmatch(r'[a-f0-9]{7,40}', tag):
        raise ValueError('Use a repository commit for a privileged release change')
    sha = github_json('/commits/' + tag)['sha']
    if not sha.startswith(tag) or not re.fullmatch(r'[a-f0-9]{40}', sha):
        raise ValueError('Unexpected repository commit')
    if github_json('/compare/' + sha + '...main')['status'] not in ('identical', 'ahead'):
        if not github_json('/commits/' + sha + '/branches-where-head'):
            raise ValueError('Privileged code must come from the production repository')
    seen, fields = {}, {}
    url = 'https://codeload.github.com/' + REPO + '/tar.gz/' + sha
    with tarfile.open(str(work / name), 'w:gz') as out:
        with urllib.request.urlopen(url, timeout=60) as src:
            add_stream(src, out, seen, fields, lambda n: n != 'admin/dist' and not n.startswith('admin/dist/'), True)
        with original.open('rb') as src:
            add_stream(src, out, seen, fields, lambda n: n == 'admin/dist' or n.startswith('admin/dist/'))
    check_links(seen)
    return fields


def prepare(archive_path, tag, work):
    name = 'release-' + tag + '.tar.gz'
    original = work / 'incoming'
    fields, seen = {}, {}
    with upload(archive_path) as source, tarfile.open(str(original), 'w:gz') as out:
        add_stream(source, out, seen, fields, lambda _: True)
    check_links(seen)
    if 'server/app/main.py' not in seen or not seen['server/app/main.py'].isreg():
        raise ValueError('Missing server entry point')
    try:
        with upload('/tmp/publish.sh.new') as supplied:
            script = supplied.read()
    except FileNotFoundError:
        script = None
    same = all(fields.get(f) == (TRUSTED / f).read_bytes() for f in PRIVILEGED)
    same = same and (APP / 'publish.sh').read_bytes() == (TRUSTED / PUBLISHER).read_bytes()
    if same:
        lock = APP / '.requirements.sha256'
        same = lock.is_file() and lock.read_text().strip() == hashlib.sha256(fields[REQUIREMENTS]).hexdigest()
    if same:
        os.replace(str(original), str(work / name))
        print('Using the uploaded release directly.', flush=True)
    else:
        canonical = upstream_release(tag, original, work, name)
        if any(canonical.get(f) != fields.get(f) for f in PRIVILEGED):
            raise ValueError('Uploaded privileged components differ from the repository')
        print('Privileged release update confirmed against repository source.', flush=True)
    if script is not None:
        if script != fields.get(PUBLISHER):
            raise ValueError('Publisher and release disagree')
        (work / 'publish.sh.new').write_bytes(script)
    return name


def publish(path, tag):
    if not re.fullmatch(r'[A-Za-z0-9._-]+', tag) or tag in ('.', '..'):
        raise ValueError('Invalid release tag')
    STAGE.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(STAGE)) as temp:
        work = Path(temp)
        name = prepare(path, tag, work)
        subprocess.run([
            'systemd-run', '--quiet', '--wait', '--pipe',
            '-p', 'RootDirectory=' + str(ROOT), '-p', 'MountAPIVFS=yes',
            '-p', 'BindPaths=' + str(work) + ':/tmp', '-p', 'BindPaths=/var/backups/citrus-app',
            '-p', 'BindReadOnlyPaths=/run/systemd/system', '-p', 'BindPaths=/run/systemd/private',
            '/usr/bin/env', 'SYSTEMD_IGNORE_CHROOT=1', 'SYSTEMD_OFFLINE=0',
            'PATH=/opt/citrus-app/host-tools:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            '/bin/bash', '/opt/citrus-app/publish.sh', '/tmp/' + name, tag
        ], check=True)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('Usage: publish.sh release.tar.gz [tag]')
    path = Path(sys.argv[1])
    default = re.sub(r'\.tar\.gz$', '', path.name)
    tag = re.sub(r'[^A-Za-z0-9._-]', '_', sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else default)
    with open('/opt/citrus-app/.publish.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        publish(path, tag)
