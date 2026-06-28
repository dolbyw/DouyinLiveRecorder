# Bundled Rclone Build Design

## Goal

Windows release builds should include a working `rclone.exe` so users do not need to install rclone manually. The packaged `config/config.ini` should point to the bundled executable by default, while still allowing advanced users to override the path.

## Approach

Add rclone handling to `DouyinLiveRecorder.spec`, following the existing FFmpeg bundle pattern:

- Prefer `DLR_RCLONE_DIR` when set, copying `rclone.exe` from that directory.
- Otherwise prefer a checked-in or locally supplied `rclone/rclone.exe` directory if present.
- Otherwise download the latest stable Windows AMD64 rclone zip from the official rclone release endpoint during packaging.
- Extract only `rclone.exe` into `build/bundle_assets/rclone/`.
- Include that directory in PyInstaller `datas` as `rclone`.

## Configuration

The packaged release config should default to:

```ini
rclone可执行文件路径 = rclone\rclone.exe
```

This keeps the config portable after users unzip the release anywhere. Runtime upload code should resolve relative `rclone可执行文件路径` values against the executable/script directory before launching rclone. Absolute paths continue to work unchanged.

## Error Handling

If the download or extraction fails during packaging, the build should fail with a clear message rather than producing a release missing rclone. If runtime config points to a missing executable, the existing upload error should clearly tell the user which path was tried and which config option controls it.

## Tests

Add focused unit tests for:

- Build helpers choosing a supplied local rclone directory.
- Build helpers extracting rclone from a downloaded zip shape.
- Config/default-package helper writing the relative bundled rclone path.
- Runtime command builders resolving relative `rclone\rclone.exe` from the application root while preserving absolute paths.

Full verification should run the Python test suite. A real package build should be run when practical because PyInstaller spec code is executed by the packaging tool.
