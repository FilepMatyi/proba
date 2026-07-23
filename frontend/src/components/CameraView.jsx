import { useEffect, useRef, useState } from 'react';

function CameraView({ isLevel, onCapture, currentIndex, totalPhotos }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [stream, setStream] = useState(null);

  useEffect(() => {
    startCamera();

    return () => {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const startCamera = async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: 'environment',
          width: { ideal: 1920 },
          height: { ideal: 1080 }
        }
      });

      setStream(mediaStream);
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
    } catch (error) {
      console.error('Camera access error:', error);
    }
  };

  const handleCapture = () => {
    try {
      if (!videoRef.current || !canvasRef.current || !isLevel) {
        return;
      }

      const video = videoRef.current;
      const canvas = canvasRef.current;

      // Use actual video dimensions to preserve the camera's native aspect ratio.
      const videoWidth = video.videoWidth;
      const videoHeight = video.videoHeight;

      // Scale to max 1920px on the longest side while preserving aspect ratio
      const MAX_DIMENSION = 1920;
      let targetWidth = videoWidth;
      let targetHeight = videoHeight;

      if (targetWidth > MAX_DIMENSION || targetHeight > MAX_DIMENSION) {
        const scale = MAX_DIMENSION / Math.max(targetWidth, targetHeight);
        targetWidth = Math.round(targetWidth * scale);
        targetHeight = Math.round(targetHeight * scale);
      }

      canvas.width = targetWidth;
      canvas.height = targetHeight;

      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, targetWidth, targetHeight);

      canvas.toBlob((blob) => {
        if (!blob) {
          throw new Error("Canvas toBlob failed - Blob is null");
        }
        onCapture(blob);
      }, 'image/jpeg', 0.92);
    } catch (error) {
      alert(`Capture Error: ${error.message}`);
      console.error('Capture error:', error);
    }
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '100dvh', touchAction: 'none' }}>
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

      {/* Distance advisory — static, always visible */}
      <div style={{
        position: 'absolute',
        top: '75px',
        left: '50%',
        transform: 'translateX(-50%)',
        backgroundColor: 'rgba(0, 0, 0, 0.55)',
        color: '#fff',
        fontSize: '13px',
        fontWeight: '500',
        padding: '6px 16px',
        borderRadius: '20px',
        whiteSpace: 'nowrap',
        textAlign: 'center',
        zIndex: 100,
        backdropFilter: 'blur(6px)',
        letterSpacing: '0.01em',
      }}>
        📏 Állj 3–4 méterre az autótól
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
          opacity: 0.3,
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

      {/* Photo counter */}
      <div
        style={{
          position: 'absolute',
          top: '120px',
          left: '50%',
          transform: 'translateX(-50%)',
          color: '#fff',
          fontSize: '16px',
          fontWeight: 'bold',
          textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
          backgroundColor: 'rgba(0,0,0,0.5)',
          padding: '8px 16px',
          borderRadius: '20px'
        }}
      >
        {currentIndex + 1} / {totalPhotos}
      </div>

      {/* Shutter button */}
      <button
        onClick={handleCapture}
        disabled={!isLevel}
        style={{
          position: 'absolute',
          bottom: '40px',
          left: '50%',
          transform: 'translateX(-50%)',
          width: '80px',
          height: '80px',
          borderRadius: '50%',
          backgroundColor: isLevel ? '#4CAF50' : 'rgba(255,255,255,0.3)',
          border: isLevel ? '4px solid #4CAF50' : '4px solid rgba(255,255,255,0.5)',
          cursor: isLevel ? 'pointer' : 'not-allowed',
          transition: 'all 0.2s'
        }}
      />

      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}

export default CameraView;
