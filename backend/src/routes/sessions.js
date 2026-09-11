const express = require('express');
const prisma = require('../lib/prisma');
const sessionService = require('../services/sessionService');
const { normalizeVehicleId } = require('../lib/vehicleId');
const { resetVehicleAssets } = require('../lib/minioClient');
const redis = require('../lib/redisConnection');

const router = express.Router();

function publicSession(session) {
  let qualityWarnings = [];
  try {
    const parsed = JSON.parse(session.qualityWarnings || '[]');
    if (Array.isArray(parsed)) qualityWarnings = parsed;
  } catch {
    // A hibás belső diagnosztika ne tegye használhatatlanná a publikus státuszt.
  }

  return {
    vehicleId: session.vehicleId,
    status: session.status,
    stage: session.stage,
    errorMessage: session.errorMessage,
    qualityScore: session.qualityScore,
    qualityWarnings,
    processedFrames: session.processedFrames,
    totalFrames: session.totalFrames,
    viewerUrl: session.viewerUrl,
    createdAt: session.createdAt,
    updatedAt: session.updatedAt,
  };
}

// GET /api/sessions
// Fetches all vehicle sessions for the dashboard
router.get('/sessions', async (req, res) => {
  try {
    const sessions = await prisma.vehicleSession.findMany({
      select: {
        vehicleId: true,
        status: true,
        stage: true,
        errorMessage: true,
        qualityScore: true,
        qualityWarnings: true,
        processedFrames: true,
        totalFrames: true,
        viewerUrl: true,
        createdAt: true,
        updatedAt: true,
      },
      orderBy: {
        updatedAt: 'desc'
      }
    });

    res.json(sessions.map(publicSession));
  } catch (error) {
    console.error('Error fetching sessions:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

router.get('/sessions/:vehicleId', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });

    const session = await sessionService.getSession(vehicleId);
    if (!session) return res.status(404).json({ error: 'Session not found' });
    return res.json(publicSession(session));
  } catch (error) {
    console.error('Error fetching session:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

// DELETE /api/sessions/:vehicleId
// Deletes a session (optional, but good for dashboard)
router.delete('/sessions/:vehicleId', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });
    
    // Check if exists
    const session = await prisma.vehicleSession.findUnique({ where: { vehicleId } });
    if (!session) {
      return res.status(404).json({ error: 'Session not found' });
    }

    if (session.status === 'processing') {
      return res.status(409).json({ error: 'Folyamatban lévő projekt nem törölhető.' });
    }

    await resetVehicleAssets(vehicleId);
    await redis.del(
      `vehicle:${vehicleId}:heights`,
      `vehicle:${vehicleId}:mask_quality`,
      `vehicle:${vehicleId}:bg_done`,
      `vehicle:${vehicleId}:studio_queued`,
      `vehicle:${vehicleId}:studio_done`,
    );
    await prisma.vehicleSession.delete({ where: { vehicleId } });
    
    res.json({ success: true });
  } catch (error) {
    console.error('Error deleting session:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
