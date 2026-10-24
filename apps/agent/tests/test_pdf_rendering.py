"""原页渲染使用项目依赖；即使服务没有 Poppler/PATH，也可在隔离子进程生成受限 PNG。"""

import os
import subprocess
import unittest
from unittest.mock import patch

from support import DOC_ID, RunnerFixture

from app.tools.contracts import ToolError
from app.tools.visuals import render_pages


class Rendering(RunnerFixture, unittest.TestCase):
    def fetched(self):
        self.tools.execute("find_documents", {"company": "同花顺", "years": [2024], "asOfDate": "2026-10-23"})
        self.tools.execute("fetch_document", {"documentId": DOC_ID})

    def test_no_poppler_path_required_and_cached_png_needs_no_worker(self):
        self.fetched()
        with patch.dict(os.environ, {"PATH": ""}):
            result = render_pages(self.tools.store, {"documentId": DOC_ID, "pages": [1, 2]})
        self.assertEqual(result["status"], "rendered_not_yet_model_processed")
        for page in result["pages"]:
            self.assertTrue(page["imageDataUrl"].startswith("data:image/png;base64,"))
            self.assertTrue(0 < page["width"] <= 1800 and 0 < page["height"] <= 1800)
        with patch("app.tools.visuals.subprocess.run", side_effect=AssertionError("cache must not render")):
            again = render_pages(self.tools.store, {"documentId": DOC_ID, "pages": [1, 2]})
        self.assertEqual([p["imageSha256"] for p in again["pages"]], [p["imageSha256"] for p in result["pages"]])

    def test_timeout_is_a_tool_error_and_records_no_successful_image(self):
        self.fetched()
        with patch("app.tools.visuals.subprocess.run", side_effect=subprocess.TimeoutExpired("isolated", 30)):
            with self.assertRaises(ToolError) as error:
                render_pages(self.tools.store, {"documentId": DOC_ID, "pages": [1]})
        self.assertEqual(error.exception.code, "PDF_RENDER_TIMEOUT")
        self.assertFalse(list((self.tools.store.root / "visual-pages").glob("*.png")))

    def test_corrupt_png_is_rejected(self):
        self.fetched()
        render_pages(self.tools.store, {"documentId": DOC_ID, "pages": [1]})
        path = next((self.tools.store.root / "visual-pages").glob("*.png"))
        path.write_bytes(b"not png")
        with self.assertRaises(ToolError) as error:
            render_pages(self.tools.store, {"documentId": DOC_ID, "pages": [1]})
        self.assertEqual(error.exception.code, "VISUAL_CACHE_INVALID")

    def test_out_of_range_is_rejected_before_worker(self):
        self.fetched()
        with patch("app.tools.visuals.subprocess.run", side_effect=AssertionError("must not render")):
            with self.assertRaises(ToolError) as error:
                render_pages(self.tools.store, {"documentId": DOC_ID, "pages": [3]})
        self.assertEqual(error.exception.code, "PAGE_OUT_OF_RANGE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
