A fork of [fe80Grau's ytdlp2STRM](https://github.com/fe80Grau/ytdlp2STRM), to fit some of my personal needs/wants

Some completed changes:
- I'm more focused on optimizing docker usage
  - added deno/yt-dlp-ejs to the docker container implementation
  - timezone support
- updated jellyfin auth token handling
- defaults (bridge vs direct mode, channel list, youtube config, episode numbering) that fit my usecase
- more logging so I can debug everything I've broken
- removed non-youtube modes to simplify codebase


TODO:
- add some notification sending via NTFY for errors, etc
- simplify youtube code - probably going to be removing direct and just keeping download + bridge
-- bridge is my main driver right now for jellyfin, but I'd like to think about download given sponsorblock only works for download mode
