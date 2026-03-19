import { describe, it, expect, vi } from 'vitest';

// ── Minimal WebSocket mock ─────────────────────────────────────────────────
const CONNECTING = 0,
  OPEN = 1,
  CLOSED = 3;

function makeMockWS(initialState = CONNECTING) {
  const ws = {
    readyState: initialState,
    _listeners: new Map(),
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    close: vi.fn(function () {
      if (this.readyState === OPEN) {
        this.readyState = CLOSED;
        this.onclose?.({ code: 1000, wasClean: true });
      }
      // NOTE: During CONNECTING close() is a no-op to simulate the bug
    }),
    send: vi.fn(),
    addEventListener: vi.fn(function (event, cb, opts) {
      if (!this._listeners.has(event)) {
        this._listeners.set(event, []);
      }
      this._listeners.get(event).push({ cb, opts });
    }),
    _fireOpen() {
      this.readyState = OPEN;
      this._listeners.get('open')?.forEach(({ cb }) => cb());
      this.onopen?.();
    },
    _fireMessage(data) {
      this.onmessage?.({ data: JSON.stringify(data) });
    },
    _fireClose(code = 1000) {
      this.readyState = CLOSED;
      this.onclose?.({ code, wasClean: code === 1000 });
    },
    _fireError() {
      this.onerror?.({});
    },
  };
  return ws;
}

// ── closeSocketSafely extracted for unit testing ───────────────────────────
function closeSocketSafely(socket) {
  if (!socket) return;
  if (socket.readyState === CONNECTING) {
    socket.addEventListener(
      'open',
      () => {
        try {
          socket.close();
        } catch {
          /* ignore late-close during teardown */
        }
      },
      { once: true }
    );
    return;
  }
  if (socket.readyState === OPEN) {
    socket.close();
  }
}

describe('closeSocketSafely', () => {
  it('defers close until OPEN when socket is CONNECTING', () => {
    const ws = makeMockWS(CONNECTING);
    closeSocketSafely(ws);
    expect(ws.close).not.toHaveBeenCalled(); // deferred
    // The event listener added by closeSocketSafely should call close
    const listener = ws._listeners.get('open')?.[0]?.cb;
    expect(listener).toBeDefined();
    listener?.();
    expect(ws.close).toHaveBeenCalled();
  });

  it('closes immediately when OPEN', () => {
    const ws = makeMockWS(OPEN);
    closeSocketSafely(ws);
    expect(ws.close).toHaveBeenCalled();
  });

  it('does nothing when socket is null', () => {
    expect(() => closeSocketSafely(null)).not.toThrow();
  });

  it('does nothing when socket is CLOSED', () => {
    const ws = makeMockWS(CLOSED);
    closeSocketSafely(ws);
    expect(ws.close).not.toHaveBeenCalled();
  });
});

// ── Simulate the hook's onmessage close logic ──────────────────────────────
const HARD_STOP_ERRORS = new Set(['unauthorized', 'auth_timeout']);

function simulateOnMessage(ws, msg, refs) {
  // Replicates the buggy onmessage close calls (pre-fix)
  if (msg.error && HARD_STOP_ERRORS.has(msg.error)) {
    refs.intentional = true;
    ws.close(); // BUG: should be closeSocketSafely(ws)
    return 'hard_stop';
  }
  if (msg.error === 'connection_limit_exceeded') {
    refs.intentional = false;
    ws.close(); // BUG: should be closeSocketSafely(ws)
    return 'cap';
  }
}

function simulateOnMessageFixed(ws, msg, refs) {
  // Post-fix version
  if (msg.error && HARD_STOP_ERRORS.has(msg.error)) {
    refs.intentional = true;
    closeSocketSafely(ws); // FIXED
    return 'hard_stop';
  }
  if (msg.error === 'connection_limit_exceeded') {
    refs.intentional = false;
    closeSocketSafely(ws); // FIXED
    return 'cap';
  }
}

describe('hard-stop errors during CONNECTING state', () => {
  it('BUG: ws.close() during CONNECTING leaves socket as zombie', () => {
    const ws = makeMockWS(CONNECTING);
    const refs = { intentional: false };
    simulateOnMessage(ws, { error: 'unauthorized' }, refs);
    // close() called but socket is still CONNECTING (our mock simulates the bug)
    expect(ws.close).toHaveBeenCalled();
    expect(ws.readyState).toBe(CONNECTING); // Socket is zombie - still CONNECTING
  });

  it('FIX: closeSocketSafely during CONNECTING defers and socket eventually closes', () => {
    const ws = makeMockWS(CONNECTING);
    const refs = { intentional: false };
    simulateOnMessageFixed(ws, { error: 'unauthorized' }, refs);
    expect(ws.close).not.toHaveBeenCalled(); // deferred
    expect(refs.intentional).toBe(true); // flag set correctly
    // When socket eventually opens, it gets closed
    const openListener = ws._listeners.get('open')?.[0]?.cb;
    openListener?.();
    expect(ws.close).toHaveBeenCalled();
  });

  it('FIX: closeSocketSafely for connection_limit_exceeded during CONNECTING', () => {
    const ws = makeMockWS(CONNECTING);
    const refs = { intentional: true }; // Start as true to test it gets set false
    simulateOnMessageFixed(ws, { error: 'connection_limit_exceeded' }, refs);
    expect(ws.close).not.toHaveBeenCalled(); // deferred
    expect(refs.intentional).toBe(false); // allows retry
  });
});

// ── handshakeCompleteRef — zombie socket detection ─────────────────────────
describe('handshakeCompleteRef — zombie socket detection', () => {
  function isActive(ws, handshakeComplete) {
    if (!ws) return false;
    if (ws.readyState === OPEN) return true;
    if (ws.readyState === CONNECTING && handshakeComplete) return true;
    return false;
  }

  it('CONNECTING socket without completed handshake is not considered active', () => {
    const ws = makeMockWS(CONNECTING);
    expect(isActive(ws, false)).toBe(false); // zombie — can reconnect
  });

  it('OPEN socket is always active regardless of handshake flag', () => {
    const ws = makeMockWS(OPEN);
    expect(isActive(ws, false)).toBe(true);
    expect(isActive(ws, true)).toBe(true);
  });

  it('handshake flag resets on each new connection cycle', () => {
    let handshakeComplete = false;
    function onConnect() {
      handshakeComplete = false;
    }
    function onConnected() {
      handshakeComplete = true;
    }

    onConnect();
    expect(handshakeComplete).toBe(false);
    onConnected();
    expect(handshakeComplete).toBe(true);
    onConnect(); // new connection cycle resets flag
    expect(handshakeComplete).toBe(false);
  });
});

// ── onerror defensive close ────────────────────────────────────────────────
describe('onerror defensive close', () => {
  it('calling closeSocketSafely from onerror on OPEN socket triggers close', () => {
    const ws = makeMockWS(OPEN);
    let closedFired = false;
    ws.onclose = () => {
      closedFired = true;
    };

    function onError() {
      if (ws.readyState !== CLOSED) {
        closeSocketSafely(ws);
      }
    }

    onError();
    expect(ws.close).toHaveBeenCalled();
    expect(closedFired).toBe(true);
  });

  it('calling closeSocketSafely from onerror on CONNECTING defers close', () => {
    const ws = makeMockWS(CONNECTING);

    function onError() {
      if (ws.readyState !== CLOSED) {
        closeSocketSafely(ws);
      }
    }

    onError();
    expect(ws.close).not.toHaveBeenCalled(); // deferred
    expect(ws.addEventListener).toHaveBeenCalledWith('open', expect.any(Function), { once: true });
  });
});
