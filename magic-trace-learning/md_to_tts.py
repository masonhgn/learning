"""Convert a markdown file to ElevenLabs-friendly text with pause tags.

Usage:
    python md_to_tts.py input.md [output.txt]

ElevenLabs supports <break time="Xs" /> tags for explicit pauses (max 3s).
This script:
  - Strips markdown formatting (bold, italic, code, links, images).
  - Inserts long pauses after H1 / H2 / H3 headers.
  - Inserts a long pause where '---' separators appear.
  - Converts the **Overview.** / **Detailed.** cues into spoken sub-beats
    with a short pause so the narration breathes between them.
"""

import re
import sys
from pathlib import Path

PAUSE_H1 = '<break time="2.5s" />'
PAUSE_H2 = '<break time="2.0s" />'
PAUSE_H3 = '<break time="1.5s" />'
PAUSE_SEPARATOR = '<break time="2.5s" />'
PAUSE_CUE = '<break time="0.7s" />'  # after "Overview." / "Detailed."


def strip_inline_markdown(text: str) -> str:
    # Images: ![alt](url) -> alt
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    # Links: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    # Inline code: `foo` -> foo
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # Bold: **foo** or __foo__ -> foo
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'__([^_]+)__', r'\1', text)
    # Italic: *foo* or _foo_ -> foo  (run after bold so ** is gone)
    text = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'\1', text)
    text = re.sub(r'(?<!_)_([^_\n]+)_(?!_)', r'\1', text)
    # Strikethrough: ~~foo~~ -> foo
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    return text


def convert(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    in_code_block = False

    for raw in lines:
        line = raw.rstrip()

        # Skip fenced code blocks entirely — they don't read well aloud.
        if line.lstrip().startswith('```'):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        stripped = line.strip()

        # Horizontal rule -> long pause.
        if re.fullmatch(r'-{3,}|\*{3,}|_{3,}', stripped):
            out.append('')
            out.append(PAUSE_SEPARATOR)
            out.append('')
            continue

        # Headers.
        m = re.match(r'^(#{1,6})\s+(.*)$', stripped)
        if m:
            level = len(m.group(1))
            title = strip_inline_markdown(m.group(2)).strip()
            # Drop a leading "N." numbering so it reads naturally.
            title = re.sub(r'^\d+\.\s*', '', title)
            if not title.endswith(('.', '!', '?', ':')):
                title += '.'
            pause = {1: PAUSE_H1, 2: PAUSE_H2}.get(level, PAUSE_H3)
            out.append('')
            out.append(f'{title} {pause}')
            out.append('')
            continue

        # Strip blockquote / list markers but keep the content.
        stripped = re.sub(r'^>\s?', '', stripped)
        stripped = re.sub(r'^[-*+]\s+', '', stripped)
        stripped = re.sub(r'^\d+\.\s+', '', stripped)

        cleaned = strip_inline_markdown(stripped)

        # The "**Overview.**" / "**Detailed.**" cues are now bare words at the
        # start of a paragraph. Add a small pause so they don't run into the
        # sentence that follows.
        cue_match = re.match(r'^(Overview|Detailed)\.\s+(.*)$', cleaned)
        if cue_match:
            cleaned = f'{cue_match.group(1)}. {PAUSE_CUE} {cue_match.group(2)}'

        out.append(cleaned)

    # Collapse runs of blank lines down to a single blank line.
    collapsed: list[str] = []
    blank = False
    for line in out:
        if line == '':
            if not blank:
                collapsed.append('')
            blank = True
        else:
            collapsed.append(line)
            blank = False

    body = '\n'.join(collapsed).strip()
    return f'<speak>\n{body}\n</speak>\n'


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else in_path.with_suffix('.tts.txt')

    md = in_path.read_text(encoding='utf-8')
    out_path.write_text(convert(md), encoding='utf-8')
    print(f'Wrote {out_path}')


if __name__ == '__main__':
    main()
