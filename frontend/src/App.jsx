import { useState } from 'react';
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom';
import CameraView from './components/CameraView';
import Dashboard from './components/Dashboard';
import { uploadVideo } from './api/uploader';

function CaptureFlow() {
  const navigate = useNavigate();
  const [vehicleId, setVehicleId] = useState('');
  
  // States: 'HOME' | 'RECORDING' | 'UPLOADING' | 'DONE' | 'ERROR'
  const [appState, setAppState] = useState('HOME');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [errorMessage, setErrorMessage] = useState('');

  const handleStart = () => {
    if (vehicleId.trim()) {
      setAppState('RECORDING');
    }
  };

  const handleVideoRecorded = async (videoBlob, sensorData) => {
    setAppState('UPLOADING');
    setUploadProgress(0);
    
    try {
      await uploadVideo(vehicleId, videoBlob, sensorData, (progress) => {
        setUploadProgress(progress);
      });
      setAppState('DONE');
    } catch (error) {
      setErrorMessage(error.message);
      setAppState('ERROR');
    }
  };

  if (appState === 'ERROR') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100dvh', backgroundColor: '#000', color: '#fff', padding: '20px', textAlign: 'center' }}>
        <h2 style={{ color: '#F44336' }}>❌ Hiba történt!</h2>
        <p style={{ marginTop: '20px' }}>{errorMessage}</p>
        <button onClick={() => setAppState('HOME')} style={{ marginTop: '30px', padding: '12px 30px', backgroundColor: '#2196F3', color: '#fff', border: 'none', borderRadius: '10px', cursor: 'pointer' }}>
          Újrapróbálkozás
        </button>
      </div>
    );
  }

  if (appState === 'DONE') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100dvh', backgroundColor: '#000', color: '#fff', padding: '20px', textAlign: 'center' }}>
        <h2 style={{ color: '#4CAF50' }}>✅ Sikeres feltöltés!</h2>
        <p style={{ marginTop: '20px' }}>
          A videó feltöltve! A szerver jelenleg is dolgozik a 360°-os forgatás generálásán.
        </p>
        <button onClick={() => navigate('/dashboard')} style={{ marginTop: '30px', padding: '12px 30px', backgroundColor: '#4CAF50', color: '#fff', border: 'none', borderRadius: '10px', cursor: 'pointer' }}>
          Tovább a Dashboardra
        </button>
      </div>
    );
  }

  if (appState === 'UPLOADING') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100dvh', backgroundColor: '#000', color: '#fff' }}>
        <h2>Videó feltöltése folyamatban...</h2>
        
        {/* Simple Progress Bar */}
        <div style={{ width: '80%', maxWidth: '300px', height: '20px', backgroundColor: '#333', borderRadius: '10px', marginTop: '30px', overflow: 'hidden' }}>
          <div style={{ width: `${uploadProgress}%`, height: '100%', backgroundColor: '#4CAF50', transition: 'width 0.3s ease' }} />
        </div>
        <p style={{ marginTop: '10px', fontWeight: 'bold' }}>{uploadProgress}%</p>
        
        <p style={{ marginTop: '20px', color: '#888' }}>Ne zárd be az alkalmazást!</p>
      </div>
    );
  }

  if (appState === 'RECORDING') {
    return (
      <CameraView onVideoRecorded={handleVideoRecorded} />
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100dvh', backgroundColor: '#000', color: '#fff', padding: '20px' }}>
      <h1 style={{ marginBottom: '40px', textAlign: 'center' }}>VehicleShoot 360<br/><span style={{fontSize:'16px', color:'#4CAF50'}}>Premium Video Mode</span></h1>
      
      <input
        type="text"
        value={vehicleId}
        onChange={(e) => setVehicleId(e.target.value)}
        placeholder="Autó azonosító (pl. Lancer-16)"
        style={{ padding: '15px 20px', fontSize: '18px', borderRadius: '10px', border: '2px solid #333', backgroundColor: '#222', color: '#fff', marginBottom: '20px', width: '100%', maxWidth: '300px', textAlign: 'center' }}
      />
      
      <button
        onClick={handleStart}
        disabled={!vehicleId.trim()}
        style={{ padding: '15px 40px', fontSize: '18px', backgroundColor: vehicleId.trim() ? '#4CAF50' : '#333', color: '#fff', border: 'none', borderRadius: '10px', cursor: vehicleId.trim() ? 'pointer' : 'not-allowed', transition: 'background-color 0.2s' }}
      >
        Videózás Indítása
      </button>

      <button onClick={() => navigate('/dashboard')} style={{ marginTop: '30px', padding: '10px 20px', fontSize: '14px', backgroundColor: 'transparent', color: '#888', border: '1px solid #444', borderRadius: '10px', cursor: 'pointer' }}>
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
