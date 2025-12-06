# Active TODO List

## High Priority
[] Prompt engineer so that the transcript match the timestamp (will review later)
[] Automate the downloading/chunking process - How to link the raw audio to the cut one? How to make sure the transcript is consistent?
[] Wire up Audio Refinement tab to actually run DeepFilterNet denoising
[] Add reviewer assignment by channel name (currently per-video only)

## Medium Priority
[] Improve Gemini processing state handling (accept both 'pending' and 'denoised' states)
[] Add batch processing options in Streamlit GUI
[] Add export statistics and validation report

## Low Priority
[] Add export preview before final export
[] Add undo functionality for segment edits
[] Add keyboard navigation for segment list

---

# Completed Items

## December 2025
[x] Change the tab name: Review Videos → Review Audio Transcript; Ingest Videos → Download Audios
[x] Reviewer tab as a drop-down list (with add option)
[x] Add another tab for audio preprocessing (Audio Refinement placeholder created)
[x] Review the database such that we have the channel name, the video name
[x] In Review Videos tab, allow to upload transcript/remove transcript
[x] Group video by channel name in Review Videos tab
[x] Add option to press play and it will play the audio according to the start millisecond in the transcript and pause after the end millisecond
[x] Test direct upload
[x] Run for one video
[x] Fix these warnings