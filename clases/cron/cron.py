import hashlib
import os
import threading
import time

import schedule
from tzlocal import get_localzone  # $ pip install tzlocal
from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from clases.config import config as c
from clases.log import log as l
from cli import main as main_cli

# -- LOAD CONFIG AND CHANNELS FILES
config_path = os.path.abspath("./config/crons.json")
running_tasks = {}
running_tasks_lock = threading.Lock()


def calculate_hash(file_path):
    """Calcula el hash SHA-256 del archivo especificado."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    except FileNotFoundError:
        return None


def load_crons():
    return c.config(config_path).get_config()


class Cron(threading.Thread):
    def __init__(self, stop_event):
        super().__init__(daemon=True)
        self.stop_event = stop_event
        self.config_hash = None
        self.schedule_lock = threading.RLock()
        self.running_tasks = running_tasks
        self.running_tasks_lock = running_tasks_lock

    def run(self):
        try:
            self.default_tz = get_localzone()
            self.schedule_tasks()
            self.watch_config()
        except Exception as e:
            l.log("cron", f"Cron thread stopped unexpectedly: {e}")

    def schedule_tasks(self):
        l.log("cron", "schedule tasks: checking for cron config update")
        with self.schedule_lock:
            new_hash = calculate_hash(config_path)
            if self.config_hash == new_hash:
                l.log("cron", "no update detected")
                return

            try:
                crons = load_crons()
            except Exception as e:
                l.log("cron", f"Could not load crons configuration: {e}")
                return

            if not isinstance(crons, list):
                l.log(
                    "cron",
                    "Invalid crons configuration format. Keeping current scheduled tasks.",
                )
                return

            self.config_hash = new_hash
            self.crons = crons
            l.log(
                "cron",
                "schedule_tasks: Update detected - scheduling tasks according to the latest crons configuration.",
            )

            # Cancel any existing scheduled jobs
            for job in schedule.get_jobs():
                l.log(
                    "cron", "schedule_tasks: Cancelling existing job due to cron update"
                )
                schedule.cancel_job(job)

            if not self.crons:
                l.log("cron", "schedule_tasks: No crons found, is the cron file empty?")

            # Schedule all new tasks
            for cron in self.crons:
                try:
                    qty = int(cron["qty"]) if cron["qty"] else 1
                except ValueError:
                    qty = 1
                    l.log(
                        "cron",
                        f"Invalid qty for cron: {cron}, using default value 1.",
                    )

                every_method = getattr(schedule.every(qty), cron["every"])

                # Wrap main_cli in a thread to prevent blocking
                task_to_do = lambda params=cron["do"]: self.start_task(main_cli, params)

                every_method.do(task_to_do)
                l.log(
                    "cron",
                    f"schedule_tasks: Scheduled task {cron['do']} every {qty} {cron['every']}.",
                )

    def start_task(self, task_func, params):
        task_params = list(params)
        task_key = tuple(task_params)
        with self.running_tasks_lock:
            running_thread = self.running_tasks.get(task_key)
            if running_thread and running_thread.is_alive():
                l.log(
                    "cron",
                    f"Skipping task {task_params}: previous execution is still running.",
                )
                return
            thread = threading.Thread(
                target=self.run_task,
                args=(task_func, task_params, task_key),
                daemon=True,
            )
            self.running_tasks[task_key] = thread
            thread.start()

    def run_task(self, task_func, params, task_key):
        started_at = time.monotonic()
        l.log(
            "cron",
            "-----------------------------------------------------------------------------------------------------",
        )
        l.log("cron", f"Running task {params}.")
        try:
            task_func(params)
        except Exception as e:
            l.log("cron", f"Error executing task {params}: {e}")
        finally:
            duration = int(time.monotonic() - started_at)
            l.log("cron", f"Finished task {params} in {duration} seconds.")
            l.log(
                "cron",
                "-----------------------------------------------------------------------------------------------------",
            )
            with self.running_tasks_lock:
                if self.running_tasks.get(task_key) is threading.current_thread():
                    del self.running_tasks[task_key]

    def watch_config(self):
        event_handler = ConfigChangeHandler(config_path, callback=self.schedule_tasks)
        observer = (
            PollingObserver()
        )  # Mueve el observador aquí para detenerlo más tarde
        observer.schedule(
            event_handler, path=os.path.dirname(config_path), recursive=False
        )
        observer.start()

        l.log("cron", f"Started watching {os.path.dirname(config_path)} for changes.")

        try:
            while not self.stop_event.is_set():
                try:
                    with self.schedule_lock:
                        schedule.run_pending()  # run the pending cron tasks - should this be done in watch_config? idts
                except Exception as e:
                    l.log("cron", f"Error running pending cron tasks: {e}")
                    self.stop_event.wait(5)
                self.stop_event.wait(1)
        except KeyboardInterrupt:
            l.log("cron", "Stopping the cron watchdog observer on exception!")
            observer.stop()
            observer.join()
        finally:
            l.log("cron", "Stopping the cron watchdog observer on finally!")
            observer.stop()
            observer.join()


class ConfigChangeHandler(FileSystemEventHandler):
    def __init__(self, file_path, callback):
        self.file_path = file_path
        self.callback = callback
        self.last_hash = calculate_hash(file_path)

    def on_modified(self, event):
        l.log(
            "cron",
            f"ConfigChangeHandler received an event of {event.event_type} on {event.src_path}",
        )
        if event.event_type == "modified" and os.path.abspath(
            event.src_path
        ) == os.path.abspath(self.file_path):
            new_hash = calculate_hash(self.file_path)
            if new_hash != self.last_hash:
                self.last_hash = new_hash
                try:
                    l.log(
                        "cron",
                        "on_modified: Hash change detected, running ConfigChangeHandler callback",
                    )
                    self.callback()
                except Exception as e:
                    l.log("cron", f"Error reloading cron configuration: {e}")
            else:
                l.log(
                    "cron",
                    "no hash change detected, not running ConfigChangeHandler callback",
                )
