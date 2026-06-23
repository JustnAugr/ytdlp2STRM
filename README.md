A fork of [fe80Grau's ytdlp2STRM](https://github.com/fe80Grau/ytdlp2STRM), to fit some of my personal needs/wants

Some completed changes:
- abandoned hope for all non-docker setups 
- rewrote dockerfile to use UV
- **strongly** opinionated defaults: youtube ONLY, no direct mode, simpler crons, different default config values
- updated jellyfin auth token handling
- more logging so I can debug everything I've broken


TODO:
- add some notification sending via NTFY for errors, etc
- re-organize routes and the flask/socketio logic to prevent circular imports
- add a bridge/download mode that will check if we have the video downloaded, else use bridge
 - the idea here being I can have some way of downloading individual videos that I want to ensure I have an offline copy of, and when the /bridge/videoId endpoint is hit, it'll prioritize the local copy 
