from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Iterable, Iterator, Optional

import cv2
import numpy as np

from . import __version__


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


@dataclass
class Detection:
    x: int
    y: int
    w: int
    h: int
    confidence: float
    status: str
    scale: float = 1.0


@dataclass
class TrackerConfig:
    search_margin: float = 1.5
    min_confidence: float = 0.45
    redetect_interval: int = 15
    redetect_confidence: float = 0.98
    scales: tuple[float, ...] = (0.92, 0.96, 1.0, 1.04, 1.08)
    recent_template_weight: float = 0.35
    template_refresh_rate: float = 0.2


class DebugImageWriter:
    def __init__(self, debug_dir: Path, png_compression: int = 1, queue_size: int = 32) -> None:
        self.debug_dir = debug_dir
        self.params = [cv2.IMWRITE_PNG_COMPRESSION, png_compression]
        self.queue: Queue[Optional[tuple[Path, np.ndarray]]] = Queue(maxsize=queue_size)
        self.error: Optional[BaseException] = None
        self.worker = Thread(target=self._run, daemon=True)
        self.worker.start()

    def submit(self, path: Path, image: np.ndarray) -> None:
        if self.error is not None:
            raise RuntimeError(f"Debug image writer failed: {self.error}") from self.error
        self.queue.put((path, image.copy()))

    def close(self) -> None:
        self.queue.put(None)
        self.worker.join()
        if self.error is not None:
            raise RuntimeError(f"Debug image writer failed: {self.error}") from self.error

    def _run(self) -> None:
        try:
            while True:
                item = self.queue.get()
                try:
                    if item is None:
                        return
                    path, image = item
                    ok = cv2.imwrite(str(path), image, self.params)
                    if not ok:
                        raise RuntimeError(f"Could not write debug image: {path}")
                finally:
                    self.queue.task_done()
        except BaseException as exc:  # pragma: no cover
            self.error = exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="waldo",
        description="Track a moving ROI across image frames or a video."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--frames-dir", type=Path, help="Directory of ordered frames.")
    input_group.add_argument("--video", type=Path, help="Video file to decode with OpenCV.")

    init_group = parser.add_mutually_exclusive_group(required=True)
    init_group.add_argument("--template", type=Path, help="ROI template image.")
    init_group.add_argument(
        "--init-bbox",
        type=str,
        help="Initial ROI bbox as x,y,w,h on the first processed frame.",
    )

    parser.add_argument("--output-csv", type=Path, default=Path("waldo_tracks.csv"))
    parser.add_argument("--debug-dir", type=Path, help="Optional directory for annotated frames.")
    parser.add_argument(
        "--debug-every",
        type=int,
        default=1,
        help="Only write every Nth debug frame when debug images are enabled.",
    )
    parser.add_argument(
        "--no-debug-images",
        action="store_true",
        help="Disable debug image generation even if --debug-dir is provided.",
    )
    parser.add_argument("--start-frame", type=int, default=0)
    parser.add_argument("--end-frame", type=int, help="Stop after this frame index, inclusive.")
    parser.add_argument("--search-margin", type=float, default=1.5)
    parser.add_argument("--redetect-interval", type=int, default=15)
    parser.add_argument(
        "--redetect-confidence",
        type=float,
        default=0.98,
        help="Periodic full-frame re-detection only runs when local confidence is at or below this value.",
    )
    parser.add_argument("--min-confidence", type=float, default=0.45)
    parser.add_argument(
        "--scales",
        type=str,
        default="0.92,0.96,1.0,1.04,1.08",
        help="Comma-separated scales to try at each step.",
    )
    parser.add_argument(
        "--recent-template-weight",
        type=float,
        default=0.35,
        help="Blend weight for the most recent accepted crop.",
    )
    parser.add_argument(
        "--template-refresh-rate",
        type=float,
        default=0.2,
        help="EMA update rate for the recent template after a confident match.",
    )
    return parser.parse_args()


def parse_bbox(raw: str) -> tuple[int, int, int, int]:
    parts = [int(value.strip()) for value in raw.split(",")]
    if len(parts) != 4:
        raise ValueError("init-bbox must be x,y,w,h")
    x, y, w, h = parts
    if w <= 0 or h <= 0:
        raise ValueError("bbox width and height must be positive")
    return x, y, w, h


