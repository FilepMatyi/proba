import { useState, useRef, useEffect } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import CameraView from './components/CameraView';
import ProgressBar from './components/ProgressBar';
import Dashboard from './components/Dashboard';

const TOTAL_PHOTOS = 36;
const ANGLE_PER_PHOTO = 360 / TOTAL_PHOTOS;

function CaptureFlow() {
  const navigate = useNavigate();
  const [vehicleId, setVehicleId] = useState('');
  
  // States: 'HOME' | 'WALKING' | 'UPLOADING' | 'DONE'
  const [appState, setAppState] = useState('HOME');
  
  const [currentIndex, setCurrentIndex] = useState(0);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [autoCaptureSignal, setAutoCaptureSignal] = useState(0);
  
  const [capturedBlobs, setCapturedBlobs] = useState([]);

  // Gyroscope tracking refs
  const lastHeadingRef = useRef(null);
  const accumulatedRotationRef = useRef(0);
  const currentIndexRef = useRef(0);
  const lastTriggeredSlotRef = useRef(0);

  useEffect(() => {
    currentIndexRef.current = currentIndex;
  }, [currentIndex]);

  const handleStart = () => {
    if (vehicleId.trim()) {
      setAppState('WALKING');
      setCurrentIndex(0);
      setUploadedCount(0);
      setCapturedBlobs([]);
      lastHeadingRef.current = null;
      accumulatedRotationRef.current = 0;
      lastTriggeredSlotRef.current = 0;
    }
  };

  const handleCapture = (blob) => {
    if (!blob) return;
    
    setCapturedBlobs(prev => {
      const newList = [...prev, blob];
      if (newList.length >= TOTAL_PHOTOS) {
        setAppState('UPLOADING');
      }
      return newList;
    });
    
    setCurrentIndex(prev => prev + 1);
  };

  function getAngleDiff(a, b) {
    let diff = (a - b) % 360;
    if (diff < -180) diff += 360;
    if (diff > 180) diff -= 360;
    return diff;
  }

  // Device orientation listener for continuous walk
  useEffect(() => {
    if (appState !== 'WALKING') return;

    const handleOrientation = (event) => {
      let heading = null;
      if (event.webkitCompassHeading !== undefined) {
        heading = event.webkitCompassHeading;
      } else if (event.alpha !== null) {
        heading = 360 - event.alpha;
      }

      if (heading === null || currentIndexRef.current >= TOTAL_PHOTOS) return;

      if (lastHeadingRef.current === null) {
        lastHeadingRef.current = heading;
        return;
      }

      const diff = getAngleDiff(heading, lastHeadingRef.current);
      lastHeadingRef.current = heading;
      
      accumulatedRotationRef.current += diff;
      const absRotation = Math.abs(accumulatedRotationRef.current);
      
      const currentSlot = Math.floor(absRotation / ANGLE_PER_PHOTO);
      
      // If we manually took the first photo (index > 0) 
      // and we have crossed into a new 10-degree slot
      if (currentIndexRef.current > 0 && currentSlot > lastTriggeredSlotRef.current) {
        lastTriggeredSlotRef.current = currentSlot;
        setAutoCaptureSignal(prev => prev + 1);
      }
    };

    window.addEventListener('deviceorientation', handleOrientation, true);
    return () => {
      window.removeEventListener('deviceorientation', handleOrientation, true);
    };
  }, [appState]);

  // Sequential uploader effect
  useEffect(() => {
    if (appState === 'UPLOADING' && capturedBlobs.length === TOTAL_PHOTOS) {
      let isCancelled = false;

      const uploadAll = async () => {
        for (let i = 0; i < TOTAL_PHOTOS; i++) {
          if (isCancelled) return;
          
          let success = false;
          let retries = 0;
          
          while (!success && retries < 3) {
            try {
              const formData = new FormData();
              formData.append('photo', capturedBlobs[i], `frame_${i+1}.jpg`);
              formData.append('photoIndex', i + 1);
              formData.append('totalPhotos', TOTAL_PHOTOS);

              const response = await fetch(`/api/vehicles/${vehicleId}/photos`, {
                method: 'POST',
                body: formData,
              });

              if (response.ok) {
                success = true;
                setUploadedCount(i + 1);
              } else {
                const errorText = await response.text();
                throw new Error(`Upload failed: ${response.status} ${errorText}`);
              }
            } catch (err) {
              retries++;
              console.error(`Upload error frame ${i+1}, retry ${retries}...`, err);
              await new Promise(r => setTimeout(r, 1000)); // wait 1s before retry
            }
          }
          
          if (!success) {
            alert('Hálózati hiba miatt megszakadt a feltöltés. Kérlek, zárd be az appot és próbáld újra!');
            return;
          }
        }
        
        if (!isCancelled) {
          setAppState('DONE');
        }
      };

      uploadAll();

      return () => { isCancelled = true; };
    }
  }, [appState, capturedBlobs, vehicleId]);

  // Request permissions button for iOS
  const [permissionsGranted, setPermissionsGranted] = useState(false);
  const requestPermissions = async () => {
    if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
      try {
        const permission = await DeviceOrientationEvent.requestPermission();
        if (permission === 'granted') setPermissionsGranted(true);
      } catch (error) {
        console.error(error);
      }
    } else {
      setPermissionsGranted(true);
    }
  };

  useEffect(() => {
    // Auto-grant for non-iOS devices
    if (typeof DeviceOrientationEvent === 'undefined' || typeof DeviceOrientationEvent.requestPermission !== 'function') {
      setPermissionsGranted(true);
    }
  }, []);

  if (appState === 'DONE') {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', height: '100dvh', width: '100vw',
        overflow: 'hidden', backgroundColor: '#000', color: '#fff', padding: '20px'
      }}>
        <h2 style={{ color: '#4CAF50' }}>✅ Sikeres feltöltés!</h2>
        <p style={{ marginTop: '20px', textAlign: 'center' }}>
          Mind a {TOTAL_PHOTOS} fotó fel lett töltve!<br />
          A szerver most feldolgozza az autót.
        </p>
        <button
          onClick={() => navigate('/dashboard')}
          style={{ marginTop: '30px', padding: '12px 30px', fontSize: '16px',
            backgroundColor: '#4CAF50', color: '#fff', border: 'none',
            borderRadius: '10px', cursor: 'pointer' }}
        >
          Tovább a Dashboardra
        </button>
      </div>
    );
  }

  if (appState === 'UPLOADING') {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', height: '100dvh', width: '100vw',
        overflow: 'hidden', backgroundColor: '#000', color: '#fff'
      }}>
        <h2>Feltöltés folyamatban</h2>
        <ProgressBar uploadedCount={uploadedCount} totalPhotos={TOTAL_PHOTOS} />
        <p style={{ marginTop: '20px', color: '#888' }}>Ne zárd be az alkalmazást, amíg ez be nem fejeződik!</p>
      </div>
    );
  }

  if (appState === 'WALKING') {
    return (
      <div style={{ height: '100dvh', width: '100vw', overflow: 'hidden' }}>
        <CameraView
          isLevel={true} // Always allow capturing in walk mode
          onCapture={handleCapture}
          autoCaptureSignal={autoCaptureSignal}
          currentIndex={currentIndex}
          totalPhotos={TOTAL_PHOTOS}
        />
        {/* Progress indicator during walk */}
        <div style={{
          position: 'absolute', bottom: '150px', left: '50%', transform: 'translateX(-50%)',
          width: '80%', zIndex: 100
        }}>
          <div style={{ textAlign: 'center', color: 'white', marginBottom: '10px', fontWeight: 'bold', textShadow: '1px 1px 2px black' }}>
            Sétálj lassan körbe! ({currentIndex}/{TOTAL_PHOTOS})
          </div>
          <ProgressBar uploadedCount={currentIndex} totalPhotos={TOTAL_PHOTOS} />
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
        height: '100dvh', width: '100vw', overflow: 'hidden', backgroundColor: '#000', color: '#fff', padding: '20px'
      }}
    >
      <h1 style={{ marginBottom: '40px' }}>VehicleShoot 360</h1>
      
      {!permissionsGranted ? (
        <button onClick={requestPermissions} style={{
          padding: '15px 40px', fontSize: '18px', backgroundColor: '#2196F3',
          color: '#fff', border: 'none', borderRadius: '10px', cursor: 'pointer', marginBottom: '20px'
        }}>
          Szenzorok Engedélyezése
        </button>
      ) : (
        <>
          <input
            type="text"
            value={vehicleId}
            onChange={(e) => setVehicleId(e.target.value)}
            placeholder="Autó azonosító (pl. Lancer-16)"
            style={{
              padding: '15px 20px', fontSize: '18px', borderRadius: '10px',
              border: '2px solid #333', backgroundColor: '#222', color: '#fff',
              marginBottom: '20px', width: '100%', maxWidth: '300px', textAlign: 'center'
            }}
          />
          <button
            onClick={handleStart}
            disabled={!vehicleId.trim()}
            style={{
              padding: '15px 40px', fontSize: '18px',
              backgroundColor: vehicleId.trim() ? '#4CAF50' : '#333',
              color: '#fff', border: 'none', borderRadius: '10px',
              cursor: vehicleId.trim() ? 'pointer' : 'not-allowed',
              transition: 'background-color 0.2s'
            }}
          >
            Fotózás Indítása
          </button>
        </>
      )}

      <button
        onClick={() => navigate('/dashboard')}
        style={{
          marginTop: '30px', padding: '10px 20px', fontSize: '14px',
          backgroundColor: 'transparent', color: '#888', border: '1px solid #444',
          borderRadius: '10px', cursor: 'pointer', transition: 'all 0.2s'
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
