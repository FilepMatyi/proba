const express = require('express');
const sessionService = require('../services/sessionService');

const router = express.Router();

/**
 * Internal endpoint for AI workers to notify when a frame is processed
 * This is called from the Python worker after each photo is processed
 */
router.patch('/vehicles/:vehicleId/frame-processed', async (req, res) => {
  try {
    const { vehicleId } = req.params;
    const { photoIndex } = req.body;

    console.log(`Frame ${photoIndex} processed for vehicle ${vehicleId}`);

    const session = await sessionService.incrementProcessedFrames(vehicleId);

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

module.exports = router;
