#!/bin/sh
PUID=${PUID:-1000}
PGID=${PGID:-1000}

#chown our directory to our puid and pgid
chown -R ${PUID}:${PGID} /app

#run as our PUID/PGID
exec gosu ${PUID}:${PGID} python main.py
