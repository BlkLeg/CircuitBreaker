import { describe, expect, it } from 'vitest';
import { KB_TABS } from '../components/kb/kbTabs.jsx';

const byKey = (k) => KB_TABS.find((t) => t.key === k);

describe('KB tab descriptors', () => {
  it('declares exactly the two KB tables', () => {
    expect(KB_TABS.map((t) => t.key)).toEqual(['oui', 'hostname']);
  });

  // CONTRACT PIN — the counterpart lives in
  // apps/backend/tests/api/test_kb.py::test_update_schemas_match_frontend_editable_columns
  // If PUT starts accepting a different set of fields, change BOTH.
  it('OUI inline-editable columns match what PUT /kb/oui/{prefix} accepts', () => {
    expect([...byKey('oui').editableColumns].sort()).toEqual([
      'device_type',
      'os_family',
      'vendor',
    ]);
  });

  it('hostname inline-editable columns exclude match_type', () => {
    // match_type IS accepted by PUT, but is an enum and must be edited through
    // the row modal — EntityTable's EditableCell is a bare text input.
    expect([...byKey('hostname').editableColumns].sort()).toEqual([
      'device_type',
      'os_family',
      'vendor',
    ]);
  });

  it('never marks identity or provenance columns editable', () => {
    for (const tab of KB_TABS) {
      expect(tab.editableColumns).not.toContain('prefix');
      expect(tab.editableColumns).not.toContain('pattern');
      expect(tab.editableColumns).not.toContain('source');
      expect(tab.editableColumns).not.toContain('seen_count');
    }
  });

  it('keys OUI rows by prefix and hostname rows by id', () => {
    expect(byKey('oui').identityKey).toBe('prefix');
    expect(byKey('hostname').identityKey).toBe('id');
  });

  it('rejects an invalid MAC prefix on create', () => {
    const errors = byKey('oui').validateCreate({ prefix: 'zz', vendor: 'Acme' });
    expect(errors).toHaveProperty('prefix');
  });

  it('accepts a colon-formatted MAC prefix on create', () => {
    expect(byKey('oui').validateCreate({ prefix: 'b8:27:eb', vendor: 'Acme' })).toBeNull();
  });

  it('offers exactly the three match types the backend allows', () => {
    const field = byKey('hostname').formFields.find((f) => f.name === 'match_type');
    expect(field.options.map((o) => o.value).sort()).toEqual(['contains', 'exact', 'prefix']);
  });
});
