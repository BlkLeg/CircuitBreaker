import { describe, expect, it } from 'vitest';
import { CERTIFICATE_FIELDS } from '../pages/CertificatesPage.jsx';
import { certificateTypeLabel } from '../utils/certificateTypes';

/**
 * INC-07: the backend now creates the type that was asked for. Three types exist, so the
 * form must be able to ask for all three and the table must be able to name all three.
 * A row typed "imported" rendered as "Self-Signed" is the same mislabelling in a new place.
 */
describe('certificate type, on the page', () => {
  const typeField = () => CERTIFICATE_FIELDS.find((f) => f.name === 'type');

  it('offers every type the API accepts', () => {
    const values = typeField().options.map((o) => o.value);
    expect(values).toEqual(['selfsigned', 'letsencrypt', 'imported']);
  });

  it('names each type distinctly in the table', () => {
    expect(certificateTypeLabel('selfsigned')).toBe('Self-Signed');
    expect(certificateTypeLabel('letsencrypt')).toBe("Let's Encrypt");
    expect(certificateTypeLabel('imported')).toBe('Imported');
  });

  it('does not claim an unknown type is self-signed', () => {
    expect(certificateTypeLabel('something-new')).toBe('something-new');
  });

  it('tells the operator the PEM fields belong to the imported type', () => {
    const pem = CERTIFICATE_FIELDS.find((f) => f.name === 'cert_pem');
    const key = CERTIFICATE_FIELDS.find((f) => f.name === 'key_pem');
    for (const field of [pem, key]) {
      expect(field.hint).toMatch(/imported/i);
      expect(field.hint).not.toMatch(/leave blank to auto-generate/i);
    }
  });
});
