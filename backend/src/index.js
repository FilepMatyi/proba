const express = require('express');
const path = require('path');
const fs = require('fs');
const config = require('./config');
const { ensureBuckets } = require('./lib/minioClient');
const { initializeConsumerGroup } = require('./queues/photoQueue');
const photoRoutes = require('./routes/photos');
const viewerRoutes = require('./routes/viewer');
const internalRoutes = require('./routes/internal');
const sessionsRoutes = require('./routes/sessions');
const studioPhotosRoutes = require('./routes/studioPhotos');
const guidedStudioRoutes = require('./routes/guidedStudio');

const app = express();

app.disable('x-powered-by');
app.use(express.json());

app.use((req, res, next) => {
  res.set('X-Content-Type-Options', 'nosniff');
  if (!req.path.startsWith('/viewer/')) res.set('X-Frame-Options', 'DENY');
  res.set('Permissions-Policy', 'camera=(self), fullscreen=(self)');
  next();
});

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', config.allowedOrigin);
  res.header('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, X-Internal-Token');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

app.use('/api', photoRoutes);
app.use('/api', sessionsRoutes);
app.use('/api', studioPhotosRoutes);
app.use('/api', guidedStudioRoutes);
app.use('/internal', internalRoutes);

// Serve static frontend files
const frontendCandidates = [
  process.env.FRONTEND_DIST_PATH,
  path.join(__dirname, '../frontend/dist'),
  path.join(__dirname, '../../frontend/dist'),
].filter(Boolean);
const frontendDistPath = frontendCandidates.find((candidate) => fs.existsSync(candidate)) || frontendCandidates[0];
app.use(express.static(frontendDistPath, { 
  fallthrough: true,
  index: 'index.html'
}));

// Health check endpoint (must be before the SPA wildcard fallback)
app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

// Viewer routes (must come after static files to avoid conflicts)
app.use('/', viewerRoutes);

// SPA fallback - serve index.html for client-side routes only.
// API, internal, and viewer routes are already handled above.
app.get('/{*splat}', (req, res) => {
  res.sendFile(path.join(frontendDistPath, 'index.html'));
});

async function start() {
  try {
    await ensureBuckets();
    await initializeConsumerGroup();
    const server = app.listen(config.port, () => {
      console.log(`Server running on port ${config.port}`);
    });

    const shutdown = async () => {
      server.close(async () => {
        const prisma = require('./lib/prisma');
        const redis = require('./lib/redisConnection');
        await Promise.allSettled([prisma.$disconnect(), redis.quit()]);
        process.exit(0);
      });
    };
    process.once('SIGTERM', shutdown);
    process.once('SIGINT', shutdown);
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

if (require.main === module) start();

module.exports = { app, start };
