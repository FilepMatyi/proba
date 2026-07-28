import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Camera, CheckCircle, Clock, Copy, ExternalLink, Trash2, ArrowLeft } from 'lucide-react';

export default function Dashboard() {
  const navigate = useNavigate();
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [copiedId, setCopiedId] = useState(null);

  const fetchSessions = async () => {
    try {
      const response = await fetch('/api/sessions');
      if (response.ok) {
        const data = await response.json();
        setSessions(data);
      }
    } catch (error) {
      console.error('Error fetching sessions:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleDelete = async (vehicleId) => {
    if (!window.confirm(`Biztosan törlöd a(z) ${vehicleId} projektet?`)) return;
    try {
      await fetch(`/api/sessions/${vehicleId}`, { method: 'DELETE' });
      fetchSessions();
    } catch (error) {
      console.error('Error deleting:', error);
    }
  };

  const copyEmbedCode = (vehicleId) => {
    const baseUrl = window.location.origin;
    const code = `<div data-vs360-vehicle="${vehicleId}"></div>\n<script src="${baseUrl}/embed.js"></script>`;
    navigator.clipboard.writeText(code);
    setCopiedId(vehicleId);
    setTimeout(() => setCopiedId(null), 2000);
  };

  return (
    <div style={{
      minHeight: '100dvh',
      backgroundColor: '#000',
      color: '#fff',
      padding: '20px',
      fontFamily: 'system-ui, -apple-system, sans-serif'
    }}>
      <div style={{ maxWidth: '800px', margin: '0 auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '30px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
            <button
              onClick={() => navigate('/')}
              style={{
                background: 'transparent',
                border: '1px solid #333',
                color: '#fff',
                borderRadius: '8px',
                padding: '8px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
            >
              <ArrowLeft size={20} />
            </button>
            <h1 style={{ margin: 0 }}>Kereskedői Dashboard</h1>
          </div>
          <button
            onClick={() => navigate('/')}
            style={{
              backgroundColor: '#4CAF50',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '10px 20px',
              fontWeight: 'bold',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <Camera size={18} /> Új Fotózás
          </button>
        </div>

        {loading ? (
          <p style={{ textAlign: 'center', color: '#888' }}>Betöltés...</p>
        ) : sessions.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '50px', backgroundColor: '#111', borderRadius: '12px' }}>
            <Camera size={48} color="#444" style={{ marginBottom: '15px' }} />
            <h3>Még nincsenek autók</h3>
            <p style={{ color: '#888' }}>Kezdj el fotózni, hogy megjelenjenek itt.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
            {sessions.map(session => (
              <div key={session.vehicleId} style={{
                backgroundColor: '#111',
                border: '1px solid #222',
                borderRadius: '12px',
                padding: '20px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '15px'
              }}>
                <div style={{ flex: '1 1 200px' }}>
                  <h3 style={{ margin: '0 0 5px 0', fontSize: '18px' }}>{session.vehicleId}</h3>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', fontSize: '14px', color: '#888' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Clock size={14} />
                      {new Date(session.createdAt).toLocaleDateString()}
                    </span>
                    <span>•</span>
                    <span style={{
                      display: 'flex', alignItems: 'center', gap: '4px',
                      color: session.status === 'completed' ? '#4CAF50' : '#FF9800'
                    }}>
                      {session.status === 'completed' ? <CheckCircle size={14} /> : <Clock size={14} />}
                      {session.status === 'completed' ? 'Kész' : `${session.processedFrames}/${session.totalFrames} feldolgozva`}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: '10px' }}>
                  <button
                    onClick={() => copyEmbedCode(session.vehicleId)}
                    style={{
                      backgroundColor: 'transparent',
                      color: '#ddd',
                      border: '1px solid #333',
                      borderRadius: '6px',
                      padding: '8px 12px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      fontSize: '13px'
                    }}
                  >
                    {copiedId === session.vehicleId ? <CheckCircle size={16} color="#4CAF50" /> : <Copy size={16} />}
                    {copiedId === session.vehicleId ? 'Másolva!' : 'Embed kód'}
                  </button>
                  
                  {session.status === 'completed' && (
                    <a
                      href={`/viewer/${session.vehicleId}`}
                      target="_blank"
                      rel="noreferrer"
                      style={{
                        backgroundColor: '#2196F3',
                        color: '#fff',
                        textDecoration: 'none',
                        borderRadius: '6px',
                        padding: '8px 12px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontSize: '13px',
                        fontWeight: '500'
                      }}
                    >
                      <ExternalLink size={16} /> Nézőke
                    </a>
                  )}

                  <button
                    onClick={() => handleDelete(session.vehicleId)}
                    style={{
                      backgroundColor: 'transparent',
                      color: '#F44336',
                      border: '1px solid #333',
                      borderRadius: '6px',
                      padding: '8px',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center'
                    }}
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
