const express = require('express');
const sessionService = require('../services/sessionService');
const config = require('../config');
const { normalizeVehicleId, parsePhotoIndex } = require('../lib/vehicleId');

const router = express.Router();

router.use((req, res, next) => {
  if (req.get('x-internal-token') !== config.internalApiToken) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  next();
});

/**
 * Internal endpoint for AI workers to notify when a frame is processed
 * This is called from the Python worker after each photo is processed
 */
router.patch('/vehicles/:vehicleId/frame-processed', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    const photoIndex = parsePhotoIndex(req.body.photoIndex, config.processing.targetFrames);

    if (!vehicleId || photoIndex === null) {
      return res.status(400).json({ error: 'Invalid vehicle or frame index' });
    }

    console.log(`Frame ${photoIndex} processed for vehicle ${vehicleId}`);

    const session = await sessionService.incrementProcessedFrames(vehicleId, photoIndex);

    res.json({
      success: true,
      vehicleId,
      processedFrames: session.processedFrames,
      totalFrames: session.totalFrames,
      status: session.status
    });
  } catch (error) {
    console.error('Error processing frame notification:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

router.post('/vehicles/:vehicleId/failed', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });

    const session = await sessionService.markSessionFailed(
      vehicleId,
      req.body.error || 'A feldolgozó worker hibával leállt.',
    );
    return res.json({ success: true, vehicleId, status: session.status });
  } catch (error) {
    console.error('Error processing failure notification:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

router.post('/vehicles/:vehicleId/quality', async (req, res) => {
  try {
    const vehicleId = normalizeVehicleId(req.params.vehicleId);
    if (!vehicleId) return res.status(400).json({ error: 'Invalid vehicle ID' });

    const warnings = Array.isArray(req.body.warnings) ? req.body.warnings : [];
    const metrics = req.body.metrics && typeof req.body.metrics === 'object' ? req.body.metrics : {};
    if (warnings.length > 12 || JSON.stringify(metrics).length > 12000) {
      return res.status(413).json({ error: 'Quality report is too large' });
    }

    const session = await sessionService.updateQualityReport(vehicleId, {
      qualityScore: req.body.qualityScore,
      warnings,
      metrics,
    });
    return res.json({
      success: true,
      vehicleId,
      qualityScore: session.qualityScore,
    });
  } catch (error) {
    console.error('Error processing quality report:', error);
    return res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
