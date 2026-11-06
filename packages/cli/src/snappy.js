// Raw snappy block decoding (no framing), for GitHub attestation bundles: the
// attestations API answers with a bundle_url whose body is a snappy block, and
// Node core has no decoder. Format: a varint of the decoded length, then
// elements, each a literal run or a back-reference copy into the output so far.
// Anything malformed is a SnappyError; nothing partial is ever returned.

export class SnappyError extends Error {
  constructor(message) { super(`snappy: ${message}`); this.code = 'SNAPPY'; }
}

const DEFAULT_MAX_LENGTH = 16 * 1024 * 1024;

function readLength(input) {
  let value = 0;
  for (let i = 0; i < 5 && i < input.length; i += 1) {
    const byte = input[i];
    value += (byte & 0x7f) * 2 ** (7 * i);
    if ((byte & 0x80) === 0) {
      if (value > 0xffffffff) throw new SnappyError('decoded length does not fit in 32 bits');
      return { length: value, pos: i + 1 };
    }
  }
  throw new SnappyError('decoded length is missing or longer than 5 bytes');
}

function readLittleEndian(input, pos, count, what) {
  if (pos + count > input.length) throw new SnappyError(`${what} runs past the end of the input`);
  let value = 0;
  for (let i = 0; i < count; i += 1) value += input[pos + i] * 2 ** (8 * i);
  return value;
}

export function snappyDecode(input, { maxLength = DEFAULT_MAX_LENGTH } = {}) {
  const { length, pos: start } = readLength(input);
  if (length > maxLength) throw new SnappyError(`declared length ${length} exceeds the cap of ${maxLength} bytes`);
  const output = Buffer.alloc(length);
  let out = 0;
  let pos = start;
  while (pos < input.length) {
    const tag = input[pos];
    pos += 1;
    const kind = tag & 0b11;
    if (kind === 0b00) {
      let run = tag >> 2;
      if (run >= 60) {
        const extra = run - 59;
        run = readLittleEndian(input, pos, extra, 'literal length');
        pos += extra;
      }
      run += 1;
      if (pos + run > input.length) throw new SnappyError('literal runs past the end of the input');
      if (out + run > length) throw new SnappyError('output would run past the declared length');
      input.copy(output, out, pos, pos + run);
      out += run;
      pos += run;
      continue;
    }
    let run;
    let offset;
    if (kind === 0b01) {
      run = 4 + ((tag >> 2) & 0b111);
      offset = ((tag >> 5) << 8) | readLittleEndian(input, pos, 1, 'copy offset');
      pos += 1;
    } else {
      const width = kind === 0b10 ? 2 : 4;
      run = (tag >> 2) + 1;
      offset = readLittleEndian(input, pos, width, 'copy offset');
      pos += width;
    }
    if (offset === 0 || offset > out) throw new SnappyError(`copy offset ${offset} points outside the ${out} bytes decoded so far`);
    if (out + run > length) throw new SnappyError('output would run past the declared length');
    // Byte by byte: a copy may overlap the bytes it is producing (a repeated run).
    for (let i = 0; i < run; i += 1) output[out + i] = output[out - offset + i];
    out += run;
  }
  if (out !== length) throw new SnappyError(`decoded ${out} bytes, short of the declared length ${length}`);
  return output;
}
