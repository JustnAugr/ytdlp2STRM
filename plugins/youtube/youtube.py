import html
import json
import os
import platform
import re
import subprocess
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from cachetools import TTLCache
from flask import Response, request, send_file, stream_with_context
from werkzeug.datastructures import Headers

from clases.config import config as c
from clases.folders import folders as f
from clases.jellyfin_notifier.jellyfin_notifier import JellyfinNotifier
from clases.log import log as l
from clases.nfo import nfo as n
from clases.worker import worker as w
from utils.episode_numbering import format_episode_title
from utils.sanitize import sanitize

recent_requests = TTLCache(maxsize=200, ttl=30)


# load config values so we don't need a restart
def _load_config_values():
    global \
        ytdlp2strm_config, \
        config, \
        channels, \
        media_folder, \
        days_dateafter, \
        videos_limit, \
        cookies, \
        cookie_value, \
        lang, \
        episode_format, \
        video_quality, \
        download_subtitles, \
        convert_subtitles_to_srt, \
        keep_vtt_subtitles, \
        source_platform, \
        host, \
        port, \
        SECRET_KEY, \
        DOCKER_PORT, \
        proxy, \
        proxy_url
    ytdlp2strm_config = c.config("./config/config.json").get_config()
    config = c.config("./plugins/youtube/config.json").get_config()
    channels = c.config(config["channels_list_file"]).get_channels()

    media_folder = config["strm_output_folder"]
    days_dateafter = config["days_dateafter"]
    videos_limit = config["videos_limit"]
    try:
        cookies = config["cookies"]
        cookie_value = config["cookie_value"]
    except Exception:
        cookies = "cookies-from-browser"
        cookie_value = "chrome"

    try:
        lang = config["lang"]
    except Exception:
        lang = "en"

    try:
        episode_format = config["episode_format"]
    except Exception:
        episode_format = "sequential"

    try:
        video_quality = str(config["video_quality"]).strip().lower()
    except Exception:
        video_quality = "best"

    try:
        download_subtitles = str(config["download_subtitles"]).lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
    except Exception:
        download_subtitles = False

    try:
        convert_subtitles_to_srt = str(config["convert_subtitles_to_srt"]).lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
    except Exception:
        convert_subtitles_to_srt = False

    try:
        keep_vtt_subtitles = str(config["keep_vtt_subtitles"]).lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
    except Exception:
        keep_vtt_subtitles = True

    source_platform = "youtube"
    host = ytdlp2strm_config["ytdlp2strm_host"]
    port = ytdlp2strm_config["ytdlp2strm_port"]

    SECRET_KEY = os.environ.get("AM_I_IN_A_DOCKER_CONTAINER", False)
    DOCKER_PORT = os.environ.get("DOCKER_PORT", False)
    if SECRET_KEY:
        port = DOCKER_PORT

    if "proxy" in config:
        proxy = config["proxy"]
        proxy_url = config["proxy_url"]
    else:
        proxy = False
        proxy_url = ""


# load config values for the first time
_load_config_values()


def _get_video_quality_height():
    if not video_quality or video_quality in ("best", "0", "none", "default"):
        return None
    match = re.search(r"\d+", video_quality)
    if not match:
        return None
    return int(match.group(0))


def _get_video_format_selector(default_selector="best"):
    max_height = _get_video_quality_height()
    if not max_height:
        l.log(
            "youtube",
            f"_get_video_format_selector: returning default selector {default_selector}",
        )
        return default_selector
    l.log(
        "youtube",
        f"_get_video_format_selector: returning bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
    )
    return f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best"


def _quality_cache_tag():
    """Tag used in cache keys/filenames so changing video_quality in config
    invalidates the previous direct-stream caches. Issue #119: without this,
    a cached low-quality variant URL keeps being served until the TTL expires.
    """
    height = _get_video_quality_height()
    return f"h{height}" if height else "best"


