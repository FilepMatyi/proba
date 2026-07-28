const express = require('express');
const prisma = require('../lib/prisma');

const router = express.Router();

// GET /api/sessions
// Fetches all vehicle sessions for the dashboard
router.get('/sessions', async (req, res) => {
  try {
    const sessions = await prisma.vehicleSession.findMany({
      include: {
        dealership: true
      },
      orderBy: {
        createdAt: 'desc'
      }
    });

    res.json(sessions);
  } catch (error) {
    console.error('Error fetching sessions:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// DELETE /api/sessions/:vehicleId
// Deletes a session (optional, but good for dashboard)
router.delete('/sessions/:vehicleId', async (req, res) => {
  try {
    const { vehicleId } = req.params;
    
    // Check if exists
    const session = await prisma.vehicleSession.findUnique({ where: { vehicleId } });
    if (!session) {
      return res.status(404).json({ error: 'Session not found' });
    }

    await prisma.vehicleSession.delete({ where: { vehicleId } });
    
    res.json({ success: true });
  } catch (error) {
    console.error('Error deleting session:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
