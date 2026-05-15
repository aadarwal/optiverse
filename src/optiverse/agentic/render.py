"""Minimal headless PNG renderer for agentic layout artifacts."""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Any

from .schema import GoalSpec

Color = tuple[int, int, int]
Point = tuple[float, float]


def _write_png(path: Path, width: int, height: int, pixels: bytearray) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    rows = bytearray()
    stride = width * 3
    for y in range(height):
        rows.append(0)
        rows.extend(pixels[y * stride : (y + 1) * stride])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + chunk(b"IEND", b"")
    )


def _put_pixel(
    pixels: bytearray, width: int, height: int, x: int, y: int, color: Color
) -> None:
    if x < 0 or y < 0 or x >= width or y >= height:
        return
    offset = (y * width + x) * 3
    pixels[offset : offset + 3] = bytes(color)


def _draw_disk(
    pixels: bytearray,
    width: int,
    height: int,
    x: int,
    y: int,
    radius: int,
    color: Color,
) -> None:
    rr = radius * radius
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= rr:
                _put_pixel(pixels, width, height, x + dx, y + dy, color)


def _draw_line(
    pixels: bytearray,
    width: int,
    height: int,
    a: tuple[int, int],
    b: tuple[int, int],
    color: Color,
    *,
    thickness: int = 2,
) -> None:
    x0, y0 = a
    x1, y1 = b
    steps = max(abs(x1 - x0), abs(y1 - y0), 1)
    for index in range(steps + 1):
        t = index / steps
        x = round(x0 + (x1 - x0) * t)
        y = round(y0 + (y1 - y0) * t)
        _draw_disk(pixels, width, height, x, y, max(1, thickness // 2), color)


def _draw_rect_outline(
    pixels: bytearray,
    width: int,
    height: int,
    center: tuple[int, int],
    half_size: int,
    color: Color,
) -> None:
    x, y = center
    left = x - half_size
    right = x + half_size
    top = y - half_size
    bottom = y + half_size
    _draw_line(pixels, width, height, (left, top), (right, top), color, thickness=2)
    _draw_line(pixels, width, height, (right, top), (right, bottom), color, thickness=2)
    _draw_line(pixels, width, height, (right, bottom), (left, bottom), color, thickness=2)
    _draw_line(pixels, width, height, (left, bottom), (left, top), color, thickness=2)


def _path_points(trace_paths: list[dict[str, Any]]) -> list[Point]:
    points: list[Point] = []
    for path in trace_paths:
        for raw_point in path.get("points_mm", []):
            if isinstance(raw_point, list | tuple) and len(raw_point) >= 2:
                points.append((float(raw_point[0]), float(raw_point[1])))
    return points


def _bounds(goal: GoalSpec, trace_paths: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    points: list[Point] = [(goal.source.x_mm, goal.source.y_mm)]
    points.extend((placement.x_mm, placement.y_mm) for placement in goal.placements)
    points.extend((target.x_mm, target.y_mm) for target in goal.targets)
    points.extend(_path_points(trace_paths))

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_min = min(xs, default=0.0)
    x_max = max(xs, default=100.0)
    y_min = min(ys, default=0.0)
    y_max = max(ys, default=100.0)

    if math.isclose(x_min, x_max):
        x_min -= 50.0
        x_max += 50.0
    if math.isclose(y_min, y_max):
        y_min -= 50.0
        y_max += 50.0

    pad_x = max(25.0, (x_max - x_min) * 0.08)
    pad_y = max(25.0, (y_max - y_min) * 0.08)
    return x_min - pad_x, y_min - pad_y, x_max + pad_x, y_max + pad_y


def render_goal_png(
    goal: GoalSpec,
    trace_paths: list[dict[str, Any]],
    output_path: Path,
    *,
    width: int = 1000,
    height: int = 700,
) -> None:
    """Render a compact top-down schematic PNG from a goal and traced paths."""
    pixels = bytearray([255] * width * height * 3)
    x_min, y_min, x_max, y_max = _bounds(goal, trace_paths)
    span_x = max(1.0, x_max - x_min)
    span_y = max(1.0, y_max - y_min)

    def project(point: Point) -> tuple[int, int]:
        x, y = point
        px = int(round((x - x_min) / span_x * (width - 1)))
        py = int(round((y_max - y) / span_y * (height - 1)))
        return px, py

    grid_color = (230, 235, 242)
    for index in range(11):
        x = round(index * (width - 1) / 10)
        y = round(index * (height - 1) / 10)
        _draw_line(pixels, width, height, (x, 0), (x, height - 1), grid_color, thickness=1)
        _draw_line(pixels, width, height, (0, y), (width - 1, y), grid_color, thickness=1)

    ray_colors = [(220, 20, 60), (0, 118, 110), (110, 74, 220), (230, 120, 0)]
    for path_index, path in enumerate(trace_paths):
        raw_points = path.get("points_mm", [])
        projected = [
            project((float(point[0]), float(point[1])))
            for point in raw_points
            if isinstance(point, list | tuple) and len(point) >= 2
        ]
        color = ray_colors[path_index % len(ray_colors)]
        for a, b in zip(projected, projected[1:], strict=False):
            _draw_line(pixels, width, height, a, b, color, thickness=4)

    source_px = project((goal.source.x_mm, goal.source.y_mm))
    _draw_disk(pixels, width, height, source_px[0], source_px[1], 8, (220, 20, 60))

    for placement in goal.placements:
        _draw_rect_outline(
            pixels,
            width,
            height,
            project((placement.x_mm, placement.y_mm)),
            9,
            (225, 72, 20),
        )

    for target in goal.targets:
        target_px = project((target.x_mm, target.y_mm))
        _draw_disk(pixels, width, height, target_px[0], target_px[1], 8, (37, 99, 235))
        _draw_disk(pixels, width, height, target_px[0], target_px[1], 4, (255, 255, 255))

    _write_png(output_path, width, height, pixels)
