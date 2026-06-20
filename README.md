A fork of [fe80Grau's ytdlp2STRM](https://github.com/fe80Grau/ytdlp2STRM), to fit some of my personal needs/wants

Some differences:
- I'm more focused on optimizing docker usage
-- ie added deno/yt-dlp-ejs to the docker container implementation
- updated jellyfin auth token handling
- defaults (bridge vs direct mode, channel list, youtube config, episode numbering) that fit my usecase
- more logging so I can debug everything I've broken

