# CLI visual previews for 0.4.7

Illustrative data, not live resource readings. These browser mockups represent
terminal output. The reviewed terminal hierarchy is implemented in the CLI;
see [implementation evidence](../../../../plans/2026-09-30-v0.4.7-npm-cli-08-terminal-surfaces.md).
Preview numbers remain illustrative. Backup subrows are combined where the native
builder exposes only one measured operation; deferred commands are omitted from help.

- [Download progress](https://p.superdesign.dev/draft/acd390bf-7c54-49e5-9ff1-a8d10e71de81): character-cell progress, transferred bytes, rate and elapsed time. This bar measures only the download phase. Verification, backup, activation and health remain separate phases. The existing artwork is retained.
- [Uninstall process](https://p.superdesign.dev/draft/42176764-36a8-4043-96be-76d32ac72f8e): software removal with configuration, vault key, database, uploads and backups retained. Shows the plan and data choice before confirmation, completed phase ledger and final result. Purge remains a separate explicit choice.
- [Purge confirmation](https://p.superdesign.dev/draft/724417d7-ee97-4bdc-af72-e4437734e091): explicit deletion scope and an empty typed confirmation before services stop. This is proposed CLI behavior, not a change to the current shell purge flag.
- [Expanded workers](https://p.superdesign.dev/draft/1ddc5c96-a43e-4ba7-98d0-fdeb7295a5af): seven worker roles in global CPU order, with totals matching the collapsed example and telemetry throttling highlighted.
- [Status](https://p.superdesign.dev/draft/9e5fc28d-12ff-4d20-8598-60d0ca250dd4): 12 native app units plus shared nginx, process state and active-since timestamps, configured endpoint and identity. Service state is distinct from readiness.
- [Doctor](https://p.superdesign.dev/draft/19ccb781-d3c5-435e-aff9-e3171c6a211e): eight passed, one failed storage check, one skipped authenticated check, read-only diagnosis and concrete next steps. Values are examples.
- [Logs](https://p.superdesign.dev/draft/085c71d3-dc4e-46aa-9d04-dc9b0a4dd489): append-only follow output with timestamp, severity, component and message; multiline continuation remains aligned with its entry.
- [Backup](https://p.superdesign.dev/draft/fc381433-4441-452b-8959-e1f24b39dd8d): proposed native full-state snapshot flow, phase timings, protected local artifact and off-host encryption guidance. Native routing/events and post-build verification require implementation; no backup is created by the preview.
- [Command overview](https://p.superdesign.dev/draft/5ee98b78-bff7-422f-8666-616663c0bb00): proposed output for `cb`, all native commands plus npm lifecycle management grouped by purpose.
- [Resources watch](https://p.superdesign.dev/draft/fcf8b81b-6fa2-419c-adf3-35242b317810): CPU/memory capacity bars, component breakdown, scoped shared limits, shared nginx usage and throttling notice. Network accounting is explicitly unavailable. The compact heading keeps routine command output readable.

The watch preview uses `cb resources --watch`; `cb resources` takes a single
snapshot and returns to the prompt, without the watch key controls. Existing JSON
and resource measurement semantics remain unchanged.

Open the HTML exports in a browser with network access to load Tailwind. The PNG
exports capture the reviewed layouts. Review both on the
[canvas](https://superdesign.dev/teams/4281dc54-7c08-491e-9c06-483e758fa325/projects/6f07cdb8-a9ff-437e-9c3e-4ee8be947161).
