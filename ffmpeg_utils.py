"""FFmpeg utilities for video processing."""

import asyncio
import logging
import math
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import config

logger = logging.getLogger(__name__)


class FFmpegError(Exception):
    """Raised when FFmpeg/FFprobe fails."""
    pass


async def _run(cmd: List[str], timeout: int = 600) -> str:
    """Run an FFmpeg/FFprobe command asynchronously."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        raise FFmpegError(f"Command timed out after {timeout}s")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="ignore")[-1200:]
        raise FFmpegError(f"FFmpeg error (rc={proc.returncode}): {err}")

    return stdout.decode("utf-8", errors="ignore")


async def get_duration(path: Path) -> float:
    """Return video duration in seconds."""
    cmd = [
        config.FFPROBE, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    out = await _run(cmd, timeout=60)
    try:
        duration = float(out.strip())
    except ValueError as exc:
        raise FFmpegError(f"Invalid duration output: {out!r}") from exc
    if duration <= 0:
        raise FFmpegError("Video duration is zero or negative")
    return duration


async def get_video_info(path: Path) -> dict:
    """Return duration (int seconds), width, height of the first video stream."""
    width, height, duration = 0, 0, 0

    # Duration
    try:
        duration = int(await get_duration(path))
    except Exception:
        duration = 0

    # Width / height
    try:
        cmd = [
            config.FFPROBE, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(path),
        ]
        out = await _run(cmd, timeout=30)
        parts = out.strip().split(",")
        if len(parts) >= 2:
            width = int(float(parts[0]))
            height = int(float(parts[1]))
    except Exception as exc:
        logger.warning("Could not read width/height: %s", exc)

    return {"duration": max(duration, 0), "width": width or 0, "height": height or 0}


async def generate_thumbnail(video_path: Path, thumb_path: Path, at_sec: float = 1.0) -> Optional[Path]:
    """Extract a single frame as JPEG thumbnail. Returns path or None on failure."""
    try:
        # Seek a bit into the video so we don't get a black first frame
        duration = await get_duration(video_path)
        seek = min(max(at_sec, 0.5), max(duration * 0.1, 0.5))
        if duration > 0 and seek >= duration:
            seek = max(0.0, duration / 2)

        cmd = [
            config.FFMPEG, "-y",
            "-ss", str(seek),
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            "-vf", "scale=320:-1",
            str(thumb_path),
        ]
        await _run(cmd, timeout=60)
        if thumb_path.exists() and thumb_path.stat().st_size > 500:
            return thumb_path
    except Exception as exc:
        logger.warning("Thumbnail generation failed: %s", exc)
    return None


async def get_video_bitrate(path: Path) -> Optional[int]:
    """Return video stream bitrate in bits per second."""
    cmd = [
        config.FFPROBE, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=bit_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = await _run(cmd, timeout=30)
        out = out.strip()
        if out and out != "N/A":
            return int(out)
    except Exception:
        pass
    return None


def _build_reencode_cmd(
    input_path: Path,
    output_path: Path,
    start: float,
    duration: float,
    bitrate: Optional[int],
) -> List[str]:
    cmd = [
        config.FFMPEG, "-y",
        "-ss", str(start),
        "-i", str(input_path),
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-threads", "2",
    ]
    if bitrate and bitrate > 0:
        cmd += ["-b:v", str(bitrate)]
    else:
        cmd += ["-crf", "23"]
    cmd += [
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    return cmd


async def split_video(
    input_path: Path,
    output_dir: Path,
    clip_duration: float,
    status_callback: Callable,
) -> List[Path]:
    """Split video into fixed-duration clips. Copy mode first, then re-encode."""
    total_duration = await get_duration(input_path)
    total_clips = math.ceil(total_duration / clip_duration)
    ext = input_path.suffix.lower() if input_path.suffix else ".mp4"
    if ext not in (".mp4", ".mkv", ".webm", ".mov"):
        ext = ".mp4"
    clips: List[Path] = []
    bitrate = await get_video_bitrate(input_path)

    for idx in range(total_clips):
        start = idx * clip_duration
        remaining = total_duration - start
        duration = min(clip_duration, remaining)
        output_path = output_dir / f"part_{idx + 1:04d}{ext}"

        await status_callback(f"✂️ Splitting… Part {idx + 1}/{total_clips}")

        cmd_copy = [
            config.FFMPEG, "-y",
            "-ss", str(start),
            "-i", str(input_path),
            "-t", str(duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts",
            str(output_path),
        ]

        try:
            await _run(cmd_copy, timeout=config.SPLIT_TIMEOUT)
        except FFmpegError:
            logger.warning("Copy split failed for part %d, re-encoding…", idx + 1)
            cmd_re = _build_reencode_cmd(input_path, output_path, start, duration, bitrate)
            await _run(cmd_re, timeout=config.SPLIT_TIMEOUT)

        if not output_path.exists() or output_path.stat().st_size < 1000:
            raise FFmpegError(f"Part {idx + 1} was not created properly")

        clips.append(output_path)

    return clips


async def merge_videos(
    clip_paths: List[Path],
    output_path: Path,
    status_callback: Callable,
) -> Path:
    """Merge clips. Copy mode first, fallback re-encode."""
    if not clip_paths:
        raise FFmpegError("No clips provided")

    list_path = output_path.with_suffix(".txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for clip in clip_paths:
            # Escape single quotes for ffmpeg concat
            safe = str(clip).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    await status_callback("🔗 Merging clips…")

    cmd_copy = [
        config.FFMPEG, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_path),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        await _run(cmd_copy, timeout=config.CONVERT_TIMEOUT)
    except FFmpegError:
        logger.warning("Copy merge failed, re-encoding…")
        bitrate = await get_video_bitrate(clip_paths[0])
        cmd_re = [
            config.FFMPEG, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_path),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-threads", "2",
        ]
        if bitrate and bitrate > 0:
            cmd_re += ["-b:v", str(bitrate)]
        else:
            cmd_re += ["-crf", "23"]
        cmd_re += [
            "-c:a", "aac",
            "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]
        await _run(cmd_re, timeout=config.CONVERT_TIMEOUT)
    finally:
        list_path.unlink(missing_ok=True)

    if not output_path.exists():
        raise FFmpegError("Merged file was not created")
    return output_path


def _parse_time(text: str) -> float:
    text = text.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        raise ValueError(f"Invalid time format: {text}")
    return float(text)


def parse_time_ranges(text: str, max_duration: float) -> List[Tuple[float, float]]:
    """Parse time ranges. Supports HH:MM:SS-HH:MM:SS, MM:SS-MM:SS, seconds, commas or newlines."""
    text = text.replace(",", "\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    ranges: List[Tuple[float, float]] = []

    for line in lines:
        if "-" not in line:
            raise ValueError(f'Invalid range (missing "-"): {line}')
        parts = line.split("-", 1)
        start = _parse_time(parts[0])
        end = _parse_time(parts[1])

        if start >= end:
            raise ValueError(f"Start must be < end: {line}")
        if start < 0 or end < 0:
            raise ValueError(f"Times cannot be negative: {line}")
        if end > max_duration + 0.5:
            raise ValueError(
                f"End ({end:.1f}s) exceeds video duration ({max_duration:.1f}s)"
            )
        if start > max_duration:
            raise ValueError(
                f"Start ({start:.1f}s) exceeds video duration ({max_duration:.1f}s)"
            )
        ranges.append((start, end))

    if not ranges:
        raise ValueError("No valid ranges found.")
    return ranges


async def cut_timeline_clips(
    input_path: Path,
    output_dir: Path,
    ranges: List[Tuple[float, float]],
    status_callback: Callable,
) -> List[Path]:
    """Cut specific timeline ranges. Copy first, then re-encode."""
    ext = input_path.suffix.lower() if input_path.suffix else ".mp4"
    if ext not in (".mp4", ".mkv", ".webm", ".mov"):
        ext = ".mp4"
    clips: List[Path] = []
    bitrate = await get_video_bitrate(input_path)
    total = len(ranges)

    for idx, (start, end) in enumerate(ranges, 1):
        duration = end - start
        output_path = output_dir / f"clip_{idx:02d}{ext}"
        await status_callback(f"✂️ Creating clip {idx}/{total}…")

        cmd_copy = [
            config.FFMPEG, "-y",
            "-ss", str(start),
            "-i", str(input_path),
            "-t", str(duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts",
            str(output_path),
        ]
        try:
            await _run(cmd_copy, timeout=config.SPLIT_TIMEOUT)
        except FFmpegError:
            logger.warning("Copy cut failed for clip %d, re-encoding…", idx)
            cmd_re = _build_reencode_cmd(input_path, output_path, start, duration, bitrate)
            await _run(cmd_re, timeout=config.SPLIT_TIMEOUT)

        if not output_path.exists() or output_path.stat().st_size < 500:
            raise FFmpegError(f"Clip {idx} was not created properly")
        clips.append(output_path)

    return clips


async def convert_to_mp4(
    input_path: Path,
    output_path: Path,
    status_callback: Optional[Callable] = None,
) -> Path:
    """Convert any video to MP4 (H.264 + AAC). Fast preset for Render free."""
    if status_callback:
        await status_callback("🔄 Converting to MP4…")

    # If already MP4 and looks good, just copy
    if input_path.suffix.lower() == ".mp4":
        # Quick check: try stream copy
        cmd_copy = [
            config.FFMPEG, "-y",
            "-i", str(input_path),
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        try:
            await _run(cmd_copy, timeout=300)
            if output_path.exists() and output_path.stat().st_size > 1000:
                return output_path
        except FFmpegError:
            pass

    bitrate = await get_video_bitrate(input_path)
    cmd = [
        config.FFMPEG, "-y",
        "-i", str(input_path),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-threads", "2",
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if bitrate and bitrate > 0:
        cmd += ["-b:v", str(min(bitrate, 8_000_000))]
    else:
        cmd += ["-crf", "23"]
    cmd.append(str(output_path))

    await _run(cmd, timeout=config.CONVERT_TIMEOUT)

    if not output_path.exists() or output_path.stat().st_size < 1000:
        raise FFmpegError("Conversion failed – output file is missing or empty")
    return output_path
