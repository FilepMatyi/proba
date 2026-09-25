import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Camera, Check, RotateCcw, Sparkles } from 'lucide-react';
import { getGuidedStudio, processGuidedStudio, startGuidedStudio, uploadGuidedPhoto } from '../api/uploader';
import { analyzePreview } from '../guided/analyzer';
import { captureStudioStill, imageSize, openStudioCamera } from '../guided/camera';
import { beginRetake, captureTick, confirmCapture, initialCaptureState,
  retryCapture, smoothOrientation } from '../guided/engine';
import { loadDraftPhotos, saveDraftPhoto } from '../guided/draftStore';

const DEBUG = new URLSearchParams(window.location.search).has('debug');
const labels = { red: 'guided-red', yellow: 'guided-yellow', green: 'guided-green' };

export default function GuidedStudioCapture() {
  const { vehicleId } = useParams();
  const navigate = useNavigate();
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const trackRef = useRef(null);
  const canvasRef = useRef(document.createElement('canvas'));
  const previousGrayRef = useRef(null);
  const orientationRef = useRef(null);
  const stateRef = useRef(initialCaptureState(0));
  const photosRef = useRef(Array(10).fill(null));
  const captureLockRef = useRef(false);
  const retakeRef = useRef(null);
  const [screen, setScreen] = useState('intro');
  const [engine, setEngine] = useState(stateRef.current);
  const [photos, setPhotos] = useState(photosRef.current);
  const [previews, setPreviews] = useState(Array(10).fill(null));
  const [backendSession, setBackendSession] = useState(null);
  const [cameraReady, setCameraReady] = useState(false);
  const [error, setError] = useState('');
  const [uploadCount, setUploadCount] = useState(0);
  const [debugSample, setDebugSample] = useState(null);

  useEffect(() => {
    let active = true;
    loadDraftPhotos(vehicleId).then((draft) => {
      if (!active || !draft.some(Boolean)) return;
      photosRef.current = draft;
      setPhotos(draft);
      setScreen('review');
    }).catch(() => {});
    getGuidedStudio(vehicleId).then((session) => { if (active) setBackendSession(session); }).catch(() => {});
    return () => { active = false; };
  }, [vehicleId]);

  useEffect(() => {
    const urls = photos.map((photo) => photo ? URL.createObjectURL(photo.blob) : null);
    setPreviews(urls);
    return () => urls.forEach((url) => { if (url) URL.revokeObjectURL(url); });
  }, [photos]);

  useEffect(() => {
    if (screen !== 'capture') return undefined;
    let active = true;
    setCameraReady(false);
    openStudioCamera().then(({ stream, track }) => {
      if (!active) { stream.getTracks().forEach((item) => item.stop()); return; }
      streamRef.current = stream;
      trackRef.current = track;
      videoRef.current.srcObject = stream;
      videoRef.current.play().catch(() => {});
      setCameraReady(true);
    }).catch((reason) => {
      if (active) { setError(reason.name === 'NotAllowedError'
        ? 'Engedélyezd a kamerát a telefonon.' : 'A kamera nem indítható ezen az eszközön.');
        setScreen('intro'); }
    });
    return () => {
      active = false;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      trackRef.current = null;
      previousGrayRef.current = null;
      orientationRef.current = null;
      setCameraReady(false);
    };
  }, [screen]);

  useEffect(() => {
    if (screen !== 'capture') return undefined;
    const onOrientation = (event) => {
      const heading = event.webkitCompassHeading ?? event.alpha;
      if (!Number.isFinite(heading)) return;
      orientationRef.current = smoothOrientation(orientationRef.current, {
        heading, beta: event.beta, gamma: event.gamma,
      });
    };
    window.addEventListener('deviceorientation', onOrientation);
    return () => window.removeEventListener('deviceorientation', onOrientation);
  }, [screen]);

  useEffect(() => {
    if (screen !== 'capture' || !cameraReady) return undefined;
    const timer = window.setInterval(async () => {
      const video = videoRef.current;
      if (!video || video.readyState < 2 || captureLockRef.current) return;
      try {
        const quality = analyzePreview(video, canvasRef.current, previousGrayRef.current);
        previousGrayRef.current = quality.gray;
        const orientation = orientationRef.current;
        const base = stateRef.current.orientationBase;
        // Relative device pose only: no false physical pitch/height claim.
        const roll = orientation && base ? orientation.gamma-base.gamma : null;
        const pitch = orientation && base ? orientation.beta-base.beta : null;
        const sample = {
          ...quality, time: performance.now(),
          landscape: window.innerWidth >= window.innerHeight,
          heading: orientation?.heading ?? null,
          orientation, roll, pitch,
        };
        const decision = captureTick(stateRef.current, sample);
        stateRef.current = decision.state;
        setEngine(decision.state);
        if (DEBUG) setDebugSample({ ...sample, gray: undefined });
        if (!decision.capture) return;
        captureLockRef.current = true;
        const sector = decision.state.nextSector;
        try {
          const { blob, method } = await captureStudioStill(trackRef.current, video);
          const size = await imageSize(blob);
          const metadata = {
            captureIndex: sector, targetSector: sector, timestamp: Date.now(),
            roll, pitch, deviceOrientationAvailable: Boolean(orientation),
            vehicleWidthRatio: quality.vehicleBox?.width ?? null,
            vehicleHeightRatio: quality.vehicleBox?.height ?? null,
            sharpnessScore: quality.sharpnessScore,
            exposureScore: quality.exposureScore,
            stabilityScore: quality.stabilityScore,
            captureQuality: decision.quality.score,
            captureConfidence: decision.quality.grade === 'green' ? 'high' : 'medium',
            captureMethod: method, sourceWidth: size.width, sourceHeight: size.height,
            sectorDurationMs: Math.round(sample.time-decision.state.sectorStartedAt),
            retryCount: decision.state.retries[sector-1],
            instructionCounts: decision.state.instructions,
          };
          const photo = { blob, metadata };
          photosRef.current = photosRef.current.map((current, index) => index === sector-1 ? photo : current);
          setPhotos([...photosRef.current]);
          try { await saveDraftPhoto(vehicleId, sector, photo); }
          catch { setError('A helyi mentés nem sikerült. Feltöltésig tartsd nyitva ezt az oldalt.'); }
          navigator.vibrate?.(65);
          const next = confirmCapture(stateRef.current, performance.now());
          stateRef.current = next;
          setEngine(next);
          if (retakeRef.current !== null || next.phase === 'done') {
            retakeRef.current = null;
            setScreen('review');
          }
        } catch (reason) {
          stateRef.current = retryCapture(stateRef.current);
          setEngine(stateRef.current);
          setError(reason.message || 'A kép készítése sikertelen, próbáld újra.');
        } finally { captureLockRef.current = false; }
      } catch {
        // A kimaradt preview minta nem szakíthatja meg a kameraképet.
      }
    }, 125);
    return () => window.clearInterval(timer);
  }, [screen, cameraReady, vehicleId]);

  const requestOrientation = async () => {
    if (typeof window.DeviceOrientationEvent?.requestPermission === 'function') {
      await window.DeviceOrientationEvent.requestPermission().catch(() => {});
    }
  };

  const start = async () => {
    setError('');
    try {
      const session = backendSession || await startGuidedStudio(vehicleId);
      setBackendSession(session);
      if (session.status === 'ready' || session.status === 'processing' || session.status === 'failed') {
        navigate(`/studio-photos/${vehicleId}`);
        return;
      }
      await requestOrientation();
      const now = performance.now();
      stateRef.current = initialCaptureState(now);
      setEngine(stateRef.current);
      setScreen('capture');
    } catch (reason) { setError(reason.message); }
  };

  const retake = async (sector) => {
    setError('');
    await requestOrientation();
    retakeRef.current = sector;
    const now = performance.now();
    stateRef.current = beginRetake(initialCaptureState(now), sector, now);
    setEngine(stateRef.current);
    setScreen('capture');
  };

  const process = async () => {
    if (!photosRef.current.every(Boolean)) return;
    setScreen('uploading');
    setError('');
    try {
      const session = backendSession || await startGuidedStudio(vehicleId);
      setBackendSession(session);
      for (let index = 0; index < 10; index++) {
        const photo = photosRef.current[index];
        if (session.photos?.[index]?.timestamp !== photo.metadata.timestamp) {
          await uploadGuidedPhoto(vehicleId, session.captureId, index+1, photo.blob, photo.metadata);
        }
        setUploadCount(index+1);
      }
      await processGuidedStudio(vehicleId, session.captureId);
      navigate(`/studio-photos/${vehicleId}`);
    } catch (reason) {
      setError(`${reason.message} A képek helyben megmaradtak; próbáld újra a feltöltést.`);
      setScreen('review');
    }
  };

  if (screen === 'intro') return <main className="guided-intro">
    <button className="back-link" onClick={() => navigate('/')}><ArrowLeft size={18} /> Vissza</button>
    <div className="guided-intro-card">
      <span className="guided-kicker">10 STUDIO PHOTOS · GUIDED CAPTURE</span>
      <h1>Sétálj egyszer körbe az autón.</h1>
      <p>Állj nagyjából az autó elé, és férjen bele a teljes jármű a keretbe. A képek automatikusan készülnek. Nem kell fokokat eltalálnod.</p>
      <p className="guided-note">Tartsd a telefont fekvő helyzetben, a főkamerával; kényelmesen, szemmagasság körül. Az autó elejétől indulva sétálj körbe jobbra.</p>
      {error && <p className="guided-error">{error}</p>}
      <button className="button button-primary" onClick={start}><Camera size={19} /> INDÍTÁS</button>
    </div>
  </main>;

  if (screen === 'capture') return <main className="guided-camera">
    <video ref={videoRef} autoPlay playsInline muted className="guided-video" />
    <div className="guided-shade" />
    <div className="guided-capture-top">
      <button className="glass-icon" onClick={() => setScreen('review')} aria-label="Kilépés"><ArrowLeft size={20} /></button>
      <strong>{photos.filter(Boolean).length} / 10</strong>
      <span>STUDIO PHOTOS</span>
    </div>
    <div className="guided-outline" aria-hidden="true"><i /><i /><i /><i /></div>
    <div className={`guided-instruction ${labels[engine.grade] || 'guided-yellow'}`}>
      {!cameraReady ? 'KAMERA INDUL…' : engine.instruction}
    </div>
    <div className="guided-dots">{photos.map((photo, index) =>
      <span key={index} className={photo ? 'complete' : index === engine.nextSector-1 ? 'active' : ''}>
        {photo ? <Check size={14} /> : ''}
      </span>)}</div>
    {error && <p className="guided-camera-error">{error}</p>}
    {DEBUG && <pre className="guided-debug">{JSON.stringify({ sector: engine.nextSector,
      phase: engine.phase, progress: engine.maxProgress.toFixed(1),
      heading: debugSample?.heading, roll: debugSample?.roll,
      pitch: debugSample?.pitch, sharpness: debugSample?.sharpnessScore?.toFixed(2),
      stability: debugSample?.stabilityScore?.toFixed(2),
      exposure: debugSample?.exposureScore?.toFixed(2),
      framing: debugSample?.vehicleBox || 'guide-only',
      method: 'native_still → stream_fallback' }, null, 2)}</pre>}
  </main>;

  if (screen === 'uploading') return <main className="guided-intro"><div className="guided-intro-card">
    <span className="guided-kicker">FELTÖLTÉS</span><h1>{uploadCount} / 10</h1>
    <p>Tartsd nyitva az oldalt. A már feltöltött képeket újrapróbáláskor nem küldjük el újra.</p>
  </div></main>;

  const weakCount = photos.filter((photo) => photo && photo.metadata.captureConfidence !== 'high').length;
  return <main className="guided-review dashboard-shell">
    <header className="dashboard-header"><div>
      <button className="back-link" onClick={() => navigate('/')}><ArrowLeft size={16} /> Kezdőlap</button>
      <p className="eyebrow">10 Studio Photos · állóképek</p>
      <h1>{photos.filter(Boolean).length} / 10 kép elkészült</h1>
      <p>{weakCount ? `${weakCount} kép javítható, de a feldolgozás folytatható.` : 'Nézd át a képeket, majd indítsd a stúdiófeldolgozást.'}</p>
    </div></header>
    {error && <p className="dashboard-alert">{error}</p>}
    <section className="guided-review-grid">{photos.map((photo, index) => <article key={index}>
      {previews[index] ? <img src={previews[index]} alt={`${index+1}. forrásfotó`} /> : <div className="guided-empty"><Camera size={26} /></div>}
      <div><strong>{String(index+1).padStart(2, '0')} {photo?.metadata.captureConfidence === 'high' ? '✓' : photo ? '⚠' : '—'}</strong>
        <button onClick={() => retake(index+1)}><RotateCcw size={15} /> {photo ? 'Újrafotózás' : 'Pótlás'}</button></div>
    </article>)}</section>
    <div className="guided-review-actions"><button className="button button-primary" disabled={!photos.every(Boolean)} onClick={process}>
      <Sparkles size={18} /> STÚDIÓKÉPEK FELDOLGOZÁSA</button></div>
  </main>;
}
