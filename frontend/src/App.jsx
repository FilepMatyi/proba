import { useEffect, useState } from 'react';
import { BrowserRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { AlertTriangle, ArrowRight, Check, ChevronRight, Gauge, LayoutDashboard, Rotate3D, ShieldCheck, Sparkles } from 'lucide-react';

import CameraView from './components/CameraView';
import Dashboard from './components/Dashboard';
import { getSession, uploadVideo } from './api/uploader';
import './styles.css';

const VEHICLE_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/;

const STAGE_LABELS = {
  uploading: 'Feltöltés fogadása',
  extracting: 'Képkockák kinyerése',
  selecting: 'A legjobb nézetek kiválasztása',
  composing: 'Prémium stúdióképek készítése',
  ready: 'A 360° bemutató elkészült',
};

function sessionWarnings(session) {
  if (Array.isArray(session?.qualityWarnings)) return session.qualityWarnings;
  try {
    const warnings = JSON.parse(session?.qualityWarnings || '[]');
    return Array.isArray(warnings) ? warnings : [];
  } catch {
    return [];
  }
}

function CaptureFlow() {
  const navigate = useNavigate();
  const [vehicleId, setVehicleId] = useState('');
  const [appState, setAppState] = useState('HOME');
  const [uploadProgress, setUploadProgress] = useState(0);
  const [processingSession, setProcessingSession] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');

  const normalizedVehicleId = vehicleId.trim().toLowerCase();
  const isVehicleIdValid = VEHICLE_ID_PATTERN.test(vehicleId.trim());

  useEffect(() => {
    if (appState !== 'PROCESSING' || !normalizedVehicleId) return undefined;

    let active = true;
    const refresh = async () => {
      try {
        const session = await getSession(normalizedVehicleId);
        if (!active) return;
        setProcessingSession(session);
        if (session.status === 'failed') {
          setErrorMessage(session.errorMessage || 'A képfeldolgozás nem fejeződött be.');
          setAppState('ERROR');
        }
      } catch {
        // A rövid hálózati kiesés ne szakítsa meg a feldolgozás képernyőjét.
      }
    };

    refresh();
    const timer = window.setInterval(refresh, 4000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [appState, normalizedVehicleId]);

  const startCapture = () => {
    if (isVehicleIdValid) setAppState('RECORDING');
  };

  const submitVideo = async (videoBlob, sensorData) => {
    setAppState('UPLOADING');
    setUploadProgress(0);
    try {
      await uploadVideo(normalizedVehicleId, videoBlob, sensorData, setUploadProgress);
      setAppState('PROCESSING');
    } catch (error) {
      setErrorMessage(error.message);
      setAppState('ERROR');
    }
  };

  if (appState === 'RECORDING') {
    return <CameraView vehicleId={normalizedVehicleId} onCancel={() => setAppState('HOME')} onVideoRecorded={submitVideo} />;
  }

  if (appState === 'UPLOADING') {
    return (
      <main className="status-screen">
        <div className="status-card">
          <div className="orb orb-upload"><span>{uploadProgress}%</span></div>
          <p className="eyebrow">Biztonságos feltöltés</p>
          <h1>A felvétel úton van</h1>
          <p className="muted">Tartsd nyitva ezt az ablakot, amíg a feltöltés befejeződik.</p>
          <div className="progress-track" aria-label={`Feltöltés ${uploadProgress}%`}>
            <span style={{ width: `${uploadProgress}%` }} />
          </div>
        </div>
      </main>
    );
  }

  if (appState === 'PROCESSING') {
    const completed = processingSession?.status === 'completed';
    const warnings = sessionWarnings(processingSession);
    const needsReview = completed && (
      warnings.length > 0
      || (processingSession?.qualityScore !== null
        && processingSession?.qualityScore !== undefined
        && processingSession.qualityScore < 68)
    );
    const progress = processingSession
      ? Math.round((processingSession.processedFrames / processingSession.totalFrames) * 100)
      : 4;
    return (
      <main className="status-screen">
        <div className="status-card">
          <div className={`orb ${needsReview ? 'orb-review' : completed ? 'orb-success' : 'orb-processing'}`}>
            {needsReview ? <AlertTriangle size={34} /> : completed ? <Check size={34} /> : <span>{progress}%</span>}
          </div>
          <p className="eyebrow">{needsReview ? 'Új felvétel ajánlott' : completed ? 'Bemutatóra kész' : normalizedVehicleId}</p>
          <h1>{needsReview ? 'Minőségellenőrzés szükséges' : completed ? 'Elkészült a prémium 360°' : STAGE_LABELS[processingSession?.stage] || 'A vizuális stúdió dolgozik'}</h1>
          <p className="muted">
            {needsReview
              ? 'Mind a 36 nézet elkészült, de a sorozatot megosztás előtt ellenőrizni vagy újra rögzíteni kell.'
              : completed
              ? 'Mind a 36 nézet elkészült, a bemutató azonnal megosztható.'
              : `${processingSession?.processedFrames || 0} / 36 végleges kép készült el. Ezt az oldalt már bezárhatod.`}
          </p>
          {processingSession?.qualityScore !== null && processingSession?.qualityScore !== undefined && (
            <div className={`status-quality ${processingSession.qualityScore < 68 ? 'status-quality-review' : ''}`}>
              <ShieldCheck size={17} />
              <span>Automatikus képminőség</span>
              <strong>{processingSession.qualityScore}/100</strong>
            </div>
          )}
          {completed && warnings.length > 0 && <p className="status-quality-note">{warnings[0]}</p>}
          {!completed && <div className="progress-track"><span style={{ width: `${progress}%` }} /></div>}
          <div className="status-actions">
            {completed && (
              <a className="button button-primary" href={`/viewer/${normalizedVehicleId}`} target="_blank" rel="noreferrer">
                360° megnyitása <ArrowRight size={18} />
              </a>
            )}
            <button className="button button-secondary" onClick={() => navigate('/dashboard')}>
              Dashboard <ChevronRight size={18} />
            </button>
          </div>
        </div>
      </main>
    );
  }

  if (appState === 'ERROR') {
    return (
      <main className="status-screen">
        <div className="status-card status-card-error">
          <div className="error-mark">!</div>
          <p className="eyebrow">Beavatkozás szükséges</p>
          <h1>A feldolgozás megállt</h1>
          <p className="muted">{errorMessage}</p>
          <div className="status-actions">
            <button className="button button-primary" onClick={() => setAppState('HOME')}>Új felvétel</button>
            <button className="button button-secondary" onClick={() => navigate('/dashboard')}>Dashboard</button>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="home-shell">
      <nav className="topbar">
        <a className="brand" href="/" aria-label="VehicleShoot kezdőlap">
          <span className="brand-mark"><Rotate3D size={20} /></span>
          <span>VehicleShoot <b>360</b></span>
        </a>
        <button className="nav-button" onClick={() => navigate('/dashboard')}>
          <LayoutDashboard size={17} /> Dashboard
        </button>
      </nav>

      <section className="capture-hero">
        <div className="hero-copy">
          <div className="live-pill"><span /> 36 nézet · egyetlen felvételből</div>
          <h1>Prémium autóbemutató, <em>stúdió nélkül.</em></h1>
          <p>Rögzíts egy egyenletes kört az autó körül. A rendszer kiválasztja és egységesíti a legjobb 36 képkockát.</p>

          <form className="capture-form" onSubmit={(event) => { event.preventDefault(); startCapture(); }}>
            <label htmlFor="vehicle-id">Autó azonosító</label>
            <div className={`input-row ${vehicleId && !isVehicleIdValid ? 'input-row-error' : ''}`}>
              <input
                id="vehicle-id"
                value={vehicleId}
                onChange={(event) => setVehicleId(event.target.value)}
                placeholder="például lancer-16"
                autoCapitalize="none"
                autoCorrect="off"
                maxLength={64}
              />
              <button type="submit" disabled={!isVehicleIdValid} aria-label="Felvétel indítása">
                <ArrowRight size={21} />
              </button>
            </div>
            {vehicleId && !isVehicleIdValid && <small>Csak betű, szám, kötőjel és aláhúzás használható.</small>}
          </form>
        </div>

        <div className="process-panel" aria-label="A feldolgozás lépései">
          <div className="process-glow" />
          <p className="panel-kicker">Automatikus vizuális pipeline</p>
          <div className="process-list">
            <div><span><Gauge size={20} /></span><p><b>Irányított felvétel</b><small>Szint- és mozgásadatokkal</small></p><i>01</i></div>
            <div><span><Sparkles size={20} /></span><p><b>AI stúdiófeldolgozás</b><small>Egységes fény, méret és háttér</small></p><i>02</i></div>
            <div><span><Rotate3D size={20} /></span><p><b>Interaktív 360°</b><small>Mobilra optimalizált, beágyazható</small></p><i>03</i></div>
          </div>
          <div className="trust-line"><ShieldCheck size={17} /> Eredeti részleteket megőrző feldolgozás</div>
        </div>
      </section>
    </main>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<CaptureFlow />} />
        <Route path="/dashboard" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>
  );
}
