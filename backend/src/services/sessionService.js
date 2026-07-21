const prisma = require('../lib/prisma');
const axios = require('axios');

/**
 * Get or create a vehicle session for a dealership
 * For MVP, we'll use a default dealership
 */
async function getOrCreateSession(vehicleId) {
  // For MVP, use a default dealership
  let dealership = await prisma.dealership.findFirst();
  
  if (!dealership) {
    dealership = await prisma.dealership.create({
      data: {
        name: 'Default Dealership',
        webhookUrl: process.env.WEBHOOK_URL || 'http://localhost:3001/webhook'
      }
    });
  }

  let session = await prisma.vehicleSession.findUnique({
    where: { vehicleId }
  });

  if (!session) {
    session = await prisma.vehicleSession.create({
      data: {
        vehicleId,
        dealershipId: dealership.id,
        totalFrames: 24,
        status: 'in_progress'
      }
    });
  }

  return session;
}

/**
 * Increment processed frames count and check for completion
 * Includes idempotency protection to prevent duplicate counting
 */
async function incrementProcessedFrames(vehicleId, photoIndex) {
  const session = await prisma.vehicleSession.findUnique({
    where: { vehicleId },
    include: { dealership: true }
  });

  if (!session) {
    throw new Error('Session not found');
  }

  // Early return if session is already completed
  if (session.status === 'completed') {
    console.log(`Session ${vehicleId} already completed, skipping frame ${photoIndex}`);
    return session;
  }

  // Parse existing processed indexes
  const processedIndexes = JSON.parse(session.processedPhotoIndexes || '[]');

  // Check if this photo index was already processed
  if (processedIndexes.includes(photoIndex)) {
    console.log(`Photo index ${photoIndex} already processed for vehicle ${vehicleId}, skipping`);
    return session;
  }

  // Add this photo index to the processed list
  processedIndexes.push(photoIndex);

  // Update session with new count and processed indexes
  const updatedSession = await prisma.vehicleSession.update({
    where: { vehicleId },
    data: {
      processedFrames: { increment: 1 },
      processedPhotoIndexes: JSON.stringify(processedIndexes)
    },
    include: { dealership: true }
  });

  // Check if all frames are processed
  if (updatedSession.processedFrames >= updatedSession.totalFrames) {
    await markSessionCompleted(vehicleId);
  }

  return updatedSession;
}

/**
 * Mark session as completed and send webhook
 */
async function markSessionCompleted(vehicleId) {
  const session = await prisma.vehicleSession.update({
    where: { vehicleId },
    data: {
      status: 'completed',
      viewerUrl: `/viewer/${vehicleId}`
    },
    include: { dealership: true }
  });

  // Send webhook to dealership
  await sendCompletionWebhook(session);

  return session;
}

/**
 * Send completion webhook to dealership
 */
async function sendCompletionWebhook(session) {
  const viewerUrl = `${process.env.BASE_URL || 'http://localhost:3000'}${session.viewerUrl}`;
  const iframeCode = `<iframe src="${viewerUrl}" width="100%" height="600" frameborder="0"></iframe>`;

  const payload = {
    vehicleId: session.vehicleId,
    status: 'completed',
    processedFrames: session.processedFrames,
    totalFrames: session.totalFrames,
    viewerUrl,
    iframeCode
  };

  try {
    await axios.post(session.dealership.webhookUrl, payload, {
      timeout: 10000
    });
    console.log(`Webhook sent for vehicle ${session.vehicleId} to ${session.dealership.webhookUrl}`);
  } catch (error) {
    console.error(`Failed to send webhook for vehicle ${session.vehicleId}:`, error.message);
    // Don't throw - webhook failure shouldn't break the flow
  }
}

module.exports = {
  getOrCreateSession,
  incrementProcessedFrames,
  markSessionCompleted,
  sendCompletionWebhook
};