class Youtube:
    def __init__(self, channel=None):
        self.channel = channel
        self.channel_url = None
        self.channel_name = None
        self.channel_description = None
        self.channel_poster = None
        self.channel_landscape = None

    @staticmethod
    def _normalize_yt_url(url):
        """Force youtube.com / m.youtube.com URLs to www.youtube.com.

        Issue #101: yt-dlp returns 'HTTP Error 400: Bad Request' on the tab
        extractor for some channels when the URL lacks 'www.' (e.g.
        'https://youtube.com/@mkbhd'). Mobile and bare hosts are coerced to
        the canonical www host so the API call succeeds.
        """
        if not url:
            return url
        return re.sub(
            r"://(?:m\.|www\.)?youtube\.com",
            "://www.youtube.com",
            url,
            count=1,
        )

    def get_results(self):
        if "extractaudio-" in self.channel:
            islist = False
            self.channel_url = self.channel.replace("extractaudio-", "")
            if "list-" in self.channel:
                islist = True
                self.channel_url = self.channel.replace("list-", "")
                if "www.youtube" not in self.channel_url:
                    self.channel_url = (
                        f"https://www.youtube.com/playlist?list={self.channel_url}"
                    )
            else:
                # Normalize URL - avoid double https://
                if self.channel_url.startswith("http"):
                    # Already a full URL, use as-is
                    pass
                elif "www.youtube" not in self.channel_url:
                    self.channel_url = f"https://www.youtube.com/{self.channel_url}"

            self.channel_url = self._normalize_yt_url(self.channel_url)

            self.channel_name = self.get_channel_name()
            self.channel_description = (
                self.get_channel_description()
                if not islist
                else f"Playlist {self.channel_name}"
            )
            thumbs = self.get_channel_images()
            self.channel_poster = thumbs["poster"]
            self.channel_landscape = thumbs["landscape"]

            return self.get_channel_audios() if not islist else self.get_list_audios()

        elif "keyword" in self.channel:
            return self.get_keyword_videos()

        elif "list" in self.channel:
            self.channel_url = self.channel.replace("list-", "")
            if "www.youtube" not in self.channel_url:
                self.channel_url = (
                    f"https://www.youtube.com/playlist?list={self.channel_url}"
                )

            self.channel_url = self._normalize_yt_url(self.channel_url)

            self.channel_name = self.get_channel_name()
            self.channel_description = f"Playlist {self.channel_name}"
            thumbs = self.get_channel_images()
            self.channel_poster = thumbs["poster"]
            self.channel_landscape = thumbs["landscape"]
            return self.get_list_videos()

        else:
            # Normalize URL - avoid double https://
            if self.channel.startswith("http"):
                # Already a full URL, use as-is
                self.channel_url = self.channel
            elif "www.youtube" not in self.channel:
                self.channel_url = f"https://www.youtube.com/{self.channel}"
            else:
                self.channel_url = self.channel

            self.channel_url = self._normalize_yt_url(self.channel_url)

            self.channel_name = self.get_channel_name()
            self.channel_description = self.get_channel_description()
            thumbs = self.get_channel_images()
            self.channel_poster = thumbs["poster"]
            self.channel_landscape = thumbs["landscape"]
            return self.get_channel_videos()

    def get_list_videos(self):
        command = [
            "yt-dlp",
            "--compat-options",
            "no-youtube-channel-redirect",
            "--compat-options",
            "no-youtube-unavailable-videos",
            "--playlist-start",
            "1",
            "--playlist-end",
            str(videos_limit),
            "--no-warning",
            "--dump-json",
            self.channel_url,
        ]
        # self.set_cookies(command)
        self.set_language(command)
        result = w.worker(command).output()
        videos = []
        for line in result.split("\n"):
            if line.strip():
                data = json.loads(line)

                video = {
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "upload_date": data.get("upload_date"),
                    "thumbnail": data.get("thumbnail"),
                    "description": data.get("description"),
                    "channel_id": self.channel_url.split("list=")[1],
                    "uploader_id": sanitize(self.channel_name),
                    "duration": data.get("duration"),
                }
                videos.append(video)

        return videos

    def get_keyword_videos(self):
        keyword = self.channel.split("-")[1]
        command = [
            "yt-dlp",
            "-f",
            _get_video_format_selector("best"),
            'ytsearch:["{}"]'.format(keyword),
            "--compat-options",
            "no-youtube-channel-redirect",
            "--compat-options",
            "no-youtube-unavailable-videos",
            "--playlist-start",
            "1",
            "--playlist-end",
            videos_limit,
            "--no-warning",
            "--dump-json",
        ]
        # self.set_cookies(command)
        self.set_language(command)

        if config["days_dateafter"] == "0":
            command.pop(8)
            command.pop(8)

        result = w.worker(command).output()
        videos = []
        for line in result.split("\n"):
            if line.strip():
                data = json.loads(line)

                video = {
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "upload_date": data.get("upload_date"),
                    "thumbnail": data.get("thumbnail"),
                    "description": data.get("description"),
                    "channel_id": data.get("channel_id"),
                    "uploader_id": data.get("uploader_id"),
                    "duration": data.get("duration"),
                }
                videos.append(video)

        return videos

    def get_keyword_audios(self):
        keyword = self.channel.split("-")[1]
        command = [
            "yt-dlp",
            "-f",
            _get_video_format_selector("best"),
            'ytsearch10:["{}"]'.format(keyword),
            "--compat-options",
            "no-youtube-channel-redirect",
            "--compat-options",
            "no-youtube-unavailable-videos",
            "--playlist-start",
            "1",
            "--playlist-end",
            videos_limit,
            "--no-warning",
            "--dump-json",
        ]
        # self.set_cookies(command)
        self.set_language(command)

        if config["days_dateafter"] == "0":
            command.pop(8)
            command.pop(8)

        result = w.worker(command).output()
        videos = []
        for line in result.split("\n"):
            if line.strip():
                data = json.loads(line)

                video = {
                    "id": f"{data.get('id')}-audio",
                    "title": data.get("title"),
                    "upload_date": data.get("upload_date"),
                    "thumbnail": data.get("thumbnail"),
                    "description": data.get("description"),
                    "channel_id": data.get("channel_id"),
                    "uploader_id": data.get("uploader_id"),
                    "duration": data.get("duration"),
                }
                videos.append(video)

        return videos

    def get_channel_audios(self):
        cu = self.channel_url

        if "/streams" not in self.channel_url:
            cu = f"{self.channel_url}/videos"

        command = [
            "yt-dlp",
            "--compat-options",
            "no-youtube-channel-redirect",
            "--compat-options",
            "no-youtube-unavailable-videos",
            "--dateafter",
            f"today-{days_dateafter}days",
            "--playlist-start",
            "1",
            "--playlist-end",
            str(videos_limit),
            "--no-warning",
            "--dump-json",
            f"{cu}",
        ]
        # self.set_cookies(command)
        self.set_language(command)

        result = w.worker(command).output()
        # Procesa la salida JSON
        videos = []
        for line in result.split("\n"):
            if line.strip():
                data = json.loads(line)
                video = {
                    "id": f"{data.get('id')}-audio",
                    "title": data.get("title"),
                    "upload_date": data.get("upload_date"),
                    "thumbnail": data.get("thumbnail"),
                    "description": data.get("description"),
                    "channel_id": data.get("channel_id"),
                    "uploader_id": data.get("uploader_id"),
                    "duration": data.get("duration"),
                }
                videos.append(video)

        return videos

    def get_list_audios(self):
        command = [
            "yt-dlp",
            "--compat-options",
            "no-youtube-channel-redirect",
            "--compat-options",
            "no-youtube-unavailable-videos",
            "--playlist-start",
            "1",
            "--playlist-end",
            str(videos_limit),
            "--no-warning",
            "--dump-json",
            self.channel_url,
        ]
        # self.set_cookies(command)
        self.set_language(command)
        result = w.worker(command).output()
        videos = []
        for line in result.split("\n"):
            if line.strip():
                data = json.loads(line)

                video = {
                    "id": f"{data.get('id')}-audio",
                    "title": data.get("title"),
                    "upload_date": data.get("upload_date"),
                    "thumbnail": data.get("thumbnail"),
                    "description": data.get("description"),
                    "channel_id": self.channel_url.split("list=")[1],
                    "uploader_id": sanitize(self.channel_name),
                    "duration": data.get("duration"),
                }
                videos.append(video)

        return videos

    def get_channel_videos(self):
        cu = self.channel_url

        if "/streams" not in self.channel_url:
            cu = f"{self.channel_url}/videos"

        command = [
            "yt-dlp",
            "--compat-options",
            "no-youtube-channel-redirect",
            "--compat-options",
            "no-youtube-unavailable-videos",
            "--dateafter",
            f"today-{days_dateafter}days",
            "--playlist-start",
            "1",
            "--playlist-end",
            str(videos_limit),
            "--no-warning",
            "--dump-json",
            f"{cu}",
        ]
        # self.set_cookies(command)
        self.set_language(command)
        result = w.worker(command).output()
        # Procesa la salida JSON
        videos = []
        for line in result.split("\n"):
            if line.strip():
                data = json.loads(line)
                video = {
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "upload_date": data.get("upload_date"),
                    "thumbnail": data.get("thumbnail"),
                    "description": data.get("description"),
                    "channel_id": data.get("channel_id"),
                    "uploader_id": data.get("uploader_id"),
                    "duration": data.get("duration"),
                }
                videos.append(video)

        return videos

    def get_channel_name(self):
        # get channel or playlist name
        if "playlist" in self.channel_url:
            command = [
                "yt-dlp",
                "--compat-options",
                "no-youtube-unavailable-videos",
                "--print",
                "%(playlist_title)s",
                "--playlist-items",
                "1",
                "--restrict-filenames",
                "--ignore-errors",
                "--no-warnings",
                "--compat-options",
                "no-youtube-channel-redirect",
                "--no-warnings",
                f"{self.channel_url}",
            ]
        else:
            # Use uploader (friendly name) instead of channel (@-name)
            # First try to get uploader (friendly name)
            command = [
                "yt-dlp",
                "--compat-options",
                "no-youtube-unavailable-videos",
                "--print",
                "%(uploader)s",
                "--restrict-filenames",
                "--ignore-errors",
                "--no-warnings",
                "--playlist-items",
                "1",
                "--compat-options",
                "no-youtube-channel-redirect",
                f"{self.channel_url}",
            ]
        # self.set_cookies(command)
        self.set_language(command)
        self.set_proxy(command)
        channel_name = w.worker(command).output().strip().replace('"', "")

        # If uploader is empty, NA, or literally "channel", try channel field
        if (
            not channel_name
            or channel_name == "NA"
            or channel_name.lower() == "channel"
        ):
            command = [
                "yt-dlp",
                "--compat-options",
                "no-youtube-unavailable-videos",
                "--print",
                "%(channel)s",
                "--restrict-filenames",
                "--ignore-errors",
                "--no-warnings",
                "--playlist-items",
                "1",
                "--compat-options",
                "no-youtube-channel-redirect",
                f"{self.channel_url}",
            ]
            # self.set_cookies(command)
            self.set_language(command)
            self.set_proxy(command)
            channel_name = w.worker(command).output().strip().replace('"', "")

        # Final fallback: use URL
        if not channel_name or channel_name == "NA":
            channel_name = self.channel_url.split("/")[-1]

        self.channel_name = channel_name
        return sanitize(self.channel_name)

    def get_channel_description(self):
        # get description
        if platform.system() == "Linux":
            command = [
                "yt-dlp",
                self.channel_url,
                "--write-description",
                "--playlist-items",
                "0",
                "--output",
                '"{}/{}.description"'.format(media_folder, sanitize(self.channel_name)),
            ]
            # self.set_cookies(command)
            self.set_language(command)
            self.set_proxy(command)
            command = command + [
                ">",
                "/dev/null",
                "2>&1",
                "&&",
                "cat",
                '"{}/{}.description"'.format(media_folder, sanitize(self.channel_name)),
            ]

            self.channel_description = w.worker(command).shell()
            try:
                os.remove(
                    "{}/{}.description".format(
                        media_folder, sanitize(self.channel_name)
                    )
                )
            except Exception:
                pass
        else:
            command = [
                "yt-dlp",
                "--write-description",
                "--playlist-items",
                "0",
                "--output",
                '"{}/{}.description"'.format(media_folder, sanitize(self.channel_name)),
                self.channel_url,
            ]
            # self.set_cookies(command)
            self.set_language(command)
            self.set_proxy(command)
            command = command + [
                ">",
                "nul",
                "2>&1",
                "&&",
                "more",
                '"{}/{}.description"'.format(media_folder, sanitize(self.channel_name)),
            ]

            try:
                self.channel_description = w.worker(command).shell()
            except Exception:
                d_file = open(
                    "{}/{}.description".format(
                        media_folder, sanitize(self.channel_name)
                    ),
                    "r",
                    encoding="utf-8",
                )

                self.channel_description = d_file.read()
                d_file.close()

            try:
                os.remove(
                    "{}/{}.description".format(
                        media_folder, sanitize(self.channel_name)
                    )
                )
            except Exception:
                pass

        return self.channel_description

    def get_channel_images(self):
        command = [
            "yt-dlp",
            "--list-thumbnails",
            "--restrict-filenames",
            "--ignore-errors",
            "--no-warnings",
            "--playlist-items",
            "0",
            self.channel_url,
        ]
        # self.set_cookies(command)
        self.set_language(command)
        self.set_proxy(command)
        landscape = None
        poster = None

        try:
            output = w.worker(command).output()
            lines = output.split("\n")

            # Parse thumbnails looking for specific IDs
            for line in lines:
                line = line.strip()

                # Look for avatar_uncropped (poster)
                if "avatar_uncropped" in line:
                    parts = line.split()
                    # URL is the last part
                    if len(parts) >= 4:
                        poster = parts[-1]

                # Look for banner_uncropped (landscape)
                if "banner_uncropped" in line:
                    parts = line.split()
                    # URL is the last part
                    if len(parts) >= 4:
                        landscape = parts[-1]

        except Exception as e:
            l.log("youtube", f"Error getting channel images: {e}")
            pass

        return {"landscape": landscape, "poster": poster}

    def set_proxy(self, command):
        if proxy:
            if proxy_url != "":
                command.append("--proxy")
                command.append(proxy_url)

    def set_cookies(self, command):
        # Only add cookies if cookie_value is not empty
        if cookie_value and cookie_value.strip():
            command.append(f"--{cookies}")
            command.append(cookie_value)

    def set_language(self, command):
        """Configura el idioma para YouTube según la configuración.

        - Añade --extractor-args youtube:lang=<lang> (idioma de metadatos/UI).
        - Añade -S "lang:<lang>" para priorizar la pista de audio del idioma
          configurado cuando el video tiene varias (doblajes). Issue #105.
        """
        extractor_args = []

        if lang and lang.strip():
            extractor_args.append(f"youtube:lang={lang}")
            # Priorizar audio track del idioma configurado sin romper si no existe
            if "-S" not in command and "--format-sort" not in command:
                command.extend(["-S", f"lang:{lang}"])

        # Agregar skip=authcheck para evitar errores con playlists que requieren autenticación
        extractor_args.append("youtubetab:skip=authcheck")

        if extractor_args:
            command.extend(["--extractor-args", ";".join(extractor_args)])


