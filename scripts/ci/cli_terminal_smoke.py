#!/usr/bin/env python3
"""Read-only PTY acceptance of the shipped renderer; never operates on an install.

Captures are event fixtures, not evidence of a completed host lifecycle journey.
Use --package for an installed/packed package directory containing src/render.js.
"""

import argparse
import errno
import fcntl
import json
import os
import pty
import re
import select
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def capture(
    command, *, columns=100, rows=40, env=None, resize=False, interrupt=False, inputs=()
):
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
    proc = subprocess.Popen(
        command,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "TERM": "xterm-256color", **(env or {})},
        start_new_session=True,
    )
    os.close(slave)
    output = bytearray()
    started = time.monotonic()
    changed = stopped = False
    input_index = 0
    try:
        while True:
            elapsed = time.monotonic() - started
            if elapsed > 8:
                raise AssertionError("terminal fixture timed out")
            if resize and elapsed > 0.22 and not changed:
                fcntl.ioctl(
                    master, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 40, 0, 0)
                )
                proc.send_signal(signal.SIGWINCH)
                changed = True
            if interrupt and elapsed > 0.35 and not stopped:
                proc.send_signal(signal.SIGTERM)
                stopped = True
            if input_index < len(inputs) and elapsed > inputs[input_index][0]:
                os.write(master, inputs[input_index][1])
                input_index += 1
            if select.select([master], [], [], 0.03)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as error:
                    if error.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output.extend(chunk)
            elif proc.poll() is not None:
                break
        proc.wait(timeout=2)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)
    return proc.returncode, output.decode("utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "packages/cli")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    module = (args.package.resolve() / "src/render.js").as_uri()
    program = f"""import {{ createPhaseRenderer }} from {json.dumps(module)};
const r = createPhaseRenderer({{write: s => process.stderr.write(s), terminal: process.stderr, proc: process, env: process.env}});
r.heading('install', null, '0.4.7');
r.phase('download', 'started');
let done = 0;
const timer = setInterval(() => {{done += 1048576; r.progress('download', done, 4194304, 'bytes');
if(done === 4194304) {{clearInterval(timer); r.phase('download', 'completed'); r.phase('verify', 'started'); r.phase('verify', 'failed');
r.result({{action:'install', outcome:'refused', target_version:'0.4.7', recovery_available:false, error:{{reason:'Fixture verification refused'}}}}); r.close();}} }}, 130);
"""
    records = []
    for name, width, height, env, resize, interrupt in [
        ("wide", 120, 45, {}, False, False),
        ("narrow", 40, 12, {}, False, False),
        ("short", 80, 4, {}, False, False),
        ("static", 80, 24, {"CB_NO_ANIMATION": "1"}, False, False),
        ("no-color", 80, 24, {"NO_COLOR": ""}, False, False),
        ("ascii", 80, 24, {"LC_ALL": "C", "CB_ASCII": "1"}, False, False),
        ("dumb", 80, 24, {"TERM": "dumb"}, False, False),
        ("resize", 100, 30, {}, True, False),
        ("interrupt", 100, 30, {}, False, True),
    ]:
        code, text = capture(
            ["node", "--input-type=module", "-e", program],
            columns=width,
            rows=height,
            env=env,
            resize=resize,
            interrupt=interrupt,
        )
        assert code == (-signal.SIGTERM if interrupt else 0), (name, code, text)
        if "\033[?25l" in text:
            assert text.endswith("\033[?25h"), (name, "cursor not restored")
        assert "INSTALL COMPLETE" not in text, name
        if not interrupt:
            assert "Fixture verification refused" in text and "REFUSED" in text, name
        if name in ("no-color", "dumb"):
            assert not re.search(r"\033\[[\d;]*m", text), name
        if name in ("static", "dumb"):
            assert "\033[?25l" not in text, name
        if name in ("ascii", "dumb"):
            assert text.isascii(), (name, text)
        if name == "wide":
            assert "C I R C U I T _ B R E A K E R" in text, name
            assert "MiB" in text and "█" in text, name
        if name in ("short", "narrow"):
            assert "C I R C U I T _ B R E A K E R" not in text, name
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            (args.output_dir / f"{name}.ansi").write_text(text)
        records.append(
            {
                "mode": name,
                "columns": width,
                "rows": height,
                "exit": code,
                "bytes": len(text.encode()),
            }
        )
    # Exercise the actual watch loop and keyboard controls with an injected
    # collector. No systemd/Docker request or real install identity is read.
    resource_module = str(ROOT / "deploy/cli/cb_resources.py")
    watch = f"""import importlib.util, time
from pathlib import Path
spec = importlib.util.spec_from_file_location('resources', {resource_module!r})
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
r.load_identity = lambda: ({{'mode':'native'}}, Path('/fixture/identity.json'))
class Collector:
    def __init__(self, identity): self.host = {{'name':'fixture','scope':'fixture app services','cpus':8,'memory_bytes':16<<30}}
    def collect(self):
        rows = []
        for name in ['circuitbreaker-backend.service', *['circuitbreaker-worker@'+w+'.service' for w in r.WORKERS], 'nginx.service']:
            row = r.observation(name, 'active', 'fixture', owned=name != 'nginx.service', key=name)
            for key in ('memory_bytes','cache_bytes','swap_bytes'):
                row['metrics'][key] = r.metric(32<<20 if key == 'memory_bytes' else 0, 'bytes', 'fixture')
            row['counters']['cpu_ns'] = r.metric(int(time.monotonic()*500000000), 'nanoseconds', 'fixture')
            rows.append(row)
        return rows, self.host, []
r.NativeCollector = Collector
raise SystemExit(r.main(['--watch','--interval','1']))
"""
    for name, width, height in [
        ("resources-wide", 120, 45),
        ("resources-narrow", 40, 12),
    ]:
        keys = b"me" if width >= 80 else b"mejjjj"
        code, text = capture(
            ["python3", "-c", watch],
            columns=width,
            rows=height,
            inputs=[(1.2, keys), (2.3, b"q")],
        )
        assert code == 0 and text.endswith("\033[?25h\033[?1049l"), (name, code, text)
        assert "[q] quit" in text and "sorted by memory" in text, (name, text)
        if name == "resources-wide":
            assert "workers (7)" in text and "worker: monitor_probe_dispatch" in text, (
                text
            )
        if args.output_dir:
            (args.output_dir / f"{name}.ansi").write_text(text)
        records.append(
            {
                "mode": name,
                "columns": width,
                "rows": height,
                "exit": code,
                "bytes": len(text.encode()),
            }
        )
    print(json.dumps({"kind": "renderer-fixtures", "captures": records}, indent=2))


if __name__ == "__main__":
    main()
