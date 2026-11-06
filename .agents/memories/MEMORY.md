# Memory

## 项目背景

- 用户希望将 dsh-bili-subagent 的 B站能力接到自己的“大肥鱼”，不引入 DSH。
- 用户要求把 dsh-qq-link 的全部 QQ 功能原生接入肥鱼，不引入 DSH。
- 大肥鱼在QQ群747869735的人设为可爱的女性朋友，爱好是看二次元动漫。
- 用户要求B站阅读实际覆盖完整视频画面，并同时读取字幕和评论，不能仅用字幕评论总结冒充看完视频。

## 踩坑记录

- B站扫码登录不能仅信任库的 DONE：凭证可能为空；须读取响应 Cookie 并校验账号后再保存，不能凭文件存在判定已登录。
- B站Lv0账号可点赞收藏，但评论(-107)、私信(21016)、动态(4126021)被平台限制；不能将这些失败当作登录故障或宣称发送已通过。
- 原生QQ接入须区分本机HTTP回归与真实QQ实测；NapCat/SnowLuma空间扩展因后端而异，未登录不能宣称全功能可用。
- NapCat WebUI defaults to all interfaces; preconfigure loopback before launch. Windows 10 user launcher works without elevation.

## 技术约定

- 用户已明确授权自动回复新私信时先关注发送者，再回复；已关注直接回复。关注失败不得发送，不自动解除黑名单。普通聊天发私信仍保留原有确认流程。
