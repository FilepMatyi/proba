const DATABASE = 'vehicleshoot-guided-studio';
const STORE = 'photos';

function openDatabase() {
  if (!globalThis.indexedDB) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function transaction(mode, action) {
  const database = await openDatabase();
  if (!database) return null;
  try {
    return await new Promise((resolve, reject) => {
      const operation = action(database.transaction(STORE, mode).objectStore(STORE));
      operation.onsuccess = () => resolve(operation.result);
      operation.onerror = () => reject(operation.error);
    });
  } finally {
    database.close();
  }
}

export const saveDraftPhoto = (vehicleId, sector, photo) =>
  transaction('readwrite', (store) => store.put(photo, `${vehicleId}:${sector}`));

export async function loadDraftPhotos(vehicleId) {
  const photos = [];
  for (let sector = 1; sector <= 10; sector++) {
    photos.push(await transaction('readonly', (store) => store.get(`${vehicleId}:${sector}`)) || null);
  }
  return photos;
}

export async function clearDraftPhotos(vehicleId) {
  for (let sector = 1; sector <= 10; sector++) {
    await transaction('readwrite', (store) => store.delete(`${vehicleId}:${sector}`));
  }
}
