import ast
from pathlib import Path

MAIN_PATH = Path("main.py")


def start_record_source() -> str:
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "start_record")
    return ast.get_source_segment(source, function) or ""


def test_start_record_exposes_resolved_single_cycle_runtime_seam():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "start_record")
    arguments = {argument.arg for argument in function.args.args}

    assert {"resolved_once", "single_cycle", "stop_token", "session_state"} <= arguments


def test_resolved_single_cycle_bypasses_async_runner_and_stops_before_legacy_delay():
    source = start_record_source()

    assert "if resolved_once is not None:" in source
    assert "DispatchResult(" in source
    assert source.index("if single_cycle:") < source.index("num = random.randint")


def test_successful_recording_leaves_inner_probe_loop_before_post_record_delay():
    source = start_record_source()

    assert "count_time = time.time()\n                                break" in source


def test_recording_pipeline_stop_callbacks_include_runtime_token():
    source = start_record_source()

    assert "stop_token.room_stop_requested" in source
    assert "stop_token.shutdown_requested" in source
    assert 'session_state["start_pushed"]' in source


def test_main_builds_and_starts_registered_async_runtime():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "def build_async_runtime_runner" in source
    assert "RegisteredPlatformProbe(" in source
    assert "RecordingExecutor(" in source
    assert "ThreadedRuntimeHost(build_async_runtime_runner)" in source
    assert "start_async_runtime_host()" in source
    assert 'os.getenv("DLR_ASYNC_RUNTIME", "1")' in source
    assert "offline=record_registered_room" not in source


def test_display_info_reads_runtime_snapshot_for_registered_rooms():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "async_runtime_state_store" in source
    assert "snapshot = async_runtime_state_store.snapshot()" in source
    assert "for status in snapshot.statuses" in source
    assert "if status.monitoring and not status.stop_requested" in source


def test_main_reconciles_all_configured_rooms_into_dashboard_store():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "dashboard_store.reconcile_rooms" in source
    assert "DashboardStateStore(started_at=start_display_time)" in source


def test_dashboard_configuration_uses_cached_recording_directory_size():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "recording_size_cache.get(save_path)" in source
    assert "recordings_size_bytes=recordings_size_bytes" in source


def test_main_routes_lifecycle_callbacks_to_dashboard_store():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "dashboard_store.mark_recording" in source
    assert "dashboard_store.mark_converting" in source
    assert "dashboard_store.mark_recording_finished" in source


def test_recording_progress_updates_dashboard_without_high_frequency_prints():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "print(format_conversion_progress" not in source
    assert 'print(f"\\r{record_name} 等待直播' not in source
    assert "print(f\"\\r{anchor_name} 准备开始录制" not in source
    assert "直播录制完成\\n\")" not in source
    assert "print('\\r检测直播间中...'" not in source


def test_plain_and_rich_display_use_the_same_snapshot_builder():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "build_plain_dashboard(view)" in source
    assert "dashboard.update(view)" in source
    assert source.count("build_dashboard_view(") >= 3


def test_only_plain_fallback_writes_to_terminal_directly():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    print_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
    ]

    assert len(print_calls) == 1
    assert "build_plain_dashboard" in (ast.get_source_segment(source, print_calls[0]) or "")


def test_main_wires_one_dashboard_without_persistent_startup_panels():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "from src.cli_ui import (" in source
    assert "RichDashboard" in source
    assert "print_startup_banner(version, platforms)" not in source
    assert "print_ffmpeg_summary(version_line, built_line)" not in source
    assert "dashboard.update(view)" in source


def test_registered_rooms_are_excluded_from_legacy_threads_only_when_runtime_is_active():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "async_runtime_active() and default_registry.find(url_tuple[1]) is not None" in source


def test_signal_handler_requests_runtime_shutdown_before_exit():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "signal_handler")
    handler_source = ast.get_source_segment(source, function) or ""

    assert "request_shutdown" in handler_source
    assert "shutdown_control.request()" in handler_source
    assert "async_runtime_host.join()" in handler_source
    assert "join(timeout=10)" not in handler_source
    assert "signal.signal(signal.SIGINT, signal_handler)" in source
    assert "signal.signal(signal.SIGTERM, signal_handler)" in source
    assert "dashboard_store.set_phase(AppDisplayPhase.STOPPING)" in handler_source
    assert "dashboard_store.set_phase(AppDisplayPhase.COMPLETE)" in handler_source
    assert "request_upload_shutdown()" in handler_source
    assert "wait_for_exit_key()" not in handler_source
    assert "sys.exit(0)" not in handler_source
    assert "dashboard_refresh_event.set()" in handler_source
    assert handler_source.index("dashboard_store.set_phase(AppDisplayPhase.COMPLETE)") < handler_source.index(
        "dashboard_refresh_event.set()"
    )


def test_upload_worker_survives_recording_shutdown_until_upload_shutdown_is_requested():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upload_worker")
    worker_source = ast.get_source_segment(source, function) or ""

    assert "upload_shutdown_requested()" in worker_source
    assert "while not exit_recording and upload_generation_active(generation):" not in worker_source
    assert "upload_recording_finished_event.wait(1)" in worker_source


