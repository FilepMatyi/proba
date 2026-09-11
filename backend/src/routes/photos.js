const express = require('express');
const multer = require('multer');
const { randomUUID } = require('crypto');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const config = require('../config');
const { minioClient, RAW_BUCKET, resetVehicleAssets } = require('../lib/minioClient');
const { normalizeVehicleId } = require('../lib/vehicleId');
const photoQueue = require('../queues/photoQueue');
const redis = require('../lib/redisConnection');
const sessionService = require('../services/sessionService');

const router = express.Router();
const VIDEO_TYPES = new Map([
  ['video/webm', '.webm'],
  ['video/mp4', '.mp4'],
  ['video/quicktime', '.mov'],
]);

const uploadVideo = multer({
  storage: multer.diskStorage({
    destination: (req, file, callback) => callback(null, os.tmpdir()),
    filename: (req, file, callback) => {
      const mimeType = file.mimetype.split(';')[0].toLowerCase();
      callback(null, `${randomUUID()}${VIDEO_TYPES.get(mimeType) || '.video'}`);
    },
  }),
  fileFilter: (req, file, callback) => {
    const mimeType = file.mimetype.split(';')[0].toLowerCase();
    callback(VIDEO_TYPES.has(mimeType) ? null : new Error('Unsupported video format'), VIDEO_TYPES.has(mimeType));
  },
  limits: {
    fileSize: 250 * 1024 * 1024,
    fieldSize: 5 * 1024 * 1024,
    fields: 2,
    files: 1,
  },
});

router.post('/vehicles/:vehicleId/video', (req, res) => {
  uploadVideo.single('video')(req, res, async (uploadError) => {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);

    if (uploadError) {
      return res.status(400).json({ error: uploadError.message });
    }
    if (!vehicleId) {
      cleanupFiles([req.file?.path]);
      return res.status(400).json({ error: 'Invalid vehicle ID' });
    }
    if (!req.file) return res.status(400).json({ error: 'Video is required' });

    let sensorData;
    try {
      sensorData = parseSensorData(req.body.sensorData);
    } catch {
      cleanupFiles([req.file.path]);
      return res.status(400).json({ error: 'Invalid sensor data' });
    }

    try {
      const existingSession = await sessionService.getSession(vehicleId);
      if (existingSession?.status === 'processing') {
        cleanupFiles([req.file.path]);
        return res.status(409).json({ error: 'Ehhez az autóhoz már fut egy feldolgozás.' });
      }

      await Promise.all([
        resetVehicleAssets(vehicleId),
        redis.del(
          `vehicle:${vehicleId}:heights`,
          `vehicle:${vehicleId}:mask_quality`,
          `vehicle:${vehicleId}:bg_done`,
          `vehicle:${vehicleId}:studio_queued`,
          `vehicle:${vehicleId}:studio_done`,
        ),
      ]);
      await sessionService.startSession(vehicleId);

      res.status(202).json({
        status: 'accepted',
        vehicleId,
        targetFrames: config.processing.targetFrames,
        message: 'A feltöltés sikerült, megkezdődött a képkockák feldolgozása.',
      });

      processVideo({ vehicleId, videoPath: req.file.path, sensorData }).catch(async (error) => {
        console.error(`Video processing failed for ${vehicleId}:`, error);
        await sessionService.markSessionFailed(
          vehicleId,
          'A videó képkockáinak feldolgozása sikertelen.',
        ).catch((stageError) => {
          console.error(`Could not mark ${vehicleId} as failed:`, stageError);
        });
      });
    } catch (error) {
      cleanupFiles([req.file.path]);
      console.error('Video upload initialization failed:', error);
      return res.status(500).json({ error: 'A feldolgozás nem indítható el.' });
    }
  });
});

function parseSensorData(rawValue) {
  if (!rawValue) return null;

  const parsed = JSON.parse(rawValue);
  if (!Array.isArray(parsed) || parsed.length > 20000) {
    throw new Error('Invalid sensor data');
  }

  return parsed
    .filter((sample) => sample && ['time', 'alpha', 'beta', 'gamma'].every((key) => Number.isFinite(Number(sample[key]))))
    .map((sample) => ({
      time: Number(sample.time),
      alpha: Number(sample.alpha),
      beta: Number(sample.beta),
      gamma: Number(sample.gamma),
    }));
}

