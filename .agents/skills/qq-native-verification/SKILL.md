---
name: qq-native-verification
description: Verify and diagnose the desktop pet native QQ integration with NapCat/SnowLuma OneBot HTTP, distinguishing local regressions from live QQ delivery. Use for QQ setup, missing replies, duplicate replies, group triggers, media or QQ space failures.
---

# Native QQ Verification

Inspect `qq/service.py`, `qq/panel.py`, and the pet integration before changing behavior. The desktop pet is native Python/Qt and must not acquire a DSH dependency. Runtime settings remain in root `qq-data/` when source files move.

## Verification Levels

- Run `python -m unittest qq.test_service -v` for native transport, routing, media, safety gates, and Qt handoff. The local HTTP test backend is not QQ.
- Check the existing Bilibili service suite after changing shared model/tool dispatch. Offscreen Qt may crash when several old panels survive between tests; isolate each failing test before attributing that crash to QQ.
- Use temporary data and mocked service constructors for full `PetWindow` startup. Do not overwrite saved account settings or start a second polling instance with the same data.
- Check OneBot `get_login_info` against the actual backend. A reachable port or a backend login page alone is not evidence of a logged-in account.
- Obtain an explicit test destination and permission before live sends. Test private/group delivery and read back from QQ before claiming end-to-end success.
- Verify optional media, file, voice, poke, and space APIs separately. Backend extensions vary. Unsupported space APIs do not imply ordinary chat is broken.

## Failure Boundaries

- For Windows Shell installation, verify the official release SHA256 before extraction. Use `launcher-win10-user.bat` on Windows 10 when supplied; elevation is not required for the verified local setup.
- Before first launch, create `config/webui.json` with host `127.0.0.1` and a strong random token. NapCat's default WebUI host is `::`, which exposes all interfaces.
- Keep OneBot HTTP on `127.0.0.1:3000` with a separate token matching the pet. The generic `config/onebot11.json` seeds account settings; inspect account-specific settings after login before assuming it was applied.
- Open the authenticated WebUI locally without printing its token. QR approval belongs to the user; `waiting_qrcode` is not a logged-in account.

- First polling establishes a history baseline and deliberately skips old messages. Send a new QQ message afterwards.
- Master switch defaults off, dry run defaults on. Dry run still permits reading/model processing but does not send account writes.
- Reply only to the source binding. Private desktop history and screen context are not QQ model context. Same named QQ sessions share QQ memory, so keep public/private names distinct.
- QQ replies use `BiliService.chat(remote=True)` for Bilibili search, video reading and scans; account writes still require desktop approval. Remote scans must not invoke automatic delivery, and inbox, saved reports and account identity tools stay unavailable.
- Do not retry an uncertain write or replay processing-state items after restart. Keep a write journal and distinguish backend receipt from actual visible delivery.
- A seen message with no pending item or reply does not prove success. Inspect persisted `last_reply_error`; reproduce long scans with QQ sends mocked. Real subtitle/comment scans can take minutes, so send a one-time start notice and a generic failure notice without exposing raw errors to the group.
- Incoming URLs must not probe private services. Outgoing files must stay in approved media directories and never include configuration or credentials.
- ASR/TTS commands are user-configured argument arrays with `shell=False`; incoming text is an argument, not a command fragment.
- Space post/like/comment and real automatic replies require explicit setting authorization. Remote participants do not grant public write permissions.
- Keep tokens and account data in ignored `qq-data`; do not print them, commit them, or attach them to a public issue.

## Report

State separately what passed locally, what passed using the actual QQ account, and what is still blocked by backend installation/login or unsupported optional APIs. Never label the entire integration usable based solely on offline tests or UI startup.
