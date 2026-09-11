const Minio = require('minio');
const config = require('../config');

const minioClient = new Minio.Client({
  endPoint: config.minio.endPoint,
  port: config.minio.port,
  useSSL: config.minio.useSSL,
  accessKey: config.minio.accessKey,
  secretKey: config.minio.secretKey,
});

const RAW_BUCKET = 'vehicle-photos-raw';
const PROCESSED_BUCKET = 'vehicle-photos-processed';

async function ensureBuckets() {
  try {
    const buckets = await minioClient.listBuckets();
    const bucketNames = buckets.map(b => b.name);

    if (!bucketNames.includes(RAW_BUCKET)) {
      await minioClient.makeBucket(RAW_BUCKET);
      console.log(`Created bucket: ${RAW_BUCKET}`);
    }

    if (!bucketNames.includes(PROCESSED_BUCKET)) {
      await minioClient.makeBucket(PROCESSED_BUCKET);
      console.log(`Created bucket: ${PROCESSED_BUCKET}`);
    }
  } catch (error) {
    console.error('Error ensuring buckets:', error);
    throw error;
  }
}

async function removeObjectsWithPrefix(bucket, prefix) {
  const names = [];
  const objects = minioClient.listObjects(bucket, prefix, true);
  for await (const object of objects) names.push(object.name);
  if (names.length > 0) await minioClient.removeObjects(bucket, names);
}

async function resetVehicleAssets(vehicleId) {
  await Promise.all([
    removeObjectsWithPrefix(RAW_BUCKET, `${vehicleId}/`),
    removeObjectsWithPrefix(PROCESSED_BUCKET, `${vehicleId}/`),
  ]);
}

module.exports = {
  minioClient,
  RAW_BUCKET,
  PROCESSED_BUCKET,
  ensureBuckets,
  resetVehicleAssets,
};
