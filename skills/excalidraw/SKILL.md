---
name: excalidraw
description: >-
  Draw a diagram for Valentin as a shared Excalidraw scene and hand him the
  https link. Use when he asks for a diagram, a drawing, a flow, a sketch or a
  picture of how parts fit together.
disable-model-invocation: true
---

# excalidraw

Prior art: pstack has no drawing skill; the API is documented at https://plus.excalidraw.com/llms-full.txt.

Every chat draws for Valentin in his own Excalidraw workspace. Write the elements, then run the helper:

```bash
timeout 60 ~/.local/bin/excalidraw-share drawing.excalidraw --name "How a ticket ships"
timeout 60 ~/.local/bin/excalidraw-share drawing.json --scene 2YaSpW57ZCO
```

It prints one line: the link. Send him that line as plain text.
Never put the link inside bold: `**https://...**` breaks the URL in his client.

Working drawing to copy: [example.excalidraw](example.excalidraw) (rectangles, text, arrows, diamonds bound together).

## What the helper does

1. Reads the key once from 1Password, vault "Yeo UX Agents", item "Excalidraw", field `credential`:
   `XDG_RUNTIME_DIR=/run/user/$(id -u) yeo-key Excalidraw credential`.
   `XDG_RUNTIME_DIR` is required, and `yeo-key --env` fails on labels with spaces.
   Never print, log or commit the key. Header: `Authorization: Bearer <key>`.
2. Creates the scene: `POST https://api.excalidraw.com/api/v1/collections/8nmjwOyvh62/scenes`
   with `{"name": "..."}`; the scene id is at `.metadata.id`. That collection is in workspace
   `1GorMHPWnnO`. With `--scene <id>` it skips this and replaces that scene instead.
3. Fills it: `PUT /scenes/<id>/content` with a full `.excalidraw` document.
4. Shares it: `PUT /scenes/<id>/link-sharing` with `{"access": "view"}`.
   The link is `https://app.excalidraw.com/s/1GorMHPWnnO/<id>`.

## Writing elements

The file is one JSON document:

```json
{"type": "excalidraw", "version": 2, "source": "https://excalidraw.com",
 "elements": [...], "appState": {"viewBackgroundColor": "#ffffff"}, "files": {}}
```

A minimal element is enough: `id`, `type`, `x`, `y`, `width`, `height`, plus `text` for text
and `points` for lines and arrows. The helper fills every other standard field with
Excalidraw's default, and gives text `fontFamily` 6 (Nunito, Valentin's pick) unless you
set it.

Layout: draw a grid by hand. Boxes 200x90 with 60 px gaps read well; put a title text
element above the row, and keep every arrow between two boxes.

## Gotchas

1. Every element needs an `index` string: fractional order keys `a0`, `a1`, `a2`, and past `az`
   `b00`, `b01`. The API rejects a scene without them. The helper fills them in document order
   whenever any element is missing one, and leaves a document that already has them alone.
2. An arrow that must follow a box needs bindings on both ends:
   `{"elementId": "todo", "fixedPoint": [0.5, 0.5], "mode": "orbit"}`, plus the arrow id listed
   in that box's `boundElements`. A one-sided binding still draws, it just does not stick.
3. `PUT /scenes/<id>/content` replaces the whole scene. To change one box, edit the file and
   rerun with `--scene <id>`; the link stays the same.
4. Sharing fails with 403 when a workspace admin has turned scene sharing off. Report that,
   do not retry.
5. Text width is not measured. Give a text element a width wide enough for its line and
   `"autoResize": true`, or the text spills outside its box.
6. A rerun without `--scene` makes a second scene. Keep the scene id if he may ask for a change.
