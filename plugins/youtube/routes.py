from __main__ import app
from plugins.youtube.youtube import bridge
from utils.validate_id import is_valid_media_id


### YOUTUBE ZONE
# Redirect to best pre-merget format youtube url
@app.route("/youtube/<youtube_id>")
def youtube_bridge(youtube_id):
    if not is_valid_media_id(youtube_id):
        return "Invalid id", 400
    return bridge(youtube_id)
