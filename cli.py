import argparse

from classes.log import log as l
from plugins.youtube import youtube
from version import __version__ as APP_VERSION


def main(raw_args=None):
    parser = argparse.ArgumentParser()

    parser.add_argument("-m", "--media", help="Media platform")
    parser.add_argument("-p", "--params", help="Params to media platform mode.")
    parser.add_argument("-v", "--version", help="Show YTDLP2STRM version")

    args = parser.parse_args(raw_args)
    params = args.params.split(",") if args.params is not None else None

    if params is None:
        params = args.p.split(",") if args.p is not None else None

    if args.version:
        log_text = "ytdlp2STRM version: {}".format(APP_VERSION)
        l.log("CLI", log_text)

    if params is not None:
        l.log("CLI", f"Running youtube with {params}")
        youtube.to_strm(*params)


if __name__ == "__main__":
    main()
