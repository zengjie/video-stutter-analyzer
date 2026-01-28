#!/usr/bin/env python3
"""Video frame time analysis for game recordings.

Detects stutters by finding duplicate frames that interrupt motion.
Uses game benchmarking methodology (1% low, 0.1% low metrics).
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class FrameTimeStats:
    fps: float
    total_frames: int
    duration: float
    duplicate_frames: int
    duplicate_ratio: float
    avg_frametime: float
    one_percent_low: float
    point_one_percent_low: float
    max_frametime: float
    avg_to_1pct_ratio: float
    stutter_score: float


@dataclass
class StutterEvent:
    frame_index: int
    timestamp: float
    frametime_ms: float
    duplicate_count: int
    motion_before: float


def analyze_frametimes(
    video_path: str,
    ema_alpha: float = 0.1,
    duplicate_threshold: float = 0.1,
    absolute_duplicate_max: float = 0.1,
    motion_threshold: float = 2.0,
    context_frames: int = 5,
) -> tuple[FrameTimeStats, list[StutterEvent]]:
    """Analyze frame times with motion-aware stutter detection."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Failed to open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_duration_ms = 1000.0 / fps

    ret, prev_frame = cap.read()
    if not ret:
        raise RuntimeError("Failed to read video frames")

    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    prev_gray = cv2.resize(prev_gray, (320, 180)).astype(np.float32)

    frame_diffs = []
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (320, 180)).astype(np.float32)
        frame_diffs.append(float(np.mean(np.abs(gray - prev_gray))))
        prev_gray = gray

    cap.release()

    if not frame_diffs:
        raise RuntimeError("No frame data extracted")

    # Adaptive duplicate detection using EMA
    ema_diff = frame_diffs[0] if frame_diffs[0] > 0 else 1.0
    is_duplicate = []
    for diff in frame_diffs:
        ema_diff = ema_alpha * diff + (1 - ema_alpha) * ema_diff
        adaptive_threshold = duplicate_threshold * max(ema_diff, 0.5)
        is_duplicate.append(diff < adaptive_threshold and diff < absolute_duplicate_max)

    # Calculate effective frame times and find stutters
    effective_frametimes = []
    stutters = []
    current_frametime = frame_duration_ms
    current_dup_start = None
    current_dup_count = 0
    current_time = 0.0

    for i, is_dup in enumerate(is_duplicate):
        if is_dup:
            if current_dup_start is None:
                current_dup_start = i
                current_dup_count = 1
            else:
                current_dup_count += 1
            current_frametime += frame_duration_ms
        else:
            if current_dup_start is not None and current_dup_count >= 1:
                start_check = max(0, current_dup_start - context_frames)
                motion_before_dups = frame_diffs[start_check:current_dup_start]
                if motion_before_dups:
                    avg_motion = float(np.mean(motion_before_dups))
                    if avg_motion >= motion_threshold:
                        stutters.append(StutterEvent(
                            frame_index=current_dup_start,
                            timestamp=current_time / 1000.0,
                            frametime_ms=current_frametime,
                            duplicate_count=current_dup_count,
                            motion_before=avg_motion,
                        ))
            effective_frametimes.append(current_frametime)
            current_time += current_frametime
            current_frametime = frame_duration_ms
            current_dup_start = None
            current_dup_count = 0

    effective_frametimes.append(current_frametime)

    # Calculate stats
    frametimes = np.array(effective_frametimes)
    duplicate_count = sum(is_duplicate)
    avg_frametime = float(np.mean(frametimes))
    sorted_ft = np.sort(frametimes)

    idx_1pct = min(int(len(sorted_ft) * 0.99), len(sorted_ft) - 1)
    idx_01pct = min(int(len(sorted_ft) * 0.999), len(sorted_ft) - 1)

    one_percent_low = float(sorted_ft[idx_1pct])
    point_one_percent_low = float(sorted_ft[idx_01pct])
    max_frametime = float(np.max(frametimes))

    avg_fps = 1000.0 / avg_frametime if avg_frametime > 0 else 0
    one_pct_fps = 1000.0 / one_percent_low if one_percent_low > 0 else 0
    avg_to_1pct_ratio = one_pct_fps / avg_fps if avg_fps > 0 else 0

    stutter_frames = sum(s.duplicate_count for s in stutters)
    stutter_ratio = stutter_frames / len(is_duplicate) if is_duplicate else 0
    stutter_score = max(0, avg_to_1pct_ratio * 100 - min(50, stutter_ratio * 500))

    return FrameTimeStats(
        fps=fps,
        total_frames=total_frames,
        duration=total_frames / fps,
        duplicate_frames=duplicate_count,
        duplicate_ratio=duplicate_count / len(is_duplicate) if is_duplicate else 0,
        avg_frametime=avg_frametime,
        one_percent_low=one_percent_low,
        point_one_percent_low=point_one_percent_low,
        max_frametime=max_frametime,
        avg_to_1pct_ratio=avg_to_1pct_ratio,
        stutter_score=stutter_score,
    ), stutters


