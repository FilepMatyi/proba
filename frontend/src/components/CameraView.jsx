import { useEffect, useRef, useState } from 'react';

function CameraView({ onVideoRecorded }) {
  const videoRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const recordedChunks = useRef([]);
  const [stream, setStream] = useState(null);
  const [isRecording, setIsRecording] = useState(false);
  const [recordingTime, setRecordingTime] = useState(0);

  useEffect(() => {
    initCamera();
    return () => stopCurrentStream();
  }, []);

  useEffect(() => {
    let interval;
    if (isRecording) {
      interval = setInterval(() => {
        setRecordingTime((prev) => prev + 1);
      }, 1000);
    } else {
      setRecordingTime(0);
      clearInterval(interval);
    }
    return () => clearInterval(interval);
  }, [isRecording]);

  const stopCurrentStream = () => {
    if (videoRef.current && videoRef.current.srcObject) {
      videoRef.current.srcObject.getTracks().forEach(track => track.stop());
    }
  };

  const initCamera = async () => {
    try {
      stopCurrentStream();
      // Request rear camera with 4K or 1080p 60fps ideally
      const constraints = {
        video: {
          facingMode: 'environment',
          width: { ideal: 1920 },
          height: { ideal: 1080 },
          frameRate: { ideal: 60, min: 30 }
        }
      };

      const mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
      setStream(mediaStream);
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
    } catch (error) {
      console.error('Camera start error:', error);
      alert('Kamera hiba: ' + error.message);
    }
  };

  const startRecording = () => {
    if (!stream) return;
    recordedChunks.current = [];
    
    let options = { videoBitsPerSecond: 8000000 }; // 8 Mbps high quality
    let mimeType = '';
    if (MediaRecorder.isTypeSupported('video/webm;codecs=vp9')) {
      mimeType = 'video/webm;codecs=vp9';
    } else if (MediaRecorder.isTypeSupported('video/webm')) {
      mimeType = 'video/webm';
    } else if (MediaRecorder.isTypeSupported('video/mp4')) {
      mimeType = 'video/mp4';
    }
    
    if (mimeType) {
      options.mimeType = mimeType;
    }

    try {
      const mediaRecorder = new MediaRecorder(stream, options);

      mediaRecorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          recordedChunks.current.push(event.data);
        }
      };

      mediaRecorder.onstop = () => {
        const blob = new Blob(recordedChunks.current, { type: mediaRecorder.mimeType });
        onVideoRecorded(blob);
      };

      mediaRecorderRef.current = mediaRecorder;
      mediaRecorder.start(1000); // collect 1s chunks
      setIsRecording(true);
      
      if (navigator.vibrate) navigator.vibrate([50, 50, 50]);
    } catch (e) {
      console.error('MediaRecorder start error:', e);
      alert('Nem sikerült elindítani a felvételt.');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
      setIsRecording(false);
      if (navigator.vibrate) navigator.vibrate(100);
    }
  };

  const formatTime = (sec) => {
    const m = Math.floor(sec / 60).toString().padStart(2, '0');
    const s = (sec % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '100dvh', touchAction: 'none', backgroundColor: '#000' }}>
      
      {/* Recording Indicator */}
      {isRecording && (
        <div style={{
          position: 'absolute', top: '20px', left: '20px', zIndex: 100,
          display: 'flex', alignItems: 'center', gap: '8px',
          backgroundColor: 'rgba(0,0,0,0.6)', padding: '6px 12px', borderRadius: '20px'
        }}>
          <div style={{
            width: '12px', height: '12px', backgroundColor: 'red', borderRadius: '50%',
            animation: 'pulse 1s infinite'
          }} />
          <span style={{ color: 'white', fontWeight: 'bold', fontFamily: 'monospace', fontSize: '16px' }}>
            {formatTime(recordingTime)}
          </span>
          <style>
            {`@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }`}
          </style>
        </div>
      )}

      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'cover'
        }}
      />

      <div style={{
        position: 'absolute',
        top: '80px',
        left: '50%',
        transform: 'translateX(-50%)',
        backgroundColor: 'rgba(0, 0, 0, 0.55)',
        color: '#fff',
        fontSize: '14px',
        fontWeight: '500',
        padding: '10px 20px',
        borderRadius: '20px',
        whiteSpace: 'nowrap',
        textAlign: 'center',
        zIndex: 100,
        backdropFilter: 'blur(6px)'
      }}>
        {isRecording 
          ? "Sétálj körbe stabilan! (Kb 30-40 másodperc)" 
          : "Nyomd meg a piros gombot és sétálj körbe!"}
      </div>
      
      {/* Car silhouette overlay */}
      <svg
        viewBox="0 0 200 100"
        style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          width: '80%',
          height: 'auto',
          opacity: 0.2,
          pointerEvents: 'none'
        }}
      >
        <path
          d="M 20 50 L 30 30 L 70 25 L 130 25 L 170 30 L 180 50 L 180 70 L 170 75 L 150 75 L 145 65 L 55 65 L 50 75 L 30 75 L 20 70 Z"
          fill="none"
          stroke="white"
          strokeWidth="2"
        />
        <circle cx="45" cy="75" r="12" fill="none" stroke="white" strokeWidth="2" />
        <circle cx="155" cy="75" r="12" fill="none" stroke="white" strokeWidth="2" />
      </svg>

      {/* Record Button */}
      <button
        onClick={isRecording ? stopRecording : startRecording}
        style={{
          position: 'absolute',
          bottom: '50px',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '80px',
          height: '80px',
          borderRadius: '50%',
          backgroundColor: 'transparent',
          border: '4px solid white',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 100
        }}
      >
        <div style={{ 
          width: isRecording ? '30px' : '60px', 
          height: isRecording ? '30px' : '60px', 
          backgroundColor: 'red', 
          borderRadius: isRecording ? '4px' : '50%',
          transition: 'all 0.2s ease'
        }} />
      </button>

    </div>
  );
}

export default CameraView;
