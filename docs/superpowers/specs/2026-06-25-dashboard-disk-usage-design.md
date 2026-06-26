# Dashboard Disk Usage Design

## Goal

The main dashboard will show two disk-related values:

- `已占用`: total size of recorded video files under the active save directory.
- `剩余`: free space on the drive that contains the active save directory.

The active save directory is the configured recording save path. If the user has not changed it, the directory is the program's default `downloads` folder under the current program directory.

## UI

Use layout A in the dashboard header health area:

```text
✓ FFmpeg 正常    ✓ 已占用 128.6 GB    ✓ 剩余 424.3 GB
```

The existing `磁盘` health item will be replaced by the two clearer items above. `已占用` reports the cached directory size. `剩余` reports drive free space from the same target path.

When a value cannot be read, show `未知`. If free space is low, keep the current warning behavior for the `剩余` item.

## Storage Scope

Only the active save directory is scanned:

- Default: `<program directory>/downloads`.
- Custom: the configured save path from `config/config.ini`.

The scan excludes unrelated project directories such as `build`, `dist`, package archives, dependencies, logs, and test output unless the user explicitly configured the save path to point there.

## Performance And Disk Health

The dashboard refreshes about once per second, but directory size scanning must not run at that cadence.

Use a small cache with a low-frequency refresh interval, such as 5 minutes:

- `shutil.disk_usage(save_path)` may run during dashboard configuration refresh because it is a cheap filesystem metadata query.
- Recursive directory size calculation runs only when the cache is stale or the save path changes.
- The scan reads directory entries and file metadata only; it does not open or read video file contents.
- Errors such as missing directories, permission issues, or transient files being moved during conversion are handled as `未知` without blocking recording.

This keeps the UI informative without continuous disk traversal.

## Components

`src/dashboard_state.py`

- Add a recording-size field to `DashboardConfig`, preferably bytes to avoid precision loss in state.

`main.py`

- Resolve the active save path using the current recording config and existing default path logic.
- Add a cache helper for total recorded-file size.
- Refresh the cache only when stale or when the save path changes.
- Pass the cached size into `DashboardConfig`.

`src/dashboard_view.py`

- Format the cached size as human-readable bytes.
- Render health entries as `已占用` and `剩余`.

`src/cli_ui.py`

- Reuse the existing health renderer. No layout rewrite is needed.

## Tests

Focused tests should cover:

- Dashboard view renders `已占用` and `剩余`.
- Unknown size renders as `未知`.
- The cached scanner does not rescan before its interval expires.
- A save path change invalidates or refreshes the cached size.
- Missing or inaccessible paths do not raise into the dashboard.
