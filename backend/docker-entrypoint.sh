#!/bin/sh
set -e

# Sync a séma szerint (db push, nem migrate — MVP fázis, nincs migrations history)
npx prisma db push --skip-generate

exec "$@"