def print_report(stats: FrameTimeStats, stutters: list[StutterEvent], video_path: str) -> None:
    print("\n" + "=" * 60)
    print("FRAME TIME ANALYSIS")
    print("=" * 60)

    print(f"\nFile: {video_path}")
    print(f"FPS: {stats.fps:.2f}")
    print(f"Total Frames: {stats.total_frames}")
    print(f"Duration: {stats.duration:.2f}s")

    print(f"\n{'=' * 60}")
    print(f"SMOOTHNESS SCORE: {stats.stutter_score:.1f}/100")
    print("=" * 60)

    print(f"\nDuplicate Frame Detection:")
    print("-" * 40)
    print(f"  Duplicate frames: {stats.duplicate_frames} ({stats.duplicate_ratio*100:.1f}%)")

    print(f"\nFrame Time Metrics:")
    print("-" * 40)
    avg_fps = 1000 / stats.avg_frametime if stats.avg_frametime > 0 else 0
    one_pct_fps = 1000 / stats.one_percent_low if stats.one_percent_low > 0 else 0
    point_one_fps = 1000 / stats.point_one_percent_low if stats.point_one_percent_low > 0 else 0

    print(f"  Average:    {stats.avg_frametime:.2f} ms ({avg_fps:.1f} FPS)")
    print(f"  1% Low:     {stats.one_percent_low:.2f} ms ({one_pct_fps:.1f} FPS)")
    print(f"  0.1% Low:   {stats.point_one_percent_low:.2f} ms ({point_one_fps:.1f} FPS)")
    print(f"  Maximum:    {stats.max_frametime:.2f} ms")

    print(f"\nSmoothness Analysis:")
    print("-" * 40)
    print(f"  1% Low / Avg ratio: {stats.avg_to_1pct_ratio:.2%}")
    if stats.avg_to_1pct_ratio > 0.9:
        print("  -> Excellent: very consistent frame times")
    elif stats.avg_to_1pct_ratio > 0.7:
        print("  -> Good: minor frame time variance")
    elif stats.avg_to_1pct_ratio > 0.5:
        print("  -> Fair: noticeable stutter")
    else:
        print("  -> Poor: significant stutter")

    if stutters:
        print(f"\nStutter Events (duplicates during motion): {len(stutters)}")
        print("-" * 40)
        sorted_stutters = sorted(stutters, key=lambda s: -s.frametime_ms)
        for i, s in enumerate(sorted_stutters[:10]):
            print(f"  [{i+1}] @ {s.timestamp:.2f}s: {s.frametime_ms:.0f}ms "
                  f"({s.duplicate_count} dup, motion={s.motion_before:.1f})")
        if len(stutters) > 10:
            print(f"  ... and {len(stutters) - 10} more")
        print(f"\n  Total stutter frames: {sum(s.duplicate_count for s in stutters)}")
    else:
        print("\nNo stutters detected (no duplicates during motion)!")

    print("\n" + "=" * 60 + "\n")


