const fs = require('fs');
const path = require('path');

// 创建一个简单的 256x256 PNG 图标
// 这是最小的有效 PNG 文件结构

function createSimpleIcon() {
    const size = 256;
    const iconPath = path.join(__dirname, 'icon.png');

    // 创建一个简单的单色 PNG
    // PNG 文件头 + IHDR + IDAT + IEND
    const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);

    // IHDR chunk
    const width = size;
    const height = size;
    const bitDepth = 8;
    const colorType = 2; // RGB
    const compression = 0;
    const filter = 0;
    const interlace = 0;

    const ihdrData = Buffer.alloc(13);
    ihdrData.writeUInt32BE(width, 0);
    ihdrData.writeUInt32BE(height, 4);
    ihdrData.writeUInt8(bitDepth, 8);
    ihdrData.writeUInt8(colorType, 9);
    ihdrData.writeUInt8(compression, 10);
    ihdrData.writeUInt8(filter, 11);
    ihdrData.writeUInt8(interlace, 12);

    const ihdrChunk = createChunk('IHDR', ihdrData);

    // 创建简单的渐变图像数据
    const rawData = [];
    for (let y = 0; y < height; y++) {
        rawData.push(0); // filter byte
        for (let x = 0; x < width; x++) {
            // 创建渐变: 从 #00d4ff 到 #a855f7
            const t = (x + y) / (width + height);
            const r = Math.floor(0 + t * (168 - 0));
            const g = Math.floor(212 + t * (85 - 212));
            const b = Math.floor(255 + t * (247 - 255));
            rawData.push(r, g, b);
        }
    }

    const zlib = require('zlib');
    const compressed = zlib.deflateSync(Buffer.from(rawData));
    const idatChunk = createChunk('IDAT', compressed);

    // IEND chunk
    const iendChunk = createChunk('IEND', Buffer.alloc(0));

    const png = Buffer.concat([PNG_SIGNATURE, ihdrChunk, idatChunk, iendChunk]);

    fs.writeFileSync(iconPath, png);
    console.log('图标已创建:', iconPath);
}

function createChunk(type, data) {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(data.length, 0);

    const typeBuffer = Buffer.from(type, 'ascii');
    const crcData = Buffer.concat([typeBuffer, data]);

    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(crcData), 0);

    return Buffer.concat([length, typeBuffer, data, crc]);
}

// CRC32 计算
function crc32(data) {
    let crc = 0xFFFFFFFF;
    const table = [];

    for (let i = 0; i < 256; i++) {
        let c = i;
        for (let j = 0; j < 8; j++) {
            c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        }
        table[i] = c;
    }

    for (let i = 0; i < data.length; i++) {
        crc = table[(crc ^ data[i]) & 0xFF] ^ (crc >>> 8);
    }

    return (crc ^ 0xFFFFFFFF) >>> 0;
}

createSimpleIcon();