def get_subtitle_info_from_video_info(video_info, preferred_lang=None):
    preferred_lang = preferred_lang or (lang if lang and lang.strip() else "en")
    subtitle_sources = []
    for source_name in ("subtitles", "automatic_captions"):
        source = video_info.get(source_name) or {}
        for subtitle_lang, subtitle_entries in source.items():
            subtitle_sources.append((subtitle_lang, subtitle_entries))

    if not subtitle_sources:
        return None

    def lang_score(subtitle_lang):
        if subtitle_lang == preferred_lang:
            return 0
        if subtitle_lang.startswith(f"{preferred_lang}-"):
            return 1
        if preferred_lang.startswith(f"{subtitle_lang}-"):
            return 2
        if subtitle_lang.split("-")[0] == preferred_lang.split("-")[0]:
            return 3
        if subtitle_lang.startswith("en"):
            return 4
        return 5

    subtitle_sources.sort(key=lambda item: lang_score(item[0]))

    for subtitle_lang, subtitle_entries in subtitle_sources:
        vtt_entries = [
            entry
            for entry in subtitle_entries
            if entry.get("ext") == "vtt" and entry.get("url")
        ]
        entries = vtt_entries or [
            entry for entry in subtitle_entries if entry.get("url")
        ]
        if entries:
            return {
                "lang": subtitle_lang,
                "name": subtitle_lang,
                "url": entries[0]["url"],
            }

    return None


