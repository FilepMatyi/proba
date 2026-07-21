#!/bin/sh
set -e

# Run Prisma migrations
npx prisma migrate deploy

# Execute the main command
exec "$@"
