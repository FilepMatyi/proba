const { Queue } = require('bullmq');
const redis = require('../lib/redisConnection');

const photoQueue = new Queue('photo-processing', {
  connection: redis,
  defaultJobOptions: {
    attempts: 3,
    backoff: {
      type: 'exponential',
      delay: 1000,
    },
  },
});

module.exports = photoQueue;