def get_subtitle_info(youtube_id, preferred_lang=None):
    command = [
        "yt-dlp",
        "-j",
        "--skip-download",
        "--no-warnings",
        f"https://www.youtube.com/watch?v={youtube_id}",
    ]
    # Youtube().set_cookies(command)
    Youtube().set_language(command)
    Youtube().set_proxy(command)
    try:
        video_info = json.loads(w.worker(command).output())
        return get_subtitle_info_from_video_info(video_info, preferred_lang)
    except Exception as e:
        l.log("youtube", f"Error getting subtitles for {youtube_id}: {e}")
        return None


def _clean_vtt_text_line(line):
    """Strip YouTube karaoke/continuation markers from a cue text line."""
    # Remove inline timestamps like <00:00:01.120>
    line = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", line)
    # Remove <c> / </c> continuation tags
    line = re.sub(r"</?c[._\w]*>", "", line)
    return line


def _fix_vtt_cue_timing_line(line):
    """Normalize timing line: center alignment, drop positional offsets."""
    line = re.sub(r"\s+position:\d+(\.\d+)?%", "", line)
    line = re.sub(r"\s+line:\d+(\.\d+)?%", "", line)
    line = re.sub(r"\s+line:\d+", "", line)
    if re.search(r"\balign:(start|left)\b", line):
        line = re.sub(r"\balign:(start|left)\b", "align:middle", line)
    elif not re.search(r"\balign:\w+\b", line):
        line += " align:middle"
    return line


