const express = require('express');
const path = require('path');
const config = require('./config');
const { ensureBuckets } = require('./lib/minioClient');
const { initializeConsumerGroup } = require('./queues/photoQueue');
const photoRoutes = require('./routes/photos');
const viewerRoutes = require('./routes/viewer');
const webhookRoutes = require('./routes/webhook');
const internalRoutes = require('./routes/internal');

const app = express();

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, PATCH, DELETE, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

app.use('/api', photoRoutes);
app.use('/api', webhookRoutes);
app.use('/internal', internalRoutes);

// Serve static frontend files
const frontendDistPath = path.join(__dirname, '../frontend/dist');
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
app.get('*', (req, res) => {
  res.sendFile(path.join(frontendDistPath, 'index.html'));
});

async function start() {
  try {
    await ensureBuckets();
    await initializeConsumerGroup();
    app.listen(config.port, () => {
      console.log(`Server running on port ${config.port}`);
    });
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

start();
