const prisma = require('../lib/prisma'); // a megosztott singleton, NE hozz létre új PrismaClient-et itt
const axios = require('axios');

/**
 * Létrehozza vagy visszaadja a session-t egy vehicleId-hoz.
 * MVP-hez egy alapértelmezett Dealership-et használ, ha még nincs egy sem.
 */
async function getOrCreateSession(vehicleId) {
  let dealership = await prisma.dealership.findFirst();

  if (!dealership) {
    dealership = await prisma.dealership.create({
      data: {
        name: 'Default Dealership',
        webhookUrl: process.env.WEBHOOK_URL || null,
      },
    });
  }

  let session = await prisma.vehicleSession.findUnique({ where: { vehicleId } });

  if (!session) {
    session = await prisma.vehicleSession.create({
      data: {
        vehicleId,
        dealershipId: dealership.id,
        status: 'processing',
        processedFrames: 0,
        totalFrames: 24,
      },
    });
    console.log(`Munkamenet létrehozva: ${vehicleId}`);
  }

  return session;
}

/**
 * Növeli a feldolgozott képek számát — idempotens: egy photoIndex csak egyszer számít.
 */
async function incrementProcessedFrames(vehicleId, photoIndex) {
  const session = await prisma.vehicleSession.findUnique({
    where: { vehicleId },
    include: { dealership: true },
  });

  if (!session) {
    throw new Error(`Session not found for vehicleId: ${vehicleId}`);
  }

  if (session.status === 'completed') {
    console.log(`Munkamenet [${vehicleId}] már kész, ${photoIndex}. képkocka kihagyva.`);
    return session;
  }

  const processedIndexes = JSON.parse(session.processedPhotoIndexes || '[]');
  if (processedIndexes.includes(photoIndex)) {
    console.log(`A(z) ${photoIndex}. képkocka már fel volt dolgozva ehhez: ${vehicleId}, kihagyva.`);
    return session;
  }
  processedIndexes.push(photoIndex);

  const updatedSession = await prisma.vehicleSession.update({
    where: { vehicleId },
    data: {
      processedFrames: { increment: 1 },
      processedPhotoIndexes: JSON.stringify(processedIndexes),
    },
    include: { dealership: true },
  });

  console.log(`Munkamenet [${vehicleId}]: ${updatedSession.processedFrames}/${updatedSession.totalFrames} kép kész.`);

  if (updatedSession.processedFrames >= updatedSession.totalFrames) {
    await markSessionCompleted(vehicleId);
  }

  return updatedSession;
}

/**
 * Lezárja a munkamenetet, elmenti a viewer URL-t, és kilövi a webhookot.
 */
async function markSessionCompleted(vehicleId) {
  const session = await prisma.vehicleSession.update({
    where: { vehicleId },
    data: {
      status: 'completed',
      viewerUrl: `/viewer/${vehicleId}`,
    },
    include: { dealership: true },
  });

  await triggerWebhook(session);

  return session;
}

/**
 * Kilövi a completion webhookot a dealership-hez, ha van beállítva webhookUrl.
 */
async function triggerWebhook(session) {
  const webhookUrl = session.dealership?.webhookUrl;
  if (!webhookUrl) {
    console.log(`Nincs beállítva webhookUrl a(z) ${session.vehicleId} dealership-jéhez, kihagyva.`);
    return;
  }

  const viewerUrl = `${process.env.BASE_URL || 'http://localhost:3000'}${session.viewerUrl}`;

  const payload = {
    event: 'vehicle_completed',
    vehicle_id: session.vehicleId,
    viewer_url: viewerUrl,
    iframe_code: `<iframe src="${viewerUrl}" width="100%" height="600" frameborder="0"></iframe>`,
    timestamp: new Date().toISOString(),
  };

  try {
    await axios.post(webhookUrl, payload, { timeout: 10000 });
    console.log(`Webhook sikeresen kilőve ide: ${webhookUrl}`);
  } catch (error) {
    console.error(`Hiba a webhook küldésekor: ${error.message}`);
  }
}

module.exports = {
  getOrCreateSession,
  incrementProcessedFrames,
  markSessionCompleted,
  triggerWebhook,
};
