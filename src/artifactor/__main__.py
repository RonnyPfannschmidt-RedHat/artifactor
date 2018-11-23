#!/usr/bin/env python3
import os

import click
import yaml
from iqe.artifactor import _random_port
from iqe.artifactor import Artifactor
from iqe.artifactor import initialize
from iqe.artifactor.plugins import filedump
from iqe.artifactor.plugins import logger
from iqe.artifactor.plugins import prometheus
from iqe.artifactor.plugins import reporter


def run(art_config, run_id=None):
    art = Artifactor(None)

    if "artifact_dir" not in art_config:
        art_config["artifact_dir"] = str(os.path.join(art_config["log_dir"], "artifacts"))
    art.set_config(art_config)

    art.register_plugin(logger.Logger, "logger")

    art.register_plugin(filedump.Filedump, "filedump")
    art.register_plugin(reporter.Reporter, "reporter")
    art.register_plugin(prometheus.Prometheus, "prometheus")

    initialize(art)

    art.configure_plugin("logger")
    art.configure_plugin("filedump")
    art.configure_plugin("reporter")
    art.configure_plugin("prometheus")
    art.fire_hook("start_session", run_id=run_id)

    # Stash this where slaves can find it
    # log.logger.info('artifactor listening on port %d', art_config['server_port'])


@click.command(help="Starts an artifactor server manually")
@click.option("--run-id", default=None)
@click.option("--port", default=None)
@click.option("--log-dir", default=None)
@click.option("--config", default=None)
def main(run_id, port, config, log_dir):
    """Main function for running artifactor server"""
    import sys

    port = port if port else _random_port()

    if config:
        with open(config, "r") as f:
            art_config = yaml.safe_load(f)
    else:
        try:
            with open("artifactor.yaml", "r") as f:
                art_config = yaml.safe_load(f)
        except IOError:
            print("Config file not declared and default (artifactor.yaml) not present, exiting.")
            sys.exit(127)

    log_dir = log_dir or art_config.get("log_dir", None)
    if not log_dir:
        print("Log dir not declared on cli or in config, exiting.")
        sys.exit(127)
    art_config["log_dir"] = log_dir
    art_config["server_port"] = int(port)

    try:
        run(art_config, run_id)
        print("Artifactor server running on port: ", port)
    except Exception as e:
        import traceback
        import sys

        with open(str(os.path.join(art_config["log_dir"], "artifactor_crash.log")), "w") as f:
            print(e, file=f)
            print(e, file=sys.stderr)
            tb = "\n".join(traceback.format_tb(sys.exc_traceback))
            print(tb, file=f)
            print(tb, file=sys.stderr)


if __name__ == "__main__":
    main()
