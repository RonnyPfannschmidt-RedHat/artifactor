""" Logger plugin for Artifactor

Add a stanza to the artifactor config like this,
artifactor:
    log_dir: /home/username/outdir
    per_run: test #test, run, None
    overwrite: True
    plugins:
        logger:
            enabled: True
            plugin: logger
            level: DEBUG
"""
import requests
from iqe.artifactor import ArtifactorBasePlugin


def overall_test_status(statuses):
    # Handle some logic for when to count certain tests as which state
    for when, status in statuses.items():
        if when == "call" and status[1] and status[0] == "skipped":
            return "xfailed"
        elif when == "call" and status[1] and status[0] == "failed":
            return "xpassed"
        elif (when == "setup" or when == "teardown") and status[0] == "failed":
            return "error"
        elif status[0] == "skipped":
            return "skipped"
        elif when == "call" and status[0] == "failed":
            return "failed"
    return "passed"


class Prometheus(ArtifactorBasePlugin):
    class Test(object):
        def __init__(self, ident):
            self.ident = ident
            self.in_progress = False

    def plugin_initialize(self):
        self.register_plugin_hook("start_test", self.start_test)
        self.register_plugin_hook("prometheus_finish_test", self.finish_test)

    def configure(self):
        self.configured = True
        self.host = self.data.get("host", "127.0.0.1")
        self.port = self.data.get("port", "5000")

    @ArtifactorBasePlugin.check_configured
    def start_test(self, artifact_path, test_name, test_location, slaveid=None):
        if not slaveid:
            slaveid = "Master"
        test_ident = "{}{}".format(test_location, test_name)
        if slaveid in self.store:
            if self.store[slaveid].in_progress:
                print("Test already running, can't start another, logger")
                return None
        self.store[slaveid] = self.Test(test_ident)
        self.store[slaveid].in_progress = True

    @ArtifactorBasePlugin.check_configured
    def finish_test(
        self, artifacts, log_dir, test_name, test_location, slaveid=None, prometheus=False
    ):
        test_ident = "{}/{}".format(test_location, test_name)
        if not slaveid:
            slaveid = "Master"
        self.store[slaveid].in_progress = False
        test_data = artifacts[test_ident]
        try:
            duration = test_data["finish_time"] - test_data["start_time"]
        except Exception as e:
            print(e)
            duration = 0.0
        if prometheus:
            try:
                requests.get(
                    "http://{}:{}/add_metric/{}/{}/{}".format(
                        self.host,
                        self.port,
                        test_name,
                        overall_test_status(artifacts[test_ident]["statuses"]),
                        duration,
                    )
                )
            except requests.exceptions.ConnectionError:
                return
