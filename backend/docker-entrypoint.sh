#!/bin/sh
set -e

# A bind mountolt forrás és a tartós node_modules volume eltérő buildből is
# származhat. Induláskor mindig igazítsuk a Prisma klienst az aktuális sémához.
npx prisma generate

# Sync a séma szerint (db push, nem migrate — MVP fázis, nincs migrations history)
npx prisma db push --skip-generate

exec "$@"
