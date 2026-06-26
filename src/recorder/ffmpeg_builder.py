from __future__ import annotations

from collections.abc import Callable

from .models import OutputPlan, RecordRequest, SaveFormat

_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 11; SAMSUNG SM-G973U) AppleWebKit/537.36 "
    "(KHTML, like Gecko) SamsungBrowser/14.2 Chrome/87.0.4280.141 Mobile Safari/537.36"
)


class FFmpegBuilder:
    def __init__(self, executable: str = "ffmpeg") -> None:
        self.executable = executable
        self._strategies: dict[SaveFormat, Callable[[RecordRequest], list[str]]] = {
            SaveFormat.TS: self._ts,
            SaveFormat.FLV: self._flv,
            SaveFormat.MKV: self._mkv,
            SaveFormat.MP4: self._mp4,
            SaveFormat.MP3: self._mp3,
            SaveFormat.M4A: self._m4a,
        }

    def build(self, request: RecordRequest, plan: OutputPlan) -> list[str]:
        if plan.save_format is not request.effective_format:
            raise ValueError("output plan does not match request effective format")
        command = [self.executable]
        if request.proxy:
            command.extend(["-http_proxy", request.proxy])
        command.extend(self._input_options(request))
        command.extend(self._strategies[plan.save_format](request))
        command.append(str(plan.output_path))
        return command

    @staticmethod
    def _input_options(request: RecordRequest) -> list[str]:
        if request.overseas:
            rw_timeout, analyzeduration, probesize, bufsize, mux_queue = (
                "50000000",
                "40000000",
                "20000000",
                "15000k",
                "2048",
            )
        else:
            rw_timeout, analyzeduration, probesize, bufsize, mux_queue = (
                "15000000",
                "20000000",
                "10000000",
                "8000k",
                "1024",
            )
        options = [
            "-y",
            "-v",
            "verbose",
            "-rw_timeout",
            rw_timeout,
            "-loglevel",
            "error",
            "-hide_banner",
        ]
        if request.headers:
            options.extend(["-headers", request.headers])
        if request.source_url.startswith(("http://", "https://")):
            options.extend(
                [
                    "-reconnect",
                    "1",
                    "-reconnect_at_eof",
                    "1",
                    "-reconnect_streamed",
                    "1",
                    "-reconnect_on_network_error",
                    "1",
                    "-reconnect_delay_max",
                    "5",
                    "-reconnect_max_retries",
                    "5",
                ]
            )
        options.extend(
            [
                "-user_agent",
                _USER_AGENT,
                "-protocol_whitelist",
                "rtmp,crypto,file,http,https,tcp,tls,udp,rtp,httpproxy",
                "-thread_queue_size",
                "1024",
                "-analyzeduration",
                analyzeduration,
                "-probesize",
                probesize,
                "-fflags",
                "+discardcorrupt",
                "-re",
                "-i",
                request.source_url,
                "-bufsize",
                bufsize,
                "-sn",
                "-dn",
                "-max_muxing_queue_size",
                mux_queue,
                "-correct_ts_overflow",
                "1",
                "-avoid_negative_ts",
                "1",
            ]
        )
        return options

    @staticmethod
    def _segment(request: RecordRequest, segment_format: str | None = None) -> list[str]:
        options = ["-f", "segment", "-segment_time", str(request.segment_seconds)]
        if segment_format:
            options.extend(["-segment_format", segment_format])
        options.extend(["-reset_timestamps", "1"])
        return options

    def _ts(self, request: RecordRequest) -> list[str]:
        options = ["-map", "0", "-c:v", "copy", "-c:a", "copy"]
        if request.split:
            return options + self._segment(request, "mpegts")
        return options + ["-f", "mpegts"]

    def _flv(self, request: RecordRequest) -> list[str]:
        options = ["-map", "0", "-c:v", "copy", "-c:a", "copy", "-bsf:a", "aac_adtstoasc"]
        if request.split:
            return options + self._segment(request, "flv")
        return options + ["-f", "flv"]

    def _mkv(self, request: RecordRequest) -> list[str]:
        options = ["-map", "0", "-c:v", "copy"]
        options.extend(["-c:a", "aac"] if request.split else ["-c:a", "copy"])
        if request.split:
            return options + self._segment(request, "matroska")
        return options + ["-f", "matroska"]

    def _mp4(self, request: RecordRequest) -> list[str]:
        options = ["-map", "0", "-c:v", "copy"]
        if request.split:
            options.extend(["-c:a", "aac", "-movflags", "+frag_keyframe+empty_moov"])
            return options + self._segment(request, "mp4")
        return options + ["-c:a", "copy", "-movflags", "+faststart"]

    def _mp3(self, request: RecordRequest) -> list[str]:
        options = ["-map", "0:a", "-c:a", "libmp3lame", "-ab", "320k"]
        return options + self._segment(request, "mp3") if request.split else options

    def _m4a(self, request: RecordRequest) -> list[str]:
        options = ["-map", "0:a", "-c:a", "aac", "-bsf:a", "aac_adtstoasc", "-ab", "320k"]
        if request.split:
            return options + self._segment(request, "ipod")
        return options + ["-movflags", "+faststart", "-f", "ipod"]