def clamp_bbox(
    bbox: tuple[int, int, int, int], frame_w: int, frame_h: int
) -> tuple[int, int, int, int]:
    x, y, w, h = bbox
    x = max(0, min(x, frame_w - 1))
    y = max(0, min(y, frame_h - 1))
    w = max(1, min(w, frame_w - x))
    h = max(1, min(h, frame_h - y))
    return x, y, w, h


def crop_frame(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = bbox
    return frame[y : y + h, x : x + w].copy()


def resize_image(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    width, height = size
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_LINEAR)


def to_gray(image: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def read_image(path: Path) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not read image: {path}")
    return image


def make_search_region(
    detection: Detection, frame_w: int, frame_h: int, margin: float
) -> tuple[int, int, int, int]:
    cx = detection.x + detection.w / 2.0
    cy = detection.y + detection.h / 2.0
    span_w = detection.w * (1.0 + 2.0 * margin)
    span_h = detection.h * (1.0 + 2.0 * margin)
    return clamp_bbox(
        (
            int(round(cx - span_w / 2.0)),
            int(round(cy - span_h / 2.0)),
            int(round(span_w)),
            int(round(span_h)),
        ),
        frame_w,
        frame_h,
    )


class HybridRoiTracker:
    def __init__(self, config: TrackerConfig) -> None:
        self.config = config
        self.original_template: Optional[np.ndarray] = None
        self.original_template_gray: Optional[np.ndarray] = None
        self.recent_template: Optional[np.ndarray] = None
        self.recent_template_gray: Optional[np.ndarray] = None
        self.last_detection: Optional[Detection] = None
        self.frame_counter = 0
        self._original_scaled_gray: dict[float, np.ndarray] = {}
        self._recent_scaled_gray: dict[float, np.ndarray] = {}

    def initialize(
        self,
        frame: np.ndarray,
        template: Optional[np.ndarray] = None,
        init_bbox: Optional[tuple[int, int, int, int]] = None,
    ) -> Detection:
        if template is None and init_bbox is None:
            raise ValueError("Either template or init_bbox is required")

        if init_bbox is not None:
            init_bbox = clamp_bbox(init_bbox, frame.shape[1], frame.shape[0])
            template = crop_frame(frame, init_bbox)
            detection = Detection(*init_bbox, confidence=1.0, status="tracked")
        else:
            assert template is not None
            self.original_template = template
            self.original_template_gray = to_gray(template)
            self._original_scaled_gray = self._build_scaled_template_cache(
                self.original_template_gray
            )
            detection = self._detect(to_gray(frame), None, "tracked")
            if detection.confidence < self.config.min_confidence:
                raise RuntimeError(
                    f"Could not find template in the initial frame. Best confidence: {detection.confidence:.3f}"
                )

        self.original_template = template
        self.original_template_gray = to_gray(template)
        self.recent_template = template.astype(np.float32)
        self.recent_template_gray = to_gray(template).astype(np.float32)
        self._original_scaled_gray = self._build_scaled_template_cache(
            self.original_template_gray
        )
        self._recent_scaled_gray = self._build_scaled_template_cache(
            self.recent_template_gray.astype(np.uint8)
        )
        self.last_detection = detection
        self.frame_counter = 1
        return detection

    def update(self, frame: np.ndarray) -> Detection:
        if self.last_detection is None or self.original_template_gray is None:
            raise RuntimeError("Tracker is not initialized")

        self.frame_counter += 1
        frame_h, frame_w = frame.shape[:2]
        search_region = make_search_region(
            self.last_detection, frame_w, frame_h, self.config.search_margin
        )

        frame_gray = to_gray(frame)
        detection = self._detect(frame_gray, search_region, "tracked")
        interval_due = (
            self.config.redetect_interval > 0
            and self.frame_counter % self.config.redetect_interval == 0
            and detection.confidence <= self.config.redetect_confidence
        )
        should_redetect = detection.confidence < self.config.min_confidence or interval_due

        if should_redetect:
            recovered = self._detect(frame_gray, None, "redetected")
            if recovered.confidence > detection.confidence:
                detection = recovered

        if detection.confidence >= self.config.min_confidence:
            self.last_detection = detection
            self._refresh_recent_template(frame, detection)
            return detection

        return Detection(
            x=self.last_detection.x,
            y=self.last_detection.y,
            w=self.last_detection.w,
            h=self.last_detection.h,
            confidence=detection.confidence,
            status="missing",
        )

    def _refresh_recent_template(self, frame: np.ndarray, detection: Detection) -> None:
        if self.recent_template is None:
            return
        crop = crop_frame(frame, (detection.x, detection.y, detection.w, detection.h))
        target_size = (self.recent_template.shape[1], self.recent_template.shape[0])
        crop = resize_image(crop, target_size).astype(np.float32)
        rate = self.config.template_refresh_rate
        self.recent_template = (1.0 - rate) * self.recent_template + rate * crop
        self.recent_template_gray = to_gray(self.recent_template.astype(np.uint8)).astype(
            np.float32
        )
        self._recent_scaled_gray = self._build_scaled_template_cache(
            self.recent_template_gray.astype(np.uint8)
        )

    def _detect(
        self,
        frame_gray: np.ndarray,
        search_region: Optional[tuple[int, int, int, int]],
        status: str,
    ) -> Detection:
        if search_region is None:
            region_x, region_y, region_w, region_h = 0, 0, frame_gray.shape[1], frame_gray.shape[0]
        else:
            region_x, region_y, region_w, region_h = search_region
        region = crop_frame(frame_gray, (region_x, region_y, region_w, region_h))

        best_confidence = -1.0
        assert self.original_template_gray is not None
        best_bbox = (
            region_x,
            region_y,
            self.original_template_gray.shape[1],
            self.original_template_gray.shape[0],
        )
        best_scale = 1.0

        for scale in self._candidate_scales(search_region):
            scaled_original = self._original_scaled_gray.get(scale)
            if scaled_original is None:
                continue
            if (
                scaled_original.shape[0] > region.shape[0]
                or scaled_original.shape[1] > region.shape[1]
            ):
                continue

            weighted_score, location = self._match_region(region, scaled_original, scale)
            if weighted_score > best_confidence:
                best_confidence = weighted_score
                best_scale = scale
                best_bbox = (
                    region_x + location[0],
                    region_y + location[1],
                    scaled_original.shape[1],
                    scaled_original.shape[0],
                )

        x, y, w, h = clamp_bbox(best_bbox, frame_gray.shape[1], frame_gray.shape[0])
        return Detection(
            x=x, y=y, w=w, h=h, confidence=best_confidence, status=status, scale=best_scale
        )

    def _match_region(
        self, region: np.ndarray, scaled_original: np.ndarray, scale: float
    ) -> tuple[float, tuple[int, int]]:
        original_score, original_location = self._template_score(region, scaled_original)
        total_weight = 1.0 - self.config.recent_template_weight
        blended_score = original_score * total_weight
        best_location = original_location

        if self.recent_template_gray is not None and self.config.recent_template_weight > 0.0:
            scaled_recent = self._recent_scaled_gray.get(scale)
            if scaled_recent is not None and scaled_recent.shape[:2] == scaled_original.shape[:2]:
                recent_score, recent_location = self._template_score(region, scaled_recent)
                blended_score += recent_score * self.config.recent_template_weight
                total_weight += self.config.recent_template_weight
                if recent_score > original_score:
                    best_location = recent_location

        return blended_score / total_weight, best_location

    @staticmethod
    def _template_score(region: np.ndarray, template: np.ndarray) -> tuple[float, tuple[int, int]]:
        result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        return float(max_value), (int(max_location[0]), int(max_location[1]))

    def _build_scaled_template_cache(self, template_gray: np.ndarray) -> dict[float, np.ndarray]:
        cache: dict[float, np.ndarray] = {}
        for scale in self.config.scales:
            width = max(4, int(round(template_gray.shape[1] * scale)))
            height = max(4, int(round(template_gray.shape[0] * scale)))
            if width <= 0 or height <= 0:
                continue
            cache[scale] = resize_image(template_gray, (width, height))
        return cache

    def _candidate_scales(
        self, search_region: Optional[tuple[int, int, int, int]]
    ) -> tuple[float, ...]:
        if search_region is None or self.last_detection is None:
            return self.config.scales
        if self.last_detection.scale not in self.config.scales:
            return self.config.scales
        index = self.config.scales.index(self.last_detection.scale)
        start = max(0, index - 1)
        end = min(len(self.config.scales), index + 2)
        return self.config.scales[start:end]


def iter_frames_from_dir(frames_dir: Path) -> Iterator[tuple[int, str, np.ndarray]]:
    files = sorted(
        path
        for path in frames_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not files:
        raise RuntimeError(f"No image frames found in {frames_dir}")
    for index, path in enumerate(files):
        yield index, path.name, read_image(path)


def iter_frames_from_video(video_path: Path) -> Iterator[tuple[int, str, np.ndarray]]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            yield index, f"frame_{index:06d}", frame
            index += 1
    finally:
        capture.release()


def draw_debug_frame(frame: np.ndarray, detection: Detection) -> np.ndarray:
    image = frame.copy()
    color = {
        "tracked": (0, 255, 0),
        "redetected": (0, 255, 255),
        "missing": (0, 0, 255),
    }[detection.status]
    cv2.rectangle(
        image,
        (detection.x, detection.y),
        (detection.x + detection.w, detection.y + detection.h),
        color,
        2,
    )
    label = f"{detection.status} {detection.confidence:.3f}"
    cv2.putText(
        image,
        label,
        (detection.x, max(20, detection.y - 8)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        color,
        2,
        cv2.LINE_AA,
    )
    return image


def build_config(args: argparse.Namespace) -> TrackerConfig:
    scales = tuple(float(value.strip()) for value in args.scales.split(",") if value.strip())
    if not scales:
        raise ValueError("At least one scale is required")
    return TrackerConfig(
        search_margin=args.search_margin,
        min_confidence=args.min_confidence,
        redetect_interval=args.redetect_interval,
        redetect_confidence=args.redetect_confidence,
        scales=scales,
        recent_template_weight=args.recent_template_weight,
        template_refresh_rate=args.template_refresh_rate,
    )


def frame_source(args: argparse.Namespace) -> Iterable[tuple[int, str, np.ndarray]]:
    if args.frames_dir is not None:
        return iter_frames_from_dir(args.frames_dir)
    return iter_frames_from_video(args.video)


def main() -> int:
    args = parse_args()
    if args.debug_every <= 0:
        raise ValueError("--debug-every must be a positive integer")
    config = build_config(args)
    tracker = HybridRoiTracker(config)

    debug_images_enabled = args.debug_dir is not None and not args.no_debug_images
    if debug_images_enabled:
        args.debug_dir.mkdir(parents=True, exist_ok=True)
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    debug_writer = DebugImageWriter(args.debug_dir) if debug_images_enabled else None

    template = read_image(args.template) if args.template else None
    init_bbox = parse_bbox(args.init_bbox) if args.init_bbox else None

    try:
        with args.output_csv.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["frame_index", "frame_id", "x", "y", "w", "h", "confidence", "status"])

            initialized = False
            for frame_index, frame_id, frame in frame_source(args):
                if frame_index < args.start_frame:
                    continue
                if args.end_frame is not None and frame_index > args.end_frame:
                    break

                if not initialized:
                    detection = tracker.initialize(frame, template=template, init_bbox=init_bbox)
                    initialized = True
                else:
                    detection = tracker.update(frame)

                writer.writerow(
                    [
                        frame_index,
                        frame_id,
                        detection.x,
                        detection.y,
                        detection.w,
                        detection.h,
                        f"{detection.confidence:.6f}",
                        detection.status,
                    ]
                )

                if debug_writer is not None and frame_index % args.debug_every == 0:
                    debug_path = args.debug_dir / f"{frame_index:06d}.png"
                    debug_image = draw_debug_frame(frame, detection)
                    debug_writer.submit(debug_path, debug_image)
    finally:
        if debug_writer is not None:
            debug_writer.close()

    return 0


def run() -> None:
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
