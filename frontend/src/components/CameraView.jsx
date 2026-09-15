import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, Camera, Check, RotateCcw, Square } from 'lucide-react';

const MIN_RECOMMENDED_SECONDS = 28;
const IDEAL_SECONDS = 36;
const MAX_SECONDS = 50;

function getRecorderOptions() {
  const candidates = [
    'video/mp4;codecs=avc1',
    'video/webm;codecs=h264',
    'video/mp4',
    'video/webm;codecs=vp9',
    'video/webm',
  ];
  const mimeType = candidates.find((type) => MediaRecorder.isTypeSupported(type));
  return mimeType ? { mimeType, videoBitsPerSecond: 7_000_000 } : { videoBitsPerSecond: 7_000_000 };
}

export default function CameraView({ vehicleId, onVideoRecorded, onCancel }) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const chunksRef = useRef([]);
  const sensorDataRef = useRef([]);
  const recordingRef = useRef(false);
  const startedAtRef = useRef(0);
  const lastOrientationUpdateRef = useRef(0);
  const headingRef = useRef({ last: null, unwrapped: 0, maximum: 0 });
  const qualityCanvasRef = useRef(null);

  const [cameraState, setCameraState] = useState('loading');
  const [cameraError, setCameraError] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);
  const [orientation, setOrientation] = useState({ beta: 90, gamma: 0, available: false });
  const [rotationCoverage, setRotationCoverage] = useState(0);
  const [lighting, setLighting] = useState('unknown');

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  };

  const startCamera = async () => {
    setCameraState('loading');
    setCameraError('');
    stopStream();
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
          frameRate: { ideal: 30, max: 30 },
        },
      });
      streamRef.current = mediaStream;
      if (videoRef.current) videoRef.current.srcObject = mediaStream;
      setCameraState('ready');
    } catch (error) {
      setCameraError(error.name === 'NotAllowedError'
        ? 'A folytatáshoz engedélyezd a kamerát a böngésző beállításaiban.'
        : 'A kamera nem indítható el ezen az eszközön.');
      setCameraState('error');
    }
  };

  useEffect(() => {
    startCamera();
    return () => {
      recordingRef.current = false;
      stopStream();
    };
  }, []);

  useEffect(() => {
    const handleOrientation = (event) => {
      if (event.beta == null || event.gamma == null) return;

      const heading = event.webkitCompassHeading ?? event.alpha ?? 0;

      if (recordingRef.current) {
        sensorDataRef.current.push({
          time: Date.now() - startedAtRef.current,
          alpha: heading,
          beta: event.beta,
          gamma: event.gamma,
        });

        if (headingRef.current.last !== null) {
          let delta = heading - headingRef.current.last;
          if (delta > 180) delta -= 360;
          if (delta < -180) delta += 360;
          if (Math.abs(delta) <= 35) {
            headingRef.current.unwrapped += delta;
            headingRef.current.maximum = Math.max(
              headingRef.current.maximum,
              Math.abs(headingRef.current.unwrapped),
            );
          }
        }
        headingRef.current.last = heading;
      }

      const now = Date.now();
      if (now - lastOrientationUpdateRef.current > 120) {
        setOrientation({ beta: event.beta, gamma: event.gamma, available: true });
        if (recordingRef.current) {
          setRotationCoverage(Math.min(headingRef.current.maximum / 340, 1));
        }
        lastOrientationUpdateRef.current = now;
      }
    };

    window.addEventListener('deviceorientation', handleOrientation);
    return () => window.removeEventListener('deviceorientation', handleOrientation);
  }, []);

  useEffect(() => {
    const sampleLighting = () => {
      const video = videoRef.current;
      if (!video || video.readyState < 2 || !video.videoWidth) return;

      const canvas = qualityCanvasRef.current || document.createElement('canvas');
      qualityCanvasRef.current = canvas;
      canvas.width = 96;
      canvas.height = 54;
      const context = canvas.getContext('2d', { willReadFrequently: true });
      if (!context) return;
      context.drawImage(video, 0, 0, canvas.width, canvas.height);
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      let luminance = 0;
      for (let index = 0; index < pixels.length; index += 16) {
        luminance += pixels[index] * 0.2126 + pixels[index + 1] * 0.7152 + pixels[index + 2] * 0.0722;
      }
      const average = luminance / (pixels.length / 16);
      setLighting(average < 48 ? 'dark' : average > 215 ? 'bright' : 'good');
    };

    const timer = window.setInterval(sampleLighting, 800);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!isRecording) return undefined;
    const timer = window.setInterval(() => {
      const elapsed = Math.floor((Date.now() - startedAtRef.current) / 1000);
      setRecordingTime(elapsed);
      if (elapsed === MIN_RECOMMENDED_SECONDS) setCameraError('');
      if (elapsed >= MAX_SECONDS && recorderRef.current?.state === 'recording') {
        recorderRef.current.stop();
        recordingRef.current = false;
        setIsRecording(false);
      }
    }, 250);
    return () => window.clearInterval(timer);
  }, [isRecording]);

  const requestOrientationPermission = async () => {
    if (typeof window.DeviceOrientationEvent?.requestPermission !== 'function') return;
    try {
      await window.DeviceOrientationEvent.requestPermission();
    } catch {
      // Szenzor nélkül is készíthető jó, időalapú képkockaválasztás.
    }
  };

  const startRecording = async () => {
    if (!streamRef.current || cameraState !== 'ready') return;
    await requestOrientationPermission();

    chunksRef.current = [];
    sensorDataRef.current = [];
    headingRef.current = { last: null, unwrapped: 0, maximum: 0 };
    setCameraError('');
    startedAtRef.current = Date.now();
    setRecordingTime(0);
    setRotationCoverage(0);

    try {
      const recorder = new MediaRecorder(streamRef.current, getRecorderOptions());
      recorder.ondataavailable = (event) => {
        if (event.data?.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        recordingRef.current = false;
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'video/webm' });
        if (blob.size > 0) onVideoRecorded(blob, sensorDataRef.current);
        else setCameraError('A felvétel üres lett. Kérlek, próbáld újra.');
      };
      recorder.onerror = () => {
        recordingRef.current = false;
        setIsRecording(false);
        setCameraError('A videórögzítés váratlanul megszakadt.');
      };
      recorderRef.current = recorder;
      recorder.start(1000);
      recordingRef.current = true;
      setIsRecording(true);
      navigator.vibrate?.([45, 35, 45]);
    } catch {
      setCameraError('A böngésző nem tudta elindítani a videórögzítést.');
    }
  };

  const stopRecording = () => {
    if (recordingTime < MIN_RECOMMENDED_SECONDS) {
      setCameraError(`Folytasd még ${MIN_RECOMMENDED_SECONDS - recordingTime} másodpercig a teljes körhöz.`);
      navigator.vibrate?.(40);
      return;
    }
    if (orientation.available && rotationCoverage > 0.05 && rotationCoverage < 0.82 && recordingTime < 40) {
      setCameraError(`A kör még csak ${Math.round(rotationCoverage * 100)}%-os. Folytasd a kezdőpontig.`);
      navigator.vibrate?.(40);
      return;
    }
    if (recorderRef.current?.state === 'recording') {
      recorderRef.current.stop();
      recordingRef.current = false;
      setIsRecording(false);
      navigator.vibrate?.(80);
    }
  };

  const isLevel = !orientation.available
    || (Math.abs(orientation.beta - 90) < 9 && Math.abs(orientation.gamma) < 7);
  const sensorTracking = orientation.available && rotationCoverage > 0.05;
  const orbitProgress = sensorTracking ? rotationCoverage : Math.min(recordingTime / IDEAL_SECONDS, 1);
  const canFinish = recordingTime >= MIN_RECOMMENDED_SECONDS
    && (!sensorTracking || rotationCoverage >= 0.82 || recordingTime >= 40);
  const lightingMessage = lighting === 'dark'
    ? 'Túl sötét – keress egyenletesebb fényt'
    : lighting === 'bright'
      ? 'Túl világos – kerüld a közvetlen ellenfényt'
      : null;
  const captureHealthy = isLevel && !lightingMessage;

  return (
    <main className="camera-shell">
      <video ref={videoRef} autoPlay playsInline muted className="camera-feed" />
      <div className="camera-vignette" />

      <header className="camera-topbar">
        <button className="glass-icon" onClick={onCancel} disabled={isRecording} aria-label="Vissza">
          <ArrowLeft size={20} />
        </button>
        <div className="camera-id"><small>Aktív jármű</small><strong>{vehicleId}</strong></div>
        <div className={`level-chip ${captureHealthy ? 'level-ok' : 'level-warn'}`}>
          <span /> {lightingMessage || (orientation.available ? (isLevel ? 'Minőség rendben' : 'Tartsd egyenesen') : 'Automatikus mód')}
        </div>
      </header>

      <div className={`capture-frame ${captureHealthy ? '' : 'capture-frame-warn'}`} aria-hidden="true">
        <i className="corner corner-tl" /><i className="corner corner-tr" />
        <i className="corner corner-bl" /><i className="corner corner-br" />
        <div className="horizon"><span /></div>
      </div>

      <section className="camera-guide">
        <p className="camera-instruction">
          {isRecording
            ? (lightingMessage || (canFinish
              ? 'Érj vissza a kezdőponthoz, majd állítsd le'
              : 'Haladj lassan; hagyj helyet az autó körül, és kerüld más járművek átfedését'))
            : 'Az egész autó maradjon a jelölésen belül, másik jármű ne takarja'}
        </p>
        {cameraError && <p className="camera-error">{cameraError}</p>}
      </section>

      <footer className="camera-controls">
        {cameraState === 'error' ? (
          <button className="camera-retry" onClick={startCamera}><RotateCcw size={19} /> Kamera újraindítása</button>
        ) : (
          <>
            <div className="record-meta">
              <span>{isRecording ? `${String(Math.floor(recordingTime / 60)).padStart(2, '0')}:${String(recordingTime % 60).padStart(2, '0')}` : '00:00'}</span>
              <small>{isRecording ? `${Math.round(orbitProgress * 100)}% ${sensorTracking ? 'kör lefedve' : 'ajánlott köridő'}` : '30–40 másodperc'}</small>
            </div>
            <button
              className={`record-button ${isRecording ? 'recording' : ''}`}
              onClick={isRecording ? stopRecording : startRecording}
              disabled={cameraState !== 'ready'}
              aria-label={isRecording ? 'Felvétel leállítása' : 'Felvétel indítása'}
              style={{ '--orbit-progress': `${orbitProgress * 360}deg` }}
            >
              <span>{isRecording ? <Square size={24} fill="currentColor" /> : <Camera size={27} />}</span>
            </button>
            <div className="record-quality">
              {canFinish ? <Check size={18} /> : <span className="quality-dot" />}
              <small>{canFinish ? 'Elegendő anyag' : '1080p · 36 nézet'}</small>
            </div>
          </>
        )}
      </footer>
    </main>
  );
}
