from __future__ import annotations

from collections import deque
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.request import urlopen

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image

ProgressCallback = Callable[[float, str], None]
DEFAULT_HAND_URL = "https://raw.githubusercontent.com/VanyaVasileva/drawing-hand-studio/main/assets/default_hand.png"


@dataclass(frozen=True)
class RenderConfig:
    sensitivity: int = 24
    minimum_change_area: int = 18
    smoothing: float = 0.42
    hide_after_frames: int = 12
    maximum_jump: int = 220
    hand_width_percent: float = 70.0
    hand_opacity: float = 0.94
    hand_side: str = "Right"
    tip_x_percent: float = 14.6
    tip_y_percent: float = 34.4
    roi_left_percent: float = 0.0
    roi_top_percent: float = 0.0
    roi_right_percent: float = 100.0
    roi_bottom_percent: float = 100.0
    hand_visual_lead_seconds: float = 0.07


@dataclass(frozen=True)
class RenderResult:
    frames: int
    tracked_frames: int
    fps: float
    width: int
    height: int
    audio_preserved: bool


def load_hand_image(_: bytes | None = None) -> np.ndarray:
    with urlopen(DEFAULT_HAND_URL, timeout=20) as response:
        data = response.read()
    from io import BytesIO
    return np.asarray(Image.open(BytesIO(data)).convert("RGBA"))


def _prepare_sprite(sprite: np.ndarray, frame_width: int, config: RenderConfig):
    target_width = max(60, int(frame_width * config.hand_width_percent / 100.0))
    ratio = target_width / sprite.shape[1]
    target_height = max(1, int(sprite.shape[0] * ratio))
    resized = cv2.resize(sprite, (target_width, target_height), interpolation=cv2.INTER_AREA)
    tip_x = int(target_width * config.tip_x_percent / 100.0)
    tip_y = int(target_height * config.tip_y_percent / 100.0)
    if config.hand_side.lower() == "left":
        resized = cv2.flip(resized, 1)
        tip_x = target_width - 1 - tip_x
    return resized, tip_x, tip_y


def _overlay_rgba(frame, sprite, anchor, tip, opacity):
    x = int(anchor[0] - tip[0])
    y = int(anchor[1] - tip[1])
    sh, sw = sprite.shape[:2]
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(fw, x + sw), min(fh, y + sh)
    if x1 >= x2 or y1 >= y2:
        return
    sx1, sy1 = x1 - x, y1 - y
    sx2, sy2 = sx1 + (x2 - x1), sy1 + (y2 - y1)
    crop = sprite[sy1:sy2, sx1:sx2]
    alpha = (crop[:, :, 3:4].astype(np.float32) / 255.0) * float(np.clip(opacity, 0.0, 1.0))
    rgb = crop[:, :, :3][:, :, ::-1].astype(np.float32)
    base = frame[y1:y2, x1:x2].astype(np.float32)
    frame[y1:y2, x1:x2] = np.clip(rgb * alpha + base * (1.0 - alpha), 0, 255).astype(np.uint8)


def _tracking_frame(small_bgr):
    softened = cv2.GaussianBlur(small_bgr, (7, 7), 0)
    return cv2.cvtColor(softened, cv2.COLOR_BGR2LAB).astype(np.float32)


def _motion_masks(current, old, baseline, config):
    motion = np.linalg.norm(current - old, axis=2)
    current_from_bg = np.linalg.norm(current - baseline, axis=2)
    old_from_bg = np.linalg.norm(old - baseline, axis=2)
    radial_change = current_from_bg - old_from_bg
    median = float(np.median(motion))
    mad = float(np.median(np.abs(motion - median)))
    noise_floor = median + 4.5 * 1.4826 * mad
    user_floor = max(1.15, float(config.sensitivity) / 16.0)
    motion_threshold = max(user_floor, noise_floor)
    outward_threshold = max(0.55, motion_threshold * 0.42)
    fallback_threshold = max(1.15, motion_threshold * 0.78)
    primary = (motion >= motion_threshold) & (radial_change >= outward_threshold)
    fallback = (motion >= motion_threshold * 1.05) & (np.abs(radial_change) >= fallback_threshold)
    kernel = np.ones((3, 3), np.uint8)
    primary_mask = cv2.morphologyEx(primary.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel)
    fallback_mask = cv2.morphologyEx(fallback.astype(np.uint8) * 255, cv2.MORPH_CLOSE, kernel)
    return primary_mask, fallback_mask


