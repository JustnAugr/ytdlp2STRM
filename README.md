A fork of [fe80Grau's ytdlp2STRM](https://github.com/fe80Grau/ytdlp2STRM), to fit some of my personal needs/wants

## Some completed changes:
- a singular 'stream' URL that will check for a direct HLS m3u8 manifest, else fallback to transcoding/bridge mode
- abandoned hope for all non-docker setups
- rewrote dockerfile to use UV
- **strongly** opinionated defaults: youtube ONLY, no direct mode, simpler crons, different default config values
- updated jellyfin auth token handling
- more logging so I can debug everything I've broken


## TODO:
- add some notification sending via NTFY for errors, etc
- re-organize routes and the flask/socketio logic to prevent circular imports
- add a download check prior to direct and bridge, that will check if we have the video downloaded, else use the direct->bridge logic
 - the idea here being I can have some way of downloading individual videos that I want to ensure I have an offline copy of, and when the /youtube endpoint is hit, it'll prioritize the local copy
- allow for configurable method download/bridge per channel, and download should occur at scan time not at watch time

## Credits
[![GitHub - fe80Grau](https://img.shields.io/badge/GitHub-fe80Grau-f3bc77?logo=GitHub)](https://github.com/fe80Grau)
[![GitHub - ShieldsIO](https://img.shields.io/badge/GitHub-ShieldsIO-42b983?logo=GitHub)](https://github.com/badges/shields)
[![GitHub - Flask](https://img.shields.io/badge/GitHub-Flask-0000ff?logo=GitHub)](https://github.com/pallets/flask)
[![GitHub - yt-dlp](https://img.shields.io/badge/GitHub-ytdlp-ff0000?logo=GitHub)](https://github.com/yt-dlp/yt-dlp)
[![GitHub - andreztz](https://img.shields.io/badge/GitHub-andreztz-ffc230?logo=GitHub)](https://gist.github.com/andreztz/9e472fa6daa17d2f954958fc33e5a296)
