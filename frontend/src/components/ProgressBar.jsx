function ProgressBar({ uploadedCount, totalPhotos }) {
  const progress = (uploadedCount / totalPhotos) * 100;

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '140px',
        left: '50%',
        transform: 'translateX(-50%)',
        width: '80%',
        maxWidth: '400px'
      }}
    >
      <div
        style={{
          width: '100%',
          height: '8px',
          backgroundColor: 'rgba(255,255,255,0.3)',
          borderRadius: '4px',
          overflow: 'hidden'
        }}
      >
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            backgroundColor: '#4CAF50',
            transition: 'width 0.3s ease'
          }}
        />
      </div>
      <div
        style={{
          textAlign: 'center',
          color: '#fff',
          fontSize: '14px',
          marginTop: '8px',
          textShadow: '1px 1px 2px rgba(0,0,0,0.8)'
        }}
      >
        Uploaded: {uploadedCount} / {totalPhotos}
      </div>
    </div>
  );
}

export default ProgressBar;
