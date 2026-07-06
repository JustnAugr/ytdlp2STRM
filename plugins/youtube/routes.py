from flask import Response, request

from __main__ import app
from plugins.youtube.youtube import stream, subtitles
from utils.validate_id import is_valid_media_id


@app.route("/youtube/<youtube_id>", methods=["GET", "OPTIONS"])
def youtube_stream(youtube_id):
    if request.method == "OPTIONS":
        response = Response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Range, Content-Type"
        return response
    if not is_valid_media_id(youtube_id):
        return "Invalid id", 400
    return stream(youtube_id, request.remote_addr)


# used when direct serving m3u8
@app.route("/youtube/subtitles/<youtube_id>.vtt")
def youtube_subtitles(youtube_id):
    if not is_valid_media_id(youtube_id):
        return "Invalid id", 400
    return subtitles(youtube_id)
