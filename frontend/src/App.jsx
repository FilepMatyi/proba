import { useState } from 'react';
import CameraView from './components/CameraView';
import Waterpass from './components/Waterpass';
import ProgressBar from './components/ProgressBar';
import UploadQueue from './api/uploader';

const TOTAL_PHOTOS = 24;

function App() {
  const [vehicleId, setVehicleId] = useState('');
  const [isCapturing, setIsCapturing] = useState(false);
  const [isLevel, setIsLevel] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [uploadQueue] = useState(() => new UploadQueue((photoIndex) => {
    setUploadedCount(prev => Math.max(prev, photoIndex));
  }));

  const handleStart = () => {
    if (vehicleId.trim()) {
      setIsCapturing(true);
      setCurrentIndex(0);
      setUploadedCount(0);
    }
  };

  const handleCapture = (blob) => {
    if (currentIndex < TOTAL_PHOTOS) {
      uploadQueue.add(vehicleId, currentIndex + 1, blob);
      setCurrentIndex(prev => prev + 1);
    }
  };

  const handleComplete = () => {
    // All photos captured, show completion message
    alert(`All ${TOTAL_PHOTOS} photos captured! Processing in progress.`);
  };

  if (isCapturing) {
    if (currentIndex >= TOTAL_PHOTOS) {
      return (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100dvh',
            width: '100vw',
            overflow: 'hidden',
            backgroundColor: '#000',
            color: '#fff'
          }}
        >
          <h2>Processing Photos</h2>
          <ProgressBar uploadedCount={uploadedCount} totalPhotos={TOTAL_PHOTOS} />
          <p style={{ marginTop: '20px' }}>
            {uploadedCount < TOTAL_PHOTOS
              ? 'Uploading and processing your photos...'
              : 'All photos uploaded! AI processing in progress.'}
          </p>
        </div>
      );
    }

    return (
      <div style={{ height: '100dvh', width: '100vw', overflow: 'hidden' }}>
        <Waterpass onLevelChange={setIsLevel} />
        <CameraView
          isLevel={isLevel}
          onCapture={handleCapture}
          currentIndex={currentIndex}
          totalPhotos={TOTAL_PHOTOS}
        />
        <ProgressBar uploadedCount={uploadedCount} totalPhotos={TOTAL_PHOTOS} />
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100dvh',
        width: '100vw',
        overflow: 'hidden',
        backgroundColor: '#000',
        color: '#fff',
        padding: '20px'
      }}
    >
      <h1 style={{ marginBottom: '40px' }}>VehicleShoot 360</h1>
      <input
        type="text"
        value={vehicleId}
        onChange={(e) => setVehicleId(e.target.value)}
        placeholder="Enter Vehicle ID (e.g., Lancer-16)"
        style={{
          padding: '15px 20px',
          fontSize: '18px',
          borderRadius: '10px',
          border: '2px solid #333',
          backgroundColor: '#222',
          color: '#fff',
          marginBottom: '20px',
          width: '100%',
          maxWidth: '300px',
          textAlign: 'center'
        }}
      />
      <button
        onClick={handleStart}
        disabled={!vehicleId.trim()}
        style={{
          padding: '15px 40px',
          fontSize: '18px',
          backgroundColor: vehicleId.trim() ? '#4CAF50' : '#333',
          color: '#fff',
          border: 'none',
          borderRadius: '10px',
          cursor: vehicleId.trim() ? 'pointer' : 'not-allowed',
          transition: 'background-color 0.2s'
        }}
      >
        Start Photography
      </button>
    </div>
  );
}

export default App;