def generate_annotated_video(stats: FrameTimeStats, stutters: list[StutterEvent],
                             video_path: str, output_path: str) -> None:
    if not stutters:
        print("No stutter events to annotate.")
        return

    duration = stats.duration
    bar_height, timeline_height = 40, 8

    filters = [
        f"pad=iw:ih+{bar_height}+{timeline_height}:0:{bar_height}:color=black",
        f"drawbox=x=0:y=0:w=iw:h={bar_height}:color=0x222222:t=fill",
        f"drawbox=x=0:y=ih-{timeline_height}:w=iw:h={timeline_height}:color=0x333333:t=fill",
        f"drawbox=x=0:y=ih-{timeline_height}:w='(t/{duration})*iw':h={timeline_height}:color=0x666666:t=fill",
    ]

    for s in stutters:
        x_pos = f"({s.timestamp}/{duration})*iw"
        severity = max(3, int(s.frametime_ms / 10))
        filters.append(f"drawbox=x={x_pos}:y=ih-{timeline_height}:w={severity}:h={timeline_height}:color=red:t=fill")

    avg_fps = 1000 / stats.avg_frametime if stats.avg_frametime > 0 else 0
    one_pct_fps = 1000 / stats.one_percent_low if stats.one_percent_low > 0 else 0
    filters.append(f"drawtext=text='Avg {avg_fps:.0f} FPS | 1% Low {one_pct_fps:.0f} FPS | {len(stutters)} stutters':"
                   f"fontsize=18:fontcolor=0x888888:x=10:y=({bar_height}-text_h)/2")

    frame_duration = 1.0 / stats.fps
    for s in stutters:
        stutter_duration = s.duplicate_count * frame_duration
        enable = f"enable='between(t,{s.timestamp},{s.timestamp + stutter_duration})'"
        filters.extend([
            f"drawbox=x=2:y={bar_height}+2:w=iw-4:h=ih-{bar_height}-{timeline_height}-4:color=red:t=4:{enable}",
            f"drawbox=x=0:y=0:w=iw:h={bar_height}:color=0x880000:t=fill:{enable}",
            f"drawtext=text='STUTTER {s.frametime_ms:.0f}ms ({s.duplicate_count} dup)':"
            f"fontsize=22:fontcolor=white:x=10:y=({bar_height}-text_h)/2:{enable}",
        ])

    cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", ",".join(filters), "-c:a", "copy", output_path]
    print(f"Generating annotated video with {len(stutters)} stutter markers...")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            print(f"Done! Output: {output_path}")
        else:
            print(f"Error: {proc.stderr}")
    except FileNotFoundError:
        print("Error: ffmpeg not found.")


def to_json(stats: FrameTimeStats, stutters: list[StutterEvent], video_path: str) -> dict:
    return {
        "video_path": video_path,
        "fps": round(stats.fps, 2),
        "total_frames": stats.total_frames,
        "duration": round(stats.duration, 3),
        "smoothness_score": round(stats.stutter_score, 1),
        "duplicate_detection": {
            "duplicate_frames": stats.duplicate_frames,
            "duplicate_ratio": round(stats.duplicate_ratio, 4),
        },
        "frame_times_ms": {
            "average": round(stats.avg_frametime, 2),
            "one_percent_low": round(stats.one_percent_low, 2),
            "point_one_percent_low": round(stats.point_one_percent_low, 2),
            "maximum": round(stats.max_frametime, 2),
        },
        "smoothness": {"avg_to_1pct_ratio": round(stats.avg_to_1pct_ratio, 4)},
        "stutter_events": [
            {"timestamp": round(s.timestamp, 3), "frametime_ms": round(s.frametime_ms, 2),
             "duplicate_count": s.duplicate_count, "motion_before": round(s.motion_before, 2)}
            for s in stutters
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze frame times in game recordings")
    parser.add_argument("video", help="Path to video file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("-o", "--output", help="Save JSON to file")
    parser.add_argument("--annotate", metavar="OUTPUT", help="Generate annotated video")

    args = parser.parse_args()
    path = Path(args.video)

    if not path.exists():
        print(f"Error: File not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    try:
        stats, stutters = analyze_frametimes(args.video)

        if args.json or args.output:
            data = to_json(stats, stutters, str(path.absolute()))
            json_str = json.dumps(data, indent=2)
            if args.output:
                with open(args.output, "w") as f:
                    f.write(json_str)
                print(f"Saved to: {args.output}")
            if args.json:
                print(json_str)
        else:
            print_report(stats, stutters, str(path.absolute()))

        if args.annotate:
            generate_annotated_video(stats, stutters, args.video, args.annotate)

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
