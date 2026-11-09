import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from .service import BiliService
from .watch import extract, ffmpeg, image_content, media_url, sample_times, watch

BV = "BV1uNk1YxEJQ"


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = BiliService(self.temporary.name)

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def test_timeline_includes_beginning_end_and_rejects_invalid_duration(self):
        self.assertEqual(sample_times(12, 5), [0, 5, 10, 11.9])
        self.assertEqual(sample_times(0.5, 5), [0, 0.4])
        for value in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                sample_times(value, 5)

    def test_media_domains_not_local_or_credentials(self):
        self.assertEqual(
            media_url("https://a.bilivideo.com/video"), "https://a.bilivideo.com/video"
        )
        for url in (
            "http://127.0.0.1/a",
            "https://bilivideo.com.evil.test/a",
            "file:///C:/test",
            "https://user:secret@a.bilivideo.com/a",
            "https://a.bilivideo.com:3000/a",
        ):
            with self.assertRaises(ValueError):
                media_url(url)

    def material(self, name, args):
        if name == "bili_video_info":
            return {"title": "test", "pages": [{"duration": 12}, {"duration": 3}]}
        if name == "bili_video_streams":
            duration = 12 if args["page"] == 1 else 3
            return {
                "segments": [{"url": "https://a.bilivideo.com/v", "duration": duration}]
            }
        if name == "bili_subtitle":
            return {"text": "", "message": "no subtitles"}
        return {"items": []}

    def frame(self, executable, source, timestamp, output):
        Image.new("RGB", (320, 180), "blue").save(output)

    def test_all_pages_images_reach_model_no_subtitles_and_cleanup(self):
        with (
            patch.object(self.service, "api", side_effect=self.material),
            patch("bili.watch.ffmpeg", return_value="ffmpeg"),
            patch(
                "bili.watch.download",
                side_effect=lambda url, path, *a: path.write_bytes(b"x" * 100) or 100,
            ),
            patch("bili.watch.probe_duration", return_value=12.0),
            patch("bili.watch.extract", side_effect=self.frame),
            patch("pathlib.Path.unlink"),
            patch.object(
                self.service, "completion", return_value={"content": "blue frames"}
            ) as model,
        ):
            result = watch(self.service, BV, "key", "base", "model")
        self.assertTrue(result["visual_complete"])
        self.assertEqual(result["frame_count"], 6)
        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(model.call_count, 2)
        content = model.call_args.args[0][-1]["content"]
        self.assertEqual(
            [p["type"] for p in content], ["text", "image_url", "image_url"]
        )
        self.assertFalse(list(self.service.home.glob("watch-*")))

    def test_limit_fails_before_download(self):
        self.service.save_config({"frame_limit": 18})
        with (
            patch("bili.watch.ffmpeg", return_value="ffmpeg"),
            patch.object(
                self.service, "api", return_value={"pages": [{"duration": 1000}]}
            ),
            patch("bili.watch.download") as download,
        ):
            with self.assertRaisesRegex(RuntimeError, "超过"):
                watch(self.service, BV, "key", "base", "model")
            download.assert_not_called()

    def test_scan_requires_visual_evidence_not_just_metadata(self):
        responses = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "1",
                        "function": {
                            "name": "bili_video_info",
                            "arguments": json.dumps({"bvid": BV}),
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "### " + BV + "\nfabricated"},
        ]
        with (
            patch.object(self.service, "completion", side_effect=responses),
            patch.object(self.service, "api", return_value={"title": "test"}),
        ):
            with self.assertRaisesRegex(RuntimeError, "没有取得"):
                self.service.scan("", BV, "key", "base", "model")
        self.assertFalse(self.service.seen)

    def test_scan_archives_visual_evidence_and_failed_vision_does_not_archive(self):
        responses = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "1",
                        "function": {
                            "name": "bili_watch",
                            "arguments": json.dumps({"bvid": BV}),
                        },
                    }
                ],
            },
            {"role": "assistant", "content": "### " + BV + "\ntest"},
        ]
        evidence = {
            "bvid": BV,
            "title": "test",
            "visual_complete": True,
            "frame_count": 4,
            "pages": [{"page": 1}],
        }
        with (
            patch.object(self.service, "completion", side_effect=responses),
            patch("bili.watch.watch", side_effect=RuntimeError("vision failed")),
        ):
            with self.assertRaises(RuntimeError):
                self.service.scan("", BV, "key", "base", "model")
        self.assertFalse(self.service.seen)
        with (
            patch.object(self.service, "completion", side_effect=responses),
            patch("bili.watch.watch", return_value=evidence),
        ):
            result = self.service.scan("", BV, "key", "base", "model")
        self.assertEqual(result["visual"][BV], {"frames": 4, "pages": 1})
        self.assertIn("非逐帧", result["report"])
        self.assertTrue(list((self.service.home / "reports").glob("*-evidence.json")))

    def test_real_ffmpeg_decode_and_image_payload(self):
        executable = ffmpeg()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "clip.mp4"
            subprocess.run(
                [
                    executable,
                    "-nostdin",
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=blue:s=320x180:d=1",
                    str(source),
                ],
                check=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            frame = root / "frame.jpg"
            extract(executable, source, 0.5, frame)
            content = image_content([(0.5, frame)])
            self.assertTrue(
                content["image_url"]["url"].startswith("data:image/jpeg;base64,")
            )


if __name__ == "__main__":
    unittest.main()
