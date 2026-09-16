import { describe, expect, it } from 'vitest';
import { buildUserMessage, decorateApiError, extractFieldErrors } from '../lib/apiErrors';

describe('buildUserMessage', () => {
  it('uses string detail for client errors', () => {
    expect(buildUserMessage(409, { detail: 'IP taken' }, new Error('x'))).toBe('IP taken');
  });

  it('joins 422 validation messages without stringifying objects', () => {
    expect(
      buildUserMessage(
        422,
        { detail: [{ loc: ['body', 'name'], msg: 'required' }, { msg: 'bad' }] },
        new Error('x')
      )
    ).toBe('required; bad');
  });

  it('never returns [object Object] for object detail', () => {
    const message = buildUserMessage(
      409,
      { detail: { nested: true } },
      new Error('[object Object]')
    );
    expect(message).not.toContain('[object Object]');
    expect(message.length).toBeGreaterThan(0);
  });

  it('prefers safe string detail on 500', () => {
    expect(buildUserMessage(500, { detail: 'boom' }, new Error('x'))).toBe('boom');
    expect(buildUserMessage(500, { detail: { x: 1 } }, new Error('x'))).toMatch(/server error/i);
  });
});

describe('extractFieldErrors', () => {
  it('reads AppError fields on 409', () => {
    expect(
      extractFieldErrors(409, {
        fields: { ip_address: 'Choose an available address.' },
      })
    ).toEqual({ ip_address: 'Choose an available address.' });
  });

  it('still reads 422 validation arrays', () => {
    expect(
      extractFieldErrors(422, {
        detail: [{ loc: ['body', 'name'], msg: 'Field required' }],
      })
    ).toEqual({ name: 'Field required' });
  });
});

describe('decorateApiError', () => {
  it('attaches conflict context for ip_conflict', () => {
    const err = decorateApiError(new Error('conflict'), 409, {
      detail: 'This IP address conflicts with an existing asset.',
      error_code: 'ip_conflict',
      fields: { ip_address: 'Choose an available address.' },
      context: {
        conflicts: [{ entity_type: 'hardware', entity_id: 3, entity_name: 'nas-01' }],
      },
    });
    expect(err.errorCode).toBe('ip_conflict');
    expect(err.fieldErrors).toEqual({ ip_address: 'Choose an available address.' });
    expect(err.conflictContext.conflicts[0].entity_name).toBe('nas-01');
  });
});
