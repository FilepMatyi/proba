const express = require('express');
const config = require('./config');
const { ensureBuckets } = require('./lib/minioClient');
const photoRoutes = require('./routes/photos');
const viewerRoutes = require('./routes/viewer');
const webhookRoutes = require('./routes/webhook');

const app = express();

app.use(express.json());
app.use(express.urlencoded({ extended: true }));

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') {
    return res.sendStatus(200);
  }
  next();
});

app.use('/api', photoRoutes);
app.use('/', viewerRoutes);
app.use('/api', webhookRoutes);

app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

async function start() {
  try {
    await ensureBuckets();
    app.listen(config.port, () => {
      console.log(`Server running on port ${config.port}`);
    });
  } catch (error) {
    console.error('Failed to start server:', error);
    process.exit(1);
  }
}

start();
