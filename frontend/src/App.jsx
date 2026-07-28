import { useState, useRef, useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import CameraView from './components/CameraView';
import Waterpass from './components/Waterpass';
import ProgressBar from './components/ProgressBar';
import UploadQueue from './api/uploader';
import Dashboard from './components/Dashboard';

const TOTAL_PHOTOS = 36;
const ANGLE_PER_PHOTO = 360 / TOTAL_PHOTOS;

function CaptureFlow() {
  const navigate = useNavigate();
  const [vehicleId, setVehicleId] = useState('');
  const [isCapturing, setIsCapturing] = useState(false);
  const [isLevel, setIsLevel] = useState(false);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [autoCaptureSignal, setAutoCaptureSignal] = useState(0);
  const [uploadQueue] = useState(() => new UploadQueue((photoIndex) => {
    setUploadedCount(prev => Math.max(prev, photoIndex));
  }));

  // Gyroscope tracking refs
  const lastHeadingRef = useRef(null);
  const accumulatedRotationRef = useRef(0);
  const currentIndexRef = useRef(0);
  const isLevelRef = useRef(false);

  // Sync refs for the gyroscope callback
  useEffect(() => {
    currentIndexRef.current = currentIndex;
    isLevelRef.current = isLevel;
  }, [currentIndex, isLevel]);

  const handleStart = () => {
    if (vehicleId.trim()) {
      setIsCapturing(true);
      setCurrentIndex(0);
      setUploadedCount(0);
      lastHeadingRef.current = null;
      accumulatedRotationRef.current = 0;
    }
  };

  const handleCapture = (blob) => {
    if (currentIndex < TOTAL_PHOTOS) {
      uploadQueue.add(vehicleId, currentIndex + 1, blob);
      setCurrentIndex(prev => prev + 1);
    }
  };

  const handleRetake = () => {
    // If they want to retake, we just decrement currentIndex.
    // The next capture will overwrite the photoIndex on the backend.
    if (currentIndex > 0) {
      setCurrentIndex(prev => prev - 1);
      // Adjust accumulated rotation back by one step so auto-capture waits
      const currentRot = accumulatedRotationRef.current;
      const sign = currentRot >= 0 ? 1 : -1;
      accumulatedRotationRef.current = currentRot - (sign * ANGLE_PER_PHOTO);
    }
  };

  function getAngleDiff(a, b) {
    let diff = (a - b) % 360;
    if (diff < -180) diff += 360;
    if (diff > 180) diff -= 360;
    return diff;
  }

  const handleHeadingChange = (heading) => {
    if (!isCapturing || currentIndexRef.current >= TOTAL_PHOTOS) return;

    if (lastHeadingRef.current === null) {
      lastHeadingRef.current = heading;
      return;
    }

    const diff = getAngleDiff(heading, lastHeadingRef.current);
    lastHeadingRef.current = heading;
    
    // Only accumulate if the phone is relatively level to avoid wild jumps
    if (isLevelRef.current) {
      accumulatedRotationRef.current += diff;
      
      const absRotation = Math.abs(accumulatedRotationRef.current);
      const targetRotation = currentIndexRef.current * ANGLE_PER_PHOTO;
      
      // If we've rotated enough for the next photo, and the phone is level, TRIGGER!
      // But only if we already took the first photo manually (index > 0) or if they just spun anyway.
      // Wait, let's let them take the first photo manually to set the starting position.
      if (currentIndexRef.current > 0 && absRotation >= targetRotation) {
        // Trigger auto capture
        setAutoCaptureSignal(prev => prev + 1);
        
        // We artificially bump the accumulated rotation slightly past the target 
        // to prevent multiple triggers in the same spot due to noise.
        // Actually, currentIndex will increment, so targetRotation will jump by 15.
        // That naturally prevents double triggers.
      }
    }
  };

  if (isCapturing) {
    if (currentIndex >= TOTAL_PHOTOS) {
      if (uploadedCount >= TOTAL_PHOTOS) {
        return (
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', height: '100dvh', width: '100vw',
            overflow: 'hidden', backgroundColor: '#000', color: '#fff', padding: '20px'
          }}>
            <h2 style={{ color: '#4CAF50' }}>✅ Success!</h2>
            <p style={{ marginTop: '20px', textAlign: 'center' }}>
              All 24 photos uploaded successfully!<br />
              You can now view the 3D model on your computer.
            </p>
            <button
              onClick={() => { setIsCapturing(false); setVehicleId(''); }}
              style={{ marginTop: '30px', padding: '12px 30px', fontSize: '16px',
                backgroundColor: '#4CAF50', color: '#fff', border: 'none',
                borderRadius: '10px', cursor: 'pointer' }}
            >
              Start New Vehicle
            </button>
          </div>
        );
      }

      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center',
          justifyContent: 'center', height: '100dvh', width: '100vw',
          overflow: 'hidden', backgroundColor: '#000', color: '#fff'
        }}>
          <h2>Processing Photos</h2>
          <ProgressBar uploadedCount={uploadedCount} totalPhotos={TOTAL_PHOTOS} />
          <p style={{ marginTop: '20px' }}>Uploading and processing your photos...</p>
        </div>
      );
    }

    return (
      <div style={{ height: '100dvh', width: '100vw', overflow: 'hidden' }}>
        <Waterpass 
          onLevelChange={setIsLevel} 
          onHeadingChange={handleHeadingChange}
        />
        <CameraView
          isLevel={isLevel}
          onCapture={handleCapture}
          onRetake={handleRetake}
          autoCaptureSignal={autoCaptureSignal}
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

      <button
        onClick={() => navigate('/dashboard')}
        style={{
          marginTop: '30px',
          padding: '10px 20px',
          fontSize: '14px',
          backgroundColor: 'transparent',
          color: '#888',
          border: '1px solid #444',
          borderRadius: '10px',
          cursor: 'pointer',
          transition: 'all 0.2s'
        }}
      >
        Admin Dashboard
      </button>
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CaptureFlow />} />
        <Route path="/dashboard" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