def _fix_vtt_alignment(vtt_text):
    """Post-process a WebVTT string for Emby/Jellyfin compatibility.

    Fixes two issues with YouTube auto-generated captions:
      1. Left alignment ('align:start' + 'position:..%') -> center.
      2. Rollup/persiana effect: YouTube emits each cue containing the
         *previous* line plus the *new* line, plus tiny transition cues
         that re-show the previous line alone. We collapse each cue to
         only the last (newest) text line and drop redundant cues.
    """
    # Split header from body: header is everything until the first blank
    # line followed by a cue (or just keep everything up to first '-->').
    parts = re.split(r"\r?\n\r?\n", vtt_text)
    if not parts:
        return vtt_text

    header = parts[0]
    cue_blocks = parts[1:]

    out_blocks = [header]
    last_text = None

    for block in cue_blocks:
        block_lines = block.splitlines()
        if not block_lines:
            continue

        # Find timing line (the one with -->)
        timing_idx = None
        for i, ln in enumerate(block_lines):
            if "-->" in ln:
                timing_idx = i
                break
        if timing_idx is None:
            # Not a cue (could be NOTE / STYLE / etc) - keep as is
            out_blocks.append(block)
            continue

        timing_line = _fix_vtt_cue_timing_line(block_lines[timing_idx])
        text_lines = [
            _clean_vtt_text_line(line) for line in block_lines[timing_idx + 1 :]
        ]

        # Filter empty / whitespace-only lines
        non_empty = [line for line in text_lines if line.strip()]
        if not non_empty:
            # Skip cues that contain no real text after cleaning
            continue

        # Keep ONLY the last non-empty text line (the newest)
        new_text = non_empty[-1].rstrip()

        # Skip duplicates (consecutive cues showing same text)
        if new_text == last_text:
            continue
        last_text = new_text

        cue = []
        # Preserve any cue identifier lines before the timing line
        cue.extend(block_lines[:timing_idx])
        cue.append(timing_line)
        cue.append(new_text)
        out_blocks.append("\n".join(cue))

    return "\n\n".join(out_blocks)


def _vtt_timestamp_to_srt(timestamp):
    return timestamp.strip().replace(".", ",")


def _vtt_text_to_srt(vtt_text):
    blocks = re.split(r"\r?\n\r?\n", vtt_text)
    srt_blocks = []
    cue_number = 1

    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines()]
        if not lines:
            continue

        timing_idx = None
        for idx, line in enumerate(lines):
            if "-->" in line:
                timing_idx = idx
                break

        if timing_idx is None:
            continue

        timing_line = lines[timing_idx]
        timing_parts = timing_line.split("-->")
        if len(timing_parts) != 2:
            continue

        start_time = _vtt_timestamp_to_srt(timing_parts[0])
        end_time = _vtt_timestamp_to_srt(timing_parts[1].split()[0])
        text_lines = [
            _clean_vtt_text_line(line)
            for line in lines[timing_idx + 1 :]
            if line.strip()
        ]
        text_lines = [re.sub(r"<[^>]+>", "", line).strip() for line in text_lines]
        text_lines = [line for line in text_lines if line]
        if not text_lines:
            continue

        srt_blocks.append(
            f"{cue_number}\n{start_time} --> {end_time}\n" + "\n".join(text_lines)
        )
        cue_number += 1

    return "\n\n".join(srt_blocks) + ("\n" if srt_blocks else "")


def _convert_vtt_file_to_srt(vtt_path):
    srt_path = os.path.splitext(vtt_path)[0] + ".srt"
    with open(vtt_path, "r", encoding="utf-8") as f:
        vtt_text = f.read()
    srt_text = _vtt_text_to_srt(_fix_vtt_alignment(vtt_text))
    if not srt_text:
        return False
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_text)
    if not keep_vtt_subtitles:
        try:
            os.remove(vtt_path)
        except Exception:
            pass
    return True


def _convert_vtt_files_to_srt_in_subtitle_dir(subtitle_dir, subtitle_base):
    converted_count = 0
    if os.path.isdir(subtitle_dir):
        for fname in os.listdir(subtitle_dir):
            if fname.startswith(subtitle_base + ".") and fname.endswith(".vtt"):
                vtt_path = os.path.join(subtitle_dir, fname)
                try:
                    if _convert_vtt_file_to_srt(vtt_path):
                        converted_count += 1
                except Exception as e:
                    l.log("youtube", f"Error converting VTT to SRT for {fname}: {e}")
    return converted_count


def _fix_vtt_files_in_subtitle_dir(subtitle_dir, subtitle_base):
    fixed_count = 0
    if os.path.isdir(subtitle_dir):
        for fname in os.listdir(subtitle_dir):
            if fname.startswith(subtitle_base + ".") and fname.endswith(".vtt"):
                vtt_path = os.path.join(subtitle_dir, fname)
                try:
                    with open(vtt_path, "r", encoding="utf-8") as f:
                        original = f.read()
                    fixed = _fix_vtt_alignment(original)
                    if fixed != original:
                        with open(vtt_path, "w", encoding="utf-8") as f:
                            f.write(fixed)
                        fixed_count += 1
                except Exception as e:
                    l.log("youtube", f"Error fixing VTT alignment for {fname}: {e}")
    return fixed_count


def _make_media_playlist_absolute(m3u8_content, playlist_url):
    absolute_lines = []
    uri_re = re.compile(r'URI="([^"]+)"')
    for line in m3u8_content.splitlines():
        stripped = line.strip()
        if not stripped:
            absolute_lines.append(line)
            continue
        if stripped.startswith("#"):
            absolute_lines.append(
                uri_re.sub(lambda m: f'URI="{urljoin(playlist_url, m.group(1))}"', line)
            )
            continue
        absolute_lines.append(urljoin(playlist_url, stripped))
    return "\n".join(absolute_lines) + "\n"


