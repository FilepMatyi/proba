# VehicleShoot 360

B2B SaaS platform for car dealers to create premium, 360° studio-quality 3D vehicle presentations using only a phone browser - no native app required.

## Features

- **Progressive Web App (PWA)**: Install on phone home screen, native-like experience
- **Camera Integration**: Capture 24 photos with live camera feed
- **Gyroscope Level**: Digital waterpass ensures level photos (shutter disabled when not level)
- **Real-time Upload**: Photos upload sequentially in background as they're taken
- **AI Processing**: Automatic background removal and studio composition with realistic shadows
- **Interactive 360° Viewer**: Embeddable iframe for dealer websites
- **Scalable Architecture**: Stateless AI workers, horizontal scaling ready

## Architecture

```
[Phone Browser - React PWA]
        | (sequential upload with retry)
        v
[Node.js/Express API] → MinIO (raw photos) → Prisma (SQLite)
        |
        v
[Redis Streams] (consumer groups with XACK)
        |
        v
[Python AI Workers] → rembg (background removal) → Pillow (studio composition)
        |
        v
[MinIO (processed photos)]
        |
        v
[Internal API] → Prisma update → Webhook → [360° Viewer]
```

**Architecture Decision: Redis Streams vs BullMQ**

We chose Redis Streams over BullMQ for the message queue because:
- Native Redis consumer group support with automatic message acknowledgment (XACK)
- Better cross-language compatibility (Node.js ↔ Python)
- Simpler implementation without external dependencies
- Built-in message persistence and delivery guarantees
- Easier to debug and monitor directly in Redis
- Sufficient for MVP requirements without BullMQ's advanced features

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React (Vite), PWA, getUserMedia, DeviceOrientationEvent |
| Backend API | Node.js, Express, Multer, Prisma ORM |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Object Storage | MinIO |
| Message Queue | Redis Streams (consumer groups) |
| AI Processing | Python, rembg (IS-Net), Pillow |
| Output | Webhook + embeddable iframe viewer |

## Project Structure

```
vehicleshoot-360/
├── frontend/                    # React PWA
│   ├── src/
│   │   ├── components/
│   │   │   ├── CameraView.jsx    # Camera stream, overlay, capture
│   │   │   ├── Waterpass.jsx     # Gyroscope level indicator
│   │   │   └── ProgressBar.jsx   # Upload progress
│   │   ├── api/
│   │   │   └── uploader.js       # Sequential upload queue with retry
│   │   ├── App.jsx               # Main app state
│   │   └── main.jsx
│   ├── public/
│   │   ├── manifest.json
│   │   └── icons/
│   ├── vite.config.js            # PWA configuration
│   └── package.json
├── backend/                      # Node.js API
│   ├── prisma/
│   │   ├── schema.prisma         # Database schema
│   │   └── dev.db                # SQLite database (generated)
│   ├── src/
│   │   ├── lib/
│   │   │   ├── minioClient.js    # MinIO connection
│   │   │   ├── redisConnection.js
│   │   │   └── prisma.js         # Prisma client
│   │   ├── queues/
│   │   │   └── photoQueue.js     # Redis Streams setup
│   │   ├── routes/
│   │   │   ├── photos.js         # Upload endpoint
│   │   │   ├── viewer.js         # 360° viewer
│   │   │   ├── webhook.js        # Webhook endpoint
│   │   │   └── internal.js      # Internal API for workers
│   │   ├── services/
│   │   │   └── sessionService.js # Session management & webhooks
│   │   ├── config.js
│   │   └── index.js
│   ├── Dockerfile
│   └── package.json
├── ai-worker/                    # Python AI processing
│   ├── processing/
│   │   ├── background_removal.py    # rembg integration
│   │   └── studio_compose.py        # Shadow generation
│   ├── worker.py                   # Redis Streams consumer
│   ├── config.py
│   ├── requirements.txt
│   └── Dockerfile
└── docker-compose.yml            # Local development setup
```

## Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for local development without Docker)
- Python 3.11+ (for local development without Docker)
- HTTPS tunnel (ngrok/Cloudflare Tunnel) for phone testing (camera requires secure context)

## Quick Start with Docker

1. **Clone and navigate to project**
   ```bash
   cd vehicleshoot-360
   ```

2. **Add PWA icons** (required for PWA to work)
   ```bash
   # Add icon-192.png and icon-512.png to frontend/public/icons/
   # See frontend/public/icons/README.md for details
   ```

3. **Start all services**
   ```bash
   docker-compose up --build
   ```

