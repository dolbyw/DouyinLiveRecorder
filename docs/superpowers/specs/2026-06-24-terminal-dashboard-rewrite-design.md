# Terminal Dashboard Rewrite Design

## Goal

Rewrite the complete terminal dashboard around a calm, full-width operational hierarchy that lets the user answer two questions immediately:

1. Does anything require human action?
2. What meaningful state changes happened recently?

The rewrite preserves recording, monitoring, conversion, shutdown, configuration, and packaging behavior. It keeps Rich as the rendering dependency and removes obsolete UI components, duplicate presentation logic, and dependencies proven unused after repository-wide verification.

## Research Basis

The design adapts patterns from established public terminal and logging tools:

- [K9s](https://github.com/derailed/k9s): full-width log focus, stable metadata framing, and restrained status color.
- [Lazydocker](https://github.com/jesseduffield/lazydocker): stable operational regions and context-specific detail instead of one undifferentiated stream.
- [Grafana Loki](https://github.com/grafana/loki): label-oriented event metadata and separation between indexed operational meaning and raw log text.

The validated browser mockups are stored under `.superpowers/brainstorm/terminal-ui-layout/content/`. `full-dashboard-v3.html` represents the approved overall direction; the room-table interaction is refined by this specification.

## Scope

### Included

- Replace the entire Rich dashboard layout.
- Introduce a Rich-independent presentation-model builder.
- Add actionable-versus-recovering attention semantics.
- Coalesce related low-level events into semantic lifecycle events.
- Add responsive width and height behavior.
- Add an `R` key toggle between compact and maximally expanded room views.
- Rebuild the plain-text fallback from the same presentation model.
- Remove obsolete UI functions, branches, fields, imports, tests, and dependency declarations after usage verification.
- Keep `pyproject.toml` and `requirements.txt` consistent.

### Excluded

- Changes to platform probing, stream extraction, recording, conversion, naming, or notification behavior.
- A general keyboard menu, room selection, scrolling, mouse interaction, or command palette.
- Deleting existing build directories, packaged ZIP files, logs, downloads, or user configuration.
- Moving raw debug output into the live dashboard.

## Architecture

The dashboard remains a read-only view over runtime state and is divided into three explicit layers.

### Runtime State

`DashboardStateStore` remains the thread-safe source of room, recording, conversion, probe, error, application-phase, and event state. Existing fields remain unless repository-wide usage analysis proves them obsolete.

The state contract is extended only where the approved interface cannot derive an honest answer:

- attention disposition: automatic recovery or human action required;
- stable incident identity for deduplication;
- recovery/cleared state and timestamps;
- structured lifecycle metadata needed to coalesce related events.

The state layer never imports Rich and never stores rendered strings or colors.

### Presentation Model

A pure presentation builder converts one `DashboardSnapshot`, terminal dimensions, and room expansion state into immutable display data:

- header status and health counts;
- compact configuration summary;
- ordered and height-limited room rows;
- pinned attention rows;
- coalesced semantic event rows;
- explicit counts for hidden rooms and older events.

This layer owns business-facing labels, event coalescing, priority ordering, width-mode selection, and row budgets. It performs no network access and does not mutate runtime state. File-size reads already required for recording detail must be isolated behind a small, failure-tolerant adapter so pure builder tests can supply deterministic values.

### Renderers

The Rich renderer consumes the presentation model and owns borders, colors, column widths, and full-screen refresh. It does not infer severity or combine events.

The plain-text renderer consumes the same model. It must preserve attention state, room priority, semantic event wording, and hidden-item counts rather than maintaining a second set of decisions.

## Visual Hierarchy

The full dashboard contains four stable regions.

### 1. Runtime Header

A compact header replaces the previous metric-card row:

- product name and application phase on the left;
- current time and elapsed runtime on the right;
- counts for total rooms, recording, monitoring, converting, and requiring action;
- FFmpeg health and free disk space.

Color communicates state only. Decorative blue borders and large empty cards are removed.

### 2. Configuration Summary

One restrained line displays save format/conversion, quality, segment duration, polling interval, request concurrency, proxy state, and an end-truncated save path. The configuration line is secondary to runtime status and never consumes a card-sized region.

### 3. Room Table

The table prioritizes rooms in this order:

1. human action required;
2. automatic recovery;
3. recording;
4. converting;
5. first probe;
6. monitoring and other normal states.

Compact mode is the default. It uses the available room-row budget for all priority rooms first and then normal monitoring rooms. The title states `已显示 X/Y · [R] 展开`.

Pressing `R` switches to maximum expanded mode. The dashboard still reserves room for pinned attention and at least three event rows. If every room fits, every room is shown. If physical terminal height prevents that, the footer explicitly states `还有 N 个`; data is never silently cropped. Pressing `R` again returns to compact mode. Expansion is a display-only state and does not reorder or alter runtime work.

### 4. Runtime Activity

The former two-column recent-event panel becomes a full-width operational section.

The header shows counts for `需处理`, `自动恢复`, and visible recent events. Pinned attention rows appear above the timeline. The timeline uses stable time, event, room, and detail fields. Normal lines use restrained color; only the short event label carries semantic color.

Raw technical logging continues to `logs/streamget.log`, and the dashboard footer points to that file.

## Attention Semantics

Attention state is persistent rather than a transient historical event.

### Automatic Recovery

Yellow indicates that the application is retrying or recovering without human action. A row includes the room or subsystem, concise failure, retry count, next attempt, and incident duration. It stays pinned until success or escalation.

### Human Action Required

Red is reserved for conditions that cannot recover under the active policy, including exhausted retries, insufficient disk, permission failures, unavailable FFmpeg, and equivalent terminal conditions. These rows remain pinned until the runtime reports recovery or the condition is removed from active state.

### Recovery

Recovery removes the pinned row immediately and appends one green semantic recovery event. Repeated failures update occurrence count and duration on one incident rather than appending duplicate timeline lines.

`error_count` and the visible `需处理` count must not conflate historical errors with current actionable incidents.

## Semantic Events

The dashboard shows state changes, not the raw application log stream.

- Poll successes, countdown refreshes, and probes with no state change do not create timeline rows.
- Repeated identical failures update one incident.
- A recording lifecycle is coalesced when sufficient metadata exists. `直播结束`, `录制完成`, `转 MP4 完成`, and output-file messages become one final result such as `录制完成并转为 MP4 · 1.2 GB · 00:35:26`.
- If conversion is still running, the event remains an intermediate `直播结束 · 等待转码` state and is updated on completion.
- If conversion fails, the final event reports failure and TS retention without hiding the actionable incident.
- Coalescing uses stable room/task identity and lifecycle identifiers, not message-text similarity alone.

Newest events appear first. The visible event budget is between three and ten rows after required header, configuration, attention, and room rows are allocated. Older events remain in state/log storage and are represented by an explicit hidden count.

## Responsive Behavior

### Width at Least 120 Columns

- Six room columns: index, name/platform, status, quality, duration/progress, detail.
- Four event columns: time, event, room, detail.
- Full runtime and configuration metadata.

### Width from 80 to 119 Columns

- Quality is merged into detail.
- Secondary header/configuration values are compacted.
- Room name, status, progress, and meaningful detail remain.
- Event rows preserve time, event label, room, and a truncated detail.

### Width Below 80 Columns

- Use compact line-oriented Rich output with minimal borders.
- Attention messages remain complete across wrapped lines.
- Normal room and event detail truncates before attention context.
- If Rich is unavailable or output is non-interactive, use the plain renderer.

### Height Allocation

Allocation priority is:

1. runtime and health header;
2. pinned actionable/recovering attention;
3. priority rooms;
4. at least three semantic events;
5. normal rooms;
6. additional events up to ten.

When the screen is too short even for the minimum layout, normal rooms are summarized first. No current actionable attention is hidden.

## Keyboard Input

Interactive Windows consoles support `R` and `r` as the only runtime dashboard command. Other ordinary keys are ignored while the application is running. Ctrl+C retains the current graceful/forced shutdown behavior.

Keyboard reading must be non-blocking and isolated from recording work. Non-interactive output does not start a key reader and remains in compact mode. When the application reaches the existing `收尾完成` phase, the current `按任意键退出` behavior takes precedence and the room toggle is disabled.

Keyboard-reader failure degrades to compact mode and cannot stop recording or dashboard refresh.

## Error Handling

- File-size or path-stat failure affects only the associated detail cell and never increments actionable error state.
- Presentation-model failure for one room produces a safe fallback row for that room and does not discard the dashboard.
- Keyboard-reader failure disables expansion and records a technical log entry.
- Unknown attention types use a conservative visible fallback without falsely claiming that human action is unnecessary.
- Rich import/render failure falls back to plain text when possible.
- Terminal resize recalculates width mode and row budgets on the next refresh.

## Cleanup and Dependencies

The rewrite removes old UI elements and their exclusive helpers, including metric cards, the card-style configuration region, the two-column event grid, duplicated plain/Rich formatting decisions, and tests tied only to the obsolete visual hierarchy.

Removal is evidence-based:

1. search static references;
2. check runtime/dynamic import and packaging wiring;
3. remove the code or dependency;
4. run focused and full verification.

Rich remains required. `tqdm` remains because the FFmpeg download/initializer path imports it. `requirements.txt` currently omits Rich while `pyproject.toml` declares it; the rewrite synchronizes them. No package is removed merely because it is not directly imported by the new renderer.

Generated build folders, ZIP artifacts, logs, downloads, and user configuration are not cleanup targets.

## Testing

Development follows test-first red-green-refactor cycles.

### Presentation Model

- priority ordering and stable tie-breaking;
- compact versus expanded budgets;
- explicit hidden-room and hidden-event counts;
- width modes at 79, 80, 119, and 120 columns;
- height pressure with guaranteed attention and three-event minimum;
- actionable, recovering, cleared, and unknown attention states;
- semantic event coalescing, conversion success, conversion failure, and repeated incidents.

### Rendering

- Rich snapshots/text assertions for wide, medium, and narrow layouts;
- plain output parity for attention and event meaning;
- safe truncation/wrapping for long Chinese names, paths, and errors;
- FFmpeg/disk/application-phase health rendering;
- absence of old metric cards and two-column event output.

### Input and Lifecycle

- `R` toggles display state without mutating runtime state;
- other keys are ignored;
- Ctrl+C remains connected to graceful and forced shutdown;
- non-interactive input creates no reader;
- `收尾完成` restores any-key exit precedence;
- reader failure safely disables interaction.

### Regression and Packaging

- focused dashboard and runtime wiring tests;
- full pytest suite;
- Ruff on changed Python and test files;
- deterministic Rich console renders at representative dimensions;
- PyInstaller build from the existing specification;
- packaged smoke checks for monitoring, recording, recovery, actionable failure, conversion, and graceful shutdown.

## Acceptance Criteria

The rewrite is accepted when:

1. a user can identify current human-action requirements from the header and pinned rows without reading the event timeline;
2. related recording lifecycle output appears as one semantic result rather than fragmented log lines;
3. compact mode favors abnormal and active rooms, while `R` exposes the maximum physically displayable room set and reports any remainder;
4. normal activity remains readable without large colored blocks or duplicate progress information;
5. current attention is never silently hidden at supported terminal sizes;
6. plain output preserves the same operational meaning;
7. old dashboard components and confirmed dead UI code are removed;
8. dependency declarations match verified runtime usage;
9. the full automated suite and packaged smoke test pass without changing recording behavior.
