# Graceful TS Remux and Progress Design

## Problem

The recorder is configured to save segmented TS files and remux them to MP4 after recording. On SIGINT or SIGTERM, `main.py` requests runtime shutdown, waits at most ten seconds, and then calls `sys.exit(0)`. The async runtime, recording workers, and legacy recording workers are daemon threads. Stopping FFmpeg alone may take up to fifteen seconds, and remuxing has no fixed upper bound, so the interpreter can terminate workers while post-processing is still active.

This explains the observed mix of MP4 and TS files: one remux may have completed or partially written its target while later TS files were never processed. The converter also catches FFmpeg errors internally, preventing `PostProcessor` from reporting a failed conversion.

## Required Behavior

1. The first SIGINT or SIGTERM requests a graceful shutdown.
2. Active recordings stop through their existing stop tokens.
3. Every successful TS recording is remuxed to MP4 before the process exits.
4. Conversion progress is visible as file position, percentage, and media time.
5. A second SIGINT or SIGTERM forces immediate termination.
6. A TS source is deleted only after a complete MP4 has been committed successfully.
7. Conversion failures preserve the TS source and are reported through the existing post-processing error channel.

## Architecture

### Conversion component

Move the FFmpeg conversion mechanics behind a focused recorder conversion component instead of keeping them embedded in `main.py`. The component accepts a source path, H.264 mode, source-deletion policy, and progress callback.

It probes media duration with `ffprobe`, starts FFmpeg with `-progress pipe:1 -nostats`, and parses machine-readable `key=value` records. `out_time_us` or `out_time_ms` is converted to elapsed media time. Percentage is clamped to the range 0–100 and is emitted monotonically. If duration probing fails, conversion still proceeds and reports elapsed time without a percentage rather than failing solely because progress metadata is unavailable.

For each source, FFmpeg writes to a sibling temporary path ending in `.converting.mp4`. On exit code zero, the component atomically replaces the final `.mp4` path and then deletes the TS source when configured. On nonzero exit, launch failure, or interrupted conversion, it removes only the temporary output, preserves the TS source, and raises a conversion exception containing bounded FFmpeg diagnostics.

Existing codec behavior remains unchanged:

- remux mode copies video and audio streams;
- H.264 mode encodes video with `libx264`, `veryfast`, CRF 23, and `yuv420p`, while copying audio.

### Progress presentation

`PostProcessor` already knows the ordered list of files, so it supplies the current file index and total count to the conversion callback. The console presentation is:

```text
[转MP4 2/3] 主播_2026-06-23_001.ts 47.2%  00:01:12 / 00:02:32
```

Updates are throttled by media progress and wall-clock time to avoid flooding redirected Rich dashboard output. At minimum, the presenter emits start, material progress changes, and completion. When duration is unknown it shows elapsed time and `--.-%`. Progress rendering is callback-driven and does not affect conversion success.

### Graceful and forced shutdown

The process-level signal handler keeps explicit shutdown state:

- on the first signal, set `exit_recording`, request async runtime shutdown, and wait for the runtime host to finish without the current ten-second cutoff;
- the runtime continues through FFmpeg stop, `PostProcessor`, and all conversions before its thread finishes;
- after the runtime and tracked legacy recording workers have drained, exit normally;
- on a repeated signal while draining, force immediate process termination with the conventional interrupted exit status.

The signal path logs that recording is stopping and post-processing may continue, so an apparently slow exit is understandable. The fix must preserve idempotent runtime shutdown and must not add arbitrary conversion timeouts.

## Data Flow

1. A stop signal sets the global exit intent and runtime stop token.
2. `RecorderProcess` asks FFmpeg to finish the TS cleanly.
3. A successful `EXIT_STOPPED` result remains eligible for post-processing.
4. `PostProcessor` enumerates real segment files in deterministic order.
5. The converter probes duration, emits progress, and writes a temporary MP4.
6. Successful FFmpeg completion commits the MP4 atomically and optionally removes the TS.
7. Failure preserves the TS and reaches `result.postprocess.errors`.
8. Shutdown returns only after all post-processing work completes, unless the user sends a second stop signal.

## Error Handling

- Missing or invalid TS: report a conversion error; never delete the source.
- `ffprobe` failure: continue with indeterminate progress.
- FFmpeg launch or nonzero exit: remove the temporary target, retain TS, propagate diagnostics.
- Progress callback failure: do not abort FFmpeg; log or suppress display-only errors.
- Existing final MP4: replace it only after the new temporary MP4 is complete.
- Forced second signal: no completion guarantee is made; any uncommitted temporary file may be cleaned on the next normal conversion attempt.

## Testing

Tests will be written before production changes and will cover:

1. parsing FFmpeg progress records and monotonic percentage calculation;
2. successful conversion atomically publishes MP4 and deletes TS only when requested;
3. failed conversion removes the temporary output, preserves TS, and raises an error;
4. duration-probe failure still permits conversion with indeterminate progress;
5. segmented post-processing reports correct file index and total count;
6. first signal requests shutdown and waits beyond ten seconds;
7. second signal selects the force-exit path;
8. existing recorder, runtime, configuration, and CLI tests remain green.

Because unit tests use fake subprocesses and controlled callbacks, they do not require real media or network access. A final integration check will use the bundled FFmpeg executables if available.

## Out of Scope

- Parallel remuxing of multiple segments.
- Resuming a partially encoded MP4.
- Automatically scanning and converting every historical TS file at startup.
- Changing recording formats or codec quality defaults.
