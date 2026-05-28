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

    def video_args(self) -> list[str]:
        return [
            "-c:v",
            self.vcodec,
            "-preset",
            self.preset,
            "-crf",
            str(self.crf),
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
        return {
            "vcodec": self.vcodec,
            "preset": self.preset,
            "crf": self.crf,
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
        return {
            "acodec": self.acodec,
            "audio_bitrate": self.audio_bitrate,
            "ar": self.ar,
            "ac": self.ac,
        }