4. **Access the application**
   - Frontend: http://localhost:5173
   - Backend API: http://localhost:3000
   - MinIO Console: http://localhost:9001 (minioadmin/minioadmin)

## Local Development (without Docker)

### Backend Setup

```bash
cd backend
npm install
npx prisma generate
npx prisma migrate dev --name init
npm start
```

### AI Worker Setup

```bash
cd ai-worker
pip install -r requirements.txt
python worker.py
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

## Phone Testing (HTTPS Required)

Camera and gyroscope APIs require HTTPS. Use ngrok or Cloudflare Tunnel:

```bash
# Example with ngrok
ngrok http 5173
```

Update `frontend/.env`:
```
VITE_API_BASE_URL=https://your-ngrok-url.ngrok-free.app/api
```

## API Endpoints

### POST /api/vehicles/:vehicleId/photos

Upload a photo for processing.

**Request:**
- Content-Type: multipart/form-data
- Fields:
  - `photo`: JPEG image (max 15MB)
  - `photoIndex`: 1-24 (photo sequence number)

**Response (202 Accepted):**
```json
{
  "status": "accepted",
  "objectKey": "vehicleId/1-uuid.jpg",
  "uploadedCount": 1
}
```

### GET /viewer/:vehicleId

Interactive 360° viewer for processed photos.

**Response:** HTML page with embeddable viewer

### POST /api/webhook

Webhook endpoint for processing completion notifications (debug/test endpoint).

**Payload:**
```json
{
  "vehicleId": "Lancer-16",
  "status": "completed",
  "processedFrames": 24,
  "totalFrames": 24,
  "viewerUrl": "http://localhost:3000/viewer/Lancer-16",
  "iframeCode": "<iframe src=\"...) ...></iframe>"
}
```

### PATCH /internal/vehicles/:vehicleId/frame-processed

Internal endpoint called by AI workers to notify when a frame is processed.

**Request:**
```json
{
  "photoIndex": 5
}
```

**Response:**
```json
{
  "success": true,
  "vehicleId": "Lancer-16",
  "processedFrames": 5,
  "totalFrames": 24,
  "status": "in_progress"
}
```

## User Flow

1. Salesperson opens PWA on phone
2. Enters vehicle ID (e.g., "Lancer-16")
3. Camera view opens with silhouette overlay and level indicator
4. Walks around vehicle, capturing 24 photos (shutter only active when level)
5. Photos upload sequentially in background with retry logic
6. Each upload creates a session in Prisma DB and enqueues job to Redis Streams
7. AI workers consume jobs from Redis Streams, process photos, and notify backend via internal API
8. Backend updates processed frame count in Prisma DB
9. When all 24 frames complete, webhook is sent to dealership URL
10. Result: embeddable iframe with interactive 360° viewer

## Configuration

### Backend (.env)
```
PORT=3000
BASE_URL=http://localhost:3000
MINIO_ENDPOINT=minio
MINIO_PORT=9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
REDIS_URL=redis://redis:6379
WEBHOOK_URL=http://localhost:3001/webhook
```

### Frontend (.env)
```
VITE_API_BASE_URL=http://localhost:3000/api
```

### AI Worker (config.py)
```python
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'localhost')
MINIO_PORT = int(os.getenv('MINIO_PORT', '9000'))
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379')
BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:3000')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'http://localhost:3001/webhook')
```

## Production Considerations

- Use proper SSL certificates (Let's Encrypt)
- Configure production MinIO with proper storage
- Scale AI workers based on load
- Implement proper authentication
- Add rate limiting
- Set up monitoring and logging
- Configure proper webhook retry logic
- Use CDN for processed images
- Migrate SQLite to PostgreSQL for production
- Configure proper CORS for production domains

## Testing with Mitsubishi Lancer 1.6

First test case: Mitsubishi Lancer 1.6

1. Enter vehicle ID: `Lancer-16`
2. Capture 24 photos walking around the vehicle
3. Wait for AI processing completion
4. Access viewer at: `http://localhost:3000/viewer/Lancer-16`
5. Embed iframe on dealer website

## Troubleshooting

**Camera not working:**
- Ensure HTTPS (required for camera access)
- Check browser permissions
- Try different browser (Chrome recommended)

**Gyroscope not working:**
- iOS: Click "Enable Gyroscope" button (permission required)
- Android: Should work automatically
- Check device orientation permissions

**Upload failures:**
- Check backend logs
- Verify MinIO connection
- Check Redis connection
- Review queue status

**AI processing slow:**
- Scale up worker containers in docker-compose.yml
- Check system resources
- Monitor queue backlog

## License

Proprietary - VehicleShoot 360

## Support

For issues and questions, contact the development team.
