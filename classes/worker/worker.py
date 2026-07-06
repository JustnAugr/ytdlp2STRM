import os
import re
import shlex
import subprocess
import threading

from classes.log import log as l

# Patrones de errores "benignos" que yt-dlp emite cuando un video del feed
# de un canal no es accesible sin credenciales. El cron sigue funcionando
# igualmente, asi que los colapsamos en un unico resumen para no llenar el
# log en cada ejecucion. Issue #109.
_BENIGN_YTDLP_PATTERNS = (
    "members-only",
    "member-only",
    "channel's members",
    "join this channel",
    "private video",
    "video unavailable",
    "this video has been removed",
    "sign in to confirm your age",
    "premium members",
    "requires payment",
    "video is not available",
)

_YOUTUBE_ID_RE = re.compile(r"\[youtube\][^:]*?\b([A-Za-z0-9_-]{11})\b")


def _classify_stderr(stderr):
    """Separa stderr de yt-dlp en (benign_ids, benign_count, other_lines).

    - benign_ids: set de IDs de YouTube detectados en lineas consideradas
      benignas (miembros de canal, privado, no disponible, etc).
    - benign_count: numero total de lineas benignas (incluye las que no
      llevan ID extraible).
    - other_lines: resto de lineas, loggeadas tal cual.
    """
    benign_ids = set()
    benign_count = 0
    other_lines = []
    for raw in stderr.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(p in lowered for p in _BENIGN_YTDLP_PATTERNS):
            benign_count += 1
            match = _YOUTUBE_ID_RE.search(line)
            if match:
                benign_ids.add(match.group(1))
            continue
        other_lines.append(line)
    return benign_ids, benign_count, other_lines


# Inicializa un objeto Lock para el control de concurrencia
preload_lock = threading.Lock()

# Variable de cierre para controlar la ejecución concurrente de la función preload_video
is_preloading = False


class worker:
    def __init__(self, command):
        self.command = command
        self.wd = os.path.abspath(".")

    def output(self):
        process = subprocess.run(
            self.command,  # Unimos el comando en una cadena de texto
            # shell=True,
            capture_output=True,  # Capturamos stdout y stderr
            text=True,
        )
        if process.stderr:
            if (
                "The channel is not currently live" in process.stderr
                or "[twitch:stream] videos: videos does not exist" in process.stderr
            ):
                pass
            else:
                benign_ids, benign_count, other_lines = _classify_stderr(process.stderr)
                if benign_count:
                    unique = len(benign_ids)
                    if unique:
                        l.log(
                            "worker",
                            "Skipped {} inaccessible video(s) (members-only/private/unavailable): {}".format(
                                unique, ", ".join(sorted(benign_ids))
                            ),
                        )
                    else:
                        l.log(
                            "worker",
                            "Skipped {} inaccessible video(s) (members-only/private/unavailable)".format(
                                benign_count
                            ),
                        )
                if other_lines:
                    l.log("worker", "\n".join(other_lines))
        return process.stdout

    def shell(self):
        process = subprocess.run(
            " ".join(self.command),  # Unimos el comando en una cadena de texto
            shell=True,
            capture_output=True,  # Capturamos stdout y stderr
        )
        try:
            return process.stdout.decode("utf-8")  # Intentamos decodificar como UTF-8
        except UnicodeDecodeError:
            return process.stdout.decode("latin1")  # Intentamos decodificar con latin1

    def call(self):
        return subprocess.call(self.command)

    def run(self):
        process = subprocess.Popen(self.command, stdout=subprocess.PIPE, shell=True)
        while True:
            line = process.stdout.readline().rstrip()
            if not line:
                break
            try:
                yield line.decode("utf-8")
            except:
                yield line.decode("latin-1")

    def run_command(self):
        process = subprocess.Popen(shlex.split(self.command), stdout=subprocess.PIPE)
        while True:
            try:
                output = process.stdout.readline().rstrip().decode("utf-8")
            except:
                output = process.stdout.readline().rstrip().decode("latin-1")
            if output == "" and process.poll() is not None:
                break
            if output:
                log_text = output.strip()
                l.log("worker", log_text)
        rc = process.poll()
        return rc
