const fs = require('fs');
const path = require('path');

// Simple SVG generation for PWA icons
function generateSVG(size, color) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">
  <rect width="${size}" height="${size}" fill="${color}"/>
  <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="Arial" font-size="${size/4}" fill="white">VS</text>
</svg>`;
}

// Generate icons
const iconsDir = path.join(__dirname, 'public', 'icons');
const sizes = [192, 512];
const color = '#000000'; // Black background

sizes.forEach(size => {
  const svg = generateSVG(size, color);
  const svgPath = path.join(iconsDir, `icon-${size}.svg`);
  fs.writeFileSync(svgPath, svg);
  console.log(`Generated ${svgPath}`);
});

console.log('SVG icons generated. Convert to PNG using online tool or ImageMagick:');
console.log('  convert public/icons/icon-192.svg public/icons/icon-192.png');
console.log('  convert public/icons/icon-512.svg public/icons/icon-512.png');
