import React from 'react';

function DistanceGuide({ detected, relativeHeight, isDistanceGood }) {
  if (!detected) {
    return (
      <div style={containerStyle}>
        <div style={{ ...barStyle, backgroundColor: '#555' }} />
        <div style={textStyle}>Autó keresése...</div>
      </div>
    );
  }

  // relativeHeight is: currentHeight / referenceHeight
  // Ideal is 1.0. Let's map it to a visual offset.
  // We'll show a needle/indicator on a range of 0.7 to 1.3
  const minRange = 0.7;
  const maxRange = 1.3;
  const clampedVal = Math.max(minRange, Math.min(maxRange, relativeHeight));
  const percent = ((clampedVal - minRange) / (maxRange - minRange)) * 100;

  let color = '#ff9800'; // Sárga (Túl távol)
  let statusText = 'Lépj közelebb!';

  if (isDistanceGood) {
    color = '#4CAF50'; // Zöld (Tökéletes)
    statusText = 'Tökéletes távolság, exponálj!';
  } else if (relativeHeight > 1.05) {
    color = '#f44336'; // Piros (Túl közel)
    statusText = 'Lépj hátra!';
  }

  return (
    <div style={containerStyle}>
      <div style={barBackgroundStyle}>
        {/* Safe zone indicator (0.95 to 1.05) */}
        <div style={safeZoneStyle} />
        {/* Current position indicator */}
        <div style={{ ...needleStyle, left: `${percent}%`, backgroundColor: color }} />
      </div>
      <div style={{ ...textStyle, color }}>
        {statusText} ({Math.round(relativeHeight * 100)}%)
      </div>
    </div>
  );
}

const containerStyle = {
  position: 'fixed',
  top: '75px', // Below Waterpass which is at top: 20px + height: 10px + text: 20px
  left: '50%',
  transform: 'translateX(-50%)',
  width: '80%',
  zIndex: 100,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: '8px',
};

const barBackgroundStyle = {
  position: 'relative',
  width: '100%',
  height: '10px',
  backgroundColor: '#333',
  borderRadius: '5px',
  overflow: 'visible',
};

const barStyle = {
  width: '100%',
  height: '100%',
  borderRadius: '5px',
};

const safeZoneStyle = {
  position: 'absolute',
  left: '41.67%', // (0.95 - 0.7) / (1.3 - 0.7) = 0.25 / 0.6 = 41.67%
  width: '16.67%', // (1.05 - 0.95) / 0.6 = 0.1 / 0.6 = 16.67%
  height: '100%',
  backgroundColor: 'rgba(76, 175, 80, 0.3)',
  borderLeft: '1px dashed rgba(76, 175, 80, 0.8)',
  borderRight: '1px dashed rgba(76, 175, 80, 0.8)',
};

const needleStyle = {
  position: 'absolute',
  top: '-4px',
  width: '6px',
  height: '18px',
  borderRadius: '3px',
  transform: 'translateX(-50%)',
  transition: 'left 0.2s ease-out, background-color 0.2s',
  boxShadow: '0 2px 4px rgba(0,0,0,0.5)',
};

const textStyle = {
  fontSize: '14px',
  fontWeight: 'bold',
  textShadow: '1px 1px 2px rgba(0,0,0,0.8)',
  whiteSpace: 'nowrap',
  transition: 'color 0.2s',
};

export default DistanceGuide;
