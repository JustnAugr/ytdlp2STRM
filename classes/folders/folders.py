import os
import platform
import time

from classes.config import config as c
from classes.log import log as l


class folders:
    ytdlp2strm_config = c.config("./config/config.json").get_config()

    keep_downloaded = 365 * 24 * 60 * 60  # one year
    temp_aria2_ffmpeg_files = 600

    # keep downloads for the same time period as our lookback
    if "days_dateafter" in ytdlp2strm_config:
        keep_downloaded = int(ytdlp2strm_config["days_dateafter"]) * 24 * 60 * 60

    def make_clean_folder(self, folder_path, forceclean, config):
        if os.path.exists(folder_path):
            if forceclean or config.get("ytdlp2strm_keep_old_strm") == "False":
                # Check the contents of the directory in a simpler way
                try:
                    file_list = os.listdir(folder_path)
                except Exception as e:
                    l.log("folder", f"Unable to listdir on {folder_path} because\n{e}")
                    return

                now = time.time()

                for file_name in file_list:
                    file_path = os.path.join(folder_path, file_name)
                    if os.path.isfile(file_path):
                        try:
                            os.remove(file_path)
                            log_text = f"Deleted file: {file_path}"
                            l.log("folder", log_text)
                            print(log_text)
                        except Exception as e:
                            log_text = f"Failed to delete file: {file_path}. Error: {e}"
                            l.log("folder", log_text)
                log_text = f"Cleaned directory: {folder_path}"
                l.log("folder", log_text)
        else:
            os.makedirs(folder_path, exist_ok=True)
            log_text = f"Created directory: {folder_path}"
            l.log("folder", log_text)

    def write_file(self, file_path, content):
        try:
            if not os.path.exists(file_path) or "tvshow.nfo" in file_path:
                # Ensure content is properly encoded
                content = content.encode("utf-8").decode("utf-8")

                # Write to file with UTF-8 encoding
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write(content.replace("\n", ""))

                file_path = file_path.encode("utf-8").decode("utf-8")
                log_text = f"File created: {file_path}"
                l.log("folder", log_text)
        except Exception as e:
            log_text = f"Error writing file: {e}"
            l.log("folder", log_text)

    def write_file_spaces(self, file_path, content):
        try:
            if not os.path.exists(file_path) or "tvshow.nfo" in file_path:
                # Ensure content is properly encoded
                content = content.encode("utf-8").decode("utf-8")

                # Write to file with UTF-8 encoding
                with open(file_path, "w", encoding="utf-8") as file:
                    file.write(content)

                file_path = file_path.encode("utf-8").decode("utf-8")
                log_text = f"File created: {file_path}"
                l.log("folder", log_text)
        except Exception as e:
            log_text = f"Error writing file: {e}"
            l.log("folder", log_text)

    def clean_waste(self, files_to_delete):
        for file_path in files_to_delete:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                else:
                    continue
            except Exception as e:
                log_text = f"Error deleting file {file_path}: {e}"
                l.log("folder", log_text)
                pass

    def creation_date(self, path_to_file):
        if platform.system() == "Windows":
            return os.path.getctime(path_to_file)
        else:
            stat = os.stat(path_to_file)
            try:
                return stat.st_birthtime
            except AttributeError:
                return stat.st_mtime

    def modified_date(self, path_to_file):
        stat = os.stat(path_to_file)
        return stat.st_mtime

    def clean_old_videos(self, stop_event):
        # inner function to clean out a folder
        def _clean_old_videos_from_folder(download_dir):
            for entry in os.listdir(download_dir):
                video_folder = os.path.join(download_dir, entry)

                # if this file in the folder is itself a folder, recurse on it
                if not os.path.isdir(video_folder):
                    l.log(
                        "folder",
                        f"Found something other than a video folder at {video_folder}, that's not right!",
                    )
                else:
                    # this is truly a video folder
                    delete_video_folder = False

                    # check the files in the folders, if we have one and delete it then we can delete the folder too
                    for file in os.listdir(video_folder):
                        file_path = os.path.join(video_folder, file)
                        now = time.time()
                        aria2_ffmpeg_files = [
                            ".part",
                            "aria2",
                            "urls",
                            ".temp",
                            "m4a",
                            ".ytdl",
                        ]

                        if any(keyword in file for keyword in aria2_ffmpeg_files):
                            if (
                                self.modified_date(file_path)
                                < now - self.temp_aria2_ffmpeg_files
                            ):
                                log_text = f"clean_old_videos: Removing old temporary file: {file_path}"
                                l.log("folder", log_text)
                                os.remove(file_path)
                        else:
                            if (
                                self.modified_date(file_path)
                                < now - self.keep_downloaded
                            ):
                                log_text = f"clean_old_videos: Removing old video file: {file_path}"
                                l.log("folder", log_text)
                                os.remove(file_path)

                    if delete_video_folder:
                        l.log(
                            "folder",
                            f"clean_old_videos: Removing old video folder because its video was deleted: {video_folder}",
                        )
                        os.removedirs(video_folder)

        l.log(
            "folder",
            f"clean_old_videos: going to be cleaning videos after {self.keep_downloaded}",
        )

        # create downloads folder if it doesn't exist
        current_dir = os.getcwd()
        download_dir = os.path.join(current_dir, "downloads")
        if not os.path.exists(download_dir):
            os.makedirs(download_dir, exist_ok=True)

        while not stop_event.is_set():
            try:
                time.sleep(5)
                _clean_old_videos_from_folder(download_dir)
            except Exception as e:
                log_text = f"clean_old_videos: Error in clean_old_videos: {e}"
                l.log("folder", log_text)
                continue

        log_text = "Exiting clean_old_videos thread."
        l.log("folder", log_text)
