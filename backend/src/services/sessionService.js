const axios = require('axios');
const prisma = require('../lib/prisma');
const config = require('../config');

const CACHE_TTL = 30 * 1000;
const dealershipCache = { data: null, timestamp: 0 };
const sessionCache = new Map();

async function getDefaultDealership() {
  const now = Date.now();
  if (dealershipCache.data && now - dealershipCache.timestamp < CACHE_TTL) {
    return dealershipCache.data;
  }

  let dealership = await prisma.dealership.findFirst();
  if (!dealership) {
    dealership = await prisma.dealership.create({
      data: {
        name: 'Default Dealership',
        webhookUrl: config.webhook.url,
      },
    });
  }

  dealershipCache.data = dealership;
  dealershipCache.timestamp = now;
  return dealership;
}

async function getSession(vehicleId) {
  const cached = sessionCache.get(vehicleId);
  const now = Date.now();
  if (cached && now - cached.timestamp < CACHE_TTL) return cached.data;

  const session = await prisma.vehicleSession.findUnique({
    where: { vehicleId },
  });
  if (session) sessionCache.set(vehicleId, { data: session, timestamp: now });
  return session;
}

async function startSession(vehicleId) {
  const dealership = await getDefaultDealership();
  const session = await prisma.vehicleSession.upsert({
    where: { vehicleId },
    create: {
      vehicleId,
      dealershipId: dealership.id,
      status: 'processing',
      stage: 'uploading',
      totalFrames: config.processing.targetFrames,
    },
    update: {
      status: 'processing',
      stage: 'uploading',
      errorMessage: null,
      qualityScore: null,
      qualityWarnings: '[]',
      qualityMetrics: '{}',
      processedFrames: 0,
      processedPhotoIndexes: '[]',
      totalFrames: config.processing.targetFrames,
      viewerUrl: null,
      createdAt: new Date(),
    },
    include: { dealership: true },
  });

  sessionCache.delete(vehicleId);
  return session;
}

async function updateStage(vehicleId, stage) {
  const session = await prisma.vehicleSession.update({
    where: { vehicleId },
    data: { stage, status: 'processing', errorMessage: null },
  });
  sessionCache.delete(vehicleId);
  return session;
}

async function markSessionFailed(vehicleId, error) {
  const message = error instanceof Error ? error.message : String(error);
  const session = await prisma.vehicleSession.update({
    where: { vehicleId },
    data: {
      status: 'failed',
      stage: 'failed',
      errorMessage: message.slice(0, 500),
    },
  });
  sessionCache.delete(vehicleId);
  return session;
}

function parseJson(value, fallback) {
  try {
    return JSON.parse(value || '');
  } catch {
    return fallback;
  }
}

async function updateQualityReport(vehicleId, report) {
  const existing = await prisma.vehicleSession.findUnique({ where: { vehicleId } });
  if (!existing) throw new Error(`Session not found for vehicleId: ${vehicleId}`);

  const previousWarnings = parseJson(existing.qualityWarnings, []);
  const incomingWarnings = Array.isArray(report.warnings) ? report.warnings : [];
  const qualityWarnings = [...new Set([...previousWarnings, ...incomingWarnings]
    .filter((warning) => typeof warning === 'string' && warning.trim())
    .map((warning) => warning.trim().slice(0, 240)))]
    .slice(0, 12);

  const previousMetrics = parseJson(existing.qualityMetrics, {});
  const incomingMetrics = report.metrics && typeof report.metrics === 'object' && !Array.isArray(report.metrics)
    ? report.metrics
    : {};
  const qualityMetrics = { ...previousMetrics, ...incomingMetrics };
  const hasScore = report.qualityScore !== null && report.qualityScore !== undefined;
  const parsedScore = hasScore ? Number(report.qualityScore) : Number.NaN;
  const qualityScore = Number.isFinite(parsedScore)
    ? Math.max(0, Math.min(100, Math.round(parsedScore)))
    : existing.qualityScore;

  const session = await prisma.vehicleSession.update({
    where: { vehicleId },
    data: {
      qualityScore,
      qualityWarnings: JSON.stringify(qualityWarnings),
      qualityMetrics: JSON.stringify(qualityMetrics).slice(0, 12000),
    },
  });
  sessionCache.delete(vehicleId);
  return session;
}

async function incrementProcessedFrames(vehicleId, photoIndex) {
  let completedNow = false;

  const updatedSession = await prisma.$transaction(async (tx) => {
    const session = await tx.vehicleSession.findUnique({
      where: { vehicleId },
      include: { dealership: true },
    });

    if (!session) throw new Error(`Session not found for vehicleId: ${vehicleId}`);
    if (session.status === 'completed') return session;

    const indexes = JSON.parse(session.processedPhotoIndexes || '[]');
    if (indexes.includes(photoIndex)) return session;

    indexes.push(photoIndex);
    indexes.sort((a, b) => a - b);
    const processedFrames = indexes.length;
    completedNow = processedFrames >= session.totalFrames;

    return tx.vehicleSession.update({
      where: { vehicleId },
      data: {
        processedFrames,
        processedPhotoIndexes: JSON.stringify(indexes),
        stage: completedNow ? 'ready' : 'composing',
        status: completedNow ? 'completed' : 'processing',
        viewerUrl: completedNow ? `/viewer/${vehicleId}` : null,
      },
      include: { dealership: true },
    });
  });

  sessionCache.delete(vehicleId);
  if (completedNow) await triggerWebhook(updatedSession);
  return updatedSession;
}

async function triggerWebhook(session) {
  const webhookUrl = session.dealership?.webhookUrl;
  if (!webhookUrl) return;

  const viewerUrl = `${config.baseUrl}${session.viewerUrl}`;
  const payload = {
    event: 'vehicle_completed',
    vehicle_id: session.vehicleId,
    processed_frames: session.processedFrames,
    quality_score: session.qualityScore,
    quality_warnings: parseJson(session.qualityWarnings, []),
    viewer_url: viewerUrl,
    iframe_code: `<iframe src="${viewerUrl}" width="100%" height="600" loading="lazy" allowfullscreen></iframe>`,
    timestamp: new Date().toISOString(),
  };

  try {
    await axios.post(webhookUrl, payload, { timeout: 10000 });
  } catch (error) {
    console.error(`Webhook delivery failed for ${session.vehicleId}: ${error.message}`);
  }
}

module.exports = {
  getSession,
  startSession,
  updateStage,
  updateQualityReport,
  markSessionFailed,
  incrementProcessedFrames,
  triggerWebhook,
};
