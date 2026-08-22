from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import streamlit as st

from processing import RenderConfig, load_hand_image, render_hand_video

st.set_page_config(page_title="Drawing Hand Studio", page_icon="✍️", layout="wide")
st.title("Drawing Hand Studio")
st.caption("Upload a drawing video and create the hand-following version.")

video = st.file_uploader("Upload drawing video", type=["mp4", "mov", "m4v"])

if video is None:
    st.info("Upload a video to begin.")
    st.stop()

suffix = Path(video.name).suffix.lower() or ".mp4"
input_bytes = video.getvalue()

with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as source:
    source.write(input_bytes)
    source_path = Path(source.name)

capture = cv2.VideoCapture(str(source_path))
ok, first_frame = capture.read()
fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
capture.release()
source_path.unlink(missing_ok=True)

if not ok:
    st.error("This video could not be opened. Please try an MP4 or MOV file.")
    st.stop()

preview_col, info_col = st.columns([1.4, 1])
with preview_col:
    st.image(cv2.cvtColor(first_frame, cv2.COLOR_BGR2RGB), caption="First frame")
with info_col:
    st.metric("Video size", f"{width} × {height}")
    st.metric("Duration", f"{frames / fps:.1f} seconds" if fps else "Unknown")

st.subheader("Drawing area")
area_a, area_b = st.columns(2)
with area_a:
    left = st.slider("Left edge (%)", 0, 80, 0)
    right = st.slider("Right edge (%)", 20, 100, 100)
with area_b:
    top = st.slider("Top edge (%)", 0, 80, 0)
    bottom = st.slider("Bottom edge (%)", 20, 100, 100)

st.subheader("Hand")
hand_a, hand_b, hand_c = st.columns(3)
with hand_a:
    hand_side = st.selectbox("Hand", ["Right", "Left"])
    hand_size = st.slider("Hand size (%)", 12, 80, 70)
with hand_b:
    tip_x = st.slider("Pencil tip X (%)", 0, 100, 15)
    tip_y = st.slider("Pencil tip Y (%)", 0, 100, 34)
with hand_c:
    opacity = st.slider("Hand opacity", 0.20, 1.00, 0.94, 0.02)
    smoothing = st.slider("Movement smoothing", 0.05, 1.00, 0.42, 0.01)

st.caption("Your hand artwork is built in. You do not need to upload a PNG.")

with st.expander("Tracking settings", expanded=False):
    track_a, track_b, track_c = st.columns(3)
    with track_a:
        sensitivity = st.slider("Sensitivity", 5, 80, 24)
    with track_b:
        minimum_area = st.slider("Minimum changed area", 4, 150, 18)
    with track_c:
        hide_after = st.slider("Lift hand after frames", 1, 30, 12)

if left >= right or top >= bottom:
    st.error("The drawing area edges overlap.")
    st.stop()

if st.button("Create hand-following video", type="primary", use_container_width=True):
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as source:
        source.write(input_bytes)
        source_path = Path(source.name)

    config = RenderConfig(
        sensitivity=sensitivity,
        minimum_change_area=minimum_area,
        smoothing=smoothing,
        hide_after_frames=hide_after,
        hand_width_percent=hand_size,
        hand_opacity=opacity,
        hand_side=hand_side,
        tip_x_percent=tip_x,
        tip_y_percent=tip_y,
        roi_left_percent=left,
        roi_top_percent=top,
        roi_right_percent=right,
        roi_bottom_percent=bottom,
    )

    progress_bar = st.progress(0.0, text="Starting")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as result_file:
        result_path = Path(result_file.name)

    try:
        hand = load_hand_image()
        result = render_hand_video(
            source_path,
            result_path,
            hand,
            config,
            progress=lambda value, label: progress_bar.progress(value, text=label),
        )
        st.session_state["rendered_video"] = result_path.read_bytes()
        st.session_state["rendered_name"] = f"hand-{Path(video.name).stem}.mp4"
        st.session_state["render_stats"] = result
    except Exception as exc:
        st.error(f"The video could not be processed: {exc}")
    finally:
        source_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)

if "rendered_video" in st.session_state:
    st.subheader("Result")
    st.video(st.session_state["rendered_video"])
    stats = st.session_state.get("render_stats")
    if stats:
        st.caption(
            f"Tracked {stats.tracked_frames:,} of {stats.frames:,} frames. "
            + ("Original audio preserved." if stats.audio_preserved else "No original audio track found.")
        )
    st.download_button(
        "Download MP4",
        data=st.session_state["rendered_video"],
        file_name=st.session_state["rendered_name"],
        mime="video/mp4",
        use_container_width=True,
    )
