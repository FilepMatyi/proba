const express = require('express');

const router = express.Router();

router.post('/webhook', async (req, res) => {
  try {
    const { vehicleId, status, processedImages, viewerUrl, iframeCode } = req.body;

    console.log('Webhook received:', {
      vehicleId,
      status,
      imageCount: processedImages?.length,
      viewerUrl
    });

    // In production, this would:
    // 1. Update the vehicle record in your database
    // 2. Send notification to the dealer
    // 3. Trigger any additional workflows
    // 4. Store the iframe code for easy embedding

    // For now, just acknowledge receipt
    res.status(200).json({
      received: true,
      vehicleId,
      status
    });
  } catch (error) {
    console.error('Webhook processing error:', error);
    res.status(500).json({ error: 'Webhook processing failed' });
  }
});

module.exports = router;