def _candidate_from_components(mask, previous, maximum_jump, minimum_area):
    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
    frame_area = mask.shape[0] * mask.shape[1]
    max_area = max(minimum_area * 4, int(frame_area * 0.035))
    choices = []
    for index in range(1, count):
        area = int(stats[index][cv2.CC_STAT_AREA])
        if area < minimum_area or area > max_area:
            continue
        cx, cy = float(centroids[index][0]), float(centroids[index][1])
        if previous is None:
            score = -float(area)
        else:
            distance = float(np.hypot(cx - previous[0], cy - previous[1]))
            if distance > maximum_jump:
                continue
            score = distance - min(area, 900) * 0.012
        choices.append((score, index))
    if not choices:
        return None
    choices.sort(key=lambda item: item[0])
    best = choices[0][1]
    return float(centroids[best][0]), float(centroids[best][1])


def _ffmpeg_exe() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _open_video_writer(path: Path, fps: float, width: int, height: int):
    ffmpeg = _ffmpeg_exe()
    command = [
        ffmpeg, "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", f"{fps:.6f}",
        "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", "13", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    return process


def _write_video_frame(process, frame):
    if process.stdin is None:
        raise RuntimeError("The H.264 encoder input closed unexpectedly.")
    process.stdin.write(frame.tobytes())


def _close_video_writer(process):
    if process.stdin is not None:
        process.stdin.close()
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"The H.264 encoder failed: {stderr[-500:]}")


def _mux_original_audio(silent_video: Path, original_video: Path, output_video: Path) -> bool:
    ffmpeg = _ffmpeg_exe()
    command = [
        ffmpeg, "-y", "-loglevel", "error", "-i", str(silent_video), "-i", str(original_video),
        "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_video),
    ]
    completed = subprocess.run(command, capture_output=True, check=False)
    if completed.returncode == 0 and output_video.exists() and output_video.stat().st_size:
        silent_video.unlink(missing_ok=True)
        probe = subprocess.run([ffmpeg, "-i", str(original_video)], capture_output=True, text=True, check=False)
        return "Audio:" in probe.stderr
    if silent_video.exists():
        silent_video.replace(output_video)
    return False


