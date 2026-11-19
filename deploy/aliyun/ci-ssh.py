#!/usr/bin/python3 -I
"""Accept the production Actions commands. SCP writes APKs to the public directory."""
import os
import re
import subprocess

cmd = os.environ.get('SSH_ORIGINAL_COMMAND', '').strip()
if cmd in ('internal-sftp', '/usr/libexec/openssh/sftp-server', '/usr/lib/openssh/sftp-server'):
    os.execl('/usr/libexec/openssh/sftp-server', 'sftp-server')
elif cmd == 'ls -lh /opt/citrus-app/downloads/ | tail -3':
    output = subprocess.check_output(['ls', '-lh', '/opt/citrus-app/downloads/']).splitlines()
    for line in output[-3:]:
        print(line.decode())
else:
    match = re.fullmatch(r'sudo /opt/citrus-app/publish\.sh (/tmp/release-([a-f0-9]{12})\.tar\.gz) \2\s*&& rm -f \1 /tmp/publish\.sh\.new', cmd)
    if not match:
        raise SystemExit('Unsupported CI operation')
    package, tag = match.groups()
    subprocess.run(['sudo', '-n', '/opt/citrus-app/publish.sh', package, tag], check=True)
    for path in (package, package + '.sig', '/tmp/publish.sh.new'):
        if os.path.lexists(path):
            os.unlink(path)
