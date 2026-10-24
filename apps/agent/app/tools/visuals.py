"""将已校验的 PDF 物理页渲染为 PNG；仅渲染，不宣称模型已理解。"""

import base64
from hashlib import sha256
import os
from pathlib import Path
import shutil
import struct
import subprocess
from tempfile import TemporaryDirectory

from app.schemas.financial import InspectArguments
from app.tools.contracts import ToolError
from app.tools.documents import atomic_write


def render_pages(store, arguments):
    args = InspectArguments.model_validate(arguments)
    if any(type(p) is not int or p < 1 for p in args.pages) or len(set(args.pages)) != len(args.pages):
        raise ToolError("INVALID_VISUAL_PAGES", "需要1至3个不重复的正整数物理页码。")
    metadata, text_pages = store.loaded(args.document_id)
    if max(args.pages) > len(text_pages):
        raise ToolError("PAGE_OUT_OF_RANGE", "视觉页码超出 PDF 范围。")
    binary = shutil.which("pdftoppm")
    if binary is None:
        raise ToolError("PDF_RENDERER_UNAVAILABLE", "缺少 Poppler pdftoppm，无法渲染 PDF 原页。")
    folder = store.root / "visual-pages"
    folder.mkdir(parents=True, exist_ok=True)
    result = []
    for page in args.pages:
        key = f"{metadata['sha256']}-p{page}-1800-v1.png"
        path = folder / key
        if not path.exists():
            with TemporaryDirectory(dir=folder) as temporary:
                prefix = Path(temporary) / "page"
                try:
                    process = subprocess.run(
                        [
                            binary,
                            "-f",
                            str(page),
                            "-l",
                            str(page),
                            "-singlefile",
                            "-scale-to",
                            "1800",
                            "-png",
                            str(store.path(args.document_id, ".pdf")),
                            str(prefix),
                        ],
                        capture_output=True,
                        timeout=30,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                except subprocess.TimeoutExpired:
                    raise ToolError("PDF_RENDER_TIMEOUT", "PDF 原页渲染超时，本页未送入模型。") from None
                except OSError:
                    raise ToolError("PDF_RENDER_FAILED", "PDF 原页渲染失败。") from None
                output = prefix.with_suffix(".png")
                if process.returncode or not output.exists() or output.stat().st_size > 4_000_000:
                    raise ToolError("PDF_RENDER_FAILED", "PDF 原页未生成大小受限的 PNG。")
                atomic_write(path, output.read_bytes())
        data = path.read_bytes()
        if len(data) < 24 or len(data) > 4_000_000 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ToolError("VISUAL_CACHE_INVALID", "原页图片缓存无效，未用于视觉理解。")
        width, height = struct.unpack(">II", data[16:24])
        if not 1 <= width <= 1800 or not 1 <= height <= 1800:
            raise ToolError("VISUAL_CACHE_INVALID", "原页图片尺寸无效。")
        result.append(
            {
                "page": page,
                "width": width,
                "height": height,
                "imageSha256": sha256(data).hexdigest(),
                "imageDataUrl": "data:image/png;base64," + base64.b64encode(data).decode(),
                "text": text_pages[page - 1]["text"][:18000],
            }
        )
    return {"document": metadata, "pages": result, "status": "rendered_not_yet_model_processed"}
