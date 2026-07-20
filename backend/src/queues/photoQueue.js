const redis = require('../lib/redisConnection');

const STREAM_NAME = 'photo-processing-stream';
const CONSUMER_GROUP = 'photo-processing-group';

/**
 * Add a job to the Redis Stream
 * @param {string} _name - Job name (unused in Redis Streams, kept for compatibility)
 * @param {Object} data - Job data (vehicleId, photoIndex, objectKey)
 */
async function add(_name, data) {
  await redis.xadd(STREAM_NAME, '*', 'vehicleId', data.vehicleId, 'photoIndex', data.photoIndex.toString(), 'objectKey', data.objectKey);
}

/**
 * Initialize the consumer group (call this on startup)
 */
async function initializeConsumerGroup() {
  try {
    await redis.xgroup('CREATE', STREAM_NAME, CONSUMER_GROUP, '0', 'MKSTREAM');
    console.log('Created Redis Streams consumer group');
  } catch (error) {
    if (error.message.includes('BUSYGROUP')) {
      console.log('Consumer group already exists');
    } else {
      console.error('Error creating consumer group:', error);
    }
  }
}

module.exports = {
  add,
  initializeConsumerGroup,
  STREAM_NAME,
  CONSUMER_GROUP
};