def render_hand_video(input_path, output_path, hand_rgba, config: RenderConfig, progress: ProgressCallback | None = None):
    input_path = Path(input_path)
    output_path = Path(output_path)
    silent_path = output_path.with_name(output_path.stem + "-silent.mp4")
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise ValueError("The uploaded video could not be opened.")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if width < 2 or height < 2:
        capture.release()
        raise ValueError("The uploaded video has an invalid frame size.")

    writer = _open_video_writer(silent_path, fps, width, height)
    left = int(width * config.roi_left_percent / 100.0)
    right = int(width * config.roi_right_percent / 100.0)
    top = int(height * config.roi_top_percent / 100.0)
    bottom = int(height * config.roi_bottom_percent / 100.0)
    if right - left < 20 or bottom - top < 20:
        capture.release()
        _close_video_writer(writer)
        raise ValueError("The selected drawing area is too small.")

    roi_width = right - left
    roi_height = bottom - top
    tracking_scale = min(1.0, 420.0 / roi_width)
    track_size = (max(1, int(roi_width * tracking_scale)), max(1, int(roi_height * tracking_scale)))
    sprite, tip_x, tip_y = _prepare_sprite(hand_rgba, width, config)

    baseline_samples = []
    calibration_frames = max(4, min(10, int(round(fps * 0.28))))
    baseline = None
    tracking_history = deque(maxlen=max(5, int(round(fps * 0.20)) + 1))
    candidate_history = deque(maxlen=5)
    tracked = None
    idle_frames = config.hide_after_frames + 1
    hold_frames = max(config.hide_after_frames, int(round(fps * 0.45)))
    minimum_component_area = max(6, int(round(config.minimum_change_area * max(0.42, tracking_scale * 0.7))))
    max_change_pixels = int(track_size[0] * track_size[1] * 0.08)
    visual_lead_frames = max(0, int(round(fps * max(0.0, config.hand_visual_lead_seconds))))
    frame_queue = deque()
    processed = written = active_count = 0

    def write_with_current_hand(output_frame):
        nonlocal written
        if tracked is not None and idle_frames <= hold_frames:
            _overlay_rgba(output_frame, sprite, tracked, (tip_x, tip_y), config.hand_opacity)
        _write_video_frame(writer, output_frame)
        written += 1

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            processed += 1
            roi = frame[top:bottom, left:right]
            small = cv2.resize(roi, track_size, interpolation=cv2.INTER_AREA)
            tracking = _tracking_frame(small)

            if baseline is None:
                baseline_samples.append(tracking)
                if len(baseline_samples) >= calibration_frames:
                    baseline = np.median(np.stack(baseline_samples, axis=0), axis=0).astype(np.float32)
                tracking_history.append(tracking)
            else:
                tracking_history.append(tracking)
                candidate = None
                if len(tracking_history) == tracking_history.maxlen:
                    old = tracking_history[0]
                    primary_mask, fallback_mask = _motion_masks(tracking, old, baseline, config)
                    guard_top = max(1, int(track_size[1] * 0.035))
                    guard_side = max(1, int(track_size[0] * 0.018))
                    for mask in (primary_mask, fallback_mask):
                        mask[:guard_top, :] = 0
                        mask[:, :guard_side] = 0
                        mask[:, -guard_side:] = 0
                    previous_local = None
                    if tracked is not None:
                        previous_local = ((tracked[0] - left) * tracking_scale, (tracked[1] - top) * tracking_scale)
                    primary_area = int(cv2.countNonZero(primary_mask))
                    if config.minimum_change_area <= primary_area <= max_change_pixels:
                        local = _candidate_from_components(primary_mask, previous_local, config.maximum_jump * tracking_scale, minimum_component_area)
                        if local is not None:
                            candidate = (local[0] / tracking_scale + left, local[1] / tracking_scale + top)
                    if candidate is None and tracked is not None:
                        fallback_area = int(cv2.countNonZero(fallback_mask))
                        if config.minimum_change_area <= fallback_area <= max_change_pixels:
                            local = _candidate_from_components(fallback_mask, previous_local, config.maximum_jump * tracking_scale * 0.72, minimum_component_area)
                            if local is not None:
                                candidate = (local[0] / tracking_scale + left, local[1] / tracking_scale + top)

                if candidate is not None:
                    candidate_history.append(candidate)
                    stable_candidate = (
                        float(np.median([point[0] for point in candidate_history])),
                        float(np.median([point[1] for point in candidate_history])),
                    )
                    if tracked is None:
                        tracked = stable_candidate
                    else:
                        dx, dy = stable_candidate[0] - tracked[0], stable_candidate[1] - tracked[1]
                        distance = float(np.hypot(dx, dy))
                        dead_zone = max(3.0, width * 0.007)
                        if distance > dead_zone:
                            max_step = max(14.0, width * 0.040)
                            scale = min(1.0, max_step / max(distance, 1e-6))
                            target = (tracked[0] + dx * scale, tracked[1] + dy * scale)
                            alpha = float(np.clip(config.smoothing, 0.18, 0.48))
                            tracked = (tracked[0] * (1.0 - alpha) + target[0] * alpha, tracked[1] * (1.0 - alpha) + target[1] * alpha)
                    idle_frames = 0
                    active_count += 1
                else:
                    idle_frames += 1

            frame_queue.append(frame.copy())
            if len(frame_queue) > visual_lead_frames:
                write_with_current_hand(frame_queue.popleft())

            if progress and (processed == 1 or processed % max(1, int(fps / 2)) == 0):
                fraction = processed / frame_count if frame_count > 0 else 0.0
                progress(min(0.97, fraction), f"Processing frame {processed:,}")

        while frame_queue:
            write_with_current_hand(frame_queue.popleft())
    finally:
        capture.release()
        _close_video_writer(writer)

    if written == 0:
        silent_path.unlink(missing_ok=True)
        raise ValueError("No readable frames were found in the uploaded video.")

    if progress:
        progress(0.98, "Restoring the original audio")
    audio_preserved = _mux_original_audio(silent_path, input_path, output_path)
    if progress:
        progress(1.0, "Finished")
    return RenderResult(written, active_count, fps, width, height, audio_preserved)
