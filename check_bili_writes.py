"""Explicitly approved live account tests, with a journal preventing repeat sends."""

import argparse
import asyncio
import json
from pathlib import Path

from bili import BiliService, read_json, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bvid", required=True)
    parser.add_argument("--uid", required=True, type=int)
    parser.add_argument("--execute-approved", action="store_true")
    parser.add_argument("--retry-level-rejected", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved:
        parser.error("Requires explicit approval of targets, text and account actions")
    service = BiliService(Path(__file__).resolve().parent / "bili-data")
    journal_path = service.home / "live-write-check.json"
    journal = read_json(journal_path, {})
    target = {"bvid": args.bvid, "uid": args.uid}
    if journal and journal.get("target") != target:
        raise RuntimeError(
            "Existing journal belongs to different targets; do not reuse"
        )
    journal["target"] = target

    def run(name, tool, values):
        if name in journal:
            previous = journal[name]
            rejected = previous.get("status") == "failed_or_uncertain" and any(
                previous.get("error", "").startswith("接口返回错误代码：" + code + "，")
                for code in ("-107", "21016", "4126021")
            )
            if not args.retry_level_rejected or not rejected:
                print(name, "already attempted:", previous["status"], flush=True)
                return previous.get("result")
            journal.setdefault("previous_attempts", []).append(
                {"operation": name, **previous}
            )
        journal[name] = {"status": "attempting"}
        write_json(journal_path, journal)
        try:
            result = service._request(tool, values)
            journal[name] = {"status": "returned", "result": result}
            print(
                name,
                "returned; receipt fields:",
                list(result.get("receipt", {})),
                flush=True,
            )
            return result
        except Exception as exc:
            journal[name] = {"status": "failed_or_uncertain", "error": str(exc)[:500]}
            print(name, type(exc).__name__, str(exc)[:500], flush=True)
        finally:
            write_json(journal_path, journal)

    def verify(name, coroutine):
        try:
            result = asyncio.run_coroutine_threadsafe(coroutine, service.loop).result(
                180
            )
            journal[name] = {"verified": result}
            print(name, result, flush=True)
        except Exception as exc:
            journal[name] = {"error": str(exc)[:500]}
            print(name, "verification failed:", str(exc)[:500], flush=True)
        write_json(journal_path, journal)

    try:
        from bilibili_api import comment, dynamic, session, video

        service.api("bili_whoami")
        credential = service.credential()
        v = video.Video(bvid=args.bvid, credential=credential)
        info = asyncio.run_coroutine_threadsafe(v.get_info(), service.loop).result(180)
        print("Video:", info["title"], flush=True)
        comment_text = "桌宠功能测试：验证B站评论接口。"
        reply_text = "桌宠功能测试：验证评论回复接口。"
        dm_text = "桌宠功能测试：验证B站私信接口。"
        dynamic_text = "桌宠功能测试：验证B站动态发布接口。"
        posted = run("comment", "bili_reply", {"bvid": args.bvid, "text": comment_text})
        rpid = (posted or {}).get("receipt", {}).get("rpid")
        if rpid:
            run(
                "reply",
                "bili_reply",
                {"bvid": args.bvid, "text": reply_text, "rpid": int(rpid)},
            )
        posted_dm = run(
            "dm", "bili_send_message", {"receiver_uid": args.uid, "text": dm_text}
        )
        run("like_fav", "bili_triple", {"bvid": args.bvid, "mode": "like_fav"})
        posted_dynamic = run("dynamic", "bili_send_dynamic", {"text": dynamic_text})

        async def video_state():
            return {"liked": await v.has_liked(), "favoured": await v.has_favoured()}

        async def dm_state():
            data = await session.fetch_session_msgs(args.uid, credential)
            msg_key = (posted_dm or {}).get("receipt", {}).get("msg_key")
            for item in data.get("messages") or []:
                content = item.get("content", {})
                if isinstance(content, str):
                    try:
                        content = json.loads(content)
                    except ValueError:
                        content = {"content": content}
                if (
                    isinstance(content, dict)
                    and content.get("content") == dm_text
                    and str(item.get("sender_uid")) == str(credential.dedeuserid)
                    and msg_key is not None
                    and str(item.get("msg_key")) == str(msg_key)
                ):
                    return True
            return False

        async def comment_state(cred):
            data = await comment.get_comments(
                info["aid"],
                comment.CommentResourceType.VIDEO,
                order=comment.OrderType.TIME,
                credential=cred,
            )
            return any(
                item.get("content", {}).get("message") == comment_text
                and str(item.get("rpid")) == str(rpid)
                for item in data.get("replies") or []
            )

        async def reply_state():
            data = await comment.Comment(
                info["aid"], comment.CommentResourceType.VIDEO, int(rpid), credential
            ).get_sub_comments()
            return any(
                item.get("content", {}).get("message") == reply_text
                for item in data.get("replies") or []
            )

        verify("video_state", video_state())
        verify("dm_readback", dm_state())
        if rpid:
            verify("comment_readback", comment_state(credential))
            verify("comment_public_readback", comment_state(None))
            verify("reply_readback", reply_state())
        receipt = (posted_dynamic or {}).get("receipt", {})
        dynamic_id = (
            receipt.get("dyn_id_str")
            or receipt.get("dynamic_id")
            or receipt.get("dyn_id")
        )
        if dynamic_id:

            async def dynamic_state(cred):
                data = await dynamic.Dynamic(
                    int(dynamic_id), credential=cred
                ).get_info()
                return dynamic_text in str(data)

            verify("dynamic_readback", dynamic_state(credential))
            verify("dynamic_public_readback", dynamic_state(None))
        print("Journal:", journal_path, flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    main()
