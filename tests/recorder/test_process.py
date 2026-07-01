import io
import signal
import subprocess

from src.recorder.models import EndReason
from src.recorder.process import RecorderProcess, sanitize_output_tail


class FakeProcess:
    def __init__(self, polls, wait_code=0, output=b""):
        self.polls = iter(polls)
        self.wait_code = wait_code
        self.stdin = io.BytesIO()
        self.signals = []
        self.wait_timeouts = []
        self.kills = 0
        self.stdout = io.BytesIO(output)

    def poll(self):
        return next(self.polls, self.wait_code)

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return self.wait_code

    def send_signal(self, sent_signal):
        self.signals.append(sent_signal)

    def kill(self):
        self.kills += 1


def make_runner(process, platform_name="Windows"):
    return RecorderProcess(
        process_factory=lambda *args, **kwargs: process, sleep=lambda _seconds: None, platform_name=platform_name
    )


def test_natural_zero_exit_is_completed():
    result = make_runner(FakeProcess([0])).run(["ffmpeg"], should_comment_stop=lambda: False, should_exit=lambda: False)
    assert result.reason is EndReason.COMPLETED
    assert result.return_code == 0


def test_running_process_invokes_tick_callback_between_polls():
    ticks = []

    result = make_runner(FakeProcess([None, 0])).run(
        ["ffmpeg"],
        should_comment_stop=lambda: False,
        should_exit=lambda: False,
        on_tick=lambda: ticks.append("tick"),
    )

    assert result.reason is EndReason.COMPLETED
    assert ticks == ["tick"]


def test_nonzero_exit_is_failed_and_keeps_return_code():
    result = make_runner(FakeProcess([7])).run(["ffmpeg"], should_comment_stop=lambda: False, should_exit=lambda: False)
    assert result.reason is EndReason.FAILED
    assert result.return_code == 7


def test_process_drains_output_and_returns_bounded_tail():
    process = FakeProcess([0], output=b"first\nsecond\nthird\n")
    captured_kwargs = {}

    def factory(*_args, **kwargs):
        captured_kwargs.update(kwargs)
        return process

    runner = RecorderProcess(
        process_factory=factory,
        sleep=lambda _seconds: None,
        platform_name="Windows",
        output_tail_lines=2,
    )

    result = runner.run(["ffmpeg"], should_comment_stop=lambda: False, should_exit=lambda: False)

    assert captured_kwargs["stdout"] is subprocess.PIPE
    assert captured_kwargs["stderr"] is subprocess.STDOUT
    assert result.output_tail == ("second", "third")


def test_sanitize_output_tail_redacts_urls_and_sensitive_headers():
    lines = (
        "HTTP error for https://example.com/live.m3u8?token=secret",
        "Cookie: session=secret Referer: https://example.com/room",
    )

    assert sanitize_output_tail(lines) == (
        "HTTP error for [URL]",
        "Cookie: [REDACTED]",
    )


def test_factory_exception_is_failed_to_start():
    error = OSError("missing ffmpeg")

    def broken_factory(*args, **kwargs):
        raise error

    result = RecorderProcess(process_factory=broken_factory).run(
        ["ffmpeg"], should_comment_stop=lambda: False, should_exit=lambda: False
    )
    assert result.reason is EndReason.FAILED_TO_START
    assert result.error is error


def test_windows_comment_stop_writes_q_once_and_waits():
    process = FakeProcess([None])
    result = make_runner(process).run(["ffmpeg"], should_comment_stop=lambda: True, should_exit=lambda: False)
    assert result.reason is EndReason.COMMENT_STOPPED
    assert process.stdin.getvalue() == b"q"
    assert process.wait_timeouts == [15]


def test_posix_exit_stop_sends_sigint_once_and_waits():
    process = FakeProcess([None])
    result = make_runner(process, "Linux").run(["ffmpeg"], should_comment_stop=lambda: False, should_exit=lambda: True)
    assert result.reason is EndReason.EXIT_STOPPED
    assert process.signals == [signal.SIGINT]
    assert process.wait_timeouts == [15]


def test_requested_windows_stop_treats_ffmpeg_255_as_graceful_exit():
    process = FakeProcess([None], wait_code=255)

    result = make_runner(process).run(["ffmpeg"], should_comment_stop=lambda: False, should_exit=lambda: True)

    assert result.reason is EndReason.EXIT_STOPPED
    assert result.return_code == 255


def test_polled_255_after_requested_exit_is_graceful():
    result = make_runner(FakeProcess([255])).run(
        ["ffmpeg"],
        should_comment_stop=lambda: False,
        should_exit=lambda: True,
    )

    assert result.reason is EndReason.EXIT_STOPPED
    assert result.return_code == 255


def test_polled_255_without_stop_request_is_failed():
    result = make_runner(FakeProcess([255])).run(
        ["ffmpeg"],
        should_comment_stop=lambda: False,
        should_exit=lambda: False,
    )

    assert result.reason is EndReason.FAILED
    assert result.return_code == 255


def test_stop_timeout_kills_and_reaps_process():
    process = FakeProcess([None])
    waits = iter([subprocess.TimeoutExpired("ffmpeg", 15), 9])

    def wait(timeout=None):
        process.wait_timeouts.append(timeout)
        result = next(waits)
        if isinstance(result, BaseException):
            raise result
        return result

    process.wait = wait
    result = make_runner(process).run(["ffmpeg"], should_comment_stop=lambda: True, should_exit=lambda: False)
    assert result.reason is EndReason.FAILED
    assert result.return_code == 9
    assert process.kills == 1
    assert process.wait_timeouts == [15, 5]
