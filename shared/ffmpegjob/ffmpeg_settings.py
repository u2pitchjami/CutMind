from __future__ import annotations

from dataclasses import dataclass

from shared.utils.settings import get_settings


@dataclass(slots=True, frozen=True)
class FFmpegExportSettings:
    vcodec: str
    preset: str
    pix_fmt: str
    crf: int
    profile_v: str
    color_primaries: str
    color_trc: str
    colorspace: str
    vsync: str
    tag_v: str
    movflags: str
    acodec: str
    audio_bitrate: str
    ar: int
    ac: int

    @classmethod
    def from_settings(cls) -> FFmpegExportSettings:
        settings = get_settings()

        return cls(
            vcodec=settings.ffsmartcut.vcodec,
            preset=settings.ffsmartcut.preset,
            pix_fmt=settings.ffsmartcut.pix_fmt,
            crf=settings.ffsmartcut.crf,
            profile_v=settings.ffsmartcut.profile_v,
            color_primaries=settings.ffsmartcut.color_primaries,
            color_trc=settings.ffsmartcut.color_trc,
            colorspace=settings.ffsmartcut.colorspace,
            vsync=settings.ffsmartcut.vsync,
            tag_v=settings.ffsmartcut.tag_v,
            movflags=settings.ffsmartcut.movflags,
            acodec=settings.ffsmartcut.acodec,
            audio_bitrate=settings.ffsmartcut.audio_bitrate,
            ar=settings.ffsmartcut.ar,
            ac=settings.ffsmartcut.ac,
        )

    @property
    def is_nvenc(self) -> bool:
        """Return True when the configured video encoder uses NVENC."""
        return self.vcodec in {"hevc_nvenc", "h264_nvenc"}

    def video_quality_args(self) -> list[str]:
        """
        Build encoder-specific quality arguments.

        libx265:
            -crf <value>

        NVENC:
            -rc vbr -cq <value> -b:v 0

        Note:
            `crf` is temporarily reused as the configured quality value
            for NVENC. CRF and CQ are not equivalent quality scales.
        """
        if self.is_nvenc:
            return [
                "-rc",
                "vbr",
                "-cq",
                str(self.crf),
                "-b:v",
                "0",
            ]

        return [
            "-crf",
            str(self.crf),
        ]

    def video_quality_kwargs(self) -> dict[str, str | int]:
        """
        Build encoder-specific quality kwargs for ffmpeg-python.
        """
        if self.is_nvenc:
            return {
                "rc": "vbr",
                "cq": self.crf,
                "b:v": "0",
            }

        return {
            "crf": self.crf,
        }

    def video_args(self) -> list[str]:
        """Build common video arguments for FFmpeg subprocess calls."""
        return [
            "-c:v",
            self.vcodec,
            "-preset",
            self.preset,
            *self.video_quality_args(),
            "-pix_fmt",
            self.pix_fmt,
            "-profile:v",
            self.profile_v,
            "-color_primaries",
            self.color_primaries,
            "-color_trc",
            self.color_trc,
            "-colorspace",
            self.colorspace,
            "-vsync",
            self.vsync,
            "-tag:v",
            self.tag_v,
            "-movflags",
            self.movflags,
        ]

    def audio_args(self) -> list[str]:
        """Build common audio arguments for FFmpeg subprocess calls."""
        return [
            "-c:a",
            self.acodec,
            "-b:a",
            self.audio_bitrate,
            "-ar",
            str(self.ar),
            "-ac",
            str(self.ac),
        ]

    def video_kwargs(self) -> dict[str, str | int]:
        """Build common video kwargs for ffmpeg-python."""
        return {
            "vcodec": self.vcodec,
            "preset": self.preset,
            **self.video_quality_kwargs(),
            "pix_fmt": self.pix_fmt,
            "color_primaries": self.color_primaries,
            "color_trc": self.color_trc,
            "colorspace": self.colorspace,
            "vsync": self.vsync,
            "movflags": self.movflags,
            "profile:v": self.profile_v,
            "tag:v": self.tag_v,
        }

    def audio_kwargs(self) -> dict[str, str | int]:
        """Build common audio kwargs for ffmpeg-python."""
        return {
            "acodec": self.acodec,
            "audio_bitrate": self.audio_bitrate,
            "ar": self.ar,
            "ac": self.ac,
        }
