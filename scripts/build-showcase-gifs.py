"""把 capture-showcase.mjs 生成的帧合成 README 动图（Pillow，项目 .venv 已有）。
用法：python scripts/build-showcase-gifs.py <帧目录> docs/assets/showcase
"""

import pathlib
import sys

from PIL import Image

frames_dir, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
for name, folder, ms in [("demo-report.gif", "a", 180), ("demo-chat-process.gif", "b", 230)]:
    images = [Image.open(f).convert("RGB").resize((1120, 700), Image.LANCZOS) for f in sorted((frames_dir / folder).glob("*.png"))]
    # 用首、中、末三帧拼出共用调色板，避免逐帧换色闪烁；界面以黑白灰为主，128 色足够
    sample = Image.new("RGB", (1120, 700 * 3))
    for k, i in enumerate([0, len(images) // 2, -1]):
        sample.paste(images[i], (0, 700 * k))
    palette = sample.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    frames = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in images]
    frames[0].save(out / name, save_all=True, append_images=frames[1:], duration=ms, loop=0, optimize=True)
    print(name, round((out / name).stat().st_size / 1e6, 2), "MB")
