A fork of [fe80Grau's ytdlp2STRM](https://github.com/fe80Grau/ytdlp2STRM), to fit some of my personal needs/wants

## Some completed changes:
- abandoned hope for all non-docker setups
- rewrote dockerfile to use UV
- **strongly** opinionated defaults: youtube ONLY, no direct mode, simpler crons, different default config values
- updated jellyfin auth token handling
- more logging so I can debug everything I've broken


## TODO:
- add some notification sending via NTFY for errors, etc
- re-organize routes and the flask/socketio logic to prevent circular imports
- add a bridge/download mode that will check if we have the video downloaded, else use bridge
 - the idea here being I can have some way of downloading individual videos that I want to ensure I have an offline copy of, and when the /bridge/videoId endpoint is hit, it'll prioritize the local copy
- merge the main config and the youtube plugin config as I'm only supporting youtube
- remove all the cookie logic - I want to use yt-dlp-ejs' ability to grab videos
- allow for configurable method download/bridge per channel, and download should occur at scan time not at watch time
- remove restart from webUI -> container only restarting
- move channel list access into the side panel
- remove the season+episode prefix from videos, NFO handles that already for jellyfin

## Credits
[![GitHub - fe80Grau](https://img.shields.io/badge/GitHub-fe80Grau-f3bc77?logo=GitHub)](https://github.com/fe80Grau)
[![GitHub - ShieldsIO](https://img.shields.io/badge/GitHub-ShieldsIO-42b983?logo=GitHub)](https://github.com/badges/shields)
[![GitHub - Flask](https://img.shields.io/badge/GitHub-Flask-0000ff?logo=GitHub)](https://github.com/pallets/flask)
[![GitHub - yt-dlp](https://img.shields.io/badge/GitHub-ytdlp-ff0000?logo=GitHub)](https://github.com/yt-dlp/yt-dlp)
[![GitHub - andreztz](https://img.shields.io/badge/GitHub-andreztz-ffc230?logo=GitHub)](https://gist.github.com/andreztz/9e472fa6daa17d2f954958fc33e5a296)
