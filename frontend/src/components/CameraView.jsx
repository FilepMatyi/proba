import { useEffect, useRef, useState } from 'react';

function CameraView({ isLevel, onCapture, onRetake, autoCaptureSignal, currentIndex, totalPhotos }) {
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const [stream, setStream] = useState(null);
  const [videoDevices, setVideoDevices] = useState([]);
  const [activeDeviceIndex, setActiveDeviceIndex] = useState(0);
  const [lastPhotoUrl, setLastPhotoUrl] = useState(null);
  const [flash, setFlash] = useState(false);

  // Watch for auto-capture signal
  useEffect(() => {
    if (autoCaptureSignal > 0) {
      handleCapture();
    }
  }, [autoCaptureSignal]);

  useEffect(() => {
    initCameras();
    return () => stopCurrentStream();
  }, []);

  const stopCurrentStream = () => {
    if (videoRef.current && videoRef.current.srcObject) {
      videoRef.current.srcObject.getTracks().forEach(track => track.stop());
    }
  };

  const initCameras = async () => {
    try {
      // First request basic environment camera to get permissions
      // which allows enumerateDevices to see labels.
      let mediaStream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' }
      });
      
      const devices = await navigator.mediaDevices.enumerateDevices();
      const vDevices = devices.filter(d => d.kind === 'videoinput');
      
      // Try to filter out front cameras, keep rear/ultra-wide ones
      let rearCameras = vDevices.filter(d => 
        !d.label.toLowerCase().includes('front') && 
        !d.label.toLowerCase().includes('user')
      );
      
      // Fallback if filtering removed everything
      if (rearCameras.length === 0) {
        rearCameras = vDevices;
      }
      
      setVideoDevices(rearCameras);
      
      // Stop the initial stream as we will start a specific device stream
      mediaStream.getTracks().forEach(track => track.stop());
      
      if (rearCameras.length > 0) {
        startCamera(rearCameras[0].deviceId);
      } else {
        // Ultimate fallback
        startCamera(null);
      }
    } catch (error) {
      console.error('Camera init error:', error);
      // Fallback to default environment camera
      startCamera(null);
    }
  };

  const startCamera = async (deviceId) => {
    stopCurrentStream();
    
    const constraints = {
      video: {
        width: { ideal: 1920 },
        height: { ideal: 1080 }
      }
    };
    
    if (deviceId) {
      constraints.video.deviceId = { exact: deviceId };
    } else {
      constraints.video.facingMode = 'environment';
    }

    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia(constraints);
      setStream(mediaStream);
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
    } catch (error) {
      console.error('Camera start error:', error);
    }
  };

  const switchCamera = () => {
    if (videoDevices.length <= 1) return;
    const nextIndex = (activeDeviceIndex + 1) % videoDevices.length;
    setActiveDeviceIndex(nextIndex);
    startCamera(videoDevices[nextIndex].deviceId);
  };

  const handleCapture = () => {
    try {
      if (!videoRef.current || !canvasRef.current || !isLevel) {
        return;
      }

      const video = videoRef.current;
      const canvas = canvasRef.current;

      const videoWidth = video.videoWidth;
      const videoHeight = video.videoHeight;

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
        
        // Show flash animation & vibrate
        setFlash(true);
        setTimeout(() => setFlash(false), 300);
        if (navigator.vibrate) navigator.vibrate(50);
        
        // Create object URL for preview
        const url = URL.createObjectURL(blob);
        setLastPhotoUrl(url);
        
        onCapture(blob);
      }, 'image/jpeg', 0.97);
    } catch (error) {
      alert(`Capture Error: ${error.message}`);
      console.error('Capture error:', error);
    }
  };

  const handleRetakeClick = () => {
    setLastPhotoUrl(null);
    if (onRetake) onRetake();
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '100dvh', touchAction: 'none' }}>
      {/* Flash overlay */}
      <div style={{
        position: 'absolute',
        top: 0, left: 0, right: 0, bottom: 0,
        backgroundColor: 'white',
        opacity: flash ? 0.8 : 0,
        pointerEvents: 'none',
        transition: 'opacity 0.1s',
        zIndex: 200
      }} />

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
      
      {/* Camera Switcher Button */}
      {videoDevices.length > 1 && (
        <button
          onClick={switchCamera}
          style={{
            position: 'absolute',
            top: '70px',
            right: '20px',
            width: '44px',
            height: '44px',
            borderRadius: '50%',
            backgroundColor: 'rgba(0,0,0,0.5)',
            border: '2px solid rgba(255,255,255,0.3)',
            color: 'white',
            fontSize: '18px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            zIndex: 100,
            backdropFilter: 'blur(5px)'
          }}
          title="Kamera váltás"
        >
          🔄
        </button>
      )}

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
        {currentIndex === 0 ? "FOTÓZZ EGYET INDULÁSHOZ" : `${currentIndex} / ${totalPhotos}`}
      </div>

      {/* Shutter button (Only show for first photo, then hide or disable, actually keep it for manual override) */}
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
          transition: 'all 0.2s',
          zIndex: 100
        }}
      />

      {/* Last photo preview and Retake button */}
      {lastPhotoUrl && currentIndex > 0 && (
        <div style={{
          position: 'absolute',
          bottom: '40px',
          left: '20px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '8px',
          zIndex: 100
        }}>
          <img 
            src={lastPhotoUrl} 
            alt="Utolsó fotó" 
            style={{
              width: '60px', 
              height: '80px', 
              objectFit: 'cover', 
              borderRadius: '8px',
              border: '2px solid white',
              boxShadow: '0 4px 12px rgba(0,0,0,0.5)'
            }} 
          />
          <button 
            onClick={handleRetakeClick}
            style={{
              backgroundColor: 'rgba(244, 67, 54, 0.9)',
              color: 'white',
              border: 'none',
              borderRadius: '12px',
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: 'bold',
              cursor: 'pointer',
              backdropFilter: 'blur(4px)'
            }}
          >
            ↻ Újra
          </button>
        </div>
      )}

      <canvas ref={canvasRef} style={{ display: 'none' }} />
    </div>
  );
}

export default CameraView;
