require('dotenv').config();

module.exports = {
  port: process.env.PORT || 3000,
  minio: {
    endPoint: process.env.MINIO_ENDPOINT || 'localhost',
    port: parseInt(process.env.MINIO_PORT) || 9000,
    useSSL: process.env.MINIO_USE_SSL === 'true',
    accessKey: process.env.MINIO_ACCESS_KEY || 'minioadmin',
    secretKey: process.env.MINIO_SECRET_KEY || 'minioadmin',
  },
  redis: {
    url: process.env.REDIS_URL || 'redis://localhost:6379',
  },
  webhook: {
    url: process.env.WEBHOOK_URL || 'http://localhost:3001/webhook',
  },
};
