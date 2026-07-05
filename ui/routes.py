import json
import logging

from flask import jsonify, render_template, request
from flask_socketio import SocketIO

from __main__ import app
from ui.ui import Ui
from version import __version__ as APP_VERSION

_ui = Ui()
socketio = SocketIO(
    app, cors_allowed_origins="*", async_mode="threading", manage_session=False
)
logging.getLogger("werkzeug").setLevel(logging.WARNING)


# {"ytdlp2strm_host": "127.0.0.1", "ytdlp2strm_port": "5005", "ytdlp2strm_keep_old_strm": "True", "ytdlp2strm_temp_file_duration": "86400"}
descriptions = {
    "ytdlp2strm_host": "host that'll be used in the bridge .strm files",
    "ytdlp2strm_port": "port that'll be used in the bridge .strm files",
    "ytdlp2strm_keep_old_strm": "should we keep strm files once they're no longer in our videos_limit # of latest videos?",
    "ytdlp2strm_temp_file_duration": "temp file duration for downloads",
}


@app.context_processor
def inject_app_version():
    """Make `app_version` available in every Jinja template."""
    return {"app_version": APP_VERSION}


# Ruta principal
@app.route("/")
def index():
    crons = _ui.crons
    last_executions = _ui.get_last_executions()
    next_executions = _ui.get_next_executions()
    return render_template(
        "index.html",
        plugins=_ui.plugins,
        crons=crons,
        last_executions=last_executions,
        next_executions=next_executions,
    )


# Ruta para las opciones generales
@app.route("/settings", methods=["GET", "POST"])
def general_settings():

    result = False
    if request.method == "POST":
        # Obtener los valores del formulario
        config_data = {}
        for key, value in request.form.items():
            config_data[key] = value

        _ui.general_settings = config_data

    config_data = _ui.general_settings
    if config_data:
        result = True

    return render_template(
        "general_settings.html",
        config_data=config_data,
        result=result,
        request=request.method,
        descriptions=descriptions,
    )


# Ruta para la edición de plugins
@app.route("/crons", methods=["GET", "POST"])
def crons_settings():
    result = False
    if request.method == "POST":
        # Obtener el código de plugins desde el formulario
        headers = ("every", "qty", "plugin", "param")
        values = (
            request.form.getlist("every[]"),
            request.form.getlist("qty[]"),
            request.form.getlist("plugin[]"),
            request.form.getlist("param[]"),
        )
        crons = [{} for i in range(len(values[0]))]
        for x, i in enumerate(values):
            for _x, _i in enumerate(i):
                if not headers[x] == "plugin" and not headers[x] == "param":
                    crons[_x][headers[x]] = _i
                elif headers[x] == "plugin":
                    crons[_x]["do"] = ["--media", _i]
                elif headers[x] == "param":
                    crons[_x]["do"].append("--param")
                    crons[_x]["do"].append(_i)

        # if we deleted crons and are saving an empty list
        if not len(values[0]):
            result = True

        # Guardar el código en el archivo de plugins
        _ui.crons = json.dumps(crons)

    crons = _ui.crons
    if crons or result:
        result = True

    return render_template(
        "crons.html", result=result, crons=crons, request=request.method
    )


# Ruta para editar config y channels un plugin
@app.route("/plugin/<plugin>/channels", methods=["GET", "POST"])
def plugin_channels(plugin):
    result = False
    plugins = _ui.plugins

    selected_plugin = list(filter(lambda p: p["name"] == plugin, plugins))

    if request.method == "POST":
        # Obtener los valores del formulario
        config_data = {}
        config_data["config_file"] = "{}/{}/{}".format(
            "./plugins", selected_plugin[0]["name"], "channel_list.json"
        )
        config_data["channels"] = request.form.getlist("channels")
        _ui.plugins = config_data

        if config_data["channels"]:
            result = True

        plugins = _ui.plugins
        selected_plugin = list(filter(lambda p: p["name"] == plugin, plugins))

    return render_template(
        "plugin_channels.html",
        plugin=selected_plugin[0],
        result=result,
        request=request.method,
    )


@app.route("/log")
def view_log():
    log_file = "ytdlp2strm.log"
    try:
        log_content = []
        with open(log_file, "r", encoding="utf-8") as file:
            for line in file:
                # Si la línea empieza con '[', formatear el texto dentro de los primeros corchetes
                if line.startswith("["):
                    end_idx = line.find("]")
                    if end_idx != -1:
                        formatted_line = (
                            '[<span style="color:yellowgreen;">'
                            + line[1:end_idx]
                            + "</span>]"
                            + line[end_idx + 1 :]
                        )
                    else:
                        formatted_line = line  # Si no hay un cierre de corchete, deja la línea como está
                else:
                    formatted_line = line
                # Añadir un <br/> al final de cada línea
                log_content.append(formatted_line)
        return render_template("log.html", log_content=log_content)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@socketio.on("connect")
def handle_connect():
    # Enviar el historial del CLI al cliente que se acaba de conectar
    from ui.ui import Ui

    for line in Ui.cli_history:
        socketio.emit("command_output", line, to=request.sid)
    # Enviar el estado de ejecución actual
    socketio.emit("execution_status", {"is_running": Ui.is_running}, to=request.sid)


@socketio.on("execute_command")
def handle_command(command):
    _ui.handle_command(command)