async function processVideo({ vehicleId, videoPath, sensorData }) {
  const outputDirectory = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'vs360-'));
  let remuxedPath;

  try {
    await sessionService.updateStage(vehicleId, 'extracting');
    remuxedPath = await remuxVideo(videoPath);
    const videoInfo = await probeVideo(remuxedPath);
    if (videoInfo.duration < 18) {
      throw new Error('A teljes körhöz legalább 18 másodperces videó szükséges.');
    }
    const captureWarnings = [];
    if (videoInfo.duration < 26) {
      captureWarnings.push('A felvétel rövidebb az ajánlottnál; lassabb körbejárás javíthatja a nézetek részletességét.');
    }
    if (videoInfo.width * videoInfo.height < 900000) {
      captureWarnings.push('A videó felbontása alacsonyabb az ajánlott 1080p minőségnél.');
    }
    await sessionService.updateQualityReport(vehicleId, {
      warnings: captureWarnings,
      metrics: { capture: videoInfo },
    });
    await extractFrames(
      remuxedPath,
      outputDirectory,
      config.processing.candidateFrames,
      videoInfo.duration,
    );

    const files = (await fs.promises.readdir(outputDirectory))
      .filter((name) => /^frame-\d{3}\.jpg$/.test(name))
      .sort()
      .slice(0, config.processing.candidateFrames);

    if (files.length < config.processing.targetFrames) {
      throw new Error(`Csak ${files.length} használható képkocka készült.`);
    }

    if (sensorData?.length) {
      const sensorBuffer = Buffer.from(JSON.stringify(sensorData));
      await minioClient.putObject(
        RAW_BUCKET,
        `${vehicleId}/candidates/sensorData.json`,
        sensorBuffer,
        sensorBuffer.length,
        { 'Content-Type': 'application/json' },
      );
    }

    await uploadCandidateFrames(vehicleId, outputDirectory, files);
    await sessionService.updateStage(vehicleId, 'selecting');
    await photoQueue.add('select-frames', {
      vehicleId,
      frameCount: files.length,
      hasSensorData: Boolean(sensorData?.length),
      targetFrames: config.processing.targetFrames,
    });
  } finally {
    cleanupFiles([videoPath, remuxedPath]);
    await fs.promises.rm(outputDirectory, { recursive: true, force: true }).catch(() => {});
  }
}

async function remuxVideo(inputPath) {
  const extension = path.extname(inputPath) || '.webm';
  const outputPath = `${inputPath}.fixed${extension}`;

  try {
    await runProcess('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-y', '-i', inputPath, '-map', '0:v:0', '-c:v', 'copy', '-an', outputPath]);
    return outputPath;
  } catch (error) {
    console.warn(`Video remux skipped: ${error.message}`);
    cleanupFiles([outputPath]);
    return inputPath;
  }
}

async function probeVideo(inputPath) {
  const probeOutput = await runProcess('ffprobe', [
    '-v', 'error', '-select_streams', 'v:0',
    '-show_entries', 'format=duration:stream=width,height', '-of', 'json', inputPath,
  ]);
  const probe = JSON.parse(probeOutput);
  const stream = probe.streams?.[0] || {};
  const info = {
    duration: Number.parseFloat(probe.format?.duration),
    width: Number.parseInt(stream.width, 10),
    height: Number.parseInt(stream.height, 10),
  };
  if (!Number.isFinite(info.duration) || info.duration <= 0) {
    throw new Error('A videó hossza nem állapítható meg.');
  }
  if (!Number.isInteger(info.width) || !Number.isInteger(info.height)) {
    throw new Error('A videó felbontása nem állapítható meg.');
  }
  return { ...info, duration: Math.round(info.duration * 100) / 100 };
}

async function extractFrames(inputPath, outputDirectory, frameCount, duration) {
  const edgeTrim = Math.min(0.35, duration * 0.015);
  const usableDuration = duration - edgeTrim * 2;

  await runProcess('ffmpeg', [
    '-hide_banner', '-loglevel', 'error', '-y', '-i', inputPath,
    '-ss', String(edgeTrim), '-t', String(usableDuration),
    '-vf', `fps=${frameCount}/${usableDuration}`, '-frames:v', String(frameCount), '-q:v', '2',
    path.join(outputDirectory, 'frame-%03d.jpg'),
  ]);
}

function runProcess(command, args) {
  return new Promise((resolve, reject) => {
    const process = spawn(command, args, { windowsHide: true });
    let stdout = '';
    let stderr = '';
    process.stdout.on('data', (chunk) => { stdout += chunk.toString(); });
    process.stderr.on('data', (chunk) => { stderr = (stderr + chunk.toString()).slice(-4000); });
    process.on('error', reject);
    process.on('close', (code) => {
      if (code === 0) resolve(stdout);
      else reject(new Error(`${command} exited with code ${code}: ${stderr.trim()}`));
    });
  });
}

async function uploadCandidateFrames(vehicleId, outputDirectory, files) {
  const batchSize = 6;
  for (let offset = 0; offset < files.length; offset += batchSize) {
    const batch = files.slice(offset, offset + batchSize);
    await Promise.all(batch.map(async (fileName, index) => {
      const absoluteIndex = offset + index + 1;
      const filePath = path.join(outputDirectory, fileName);
      await minioClient.fPutObject(
        RAW_BUCKET,
        `${vehicleId}/candidates/frame-${String(absoluteIndex).padStart(3, '0')}.jpg`,
        filePath,
        { 'Content-Type': 'image/jpeg' },
      );
    }));
  }
}

function cleanupFiles(files) {
  for (const file of files.filter(Boolean)) {
    try {
      fs.unlinkSync(file);
    } catch (error) {
      if (error.code !== 'ENOENT') console.warn(`Could not remove temporary file ${file}: ${error.message}`);
    }
  }
}

module.exports = router;
