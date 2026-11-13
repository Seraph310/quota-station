"""Optional preview encoder (Pillow), run after render_page_turn.py."""
from pathlib import Path
import json
from PIL import Image

base = Path(__file__).resolve().parents[1]
frames = []
durations = []
frame_times = json.loads((base / 'tests/artifacts/page-turn/manifest.json').read_text('utf-8'))['frame_times']
for direction in ('next', 'previous'):
    for index, milliseconds in enumerate(frame_times):
        with Image.open(base / 'tests' / 'artifacts' / 'page-turn' / f'{direction}-{index:02d}.png') as source:
            frame = Image.new('RGBA', source.size, '#f3f5f0')
            frame.alpha_composite(source.convert('RGBA'))
            frames.append(frame.convert('RGB'))
            delay = frame_times[index + 1] - milliseconds if index < len(frame_times) - 1 else 600
            durations.append(delay + (750 if index == 0 else 0))
frames[0].save(base / 'docs' / 'images' / 'page-turn-fold.gif', save_all=True,
               append_images=frames[1:], duration=durations, loop=0, disposal=2)
print('Animated preview encoded from the real widget demo frames.')
