require('dotenv').config();

function boundedInteger(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) ? Math.min(Math.max(parsed, minimum), maximum) : fallback;
}

const targetFrames = boundedInteger(process.env.TARGET_FRAMES, 36, 12, 72);
const candidateFrames = boundedInteger(process.env.CANDIDATE_FRAMES, 108, targetFrames, 360);

module.exports = {
  port: process.env.PORT || 3000,
  baseUrl: process.env.BASE_URL || 'http://localhost:3000',
  allowedOrigin: process.env.ALLOWED_ORIGIN || '*',
  internalApiToken: process.env.INTERNAL_API_TOKEN || 'development-only-change-me',
  processing: {
    candidateFrames,
    targetFrames,
  },
  minio: {
    endPoint: process.env.MINIO_ENDPOINT || 'localhost',
    port: boundedInteger(process.env.MINIO_PORT, 9000, 1, 65535),
    useSSL: process.env.MINIO_USE_SSL === 'true',
    accessKey: process.env.MINIO_ACCESS_KEY || 'minioadmin',
    secretKey: process.env.MINIO_SECRET_KEY || 'minioadmin',
  },
  minioPublic: {
    endPoint: process.env.MINIO_PUBLIC_ENDPOINT || 'localhost',
    port: boundedInteger(process.env.MINIO_PUBLIC_PORT, 9000, 1, 65535),
    useSSL: process.env.MINIO_PUBLIC_USE_SSL === 'true',
  },
  redis: {
    url: process.env.REDIS_URL || 'redis://localhost:6379',
  },
  webhook: {
    url: process.env.WEBHOOK_URL || null,
  },
};
