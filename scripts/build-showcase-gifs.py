"""把 capture-showcase.mjs 生成的帧合成 README 动图（Pillow，项目 .venv 已有）。
用法：python scripts/build-showcase-gifs.py <帧目录> docs/assets/showcase
"""

import pathlib
import sys

from PIL import Image

frames_dir, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])

# 09 预兆：左边四个预兆的选择，右边报告里的预兆覆盖自检，中间细分隔线
picker, coverage = (Image.open(frames_dir / n).convert("RGB") for n in ("omen-picker.png", "omen-coverage.png"))
pad, gap = 48, 64
canvas = Image.new("RGB", (pad * 2 + picker.width + gap + coverage.width, pad * 2 + max(picker.height, coverage.height)), "white")
canvas.paste(picker, (pad, pad))
canvas.paste(coverage, (pad + picker.width + gap, pad))
for y in range(pad, canvas.height - pad):
    canvas.putpixel((pad + picker.width + gap // 2, y), (229, 229, 229))
canvas.save(out / "09-omens.png", optimize=True)
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
