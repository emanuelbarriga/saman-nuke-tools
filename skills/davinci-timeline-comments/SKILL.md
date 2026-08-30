---
name: davinci-timeline-comments
description: "Trigger: comentarios davinci, marcadores timeline, davinci markers, crear secuencias davinci, davinci timeline comments. Add DaVinci Resolve timeline markers from comment blocks and create sequences from clips with matching start timecode."
license: Apache-2.0
metadata:
  author: "emanuel"
  version: "1.0"
---

# DaVinci Timeline Comments

## Activation Contract

Load when asked to add comments/markers to a DaVinci Resolve timeline, import review notes as markers, or create Resolve sequences from clips with the clip's start timecode.

## Hard Rules

- Resolve MUST be running. Connect with env vars: `RESOLVE_SCRIPT_API`, `RESOLVE_SCRIPT_LIB`, and `PYTHONPATH` (Mac paths in References).
- Resolve 21 API: use `project.GetMediaPool()`. `resolve.GetMediaPool()` does NOT exist (returns None).
- Timeline start timecode is set with `timeline.SetStartTimecode("HH:MM:SS:FF")`, NOT with SetSetting (returns False).
- Markers: `timeline.AddMarker(frameId, color, name, note, duration, customData)`. frameId is 1-based relative to the timeline start TC.
- TC → frame: `frame = round((tc_seconds - start_tc_seconds) * fps) + 1`, with `fps = project.GetSetting("timelineFrameRate")` (23.976) and `start_tc = timeline.GetStartTimecode()`.
- Never add markers or create sequences without an explicit user request listing them; deleting is via `mediaPool.DeleteTimelines([tl])` or `timeline.DeleteMarkerAtFrame(frameId)`.

## Decision Gates

| Need | Action |
|---|---|
| Comments as text blocks (author/day/#/TC/note) | Parse each block; TC is the anchor |
| Timeline not current | `project.GetTimelineByIndex(i)` is 1-based; or ask the user to open it |
| Wrong TC anchor | Ask the user for the real sequence start TC before converting |
| Create sequences from bin clips | `CreateTimelineFromClips(name_without_ext, [clip])` then `SetStartTimecode(clip.GetClipProperty("Start TC"))` |

## Execution Steps

1. Probe read-only: project name, timeline name, fps, start TC, current marker count.
2. Parse the comment blocks; for each, capture TC (`HH:MM:SS:FF`) and note text.
3. Convert each TC to frameId with the formula above.
4. `AddMarker` with color (Red for notes), name = `"{num} {author}"` (e.g. `#1 Diego Quintana`), note = comment text, customData = author.
5. Verify `GetMarkers()` and report the TC → frameId mapping.

Optional — create sequences from clips:
6. Find source bin (`GetRootFolder` + `GetSubFolderList`) and destination bin; `SetCurrentFolder(dest)`.
7. For each clip: `CreateTimelineFromClips(name_without_ext, [clip])`, then `SetStartTimecode(clip.GetClipProperty("Start TC"))`; verify with `GetStartTimecode()`.

## Output Contract

Return markers added (TC → frameId, note) or sequences created (name → start TC), with counts and any failures.

## References

- API README: `/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/README.txt`
- Mac env: `RESOLVE_SCRIPT_API="/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"`; `RESOLVE_SCRIPT_LIB="/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"`; `PYTHONPATH="$PYTHONPATH:$RESOLVE_SCRIPT_API/Modules/"`
- Bin convention: clips in `Master/TO_VFX/EP_{EP}/{fecha}/SECUENCES` → timelines in `Master/SECUENCES`.