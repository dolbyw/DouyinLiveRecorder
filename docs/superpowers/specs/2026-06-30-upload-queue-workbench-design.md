# Upload Queue And Workbench Design

## Goal

Build a robust automatic upload system for long-running recording sessions, while keeping the existing recording dashboard as the default main interface.

The upload feature should handle many videos across nested recording folders, safely compare local and remote state, avoid data loss when duplicate remote files exist, and expose upload status through a separate read-only upload workbench window.

## User Decisions

- When a remote path already has a file with the same relative path but different content, upload the local file with a renamed filename and keep both copies.
- The application should still open to the normal recording dashboard.
- Each recording room row should show only brief upload information.
- Pressing `U` should open a separate upload workbench console window.
- Closing the upload workbench must not affect recording or upload execution.
- The upload workbench is read-only in the first version. It does not pause, retry, delete, or rescan.
- The simplified upload workbench layout is approved.

## Current Limitations

The current implementation delegates most behavior to a single `rclone move` over one source directory. This works for basic uploads, but it is not enough for a resilient long-running uploader:

- It has one coarse upload status instead of per-file task state.
- It does not persist upload progress across process restarts.
- It relies mostly on rclone's default local/remote comparison.
- It cannot explain duplicate handling clearly.
- It has limited visibility in the main dashboard.
- It treats uploads as one service loop rather than a durable queue.

## Proposed Architecture

### Main Process

The main application remains the only process that performs real work:

- Records live streams.
- Scans local recording directories.
- Builds upload tasks.
- Compares local files with remote files.
- Uploads files.
- Verifies remote results.
- Deletes local files only after verification.
- Writes upload state snapshots.

The main process owns all mutable upload state. This prevents the upload workbench from accidentally stopping or mutating uploads.

### Upload Queue

Introduce a durable upload queue backed by SQLite.

Each upload task represents one local file and contains:

- Local path.
- Relative path under the upload source root.
- Planned remote path.
- File size.
- Modified time.
- Room or streamer label if discoverable.
- Status: waiting, cooling, comparing, uploading, verifying, done, skipped, renamed, failed.
- Attempt count.
- Last error.
- Last status update time.

The queue survives application restarts. On startup, the scanner reconciles the queue with the local filesystem and remote index.

### Scanner

The scanner walks configured source roots and finds eligible files.

A file becomes uploadable only when:

- It is not a temporary or partial recording artifact.
- It is not currently being written by the recorder or converter.
- Its size and modified time have remained stable for the configured cooling interval.
- It is not already complete in the queue.

The scanner should support nested folders and multiple room directories under a shared recording root.

### Remote Difference Planner

Before uploading, the uploader builds or refreshes a remote index with `rclone lsjson`.

For each local file:

- If the remote relative path does not exist, upload normally.
- If the remote path exists and appears equivalent, mark as skipped or already uploaded.
- If the remote path exists but differs, rename the local upload target and keep both copies.
- If the remote cannot be listed, fail safely and keep local files.

Equivalence should prefer hashes when supported. For WebDAV providers such as 123pan where hashes are unavailable, use size plus remote existence, with optional delayed recheck for known flaky responses.

### Duplicate Naming

For same-path remote conflicts, use deterministic rename behavior:

- `name.ext`
- `name (2).ext`
- `name (3).ext`

The planner checks remote existence before selecting the final name. The selected target path is persisted in the queue so retries use the same target and do not create endless new names.

### Upload Execution

Upload execution should be file-level or small batch-level, not one large source-directory move.

Recommended flow:

1. Copy local file to planned remote path.
2. Verify remote file exists and matches expected size/hash.
3. Delete local file only after verification.
4. Remove empty local folders if configured.
5. Mark task complete.

This is safer than direct `move`, especially for WebDAV providers that may return misleading errors after a successful upload.

### Error Handling

Errors should be classified:

- Authentication failure: action required.
- Remote permission or path failure: action required.
- Network timeout: automatic retry.
- Provider throttling: automatic retry with backoff.
- Remote conflict: automatic rename according to policy.
- Remote verification mismatch: keep local file and mark failed.
- Known 123pan `object not found` after upload: verify remote file before treating as success.

Retries should use backoff and should never delete local files unless verification succeeds.

## Main Recording Dashboard

The default dashboard remains focused on recording.

Each room row may show brief upload status only:

- `待上传 2`
- `上传中 62%`
- `已上传`
- `上传失败`
- `远端重名，已改名`

The health/config area can show aggregate upload status:

- Upload enabled or disabled.
- Uploading count.
- Waiting count.
- Failed count.

The main dashboard should not become an upload operations screen.

## Upload Workbench Window

Pressing `U` opens a separate console window.

The workbench is a read-only observer:

- It reads upload state snapshots or SQLite state.
- It does not call rclone directly.
- It does not own upload threads.
- It does not write task state.
- Closing it has no effect on recording or upload.

If the workbench is already open, pressing `U` should avoid launching duplicate windows. The first version can either focus the existing window when possible or display a main-dashboard event saying the workbench is already open.

The workbench can be closed with normal window close, `Q`, or `Esc`.

## Workbench Layout

Use the approved simplified layout:

- Top counters: uploading, waiting, verifying, conflicts, failed.
- Left area:
  - Current uploads.
  - Next queue items.
- Right area:
  - Upload strategy.
  - Remote name/path.
  - Status summary.
- Bottom:
  - One-line difference summary.

No quick action buttons in the first version.

## State Sharing

The main process should publish a compact upload snapshot for the workbench and main dashboard.

Recommended snapshot fields:

- Aggregates: uploading, waiting, verifying, conflicts, failed, completed today.
- Current tasks: filename, percent, speed, ETA, remote path.
- Next tasks: filename, reason/status.
- Recent status summary.
- Difference summary.
- Last update time.

The snapshot can be written as JSON for easy read-only consumption. SQLite remains the durable source of truth.

## Testing Strategy

Unit tests:

- File cooling and stable-file detection.
- Local/remote difference planning.
- Duplicate rename selection.
- Safe delete after successful verification.
- Failure classification.
- 123pan `object not found` verification fallback.

Integration tests:

- Multiple nested room directories with dozens of files.
- Remote contains identical files.
- Remote contains same-path different files.
- Remote listing fails.
- Process restart with partially completed queue.
- Workbench starts and exits without affecting uploader.

Manual smoke tests:

- Packaged rclone exists and runs.
- WebDAV remote can be configured from `config.ini`.
- A small file uploads to 123pan.
- The file is visible remotely.
- Local source is deleted only after verification.
- Workbench close does not stop upload or recording.

## Rollout Plan

Phase 1:

- Introduce queue and planner.
- Keep existing config mostly compatible.
- Add read-only upload snapshot.
- Add main-dashboard brief upload status.

Phase 2:

- Add separate upload workbench console.
- Press `U` opens the observer window.
- Workbench reads state only.

Phase 3:

- Expand remote-difference handling and provider-specific resilience.
- Add richer diagnostics if needed.

## Non-Goals For First Version

- Upload control buttons in the workbench.
- Multiple remote destinations.
- GUI/browser-based workbench.
- User-triggered deletion from the workbench.
- Complex bandwidth scheduling.

