#!/bin/sh
# This PATH entry is private to the original publisher's Ubuntu context.
set -eu
if [ "$#" -ne 4 ] || [ "$1" != -u ] || [ "$2" != postgres ] || [ "$3" != pg_dump ] || [ "$4" != citrus_app ]; then
    echo 'Unexpected database backup invocation' >&2
    exit 2
fi
exec /usr/bin/setpriv --reuid=citruspg --regid=citruspg --init-groups /usr/bin/pg_dump -h /var/lib/postgresql/citrus-socket citrus_app
