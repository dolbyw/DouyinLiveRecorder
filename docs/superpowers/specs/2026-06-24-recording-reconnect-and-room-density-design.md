# Recording Reconnect and Room Density Design

## Problem

A room that remained live produced `直播结束` followed seconds later by `开始录制`. Evidence shows the application emitted `recording_finished` when FFmpeg exited successfully after seven seconds, then immediately detected the room as live and started another recording.

Two defects contribute:

1. The dashboard maps `recording_finished` to `直播结束`, although an FFmpeg process exit does not prove the platform live state ended.
2. HTTP reconnect options are placed after `-i` and omit `-reconnect 1`, so they are not reliably applied to the input protocol. FFmpeg output is not retained, leaving no diagnostic reason for short successful exits.

The compact room view also caps normal visibility at six rows despite the approved requirement for ten.

## Design

### Accurate Event Semantics

Map `recording_finished` to `录制结束`. Only a future event backed by an explicit platform probe reporting offline may use `直播结束`. A quick end/restart remains visible rather than being hidden or merged, because it is operationally meaningful.

### Finite Input Reconnect

Place these HTTP input options before `-i`:

- `-reconnect 1`
- `-reconnect_at_eof 1`
- `-reconnect_streamed 1`
- `-reconnect_on_network_error 1`
- `-reconnect_delay_max 5`
- `-reconnect_max_retries 5`

Finite retries bridge brief transport interruptions without trapping a genuinely ended stream forever. When retries are exhausted, the existing application-level probe obtains a fresh stream URL.

### FFmpeg Diagnostic Tail

Launch FFmpeg with merged stdout/stderr captured through a pipe. A daemon reader drains the pipe continuously into a bounded deque so the child cannot block on a full output buffer. `ProcessResult` carries the final bounded output tuple for successful, failed, stopped, and failed-to-start outcomes.

When a recording exits unusually quickly, `main.py` writes the return code and final output tail to the technical log. The live dashboard shows only the semantic event and does not expose URLs, headers, cookies, or full commands.

### Compact Room Density

Compact mode displays at most ten room rows when terminal height allows. Priority remains: action required, automatic recovery, recording, conversion, probing, retrying, then normal monitoring. At least three activity events remain reserved.

## Testing

- FFmpeg builder tests assert reconnect options exist before `-i`, include explicit values, and remain finite.
- Recorder process tests assert output is continuously drained and the bounded tail is returned for exit and stop paths.
- Dashboard view tests assert the event label is `录制结束` and compact mode shows ten rows when height permits.
- Main wiring tests assert short completion diagnostics use the process output tail.
- Full pytest, Ruff, PyInstaller, and isolated packaged startup verification remain required.

## Non-Goals

- Inferring platform offline state from FFmpeg exit.
- Hiding rapid recording restarts.
- Infinite FFmpeg reconnect attempts.
- Changing polling intervals, stream URL extraction, or recording filenames.