def test_dashboard_refresh_uses_wake_event_instead_of_fixed_sleep():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "dashboard_refresh_event = threading.Event()" in source
    assert "dashboard_refresh_event.wait(1)" in source
    assert "dashboard_refresh_event.clear()" in source


def test_start_record_stops_before_a_new_probe_when_shutdown_is_requested():
    source = start_record_source()
    guard = "if exit_recording or bool(stop_token and stop_token.shutdown_requested):"

    assert guard in source
    assert source.index(guard) < source.index("record_quality_zh, record_url, anchor_name = url_data")


def test_compatibility_scheduler_does_not_start_threads_during_shutdown():
    source = MAIN_PATH.read_text(encoding="utf-8")
    scheduling = source[source.index("if len(text_no_repeat_url) > 0:") :]

    assert "if exit_recording:" in scheduling
    assert scheduling.index("if exit_recording:") < scheduling.index("threading.Thread(target=start_record")


def test_compatibility_scheduler_uses_automatic_start_spacing():
    source = MAIN_PATH.read_text(encoding="utf-8")
    scheduling = source[source.index("if len(text_no_repeat_url) > 0:") :]

    assert "compatibility_candidates" in scheduling
    assert "calculate_legacy_first_start_spacing(" in scheduling
    assert "len(compatibility_candidates)" in scheduling
    assert "local_delay_default" in scheduling
    assert "time.sleep(compatibility_spacing)" in scheduling


def test_main_wires_atomic_converter_and_progress_presenter():
    source = MAIN_PATH.read_text(encoding="utf-8")
    start_source = start_record_source()

    assert "FFmpegConverter(" in source
    assert "dashboard_store.mark_converting(" in source
    assert "print(format_conversion_progress" not in source
    assert "converter=convert_recording_file" in start_source
    assert "ffmpeg_converter.convert(" in start_source
    assert "converts_mp4(" not in start_source


def test_main_wires_segment_finalizer_for_split_ts_conversion_uploads():
    source = MAIN_PATH.read_text(encoding="utf-8")
    start_source = start_record_source()

    assert "SegmentFinalizer" in source
    assert 'finalizer_ref["finalizer"]' in start_source
    assert "finalizer.scan()" in start_source
    assert "on_tick=scan_early_segment_finalizer" in start_source
    assert "notify_recording_finished_upload()" in start_source
    assert '"*.converting.mp4", "*.ts"' in source
    assert "exclude_patterns=upload_exclude_patterns" in source


def test_main_publishes_real_probe_and_recording_detail_data():
    source = MAIN_PATH.read_text(encoding="utf-8")
    start_source = start_record_source()

    assert "output_path=str(plan.output_path)" in start_source
    assert "dashboard_store.mark_monitoring(room.room_id)" in source
    assert "dashboard_store.mark_monitoring(status.room_id, checked=False)" in source
    assert 'f"{index}/{total} · {progress.source.name}"' in source


def test_conversion_only_marks_application_finalizing_during_shutdown():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "make_conversion_progress_callback"
    )
    callback_source = ast.get_source_segment(source, function) or ""

    assert "if exit_recording:" in callback_source
    assert "dashboard_store.set_phase(AppDisplayPhase.FINALIZING)" in callback_source


def test_main_skips_ffmpeg_gate_when_push_only_mode_is_enabled():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "initial_app_config = load_app_config(config_file, encoding=text_encoding)" in source
    assert "if not initial_app_config.push.disable_record and not check_ffmpeg_existence():" in source


def test_main_wires_first_probe_lifecycle_into_dashboard():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "dashboard_store.mark_initial_probe_started(room.room_id)" in source
    assert "dashboard_store.mark_initial_probe_finished(room.room_id)" in source


def test_dashboard_refresh_builds_one_shared_presentation_view_with_terminal_dimensions():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "build_dashboard_view(" in source
    assert "width=dashboard.console.size.width" in source
    assert "height=dashboard.console.size.height" in source
    assert "room_mode=dashboard_input.room_mode" in source
    assert "upload_detail_expanded=dashboard_input.upload_detail_expanded" in source
    assert "dashboard.update(view)" in source


def test_plain_dashboard_builds_the_same_view_model_in_compact_mode():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "RoomListMode.COMPACT" in source
    assert "build_plain_dashboard(view)" in source


def test_interactive_dashboard_starts_and_stops_the_key_reader():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "DashboardInputController" in source
    assert "DashboardKeyReader" in source
    assert "dashboard_key_reader.start()" in source
    assert "dashboard_key_reader.stop()" in source
    assert "dashboard_input.disable()" in source


def test_retry_and_recovery_paths_report_and_clear_stable_incidents():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "AttentionDisposition.AUTOMATIC" in source
    assert "dashboard_store.report_incident(" in source
    assert "dashboard_store.clear_incident(" in source
    assert '"probe"' in source
    assert '"recording-connection"' in source


