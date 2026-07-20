const Redis = require('ioredis');
const config = require('../config');

const redis = new Redis(config.redis.url, { maxRetriesPerRequest: null });

redis.on('connect', () => {
  console.log('Connected to Redis');
});

redis.on('error', (error) => {
  console.error('Redis connection error:', error);
});

module.exports = redis;