def _get_stream_inf_height(info):
    match = re.search(r"\bRESOLUTION=\d+x(\d+)", info)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def download_subtitles_for_video(youtube_id, file_path):
    if not download_subtitles or "-audio" in youtube_id:
        return

    base_path = os.path.splitext(file_path)[0]
    subtitle_dir = os.path.dirname(base_path)
    subtitle_base = os.path.basename(base_path)
    if os.path.isdir(subtitle_dir):
        for fname in os.listdir(subtitle_dir):
            if fname.startswith(subtitle_base + ".") and fname.endswith(
                (".vtt", ".srt", ".ass")
            ):
                fixed_count = _fix_vtt_files_in_subtitle_dir(
                    subtitle_dir, subtitle_base
                )
                if fixed_count:
                    l.log(
                        "youtube",
                        f"Fixed VTT alignment for {fixed_count} subtitle file(s) of {youtube_id}",
                    )
                if convert_subtitles_to_srt:
                    converted_count = _convert_vtt_files_to_srt_in_subtitle_dir(
                        subtitle_dir, subtitle_base
                    )
                    if converted_count:
                        l.log(
                            "youtube",
                            f"Converted {converted_count} VTT subtitle file(s) to SRT for {youtube_id}",
                        )
                return

    sub_langs = f"{lang},{lang}-orig,en,en-orig"
    command = [
        "yt-dlp",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        sub_langs,
        "--sub-format",
        "vtt",
        "--no-warnings",
        "--ignore-errors",
        "-o",
        f"{base_path}.%(ext)s",
        f"https://www.youtube.com/watch?v={youtube_id}",
    ]
    # Youtube().set_cookies(command)
    Youtube().set_language(command)
    Youtube().set_proxy(command)
    try:
        w.worker(command).output()
        l.log("youtube", f"Subtitles downloaded for {youtube_id}")
        time.sleep(2)
        fixed_count = _fix_vtt_files_in_subtitle_dir(subtitle_dir, subtitle_base)
        if fixed_count:
            l.log(
                "youtube",
                f"Fixed VTT alignment for {fixed_count} subtitle file(s) of {youtube_id}",
            )
        if convert_subtitles_to_srt:
            converted_count = _convert_vtt_files_to_srt_in_subtitle_dir(
                subtitle_dir, subtitle_base
            )
            if converted_count:
                l.log(
                    "youtube",
                    f"Converted {converted_count} VTT subtitle file(s) to SRT for {youtube_id}",
                )
    except Exception as e:
        l.log("youtube", f"Error downloading subtitles for {youtube_id}: {e}")


def clean_text(text):
    # Reemplazar los caracteres especiales habituales y eliminar los que no son necesarios

    # Escapando caracteres que deben mantenerse pero asegurándote de que sean seguros
    text = html.escape(text)

    # Eliminar cualquier carácter no deseado usando expresiones regulares
    text = re.sub(r"[^\w\s\[\]\(\)\-\_\'\"\/\.\:\;\,]", "", text)

    return text


def video_id_exists_in_content(media_folder, video_id):
    return find_strm_path_for_video_id(media_folder, video_id) is not None


