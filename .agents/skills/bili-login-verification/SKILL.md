---
name: bili-login-verification
description: Diagnose Bilibili QR login that reports success but saves empty credentials, and verify the native desktop-pet integration with safe live read-only tests.
---

# Bilibili Login Verification

Treat QR confirmation, credential storage, and verified account access as separate stages.

1. Inspect the installed login library and native login handler before changing code. Some library versions parse only the callback URL and discard response cookies.
2. Inspect saved credential field types and lengths only. Never print cookies, QR keys, refresh tokens, or model API keys.
3. Capture cookies from the QR poll response. Decode callback query parameters only as a fallback. Require explicit success code zero; waiting and expiration are not success.
4. Require nonempty SESSDATA, bili_jct, and DedeUserID. Check the returned account UID matches before atomically saving. Failed login must preserve existing credentials.
5. Do not infer readiness from credential-file existence. Reject incomplete saved credentials. Report expiration and validation errors in the UI without announcing success.
6. Test empty credentials, cookie-only responses, encoded callbacks, account mismatches, waiting/expiration, and replacing a QR session during an in-flight request.
7. Run live anonymous QR generation, waiting-state polling, search, and configured model tool calls independently. These checks do not prove authenticated reading works.
8. Use `python -m bili.check_live --login` for user-assisted fresh QR login followed by the real account-to-scan-to-report diagnostic. Source lives in `bili/`; saved data remains in root `bili-data/`. Do not call outgoing delivery operations as part of verification.
9. Run `python -m bili.check_live --panel -platform offscreen` to verify a live named-video scan through Qt, model summary, report display, and pet chat-history handoff. This diagnostic disables outgoing destinations in memory and blocks account-write requests without changing saved settings. State exactly which live checks passed and which require the user to scan or authorize a write. Offscreen UI success does not prove an already-running pet has reloaded the code.

If a scan is required, request that action directly rather than accessing browser cookies or unrelated account stores. Default to read-only Bilibili checks; local report files may be written.

## Authorized Account Tests

When the user explicitly requests remaining write-feature tests, obtain the video BV, recipient UID, exact comment/reply/message/dynamic text, and like/favourite permissions before executing. Do not treat general testing permission as permission to choose arbitrary recipients or publish arbitrary content.

Use `python -m bili.check_writes --bvid <approved-BV> --uid <approved-UID> --execute-approved` only after reviewing its fixed test texts and getting matching approval. Its local journal records attempts before transmission, preventing accidental repeat sends after an uncertain response. Verify likes/favourites by reading their state, private messages by reading the sending conversation, and comments/dynamics through authenticated and anonymous reads when possible.

Account Lv0 can reject comments with code -107 (not a full member), private messages with 21016 (insufficient level), and dynamics with 4126021 (insufficient level), while likes/favourites still work. These are platform capability restrictions, not login failures. Show account level, retain honest error messages, and ask the user to complete Bilibili membership/level requirements or switch accounts. Never bypass restrictions or label blocked operations as passed. A failed parent comment means the approved self-reply test cannot run.

After the user authorizes retrying following membership activation, check the live account level. `--retry-level-rejected` retries only the journal's explicitly rejected -107/21016/4126021 attempts, preserving prior records and skipping successful or uncertain transmissions. Lv1 may allow private messages and dynamics while comments still reject with 12074, requiring Lv2. Do not resend successful tests to recheck visibility: rerun without the retry flag for readback only. Decode JSON message content before comparing Unicode text, and match both sender and receipt message ID. Newly posted dynamics can temporarily fail anonymous reads; recheck existing IDs without publishing duplicates.

Use `python -m unittest bili.test_service bili.test_panel -v` to cover write routing/receipts, image inputs, quotas, automatic destinations, incoming deduplication, Qt notifications, exact-target approval and scheduler dispatch. These tests mock transmission and cannot prove publication or recipient delivery. Image upload and live incoming notification remain unverified without corresponding authorized real inputs.
