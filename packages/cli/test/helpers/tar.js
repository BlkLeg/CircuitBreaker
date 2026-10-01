import { gzipSync } from 'node:zlib';

// Minimal ustar writer for fixtures: one 512-byte header per entry, then data
// padded to 512, then two zero blocks. type: '0' file, '5' dir, '2' symlink,
// '1' hardlink, '3' char device.
export function makeTarGz(entries) {
  const blocks = [];
  for (const { name, type = '0', data = Buffer.alloc(0), linkname = '' } of entries) {
    const header = Buffer.alloc(512);
    header.write(name, 0, 100, 'utf8');
    header.write('0000644\0', 100);
    header.write('0000000\0', 108);
    header.write('0000000\0', 116);
    header.write(data.length.toString(8).padStart(11, '0') + '\0', 124);
    header.write('00000000000\0', 136);
    header.write('        ', 148);
    header.write(type, 156);
    header.write(linkname, 157, 100, 'utf8');
    header.write('ustar\0', 257);
    header.write('00', 263);
    let sum = 0;
    for (const byte of header) sum += byte;
    header.write(sum.toString(8).padStart(6, '0') + '\0 ', 148);
    blocks.push(header, data, Buffer.alloc((512 - (data.length % 512)) % 512));
  }
  blocks.push(Buffer.alloc(1024));
  return gzipSync(Buffer.concat(blocks));
}
