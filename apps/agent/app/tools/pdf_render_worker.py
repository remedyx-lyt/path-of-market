"""在独立、可超时终止的进程中渲染单页。PDFium 不在 FastAPI 的多个线程间共享。"""

import math
import sys

import pypdfium2 as pdfium


def render(source, page_number, output):
    pdf = pdfium.PdfDocument(source)
    try:
        page = pdf[page_number - 1]
        try:
            width, height = page.get_size()
            if not all(math.isfinite(n) and n > 0 for n in (width, height)):
                raise ValueError("invalid page size")
            bitmap = page.render(scale=1799 / max(width, height))
            try:
                image = bitmap.to_pil()
                try:
                    image.save(output, format="PNG")
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        pdf.close()


if __name__ == "__main__":
    try:
        render(sys.argv[1], int(sys.argv[2]), sys.argv[3])
    except Exception:
        sys.exit(1)  # 只向父进程返回失败，不回显路径、PDF 内容或第三方堆栈。
