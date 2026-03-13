/* eslint-disable security/detect-object-injection -- algorithm lookup tables */
/**
 * Minimal MD5 implementation used solely for Gravatar hash generation.
 * MD5 usage outside this Gravatar path is prohibited.
 * Public-domain algorithm (Ronald Rivest, RFC 1321).
 */

function md5(str) {
  function safeAdd(x, y) {
    const lsw = (x & 0xffff) + (y & 0xffff);
    const msw = (x >> 16) + (y >> 16) + (lsw >> 16);
    return (msw << 16) | (lsw & 0xffff);
  }
  function bitRotateLeft(num, cnt) {
    return (num << cnt) | (num >>> (32 - cnt));
  }
  function md5cmn(q, a, b, x, s, t) {
    return safeAdd(bitRotateLeft(safeAdd(safeAdd(a, q), safeAdd(x, t)), s), b);
  }
  function md5ff(a, b, c, d, x, s, t) {
    return md5cmn((b & c) | (~b & d), a, b, x, s, t);
  }
  function md5gg(a, b, c, d, x, s, t) {
    return md5cmn((b & d) | (c & ~d), a, b, x, s, t);
  }
  function md5hh(a, b, c, d, x, s, t) {
    return md5cmn(b ^ c ^ d, a, b, x, s, t);
  }
  function md5ii(a, b, c, d, x, s, t) {
    return md5cmn(c ^ (b | ~d), a, b, x, s, t);
  }

  function strtobytes(str) {
    const bytes = [];
    for (let i = 0; i < str.length; i++) {
      let c = str.charCodeAt(i);
      if (c < 128) {
        bytes.push(c);
      } else if (c < 2048) {
        bytes.push((c >> 6) | 192, (c & 63) | 128);
      } else {
        bytes.push((c >> 12) | 224, ((c >> 6) & 63) | 128, (c & 63) | 128);
      }
    }
    return bytes;
  }

  function bytestowords(bytes) {
    const words = new Array(Math.ceil(bytes.length / 4)).fill(0);
    for (let i = 0; i < bytes.length; i++) {
      words[i >> 2] |= bytes[i] << ((i % 4) * 8);
    }
    return words;
  }

  const bytes = strtobytes(str);
  const bitLen = bytes.length * 8;
  bytes.push(0x80);
  while (bytes.length % 64 !== 56) bytes.push(0);
  bytes.push(
    bitLen & 0xff,
    (bitLen >>> 8) & 0xff,
    (bitLen >>> 16) & 0xff,
    (bitLen >>> 24) & 0xff,
    0,
    0,
    0,
    0
  );
  const M = bytestowords(bytes);

  let a = 0x67452301,
    b = 0xefcdab89,
    c = 0x98badcfe,
    d = 0x10325476;

  for (let i = 0; i < M.length; i += 16) {
    const [A, B, C, D] = [a, b, c, d];
    a = md5ff(a, b, c, d, M[i], 7, -680876936);
    d = md5ff(d, a, b, c, M[i + 1], 12, -389564586);
    c = md5ff(c, d, a, b, M[i + 2], 17, 606105819);
    b = md5ff(b, c, d, a, M[i + 3], 22, -1044525330);
    a = md5ff(a, b, c, d, M[i + 4], 7, -176418897);
    d = md5ff(d, a, b, c, M[i + 5], 12, 1200080426);
    c = md5ff(c, d, a, b, M[i + 6], 17, -1473231341);
    b = md5ff(b, c, d, a, M[i + 7], 22, -45705983);
    a = md5ff(a, b, c, d, M[i + 8], 7, 1770035416);
    d = md5ff(d, a, b, c, M[i + 9], 12, -1958414417);
    c = md5ff(c, d, a, b, M[i + 10], 17, -42063);
    b = md5ff(b, c, d, a, M[i + 11], 22, -1990404162);
    a = md5ff(a, b, c, d, M[i + 12], 7, 1804603682);
    d = md5ff(d, a, b, c, M[i + 13], 12, -40341101);
    c = md5ff(c, d, a, b, M[i + 14], 17, -1502002290);
    b = md5ff(b, c, d, a, M[i + 15], 22, 1236535329);
    a = md5gg(a, b, c, d, M[i + 1], 5, -165796510);
    d = md5gg(d, a, b, c, M[i + 6], 9, -1069501632);
    c = md5gg(c, d, a, b, M[i + 11], 14, 643717713);
    b = md5gg(b, c, d, a, M[i], 20, -373897302);
    a = md5gg(a, b, c, d, M[i + 5], 5, -701558691);
    d = md5gg(d, a, b, c, M[i + 10], 9, 38016083);
    c = md5gg(c, d, a, b, M[i + 15], 14, -660478335);
    b = md5gg(b, c, d, a, M[i + 4], 20, -405537848);
    a = md5gg(a, b, c, d, M[i + 9], 5, 568446438);
    d = md5gg(d, a, b, c, M[i + 14], 9, -1019803690);
    c = md5gg(c, d, a, b, M[i + 3], 14, -187363961);
    b = md5gg(b, c, d, a, M[i + 8], 20, 1163531501);
    a = md5gg(a, b, c, d, M[i + 13], 5, -1444681467);
    d = md5gg(d, a, b, c, M[i + 2], 9, -51403784);
    c = md5gg(c, d, a, b, M[i + 7], 14, 1735328473);
    b = md5gg(b, c, d, a, M[i + 12], 20, -1926607734);
    a = md5hh(a, b, c, d, M[i + 5], 4, -378558);
    d = md5hh(d, a, b, c, M[i + 8], 11, -2022574463);
    c = md5hh(c, d, a, b, M[i + 11], 16, 1839030562);
    b = md5hh(b, c, d, a, M[i + 14], 23, -35309556);
    a = md5hh(a, b, c, d, M[i + 1], 4, -1530992060);
    d = md5hh(d, a, b, c, M[i + 4], 11, 1272893353);
    c = md5hh(c, d, a, b, M[i + 7], 16, -155497632);
    b = md5hh(b, c, d, a, M[i + 10], 23, -1094730640);
    a = md5hh(a, b, c, d, M[i + 13], 4, 681279174);
    d = md5hh(d, a, b, c, M[i], 11, -358537222);
    c = md5hh(c, d, a, b, M[i + 3], 16, -722521979);
    b = md5hh(b, c, d, a, M[i + 6], 23, 76029189);
    a = md5hh(a, b, c, d, M[i + 9], 4, -640364487);
    d = md5hh(d, a, b, c, M[i + 12], 11, -421815835);
    c = md5hh(c, d, a, b, M[i + 15], 16, 530742520);
    b = md5hh(b, c, d, a, M[i + 2], 23, -995338651);
    a = md5ii(a, b, c, d, M[i], 6, -198630844);
    d = md5ii(d, a, b, c, M[i + 7], 10, 1126891415);
    c = md5ii(c, d, a, b, M[i + 14], 15, -1416354905);
    b = md5ii(b, c, d, a, M[i + 5], 21, -57434055);
    a = md5ii(a, b, c, d, M[i + 12], 6, 1700485571);
    d = md5ii(d, a, b, c, M[i + 3], 10, -1894986606);
    c = md5ii(c, d, a, b, M[i + 10], 15, -1051523);
    b = md5ii(b, c, d, a, M[i + 1], 21, -2054922799);
    a = md5ii(a, b, c, d, M[i + 8], 6, 1873313359);
    d = md5ii(d, a, b, c, M[i + 15], 10, -30611744);
    c = md5ii(c, d, a, b, M[i + 6], 15, -1560198380);
    b = md5ii(b, c, d, a, M[i + 13], 21, 1309151649);
    a = md5ii(a, b, c, d, M[i + 4], 6, -145523070);
    d = md5ii(d, a, b, c, M[i + 11], 10, -1120210379);
    c = md5ii(c, d, a, b, M[i + 2], 15, 718787259);
    b = md5ii(b, c, d, a, M[i + 9], 21, -343485551);
    a = safeAdd(a, A);
    b = safeAdd(b, B);
    c = safeAdd(c, C);
    d = safeAdd(d, D);
  }

  function wordsToHex(val) {
    let hex = '';
    for (let j = 0; j < 4; j++) {
      const byte = (val >>> (j * 8)) & 0xff;
      hex += ('0' + byte.toString(16)).slice(-2);
    }
    return hex;
  }
  return wordsToHex(a) + wordsToHex(b) + wordsToHex(c) + wordsToHex(d);
}

export function gravatarHash(email) {
  return md5(email.trim().toLowerCase());
}

export default md5;
