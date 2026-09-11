FROM node:18-alpine

WORKDIR /app

# Install OpenSSL and other dependencies required by Prisma and FFmpeg
RUN apk add --no-cache openssl ffmpeg

COPY package*.json ./
RUN npm ci

COPY . .

# Generate Prisma client
RUN npx prisma generate

# Copy and setup entrypoint script
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["npm", "start"]
