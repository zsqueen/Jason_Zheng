import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from .service import (
    BEIJING,
    DEFAULTS,
    READ_TOOLS,
    BiliService,
    due_dynamic,
    due_scan,
    eligible_videos,
    normalize_config,
    normalize_dm,
    read_json,
    valley,
    write_json,
)

BV = "BV1uNk1YxEJQ"
OTHER = "BV1ednc6jE3j"


class BiliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = BiliService(self.temporary.name)

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def test_remote_chat_tools_and_write_approval(self):
        calls = [
            ("bili_search", {"keyword": "anime"}),
            ("bili_scan", {"direction": "anime"}),
            ("bili_send_dynamic", {"text": "test"}),
            ("bili_inbox", {}),
        ]
        response = {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": str(i),
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
                for i, (name, args) in enumerate(calls)
            ],
        }
        messages = [{"role": "user", "content": "Bilibili anime"}]
        with (
            patch.object(
                self.service,
                "completion",
                side_effect=[response, {"role": "assistant", "content": "tool result"}],
            ) as completion,
            patch.object(self.service, "api", return_value={"videos": []}) as api,
            patch.object(
                self.service, "scan", return_value={"report": "report"}
            ) as scan,
            patch.object(self.service, "deliver") as deliver,
            patch.object(self.service, "_request") as write,
        ):
            approve = MagicMock(return_value=False)
            progress = MagicMock()
            self.assertEqual(
                self.service.chat(
                    messages,
                    "key",
                    "base",
                    "model",
                    approve,
                    remote=True,
                    progress=progress,
                ),
                "tool result",
            )
            api.assert_called_once_with("bili_search", {"keyword": "anime"})
            scan.assert_called_once_with("anime", "", "key", "base", "model")
            deliver.assert_not_called()
            progress.assert_called_once_with()
            write.assert_not_called()
            approve.assert_called_once_with("bili_send_dynamic", {"text": "test"})
            names = {t["function"]["name"] for t in completion.call_args.args[4]}
            self.assertTrue(
                {"bili_inbox", "bili_status", "bili_whoami"}.isdisjoint(names)
            )
            results = [
                json.loads(m["content"]) for m in messages if m["role"] == "tool"
            ]
            self.assertTrue(results[2]["blocked"])
            self.assertIn("error", results[3])

    def test_auto_reply_new_message_dedup_and_follow_requirement(self):
        import tempfile
        import time
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        from .service import BiliService

        with tempfile.TemporaryDirectory() as directory:
            service = BiliService(directory)
            try:
                service.save_config({"auto_reply": True})
                service.update_state({"reply_enabled_at": time.time() - 5})
                cred = SimpleNamespace(dedeuserid="1")
                message = {
                    "sender_uid": 2,
                    "msg_key": "new",
                    "msg_type": 1,
                    "timestamp": time.time(),
                    "content": '{"content":"hello"}',
                }
                with (
                    patch.object(service, "credential", return_value=cred),
                    patch(
                        "bilibili_api.session.get_sessions",
                        new=AsyncMock(
                            return_value={
                                "session_list": [{"talker_id": 2, "unread_count": 1}]
                            }
                        ),
                    ),
                    patch(
                        "bilibili_api.session.fetch_session_msgs",
                        new=AsyncMock(return_value={"messages": [message]}),
                    ),
                    patch(
                        "bilibili_api.user.User.get_relation",
                        new=AsyncMock(return_value={"relation": {"attribute": 0}}),
                    ) as relation,
                    patch(
                        "bilibili_api.user.User.modify_relation", new=AsyncMock()
                    ) as follow,
                    patch.object(
                        service, "completion", return_value={"content": "你好呀~"}
                    ) as model,
                    patch.object(
                        service, "_request", return_value={"success": True}
                    ) as send,
                ):
                    self.assertIn(
                        "关注尚未确认",
                        service.auto_reply_messages("key", "base", "model")[0],
                    )
                    model.assert_not_called()
                    follow.assert_awaited_once()
                    follow.reset_mock()
                    relation.side_effect = [
                        {"relation": {"attribute": 0}},
                        {"relation": {"attribute": 2}},
                    ]
                    self.assertEqual(
                        len(service.auto_reply_messages("key", "base", "model")), 1
                    )
                    follow.assert_awaited_once()
                    service.auto_reply_messages("key", "base", "model")
                    send.assert_called_once_with(
                        "bili_send_message", {"receiver_uid": 2, "text": "你好呀~"}
                    )
                    service.save_config({"auto_reply": False})
                    self.assertEqual(
                        service.auto_reply_messages("key", "base", "model"), []
                    )
            finally:
                service.close()

    def test_defaults_do_not_publish_or_poll(self):
        cfg = self.service.config()
        self.assertEqual(cfg["auto_mode"], "manual")
        self.assertEqual(cfg["dm_mode"], "off")
        self.assertEqual(cfg["triple_mode"], "off")
        self.assertFalse(cfg["auto_comment"] or cfg["dynamic_on"] or cfg["watch_on"])

    def test_config_bounds_and_invalid_types(self):
        cfg = normalize_config(
            {
                "per_scan": 999,
                "gap_min": -1,
                "watch_interval": 1,
                "auto_comment": "true",
                "dynamic_time": "99:99",
            }
        )
        self.assertEqual(
            (cfg["per_scan"], cfg["gap_min"], cfg["watch_interval"]), (10, 5, 60)
        )
        self.assertFalse(cfg["auto_comment"])
        self.assertEqual(cfg["dynamic_time"], "22:00")

    def test_beijing_valley_and_weekend(self):
        self.assertFalse(valley(datetime(2026, 11, 5, 10, tzinfo=BEIJING)))
        self.assertTrue(valley(datetime(2026, 11, 5, 19, tzinfo=BEIJING)))
        self.assertTrue(valley(datetime(2026, 11, 7, 10, tzinfo=BEIJING)))

    def test_auto_quota_gap_cooldown_and_day_reset(self):
        cfg = {**DEFAULTS, "auto_mode": "always", "per_day": 1}
        now = datetime(2026, 11, 5, 19, tzinfo=BEIJING)
        self.assertTrue(due_scan(cfg, {}, now))
        self.assertFalse(
            due_scan(cfg, {"auto_day": "2026-11-05", "auto_count": 1}, now)
        )
        self.assertTrue(due_scan(cfg, {"auto_day": "2026-11-04", "auto_count": 1}, now))
        self.assertFalse(due_scan(cfg, {"auto_at": now.timestamp() - 60}, now))
        self.assertFalse(due_scan(cfg, {"retry_after": now.timestamp() + 600}, now))

    def test_dynamic_once_per_day_and_three_hour_window(self):
        cfg = {**DEFAULTS, "dynamic_on": True, "dynamic_auto": True}
        self.assertTrue(
            due_dynamic(cfg, {}, datetime(2026, 11, 5, 22, 30, tzinfo=BEIJING))
        )
        self.assertFalse(
            due_dynamic(
                cfg,
                {"dynamic_auto_day": "2026-11-05"},
                datetime(2026, 11, 5, 23, tzinfo=BEIJING),
            )
        )
        self.assertFalse(
            due_dynamic(cfg, {}, datetime(2026, 11, 5, 21, tzinfo=BEIJING))
        )

    def test_filter_views_age_seen_and_html(self):
        cfg = {**DEFAULTS, "min_views": 100, "min_age_days": 2}
        items = [
            {"bvid": BV, "play": 200, "pubdate": 1, "title": "<em>AI</em> &amp; 鱼"},
            {"bvid": OTHER, "play": 1, "pubdate": 1},
        ]
        filtered = eligible_videos(items, cfg, {}, 86400 * 3)
        self.assertEqual(filtered[0]["title"], "AI & 鱼")
        self.assertFalse(eligible_videos(items, cfg, {BV: "2026-11-05"}, 86400 * 3))

    def test_dm_cards_and_plain_messages(self):
        card = normalize_dm(
            {
                "content": json.dumps(
                    {
                        "jump_url": "https://www.bilibili.com/video/" + BV,
                        "title": "分享",
                    }
                ),
                "msg_key": 1,
                "sender_uid": 123,
            },
            123,
        )
        self.assertEqual(card["bvid"], BV)
        text = normalize_dm({"content": '{"content":"你好"}', "msg_key": 2}, 123)
        self.assertEqual(text["text"], "你好")

    def test_read_only_worker_has_no_write_tools(self):
        names = {t["function"]["name"] for t in READ_TOOLS}
        self.assertNotIn("bili_reply", names)
        self.assertNotIn("bili_send_message", names)
        self.assertNotIn("bili_send_dynamic", names)
        with self.assertRaises(PermissionError):
            self.service.api("bili_reply", {"bvid": BV, "text": "禁止"})

    def test_rejection_blocks_all_following_writes(self):
        def response(name):
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": name,
                        "function": {
                            "name": name,
                            "arguments": '{"text":"测试","bvid":"' + BV + '"}',
                        },
                    }
                ],
            }

        with (
            patch.object(
                self.service,
                "completion",
                side_effect=[
                    response("bili_reply"),
                    response("bili_send_dynamic"),
                    {"role": "assistant", "content": "取消"},
                ],
            ),
            patch.object(self.service, "_request") as request,
        ):
            approvals = []
            result = self.service.chat(
                [],
                "key",
                "https://example.test",
                "model",
                lambda name, args: approvals.append(name) or False,
            )
            self.assertEqual(result, "取消")
            self.assertEqual(approvals, ["bili_reply"])
            request.assert_not_called()

    def test_tool_name_injection_is_blocked(self):
        result = []
        responses = [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "1", "function": {"name": "delete_files", "arguments": "{}"}}
                ],
            },
            {"role": "assistant", "content": "结束"},
        ]
        with patch.object(self.service, "completion", side_effect=responses):
            self.service.agent(
                [],
                "key",
                "base",
                "model",
                READ_TOOLS,
                lambda name, args: result.append(name),
            )
        self.assertFalse(result)

    def test_scan_persists_only_selected_not_all_candidates(self):
        responses = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "1",
                        "function": {
                            "name": "bili_subtitle",
                            "arguments": json.dumps({"bvid": BV}),
                        },
                    },
                    {
                        "id": "2",
                        "function": {
                            "name": "bili_subtitle",
                            "arguments": json.dumps({"bvid": OTHER}),
                        },
                    },
                ],
            },
            {
                "role": "assistant",
                "content": "### " + BV + "\n标题：测试\n档位：值得看\n确实取得字幕。",
            },
        ]
        with (
            patch.object(self.service, "completion", side_effect=responses),
            patch.object(
                self.service, "api", return_value={"text": "字幕内容", "title": "测试"}
            ),
        ):
            result = self.service.scan("AI", "", "key", "base", "model")
        self.assertEqual(result["bvids"], [BV])
        self.assertIn(BV, self.service.seen)
        self.assertNotIn(OTHER, self.service.seen)
        self.assertTrue(Path(result["path"]).exists())
        self.assertEqual(len(list((self.service.home / "reports").glob("*.md"))), 1)

    def test_only_dm_never_posts_comment(self):
        self.service.save_config(
            {
                "auto_comment": True,
                "mention_name": "主人",
                "dm_mode": "only",
                "dm_uid": "123",
            }
        )
        with (
            patch.object(
                self.service, "completion", return_value={"content": "结果 " + BV}
            ),
            patch.object(
                self.service, "_request", return_value={"success": True}
            ) as request,
        ):
            self.service.deliver(
                {"report": "报告", "bvids": [BV]}, "key", "base", "model"
            )
        self.assertEqual(request.call_args.args[0], "bili_send_message")
        self.assertEqual(request.call_count, 1)

    def test_acknowledge_only_delivered_items(self):
        self.service.acknowledge([{"key": "dm:123:1"}])
        self.assertEqual(set(self.service.watch_seen), {"dm:123:1"})

    def test_api_missing_login_has_clear_error(self):
        with self.assertRaisesRegex(RuntimeError, "扫码登录"):
            self.service.api("bili_whoami")

    def test_empty_saved_credentials_are_not_logged_in(self):
        write_json(
            self.service.home / "credential.json", {"sessdata": "", "bili_jct": ""}
        )
        self.assertFalse(self.service.status()["logged_in"])
        with self.assertRaisesRegex(RuntimeError, "扫码登录"):
            self.service.credential()

    def test_login_cookies_are_verified_before_saving(self):
        self.service.login = {"key": "test"}
        cookies = {"SESSDATA": "session", "bili_jct": "csrf", "DedeUserID": "123"}
        with (
            patch.object(
                self.service,
                "_login_response",
                new=AsyncMock(
                    return_value=(
                        {
                            "code": 0,
                            "url": "https://www.bilibili.com/",
                            "refresh_token": "refresh",
                        },
                        cookies,
                    )
                ),
            ),
            patch(
                "bilibili_api.user.get_self_info",
                new=AsyncMock(return_value={"mid": 123, "name": "test"}),
            ),
        ):
            self.assertEqual(self.service.api("bili_login_poll")["status"], "done")
        self.assertTrue(self.service.status()["logged_in"])
        self.assertEqual(self.service.credential().ac_time_value, "refresh")

    def test_login_callback_query_is_decoded(self):
        self.service.login = {"key": "test"}
        with (
            patch.object(
                self.service,
                "_login_response",
                new=AsyncMock(
                    return_value=(
                        {
                            "code": 0,
                            "url": "https://www.bilibili.com/?SESSDATA=a%2Cb&bili_jct=csrf&DedeUserID=123",
                        },
                        {},
                    )
                ),
            ),
            patch(
                "bilibili_api.user.get_self_info",
                new=AsyncMock(return_value={"mid": 123}),
            ),
        ):
            self.service.api("bili_login_poll")
        self.assertEqual(
            read_json(self.service.home / "credential.json", {})["sessdata"], "a,b"
        )

    def test_failed_login_preserves_old_credentials(self):
        path = self.service.home / "credential.json"
        old = {"sessdata": "old", "bili_jct": "old", "dedeuserid": "123"}
        write_json(path, old)
        for data, cookies, account, error in (
            (
                {"code": 0, "url": "https://www.bilibili.com/"},
                {},
                {"mid": 123},
                "完整登录凭证",
            ),
            ({"code": 999}, {}, {"mid": 123}, "未确认登录"),
            (
                {"code": 0},
                {"SESSDATA": "new", "bili_jct": "new", "DedeUserID": "123"},
                {"mid": 456},
                "账号校验",
            ),
        ):
            with self.subTest(error=error):
                self.service.login = {"key": "test"}
                with (
                    patch.object(
                        self.service,
                        "_login_response",
                        new=AsyncMock(return_value=(data, cookies)),
                    ),
                    patch(
                        "bilibili_api.user.get_self_info",
                        new=AsyncMock(return_value=account),
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, error):
                        self.service.api("bili_login_poll")
                self.assertEqual(read_json(path, {}), old)
                self.assertIsNone(self.service.login)

    def test_login_waiting_timeout_and_replaced_session(self):
        for code, status in (
            (86101, "waiting"),
            (86090, "waiting"),
            (86038, "timeout"),
        ):
            self.service.login = {"key": "test"}
            with patch.object(
                self.service,
                "_login_response",
                new=AsyncMock(return_value=({"code": code}, {})),
            ):
                self.assertEqual(self.service.api("bili_login_poll")["status"], status)

        async def replaced(*args):
            self.service.login = {"key": "new"}
            return {"code": 0}, {}

        self.service.login = {"key": "old"}
        with patch.object(self.service, "_login_response", new=replaced):
            self.assertEqual(self.service.api("bili_login_poll")["status"], "waiting")
        self.assertEqual(self.service.login["key"], "new")

    def test_named_video_must_have_actually_been_requested(self):
        with patch.object(
            self.service,
            "completion",
            return_value={"content": "### " + BV + "\n凭空编造"},
        ):
            with self.assertRaisesRegex(RuntimeError, "没有取得"):
                self.service.scan("", BV, "key", "base", "model")
        self.assertFalse(self.service.seen)

    def test_service_can_close_twice(self):
        self.service.close()
        self.service.close()
        self.assertFalse(self.service.thread.is_alive())

    def test_comment_reply_receipt_and_parent_routing(self):
        with (
            patch.object(self.service, "credential"),
            patch("bilibili_api.video.Video") as video,
            patch(
                "bilibili_api.comment.send_comment",
                new=AsyncMock(return_value={"rpid": 11}),
            ) as send,
        ):
            video.return_value.get_info = AsyncMock(return_value={"aid": 123})
            for args, root, parent in (
                ({}, None, None),
                ({"rpid": 10}, 10, 10),
                ({"rpid": 11, "root": 10}, 10, 11),
            ):
                result = self.service._request(
                    "bili_reply", {"bvid": BV, "text": "test", **args}
                )
                self.assertTrue(result["success"])
                self.assertEqual(send.call_args.kwargs["root"], root)
                self.assertEqual(send.call_args.kwargs["parent"], parent)
            send.return_value = {}
            with self.assertRaisesRegex(RuntimeError, "评论ID"):
                self.service._request("bili_reply", {"bvid": BV, "text": "test"})

    def test_dm_receipt_and_invalid_targets(self):
        with (
            patch.object(self.service, "credential"),
            patch("bilibili_api.user.User") as recipient,
            patch(
                "bilibili_api.session.send_msg",
                new=AsyncMock(return_value={"msg_key": 123}),
            ) as send,
        ):
            recipient.return_value.get_relation = AsyncMock(
                return_value={"relation": {"attribute": 2}}
            )
            result = self.service._request(
                "bili_send_message", {"receiver_uid": 123, "text": "test"}
            )
            self.assertTrue(result["success"])
            self.assertEqual(send.call_args.kwargs["receiver_id"], 123)
            send.return_value = {}
            with self.assertRaisesRegex(RuntimeError, "消息ID"):
                self.service._request(
                    "bili_send_message", {"receiver_uid": 123, "text": "test"}
                )
            for values in (
                {"receiver_uid": 0, "text": "test"},
                {"receiver_uid": 123, "text": ""},
            ):
                with self.assertRaises(ValueError):
                    self.service._request("bili_send_message", values)

    def test_dm_requires_outgoing_follow_and_never_auto_follows(self):
        with (
            patch.object(self.service, "credential"),
            patch("bilibili_api.user.User") as recipient,
            patch(
                "bilibili_api.session.send_msg",
                new=AsyncMock(return_value={"msg_key": 123}),
            ) as send,
        ):
            relation = recipient.return_value.get_relation = AsyncMock()
            for attribute in (0, 1, 128, None):
                relation.return_value = {
                    "relation": {"attribute": attribute},
                    "be_relation": {"attribute": 2},
                }
                with self.assertRaisesRegex(RuntimeError, "先在B站关注"):
                    self.service._request(
                        "bili_send_message", {"receiver_uid": 456, "text": "test"}
                    )
            send.assert_not_awaited()
            recipient.return_value.modify_relation.assert_not_called()
            for attribute in (2, 6):
                relation.return_value = {"relation": {"attribute": attribute}}
                self.assertTrue(
                    self.service._request(
                        "bili_send_message", {"receiver_uid": 456, "text": "test"}
                    )["success"]
                )
            relation.side_effect = RuntimeError("relation unavailable")
            with self.assertRaisesRegex(RuntimeError, "relation unavailable"):
                self.service._request(
                    "bili_send_message", {"receiver_uid": 456, "text": "test"}
                )
            self.assertEqual(send.await_count, 2)

    def test_dynamic_image_receipt_and_rate_limit(self):
        from PIL import Image

        image = self.service.home / "test.png"
        Image.new("RGB", (16, 16), "white").save(image)
        with (
            patch.object(self.service, "credential"),
            patch(
                "bilibili_api.dynamic.send_dynamic",
                new=AsyncMock(return_value={"dyn_id_str": "123"}),
            ) as send,
        ):
            result = self.service._request(
                "bili_send_dynamic", {"text": "test", "images": [str(image)]}
            )
            self.assertTrue(result["success"])
            self.assertEqual(len(send.call_args.kwargs["info"].pics), 1)
            with self.assertRaisesRegex(RuntimeError, "最短间隔"):
                self.service._request("bili_send_dynamic", {"text": "test"})
            send.assert_awaited_once()

    def test_dynamic_missing_receipt_and_invalid_images(self):
        with (
            patch.object(self.service, "credential"),
            patch(
                "bilibili_api.dynamic.send_dynamic", new=AsyncMock(return_value={})
            ) as send,
        ):
            for images in (["missing.png"], ["missing.png"] * 10):
                with self.assertRaises(ValueError):
                    self.service._request(
                        "bili_send_dynamic", {"text": "test", "images": images}
                    )
            send.assert_not_called()
            with self.assertRaisesRegex(RuntimeError, "动态ID"):
                self.service._request("bili_send_dynamic", {"text": "test"})

    def test_like_favourite_only_adds_missing_actions(self):
        credential = MagicMock(dedeuserid="123")
        with (
            patch.object(self.service, "credential", return_value=credential),
            patch("bilibili_api.video.Video") as video,
            patch(
                "bilibili_api.favorite_list.get_video_favorite_list",
                new=AsyncMock(return_value={"list": [{"id": 456}]}),
            ),
        ):
            v = video.return_value
            v.get_info = AsyncMock(return_value={"title": "test"})
            v.has_liked = AsyncMock(return_value=False)
            v.has_favoured = AsyncMock(return_value=False)
            v.like = AsyncMock()
            v.set_favorite = AsyncMock()
            self.assertEqual(
                self.service._request("bili_triple", {"bvid": BV, "mode": "like_fav"})[
                    "actions"
                ],
                ["点赞", "收藏"],
            )
            v.like.assert_awaited_once_with(1)
            v.set_favorite.assert_awaited_once_with(
                add_media_ids=[456], del_media_ids=[]
            )
            v.has_liked.return_value = True
            v.has_favoured.return_value = True
            self.assertEqual(
                self.service._request("bili_triple", {"bvid": BV, "mode": "like_fav"})[
                    "actions"
                ],
                [],
            )
            with self.assertRaises(ValueError):
                self.service._request("bili_triple", {"bvid": BV, "mode": "coin"})

    def test_inbox_routes_filters_deduplicates_and_preserves_self_messages(self):
        self.service.save_config({"inbox_uids": "456"})
        self.service.acknowledge([{"key": "dm:456:1"}])
        with (
            patch.object(
                self.service, "credential", return_value=MagicMock(dedeuserid="123")
            ),
            patch(
                "bilibili_api.session.get_sessions",
                new=AsyncMock(
                    return_value={
                        "session_list": [
                            {"talker_id": 456, "unread_count": 2},
                            {"talker_id": 789, "unread_count": 1},
                        ]
                    }
                ),
            ),
            patch(
                "bilibili_api.session.fetch_session_msgs",
                new=AsyncMock(
                    return_value={
                        "messages": [
                            {"sender_uid": 123, "msg_key": 3, "content": "own"},
                            {"sender_uid": 456, "msg_key": 2, "content": "incoming"},
                            {"sender_uid": 456, "msg_key": 1, "content": "seen"},
                        ]
                    }
                ),
            ),
            patch(
                "bilibili_api.session.get_at",
                new=AsyncMock(
                    return_value={
                        "items": [
                            {
                                "id": 10,
                                "user": {"mid": 456},
                                "item": {"source_content": "at", "source_id": 11},
                            }
                        ]
                    }
                ),
            ),
            patch(
                "bilibili_api.session.get_replies",
                new=AsyncMock(side_effect=RuntimeError("test unavailable")),
            ),
        ):
            result = self.service.api("bili_inbox")
        self.assertEqual({i["key"] for i in result["items"]}, {"dm:456:2", "at:10"})
        self.assertEqual(len(result["errors"]), 1)

    def test_approved_chat_write_executes_once(self):
        with (
            patch.object(
                self.service,
                "completion",
                side_effect=[
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "1",
                                "function": {
                                    "name": "bili_send_message",
                                    "arguments": '{"receiver_uid":123,"text":"test"}',
                                },
                            }
                        ],
                    },
                    {"role": "assistant", "content": "sent"},
                ],
            ),
            patch.object(
                self.service, "_request", return_value={"success": True}
            ) as send,
        ):
            approvals = []
            self.assertEqual(
                self.service.chat(
                    [],
                    "key",
                    "base",
                    "model",
                    lambda name, args: approvals.append((name, args)) or True,
                ),
                "sent",
            )
            self.assertEqual(len(approvals), 1)
            send.assert_called_once_with(
                "bili_send_message", {"receiver_uid": 123, "text": "test"}
            )

    def test_auto_delivery_uses_only_configured_destinations(self):
        self.service.save_config(
            {
                "auto_comment": True,
                "mention_name": "test",
                "dm_mode": "both",
                "dm_uid": "123",
                "triple_mode": "like",
            }
        )
        with (
            patch.object(
                self.service, "completion", return_value={"content": "test summary"}
            ),
            patch.object(
                self.service, "_request", return_value={"success": True}
            ) as send,
        ):
            self.service.deliver(
                {"report": "test", "bvids": [BV]}, "key", "base", "model"
            )
        self.assertEqual(
            [call.args[0] for call in send.call_args_list],
            ["bili_triple", "bili_reply", "bili_send_message"],
        )

    def test_auto_dynamic_once_per_day_and_missing_report(self):
        self.service.save_config({"dynamic_on": True, "dynamic_auto": True})
        self.assertIn("跳过", self.service.auto_dynamic("key", "base", "model"))
        today = datetime.now(BEIJING).date().isoformat()
        self.assertEqual(self.service.state["dynamic_auto_day"], today)
        folder = self.service.home / "out"
        folder.mkdir()
        (folder / (today + ".md")).write_text("test report", encoding="utf-8")
        with (
            patch.object(
                self.service, "completion", return_value={"content": "test dynamic"}
            ),
            patch.object(
                self.service, "_request", return_value={"success": True}
            ) as send,
        ):
            self.service.auto_dynamic("key", "base", "model")
            send.assert_called_once_with("bili_send_dynamic", {"text": "test dynamic"})


if __name__ == "__main__":
    unittest.main()
