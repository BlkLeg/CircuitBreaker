import { createEventWriter } from './events.js';
import { redactText } from './lifecycle-contract.js';
import { ART } from './art.js';

const LABELS = { resolve: 'Resolve release', download: 'Download release', verify: 'Verify release', apply: 'Apply verified release', recover: 'Restore previous release', preflight: 'Preflight checks', stage: 'Stage verified release', migrate: 'Apply database migrations', stop: 'Stop app services', health: 'Check readiness', commit: 'Commit healthy release', remove: 'Remove application files', cleanup: 'Finish removal', bundle: 'Download bundle', files: 'Stage release files', deps: 'Install dependencies', database: 'Prepare database', services: 'Configure services', start: 'Start and check readiness', upgrade_check: 'Preflight checks', backup: 'Save recovery snapshot', apply_bundle: 'Activate release' };
const SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧'];
const bytes = n => n < 1024 ? `${Math.round(n)} B` : `${(n / (n < 1048576 ? 1024 : 1048576)).toFixed(1)} ${n < 1048576 ? 'KiB' : 'MiB'}`;
const clean = s => redactText(String(s), { singleLine: true });

// The live region is bounded by terminal dimensions. No full-screen clears.
// Completed rows are permanent. Percentages measure bytes only, never an operation.
export function createPhaseRenderer({ write: rawWrite, now = Date.now, env = {}, terminal = {}, proc, schedule = setInterval, cancel = clearInterval }) {
  const tty = terminal.isTTY === true && env.TERM !== 'dumb';
  const ascii = env.TERM === 'dumb' || env.CB_ASCII === '1' || env.LC_ALL === 'C';
  const display = s => ascii ? s.replaceAll('→', '->').replaceAll('—', '-').replaceAll('·', ';') : s;
  const write = s => rawWrite(display(s));
  const color = tty && !Object.hasOwn(env, 'NO_COLOR');
  const motion = tty && env.CB_NO_ANIMATION !== '1' && env.CB_REDUCED_MOTION !== '1';
  const paint = (s, slot) => color ? `\x1b[38;5;${slot}m${s}\x1b[0m` : s;
  const good = ascii ? 'OK' : '✓', bad = ascii ? 'FAIL' : '✗';
  const active = new Map();
  let current = null, live = [], last = -Infinity, frame = 0, ordinal = 0, closed = false, timer, partial = false, artwork = false;
  let previous;
  const startedAt = now();
  const width = () => Math.max(1, (terminal.columns ?? 80) - 1);
  const fit = s => Array.from(display(s)).slice(0, width()).join('');
  const clear = () => {
    if (!live.length) return;
    // Account for terminal reflow before erasing only our own live rows.
    const rows = live.reduce((n, row) => n + Math.max(1, Math.ceil(Array.from(row).length / Math.max(1, terminal.columns ?? 80))), 0);
    write('\r\x1b[2K' + '\x1b[1A\r\x1b[2K'.repeat(rows - 1));
    live = [];
  };
  const line = text => { clear(); write(text); };
  const keyOf = e => `${e.source}:${e.operation_id}:${e.phase}`;
  const liveText = () => {
    if (!current) return '';
    const elapsed = Math.max(0, (now() - current.start) / 1000);
    let detail = `${elapsed.toFixed(1)}s elapsed`;
    if (current.progress) {
      const { done, total, unit } = current.progress;
      detail = unit === 'bytes' ? bytes(done) : `${done} ${unit}`;
      if (total > 0) {
        const pct = Math.min(100, Math.floor(done * 100 / total));
        const count = Math.max(4, Math.min(24, width() - 65));
        const filled = Math.floor(pct * count / 100);
        const bar = (ascii ? '#' : '█').repeat(filled) + (ascii ? '-' : '░').repeat(count - filled);
        detail += ` / ${unit === 'bytes' ? bytes(total) : `${total} ${unit}`} ${pct}% [${bar}]`;
      }
      if (elapsed > 0 && done > current.base) detail += ` · ${bytes((done - current.base) / elapsed)}/s`;
      detail += ` · ${elapsed.toFixed(1)}s elapsed`;
    }
    const marker = ascii ? '|/-\\'[frame % 4] : SPINNER[frame % SPINNER.length];
    return fit(current.progress ? `${marker} ${detail}` : `${marker} Phase ${current.ordinal} — ${LABELS[current.phase] ?? clean(current.phase)} · ${detail}`);
  };
  const liveRows = () => {
    const text = liveText();
    if (!current || !current.progress || current.progress.unit !== 'bytes' || !(current.progress.total > 0) || width() < 65 || (terminal.rows ?? 24) < 6) return [text];
    const marker = ascii ? '|/-\\'[frame % 4] : SPINNER[frame % SPINNER.length];
    const { done, total } = current.progress;
    const pct = total > 0 ? Math.min(100, Math.floor(done * 100 / total)) : null;
    const count = Math.min(32, width() - 4), filled = pct === null ? 0 : Math.floor(pct * count / 100);
    const bar = `[${(ascii ? '#' : '█').repeat(filled)}${(ascii ? '-' : '░').repeat(count - filled)}]`;
    // Keep the measurements intact; the bar has its own line in wide terminals.
    const elapsed = Math.max(0, (now() - current.start) / 1000);
    const rate = elapsed > 0 && done > current.base ? ` · ${bytes((done - current.base) / elapsed)}/s` : '';
    return [fit(`${marker} Phase ${current.ordinal} — ${LABELS[current.phase] ?? clean(current.phase)}`), fit(`  ${bytes(done)}${total > 0 ? ` / ${bytes(total)} · ${pct}%` : ''}${rate} · ${elapsed.toFixed(1)}s elapsed`), fit(`  ${bar}`)];
  };
  const tick = () => {
    if (closed || partial || !motion || !current || now() - last < 125) return;
    clear();
    live = liveRows();
    write(live.map((row, i) => paint(row, i === 2 ? 209 : 141)).join('\n'));
    last = now(); frame++;
  };
  const render = event => {
    if (closed) return;
    if (event.type === 'diagnostic') { line(`${clean(event.message)}\n`); return; }
    if (event.type === 'progress') {
      const phase = active.get(keyOf(event));
      if (phase) {
        // A resumed/restarted transfer is measured from its new baseline.
        if (!phase.progress || event.done < phase.progress.done) { phase.base = event.done; phase.start = now(); }
        phase.progress = event;
      }
      tick(); return;
    }
    if (event.type !== 'phase') return;
    const key = keyOf(event);
    if (event.status === 'started') {
      current = { phase: event.phase, start: now(), ordinal: ++ordinal, base: 0 };
      active.set(key, current);
      if (tty && !motion) line(`  ${ascii ? '>' : '▸'} Phase ${ordinal} — ${LABELS[event.phase] ?? clean(event.phase)}\n`);
      tick(); return;
    }
    const phase = active.get(key);
    active.delete(key);
    if (current === phase) current = [...active.values()].at(-1) ?? null;
    const mark = event.status === 'failed' ? bad : event.status === 'skipped' ? '-' : good;
    const time = event.duration_ms === undefined ? '' : ` (${(event.duration_ms / 1000).toFixed(1)}s)`;
    line(tty ? `  ${paint(mark, event.status === 'failed' ? 203 : 142)} ${(LABELS[event.phase] ?? clean(event.phase)).padEnd(Math.min(38, Math.max(0, width() - 18)))}${time}\n` : `${mark} ${clean(event.phase)}${time}\n`);
    tick();
  };
  const events = createEventWriter({ write: s => render(JSON.parse(s)), now });
  const resize = () => { clear(); }; // next bounded tick uses the new width
  const signals = new Map(['SIGINT', 'SIGTERM', 'SIGHUP'].map(signal => [signal, () => {
    close();
    // Do not swallow the OS default when no native runner owns the signal.
    if (proc === process && proc.listenerCount(signal) === 0) proc.kill(proc.pid, signal);
  }]));
  const close = () => {
    if (closed) return;
    clear(); closed = true;
    if (timer) cancel(timer);
    terminal.off?.('resize', resize);
    for (const [signal, handler] of signals) proc?.off(signal, handler);
    proc?.off('exit', close);
    if (motion) write('\x1b[?25h');
  };
  if (motion) {
    write('\x1b[?25l');
    timer = schedule(tick, 125); timer?.unref?.();
    terminal.on?.('resize', resize);
    for (const [signal, handler] of signals) proc?.on(signal, handler);
    proc?.on('exit', close);
  }
  return {
    ...events, machine: false, relay: render, tick, liveText, liveRows, close,
    // Native narration clears the live region before printing on either stream.
    output(text, sink = write) { clear(); sink(text); partial = !text.endsWith('\n'); },
    diagnostic(message) { line(`${redactText(String(message))}\n`); },
    heading(action, currentVersion, targetVersion, context = {}) {
      if (!artwork && tty && (terminal.columns ?? 80) >= 66 && (terminal.rows ?? 24) >= 30 && action === 'install') {
        line(color ? ART : ART.replace(/\x1b\[[0-9;]*m/g, '')); artwork = true;
        if (context.cliVersion) line(`                         CLI v${clean(context.cliVersion)}\n`);
      }
      line(`\n${paint(action.toUpperCase(), 209)}${context.arch ? `  native / linux-${clean(context.arch)}` : ''}\n`);
      previous = currentVersion ?? null;
      line(`${clean(currentVersion ?? 'new install')} → ${clean(targetVersion ?? 'selected release')}\n\n`);
    },
    target(version) { line(`  Verified target: ${clean(version)}\n\n`); },
    result(result, identity) {
      clear(); current = null; active.clear();
      const success = result.outcome === 'committed';
      line(`\n${paint(success ? `${result.action.toUpperCase()} COMPLETE` : result.outcome.toUpperCase().replaceAll('_', ' '), success ? 142 : 203)}\n`);
      // result.current_version is what runs after the operation; the heading recorded what ran before it.
      // Without a heading, only an uncommitted result still names the earlier version.
      const prior = previous !== undefined ? previous ?? 'none (new install)'
        : success ? 'unavailable' : result.current_version ?? 'unavailable';
      line(`  Previous: ${clean(prior)}\n  Target:   ${clean(result.target_version ?? 'unavailable')}\n`);
      if (success) line('  Health:   native readiness checks committed\n');
      else line('  Health:   inspect current state with cb doctor\n');
      if (success && identity?.health_url) line(`  Endpoint: ${clean(identity.health_url)}\n`);
      if (identity?.data_dir) line(`  Log: ${clean(identity.data_dir)}/logs/install.log\n`);
      line(`  Duration: ${((now() - startedAt) / 1000).toFixed(1)}s\n`);
      if (result.operation_id) line(`  Operation: ${clean(result.operation_id)}\n`);
      line(`  Recovery: ${result.recovery_available ? 'recorded; inspect circuitbreaker history' : 'not reported'}\n`);
      if (result.error?.reason) line(`  Cause: ${clean(result.error.reason)}\n`);
      if (!success) line('  Next: cb doctor · circuitbreaker history\n');
    },
  };
}
