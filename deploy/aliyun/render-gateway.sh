#!/usr/bin/env bash
# Runs in the Ubuntu service root, using the renderer shipped with current.
set -euo pipefail
GATE=/var/lib/citrus-gateway
CUR=/opt/citrus-app/current
DOMAIN=api.homemanager.com.cn
output=${CITRUS_RENDER_OUTPUT:-$GATE/staging}

/opt/citrus-app/venv/bin/python -B "$CUR/deploy/nginx/render.py" \
    --mode production --output "$output" --frontend "$CUR/admin/dist" \
    --upstream 127.0.0.1:18080 --domain "$DOMAIN" \
    --cert "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" \
    --key "/etc/letsencrypt/live/$DOMAIN/privkey.pem" --acme-root /var/lib/citrus-acme

/opt/citrus-app/venv/bin/python -B - "$output/nginx.conf" "$DOMAIN" <<'PY'
import importlib.util
from pathlib import Path
import sys
p = Path(sys.argv[1])
domain = sys.argv[2]
spec = importlib.util.spec_from_file_location("render", "/opt/citrus-app/current/deploy/nginx/render.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
cfg = p.read_text()
end = cfg.rindex('}')
cfg = cfg[:end] + module.application_server(Path('/opt/citrus-app/current/admin/dist'),
            '127.0.0.1:18080', '127.0.0.1:18081', 'localhost 127.0.0.1') + cfg[end:]
# Keep the old forwarder's client-IP semantics and follow certificate renewals.
if cfg.count('http {') != 1:
    raise SystemExit('Unexpected Nginx HTTP context')
cfg = cfg.replace('http {', 'http {\n    set_real_ip_from 8.217.13.178;', 1)
for directive, stem in [('ssl_certificate', 'fullchain'), ('ssl_certificate_key', 'privkey')]:
    live = Path('/etc/letsencrypt/live') / domain / (stem + '.pem')
    resolved = directive + ' "' + str(live.resolve()) + '";'
    if cfg.count(resolved) != 1:
        raise SystemExit('Unexpected certificate directive: ' + directive)
    cfg = cfg.replace(resolved, directive + ' "' + str(live) + '";')
p.write_text(cfg)
PY

/usr/sbin/nginx -t -p "$GATE/" -c "$output/nginx.conf"
if [ "${1:-}" = "--check-only" ]; then exit 0; fi
cp -a "$GATE/nginx.conf" "$GATE/nginx.conf.bak-$(date +%Y%m%d%H%M%S)"
cp "$output/nginx.conf" "$GATE/nginx.conf"
systemctl reload citrus-gateway
sleep 1
systemctl is-active citrus-gateway