def test_main_wires_auto_upload_config_status_and_service():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "create_upload_service" in source
    assert "resolve_upload_source" in source
    assert "prepare_upload_config_for_run" in source
    assert "def start_upload_service" in source
    assert "upload_config = current_config.upload" in source
    assert "dashboard_store.set_upload(" in source
    assert "DashboardUploadStatus(" in source
    assert "resolve_upload_source(upload_config, recording_save_path, default_path)" in source
    assert "create_upload_service(" in source
    assert "upload_config_for_run," in source
    assert "progress_callback=publish_upload_progress" in source
    assert "stop_requested=upload_shutdown_requested" in source
    assert "target=upload_worker" in source
    assert "start_upload_service(" in source
    assert "app_config.upload," in source
    assert "recording_cfg.save_path," in source
    assert "def publish_upload_progress" in source
    assert "def format_upload_progress" in source
    assert "def format_upload_bytes" in source


def test_main_upload_service_supports_config_hot_reload_generations():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "def upload_config_signature" in source
    assert "upload_service_generation" in source
    assert "upload_service_signature" in source
    assert "def upload_generation_active" in source
    assert "upload_generation_active(generation)" in source
    assert "upload_service_generation += 1" in source
    assert "args=(upload_config, recording_save_path, upload_service_generation" in source


def test_auto_upload_debounces_recording_finished_events_and_serializes_runs():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upload_worker")
    worker_source = ast.get_source_segment(source, function) or ""

    assert "UPLOAD_TRIGGER_DEBOUNCE_SECONDS" in source
    assert "upload_run_lock = threading.Lock()" in source
    assert "debounce_recording_finished_upload_trigger(generation)" in worker_source
    assert "acquire_upload_run_slot(generation, trigger, upload_config.remote_path)" in worker_source
    assert "upload_run_lock.acquire(timeout=1)" in source
    assert "upload_run_lock.release()" in worker_source
    assert "upload_service.run_once(source_path)" in worker_source


def test_auto_upload_runs_startup_recovery_scan_for_recording_finished_mode():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "start_upload_service"
    )
    start_source = ast.get_source_segment(source, function) or ""

    assert "initial_scan" in source
    assert 'upload_config.trigger_mode == "录制结束"' in start_source
    assert "args=(upload_config, recording_save_path, upload_service_generation, initial_scan)" in start_source
    assert "startup_recovery_upload" in start_source


def test_auto_upload_can_be_triggered_after_successful_recording_finishes():
    source = MAIN_PATH.read_text(encoding="utf-8")
    start_source = start_record_source()

    assert "upload_recording_finished_event = threading.Event()" in source
    assert "def notify_recording_finished_upload()" in source
    assert "upload_recording_finished_event.wait(1)" in source
    assert "cooldown_seconds = parse_rclone_duration_seconds(upload_config.min_age)" not in source
    assert "等待文件冷却" not in source
    assert 'upload_config.trigger_mode == "录制结束"' in source
    assert "upload_config_for_run = prepare_upload_config_for_run(upload_config)" in source
    assert "notify_recording_finished_upload()" in start_source
    success_check_index = start_source.index("result.process.reason.is_success")
    upload_notify_index = start_source.rindex("notify_recording_finished_upload()")
    assert success_check_index < upload_notify_index


def test_upload_worker_records_per_streamer_upload_results():
    source = MAIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upload_worker")
    worker_source = ast.get_source_segment(source, function) or ""

    assert "upload_snapshot_before = snapshot_upload_files(source_path)" in worker_source
    assert "upload_snapshot_after = snapshot_upload_files(source_path)" in worker_source
    assert "file_records = build_upload_file_records(" in worker_source
    assert "write_upload_file_records(file_records, next_status)" in worker_source
    assert "append_upload_record(next_status, result, file_records)" in worker_source


def test_upload_file_record_helpers_infer_streamer_without_database():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "def snapshot_upload_files" in source
    assert "def infer_upload_streamer" in source
    assert "def build_upload_file_records" in source
    assert "def write_upload_file_records" in source
    assert "upload_records.jsonl" in source
    assert "sqlite" not in source.lower()


def test_short_recording_completion_logs_raw_ffmpeg_tail():
    source = MAIN_PATH.read_text(encoding="utf-8")
    start_source = start_record_source()

    assert "result.process.output_tail" in source
    assert "sanitize_output_tail" not in start_source
    assert "recording_elapsed < 30" in source
    assert "on_probe_started=mark_initial_probe_started" in source
    assert "on_probe_finished=mark_initial_probe_finished" in source
    assert '"first_sweep_completed"' in source


def test_failed_recording_logs_raw_ffmpeg_tail_with_return_code():
    source = start_record_source()
    failure_source = source[source.index("else:") : source.index("if result.postprocess.errors:")]

    assert "result.process.output_tail" in failure_source
    assert '" | ".join(result.process.output_tail[-10:])' in failure_source
    assert "FFmpeg 尾部" in failure_source
    assert "logger.error" in failure_source


def test_legacy_threads_use_adaptive_first_start_spacing():
    source = MAIN_PATH.read_text(encoding="utf-8")

    assert "calculate_legacy_first_start_spacing(" in source
    assert "delay_default,\n                len(compatibility_candidates)" not in source