def find_strm_path_for_video_id(media_folder, video_id):
    """Return the absolute path of the .strm file that references video_id,
    or None if no such file exists. Robust to unreadable/locked files."""
    if not os.path.isdir(media_folder):
        return None
    for root, dirs, files in os.walk(media_folder):
        for file in files:
            if file.endswith(".strm"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        if video_id in f.read():
                            return file_path
                except Exception:
                    continue
    return None


def to_strm(method):
    # reload our channel list and youtube settings config in case it's changed
    _load_config_values()

    l.log(
        "youtube", f"to_strm: Running for the following channels: {', '.join(channels)}"
    )
    l.log("youtube", f"to_strm: Going to process {videos_limit} # of videos")

    for youtube_channel in channels:
        yt = Youtube(youtube_channel)

        log_text = " --------------- "
        l.log("youtube", log_text)
        log_text = f"Working {youtube_channel}..."
        l.log("youtube", log_text)

        # get videos under video limit
        videos = yt.get_results()
        channel_name = yt.channel_name
        channel_url = yt.channel_url
        channel_description = yt.channel_description

        log_text = f"Channel URL: {channel_url}"
        l.log("youtube", log_text)
        log_text = f"Channel Name: {channel_name}"
        l.log("youtube", log_text)
        log_text = f"Channel Poster: {yt.channel_poster}"
        l.log("youtube", log_text)
        log_text = f"Channel Landscape: {yt.channel_landscape}"
        l.log("youtube", log_text)
        log_text = "Channel Description: "
        l.log("youtube", log_text)
        log_text = channel_description
        l.log("youtube", log_text)

        if videos:
            log_text = f"Videos detected: {len(videos)}"
            l.log("youtube", log_text)
            # Reverse video list so oldest videos get lower episode numbers
            videos.reverse()
            channel_nfo = False
            channel_folder_created = False

            # Get channel_id from first video to create channel folder and NFO
            first_video = videos[0]
            channel_id = first_video["channel_id"]
            youtube_channel_folder = (
                first_video["uploader_id"]
                .replace("/user/", "@")
                .replace("/streams", "")
            )

            # Create channel folder
            channel_folder = sanitize(
                "{} [{}]".format(youtube_channel_folder, channel_id)
            )
            f.folders().make_clean_folder(
                "{}/{}".format(media_folder, channel_folder), False, ytdlp2strm_config
            )

            # Create channel NFO with correct images
            n.nfo(
                "tvshow",
                "{}/{}".format(media_folder, channel_folder),
                {
                    "title": channel_name,
                    "plot": channel_description.replace("\n", " <br/>"),
                    "landscape": yt.channel_landscape,
                    "poster": yt.channel_poster,
                    "studio": "Youtube",
                },
            ).make_nfo()
            channel_nfo = True
            channel_folder_created = True

            for video in videos:
                video_id = video["id"]
                channel_id = video["channel_id"]
                video_name = video["title"]
                thumbnail = video["thumbnail"]
                description = video["description"]
                date = datetime.strptime(video["upload_date"], "%Y%m%d")
                upload_date = date.strftime("%Y-%m-%d")
                # Issue #111: expose duration in the NFO so Jellyfin/Emby
                # can show content length without having to play the video.
                raw_duration = video.get("duration")
                try:
                    duration_seconds = int(raw_duration) if raw_duration else 0
                except (TypeError, ValueError):
                    duration_seconds = 0
                # Kodi/Jellyfin/Emby <runtime> is expressed in minutes.
                runtime_minutes = (
                    max(1, (duration_seconds + 59) // 60) if duration_seconds else ""
                )
                year = date.year
                youtube_channel = video["uploader_id"]
                youtube_channel_folder = youtube_channel.replace("/user/", "@").replace(
                    "/streams", ""
                )
                # In `iframe` mode the STRM points directly to the public YouTube
                # watch URL, so players that support web/iframe playback (or the
                # user's external app) can resolve it natively without going
                # through ytdlp2STRM.
                if method == "iframe":
                    file_content = f"https://www.youtube.com/watch?v={video_id}"
                else:
                    file_content = (
                        f"http://{host}:{port}/{source_platform}/{method}/{video_id}"
                    )

                channel_folder = sanitize(
                    "{} [{}]".format(youtube_channel_folder, channel_id)
                )

                # Create season folder based on video year
                season_folder = f"Season {year}"
                folder_full_path = "{}/{}/{}".format(
                    media_folder, channel_folder, season_folder
                )

                folder_path = "{}/{}".format(
                    media_folder,
                    sanitize("{} [{}]".format(youtube_channel_folder, channel_id)),
                )

                # Check first whether this video already has an STRM somewhere
                # in the channel folder. If it does, reuse the EXISTING file path
                # (with its original episode number and title) for subtitle
                # downloads instead of recomputing a new one. Otherwise a renamed
                # YouTube title or an incremented episode counter would generate
                # duplicate .nfo/.png/.vtt/.srt files under a non-existent STRM.
                existing_strm_path = find_strm_path_for_video_id(folder_path, video_id)
                if existing_strm_path:
                    l.log(
                        "youtube",
                        f"Video {video_id} already exists at {existing_strm_path}",
                    )
                    download_subtitles_for_video(video_id, existing_strm_path)
                    continue

                # Format title with episode number (only for NEW videos)
                use_mmdd = episode_format.lower() == "mmdd"
                formatted_title = format_episode_title(
                    video_name, folder_full_path, upload_date, use_mmdd, year
                )

                file_path = "{}/{}/{}/{}.{}".format(
                    media_folder,
                    channel_folder,
                    season_folder,
                    sanitize(formatted_title),
                    "strm",
                )

                if not channel_folder_created:
                    f.folders().make_clean_folder(
                        "{}/{}".format(
                            media_folder,
                            sanitize(
                                "{} [{}]".format(youtube_channel_folder, channel_id)
                            ),
                        ),
                        False,
                        ytdlp2strm_config,
                    )
                    channel_folder_created = True

                # Create season folder if it doesn't exist
                season_folder_path = "{}/{}/{}".format(
                    media_folder, channel_folder, season_folder
                )
                if not os.path.exists(season_folder_path):
                    os.makedirs(season_folder_path, exist_ok=True)

                if channel_url is None:
                    channel_url = f"https://www.youtube.com/channel/{channel_id}"
                    channel = Youtube(channel_url)
                    images = channel.get_channel_images()
                    channel.channel_url = channel_url
                    channel_name = channel.get_channel_name()
                    channel_description = channel.get_channel_description()
                    channel_landscape = images["landscape"]
                    channel_poster = images["poster"]
                else:
                    channel_landscape = yt.channel_landscape
                    channel_poster = yt.channel_poster

                ## -- BUILD CHANNEL NFO FILE
                if not channel_nfo:
                    n.nfo(
                        "tvshow",
                        "{}/{}".format(
                            media_folder, "{} [{}]".format(youtube_channel, channel_id)
                        ),
                        {
                            "title": channel_name,  # Use friendly name instead of @-handle
                            "plot": channel_description.replace("\n", " <br/>"),
                            "landscape": channel_landscape,
                            "poster": channel_poster,
                            "studio": "Youtube",
                        },
                    ).make_nfo()
                    channel_nfo = True
                ## -- END

                ## -- BUILD VIDEO NFO FILE
                n.nfo(
                    "episode",
                    "{}/{}/{}".format(
                        media_folder,
                        "{} [{}]".format(youtube_channel, channel_id),
                        season_folder,
                    ),
                    {
                        "item_name": sanitize(formatted_title),
                        "title": sanitize(formatted_title),
                        "upload_date": upload_date,
                        "year": year,
                        "plot": description.replace("\n", " <br/>\n "),
                        "season": year,
                        "episode": "",
                        "preview": thumbnail,
                        "runtime": runtime_minutes,
                        "duration_seconds": duration_seconds or "",
                    },
                ).make_nfo()
                ## -- END

                if not os.path.isfile(file_path):
                    f.folders().write_file(file_path, file_content)
                download_subtitles_for_video(video_id, file_path)

            # Notify Jellyfin/Emby after processing all videos for this channel
            jellyfin_notifier = JellyfinNotifier(config)
            if jellyfin_notifier.enabled:
                jellyfin_notifier.notify_new_content(f"{media_folder}/{channel_folder}")
        else:
            log_text = " no videos detected..."
            l.log("youtube", log_text)
    l.log("youtube", "Finished to_strm for youtube")


def subtitles(youtube_id):
    subtitle_lang = request.args.get("lang")
    subtitle_info = get_subtitle_info(youtube_id, subtitle_lang)
    if not subtitle_info:
        return "Subtitles not found.", 404

    try:
        response = requests.get(subtitle_info["url"], timeout=15)
        if response.status_code != 200:
            return "Subtitles not found.", 404
        vtt_text = _fix_vtt_alignment(response.text)
        flask_response = Response(vtt_text, mimetype="text/vtt")
        flask_response.headers["Content-Type"] = "text/vtt; charset=utf-8"
        flask_response.headers["Cache-Control"] = "public, max-age=3600"
        flask_response.headers["Access-Control-Allow-Origin"] = "*"
        return flask_response
    except Exception as e:
        l.log("youtube", f"Error serving subtitles for {youtube_id}: {e}")
        return "Subtitles not found.", 404


def bridge(youtube_id):
    s_youtube_id = youtube_id.split("-audio")[0]
    s_youtube_id_url = f"https://www.youtube.com/watch?v={s_youtube_id}"

    l.log("youtube", f"bridge: stream requested on {s_youtube_id_url}")

    # Get info for duration and size
    duration = None
    file_size = None
    try:
        command_info = ["yt-dlp", "--dump-json", "--no-warnings", s_youtube_id_url]
        # Youtube().set_cookies(command_info)
        Youtube().set_proxy(command_info)
        info = json.loads(w.worker(command_info).output())

        duration = info.get("duration")
        file_size = info.get("filesize") or info.get("filesize_approx")
    except Exception as e:
        l.log("youtube", f"Error getting info: {e}")

    # Parse Range Header
    range_header = request.headers.get("Range", None)
    byte_start = 0
    byte_end = None
    length = file_size

    if range_header and file_size:
        match = re.search(r"(\d+)-(\d*)", range_header)
        if match:
            start_str, end_str = match.groups()
            byte_start = int(start_str)
            if end_str:
                byte_end = int(end_str)
            else:
                byte_end = file_size - 1

            length = byte_end - byte_start + 1

    # Calculate start time for yt-dlp
    start_time = 0
    if byte_start > 0 and file_size and duration:
        start_time = (byte_start / file_size) * duration

    def generate():
        command = [
            "yt-dlp",
            "--no-warnings",
            "-o",
            "-",
            "-f",
            _get_video_format_selector("bestvideo+bestaudio"),
            "--restrict-filenames",
        ]

        if start_time > 0:
            command.extend(["--download-sections", f"*{start_time}-inf"])

        command.append(s_youtube_id_url)

        # Youtube().set_cookies(command)
        Youtube().set_language(command)
        Youtube().set_proxy(command)

        if "-audio" in youtube_id:
            try:
                f_index = command.index("-f")
                command[f_index + 1] = "bestaudio"
            except ValueError:
                pass

        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )

        try:
            while True:
                data = process.stdout.read(4096)
                if not data:
                    break
                yield data
        finally:
            process.kill()

    headers = Headers()
    headers.add("Accept-Ranges", "bytes")

    if file_size:
        headers.add("Content-Length", str(length))
        if range_header:
            headers.add("Content-Range", f"bytes {byte_start}-{byte_end}/{file_size}")

    response = Response(
        stream_with_context(generate()),
        mimetype="video/mp4",
        direct_passthrough=True,
        headers=headers,
    )

    response.cache_control.public = True
    response.cache_control.max_age = int(60000)

    if file_size and range_header:
        l.log(
            "youtube",
            "bridge: returning status code 206 because range_header requested",
        )
        response.status_code = 206

    return response


def download(youtube_id):
    s_youtube_id = youtube_id.split("-audio")[0]
    current_dir = os.getcwd()

    # Construyes la ruta hacia la carpeta 'temp' dentro del directorio actual
    temp_dir = os.path.join(current_dir, "temp")
    if config["sponsorblock"]:
        command = [
            "yt-dlp",
            "-f",
            "bv*+ba+ba.2",
            "-o",
            os.path.join(temp_dir, "%(title)s.%(ext)s"),
            "--sponsorblock-remove",
            config["sponsorblock_cats"],
            "--restrict-filenames",
            s_youtube_id,
        ]
    else:
        command = [
            "yt-dlp",
            "-f",
            "bv*+ba+ba.2",
            "-o",
            os.path.join(temp_dir, "%(title)s.%(ext)s"),
            "--restrict-filenames",
            s_youtube_id,
        ]
    # Youtube().set_cookies(command)
    Youtube().set_language(command)
    Youtube().set_proxy(command)
    if "-audio" in youtube_id:
        command[2] = "bestaudio"

    w.worker(command).call()

    filename_command = [
        "yt-dlp",
        "--print",
        "filename",
        "--restrict-filenames",
        "{}".format(youtube_id),
    ]
    # Youtube().set_cookies(filename_command)
    Youtube().set_language(filename_command)
    filename = w.worker(filename_command).output()
    return send_file(os.path.join(temp_dir, filename))
