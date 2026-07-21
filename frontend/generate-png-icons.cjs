const fs = require('fs');
const path = require('path');

// Create a simple solid color PNG (black square)
function createSolidColorPNG(width, height, r, g, b) {
  const pixelData = Buffer.alloc(width * height * 4);
  for (let i = 0; i < pixelData.length; i += 4) {
    pixelData[i] = r;     // Red
    pixelData[i + 1] = g; // Green
    pixelData[i + 2] = b; // Blue
    pixelData[i + 3] = 255; // Alpha
  }

  // PNG signature
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

  // IHDR chunk
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData.writeUInt8(8, 8); // bit depth
  ihdrData.writeUInt8(6, 9); // color type (RGBA)
  ihdrData.writeUInt8(0, 10); // compression
  ihdrData.writeUInt8(0, 11); // filter
  ihdrData.writeUInt8(0, 12); // interlace

  const ihdr = createChunk('IHDR', ihdrData);

  // IDAT chunk (simplified - no compression for MVP)
  const idatData = Buffer.concat([
    Buffer.from([0x78, 0x9c]), // zlib header
    Buffer.from([0x01]), // final block
    Buffer.from([0x00]), // no compression
    pixelData,
    Buffer.from([0x00, 0x00, 0xff, 0xff]) // adler32 (simplified)
  ]);
  const idat = createChunk('IDAT', idatData);

  // IEND chunk
  const iend = createChunk('IEND', Buffer.alloc(0));

  return Buffer.concat([signature, ihdr, idat, iend]);
}

function createChunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeBuffer = Buffer.from(type);
  const crc = calculateCRC(Buffer.concat([typeBuffer, data]));
  const crcBuffer = Buffer.alloc(4);
  crcBuffer.writeUInt32BE(crc, 0);
  return Buffer.concat([length, typeBuffer, data, crcBuffer]);
}

function calculateCRC(data) {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

// Generate icons
const iconsDir = path.join(__dirname, 'public', 'icons');
const sizes = [192, 512];

// Ensure directory exists
if (!fs.existsSync(iconsDir)) {
  fs.mkdirSync(iconsDir, { recursive: true });
}

sizes.forEach(size => {
  const png = createSolidColorPNG(size, size, 0, 0, 0); // Black
  const pngPath = path.join(iconsDir, `icon-${size}.png`);
  fs.writeFileSync(pngPath, png);
  console.log(`Generated ${pngPath}`);
});

console.log('PNG icons generated successfully!');
