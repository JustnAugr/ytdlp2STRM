from __main__ import app
from plugins.youtube.youtube import bridge, download, subtitles
from utils.validate_id import is_valid_media_id


### YOUTUBE ZONE
# Redirect to best pre-merget format youtube url
@app.route("/youtube/bridge/<youtube_id>")
def youtube_bridge(youtube_id):
    if not is_valid_media_id(youtube_id):
        return "Invalid id", 400
    return bridge(youtube_id)


@app.route("/youtube/subtitles/<youtube_id>.vtt")
def youtube_subtitles(youtube_id):
    if not is_valid_media_id(youtube_id):
        return "Invalid id", 400
    return subtitles(youtube_id)


# Download video and semd data throught http (serve video duration info, disk usage **clean_old_videos fucntion save your money)
@app.route("/youtube/download/<youtube_id>")
def youtube_download(youtube_id):
    if not is_valid_media_id(youtube_id):
        return "Invalid id", 400
    return download(youtube_id)
