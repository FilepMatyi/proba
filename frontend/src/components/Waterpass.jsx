import { useState, useEffect } from 'react';

function Waterpass({ onLevelChange }) {
  const [isLevel, setIsLevel] = useState(false);
  const [beta, setBeta] = useState(0);
  const [permissionGranted, setPermissionGranted] = useState(false);
  const [needsPermission, setNeedsPermission] = useState(false);

  useEffect(() => {
    // Check if device orientation is supported
    if (!window.DeviceOrientationEvent) {
      console.log('Device orientation not supported');
      return;
    }

    // iOS 13+ requires permission request
    if (typeof DeviceOrientationEvent.requestPermission === 'function') {
      setNeedsPermission(true);
    } else {
      setPermissionGranted(true);
      startListening();
    }

    return () => {
      if (permissionGranted) {
        window.removeEventListener('deviceorientation', handleOrientation);
      }
    };
  }, [permissionGranted]);

  const requestPermission = async () => {
    try {
      const permission = await DeviceOrientationEvent.requestPermission();
      if (permission === 'granted') {
        setPermissionGranted(true);
        setNeedsPermission(false);
        startListening();
      }
    } catch (error) {
      console.error('Permission denied:', error);
    }
  };

  const startListening = () => {
    window.addEventListener('deviceorientation', handleOrientation);
  };

  const handleOrientation = (event) => {
    if (event.beta !== null) {
      const betaValue = event.beta;
      setBeta(betaValue);

      // Check if device is level (within ±5 degrees of horizontal)
      const level = Math.abs(betaValue) < 5;
      setIsLevel(level);
      onLevelChange(level);
    }
  };

  if (needsPermission) {
    return (
      <button
        onClick={requestPermission}
        style={{
          position: 'fixed',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          padding: '20px 40px',
          fontSize: '18px',
          backgroundColor: '#000',
          color: '#fff',
          border: 'none',
          borderRadius: '10px',
          zIndex: 1000
        }}
      >
        Enable Gyroscope
      </button>
    );
  }

  return (
    <div
      style={{
        position: 'fixed',
        top: '20px',
        left: '50%',
        transform: 'translateX(-50%)',
        width: '80%',
        height: '10px',
        backgroundColor: '#333',
        borderRadius: '5px',
        zIndex: 100
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          backgroundColor: isLevel ? '#4CAF50' : '#f44336',
          borderRadius: '5px',
          transition: 'background-color 0.2s'
        }}
      />
      <div
        style={{
          position: 'absolute',
          top: '-25px',
          left: '50%',
          transform: 'translateX(-50%)',
          color: '#fff',
          fontSize: '14px',
          fontWeight: 'bold',
          textShadow: '1px 1px 2px rgba(0,0,0,0.8)'
        }}
      >
        {isLevel ? 'LEVEL' : `${beta.toFixed(1)}°`}
      </div>
    </div>
  );
}

export default Waterpass;
