# -*- coding: utf-8 -*-
""" Reporter plugin for Artifactor

Add a stanza to the artifactor config like this,
artifactor:
    log_dir: /home/username/outdir
    per_run: test #test, run, None
    reuse_dir: True
    plugins:
        reporter:
            enabled: True
            plugin: reporter
            only_failed: False #Only show faled tests in the report
"""
import csv
import datetime
import math
import os
import re
import shutil
import time
from copy import deepcopy
from pathlib import Path

from iqe import artifactor
from iqe.artifactor import ArtifactorBasePlugin
from iqe.artifactor.utils import process_pytest_path
from jinja2 import Environment
from jinja2 import FileSystemLoader

TEMPLATE_PATH = Path(os.path.split(artifactor.__file__)[0], "templates")

_tests_tpl = {
    "_sub": {},
    "_stats": {"passed": 0, "failed": 0, "skipped": 0, "error": 0, "xpassed": 0, "xfailed": 0},
    "_duration": 0,
}

# Regexp, that finds all URLs in a string
# Does not cover all the cases, but rather only those we can
URL = re.compile(r"https?://[^/\s]+(?:/[^/\s?]+)*/?(?:\?(?:[^&\s=]+(?:=[^&\s]+)?&?)*)?")


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


class ReporterBase(object):
    def _run_report(
        self, old_artifacts, artifact_dir, run_type, run_id, version=None, fw_version=None
    ):
        if run_type == "run" and run_id:
            dir = str(os.path.join(artifact_dir, run_id))
        else:
            dir = artifact_dir
        template_data = self.process_data(old_artifacts, dir, version, fw_version)

        if hasattr(self, "only_failed") and self.only_failed:
            template_data["tests"] = [
                x for x in template_data["tests"] if x["outcomes"]["overall"] not in ["passed"]
            ]

        self.render_report(template_data, "report", dir, "test_report.html")

    def render_report(self, report, filename, log_dir, template):
        template_env = Environment(loader=FileSystemLoader(str(TEMPLATE_PATH)))
        data = template_env.get_template(template).render(**report)

        with open(os.path.join(log_dir, f"{filename}.html"), "w") as f:
            f.write(data)
        try:
            shutil.copytree(str(TEMPLATE_PATH / "dist"), os.path.join(log_dir, "dist"))
        except OSError:
            pass

    def process_data(self, artifacts, log_dir, version, fw_version, name_filter=None):
        blocker_skip_count = 0
        provider_skip_count = 0
        template_data = {"tests": [], "qa": []}
        template_data["version"] = version
        template_data["fw_version"] = fw_version
        log_dir = str(Path(log_dir)) + "/"
        counts = {"passed": 0, "failed": 0, "skipped": 0, "error": 0, "xfailed": 0, "xpassed": 0}
        current_counts = {
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "xfailed": 0,
            "xpassed": 0,
        }
        colors = {
            "passed": "success",
            "failed": "warning",
            "error": "danger",
            "xpassed": "danger",
            "xfailed": "success",
            "skipped": "info",
        }
        # Iterate through the tests and process the counts and durations
        for test_name, test in artifacts.items():
            if not test.get("statuses"):
                continue
            overall_status = overall_test_status(test["statuses"])
            counts[overall_status] += 1
            if not test.get("old", False):
                current_counts[overall_status] += 1
            color = colors[overall_status]
            # This was removed previously but is needed as the overall is not generated
            # until the test finishes. So this is here as a shim.
            test["statuses"]["overall"] = overall_status
            test_data = {
                "name": test_name,
                "outcomes": test["statuses"],
                "slaveid": test.get("slaveid", "Unknown"),
                "color": color,
            }
            if "composite" in test:
                test_data["composite"] = test["composite"]

            if "skipped" in test:
                if test["skipped"].get("type") == "provider":
                    provider_skip_count += 1
                    test_data["skip_provider"] = test["skipped"].get("reason")
                if test["skipped"].get("type") == "blocker":
                    blocker_skip_count += 1
                    test_data["skip_blocker"] = test["skipped"].get("reason")

            if "skip_blocker" in test_data:
                # Fix the inconveniently long list of repeated blockers until we sort out sets
                # in riggerlib somehow.
                test_data["skip_blocker"] = sorted(set(test_data["skip_blocker"]))

            if test.get("old", False):
                test_data["old"] = True

            if test.get("start_time"):
                if test.get("finish_time"):
                    test_data["in_progress"] = False
                    test_data["duration"] = test["finish_time"] - test["start_time"]
                else:
                    test_data["duration"] = time.time() - test["start_time"]
                    test_data["in_progress"] = True

            # Set up destinations for the files
            test_data["file_groups"] = []
            test_data["qa_contact"] = []
            processed_groups = {}
            order = 0
            for file_dict in test.get("files", []):
                group = file_dict["group_id"]
                if group not in processed_groups:
                    processed_groups[group] = (order, [])
                    order += 1
                processed_groups[group][-1].append(file_dict)
            # Current structure:
            # {groupid: (group_order, [{filedict1}, {filedict2}])}
            # Sorting by group_order
            processed_groups = sorted(processed_groups.items(), key=lambda kv: kv[1][0])
            # And now make it [(groupid, [{filedict1}, {filedict2}, ...])]
            processed_groups = [(group_name, files) for group_name, (_, files) in processed_groups]
            for group_name, file_dicts in processed_groups:
                group_file_list = []
                for file_dict in file_dicts:
                    if file_dict["file_type"] == "qa_contact":
                        with open(file_dict["os_filename"], "rb") as qafile:
                            qareader = csv.reader(qafile, delimiter=",", quotechar='"')
                            for qacontact in qareader:
                                test_data["qa_contact"].append(qacontact)
                                if qacontact[0] not in template_data["qa"]:
                                    template_data["qa"].append(qacontact[0])
                        continue  # Do not store, handled a different way :)
                    elif file_dict["file_type"] == "short_tb":
                        with open(file_dict["os_filename"], "r") as short_tb:
                            test_data["short_tb"] = short_tb.read()
                        continue
                    file_dict["filename"] = file_dict["os_filename"].replace(log_dir, "")
                    group_file_list.append(file_dict)

                test_data["file_groups"].append((group_name, group_file_list))
            # Snd remove groups that are left empty because of eg. traceback or qa contact
            test_data["file_groups"] = filter(
                lambda group: len(group[1]) > 0, test_data["file_groups"]
            )
            if "short_tb" in test_data and test_data["short_tb"]:
                urls = [url for url in URL.findall(test_data["short_tb"])]
                if urls:
                    test_data["urls"] = urls
            template_data["tests"].append(test_data)
        template_data["counts"] = counts
        template_data["current_counts"] = current_counts
        template_data["blocker_skip_count"] = blocker_skip_count
        template_data["provider_skip_count"] = provider_skip_count

        if name_filter:
            template_data["tests"] = [
                x
                for x in template_data["tests"]
                if re.findall(r"{}[-\]]+".format(name_filter), x["name"])  # Valid use of .format
            ]

        # Create the tree dict that is used for js tree
        # Note template_data['tests'] != tests
        tests = deepcopy(_tests_tpl)
        tests["_sub"]["tests"] = deepcopy(_tests_tpl)

        for test in template_data["tests"]:
            self.build_dict(test["name"].replace("iqe/", ""), tests, test)

        template_data["ndata"] = self.build_li(tests)

        for test in template_data["tests"]:
            if test.get("duration"):
                test["duration"] = str(datetime.timedelta(seconds=math.ceil(test["duration"])))

        return template_data

    def build_dict(self, path, container, contents):
        """
        Build a hierarchical dictionary including information about the stats at each level
        and the duration.
        """

        if isinstance(path, str):
            segs = process_pytest_path(path)
        else:
            segs = path

        head = segs[0]
        end = segs[1:]

        # If we are at the end node, ie a test.
        if not end:
            container["_sub"][head] = contents
            container["_stats"][contents["outcomes"]["overall"]] += 1
            container["_duration"] += contents["duration"]
        # If we are in a module.
        else:
            if head not in container["_sub"]:
                container["_sub"][head] = deepcopy(_tests_tpl)
            # Call again to recurse down the tree.
            self.build_dict(end, container["_sub"][head], contents)
            container["_stats"][contents["outcomes"]["overall"]] += 1
            container["_duration"] += contents["duration"]

    def build_li(self, lev):
        """
        Build up the actual HTML tree from the dict from build_dict
        """
        bimdict = {
            "passed": "success",
            "failed": "warning",
            "error": "danger",
            "skipped": "primary",
            "xpassed": "danger",
            "xfailed": "success",
        }
        list_string = "<ul>\n"
        for k, v in lev["_sub"].items():

            # If 'name' is an attribute then we are looking at a test (leaf).
            if "name" in v:
                pretty_time = str(datetime.timedelta(seconds=math.ceil(v["duration"])))
                teststring = '<span name="mod_lev" class="label label-primary">T</span>'
                label = '<span class="label label-{}">{}</span>'.format(
                    bimdict[v["outcomes"]["overall"]], v["outcomes"]["overall"].upper()
                )
                proc_name = process_pytest_path(v["name"])[-1]
                link = (
                    '<a href="#{}">{} {} {} <span style="color:#888888">'
                    "<em>[{}]</em></span></a>".format(
                        v["name"], proc_name, teststring, label, pretty_time
                    )
                )
                # Do we really need the os.path.split (now process_pytest_path) here?
                # For me it seems the name is always the leaf
                list_string += "<li>{}</li>\n".format(link)

            # If there is a '_sub' attribute then we know we have other modules to go.
            elif "_sub" in v:
                percenstring = ""
                bmax = 0
                for _, val in v["_stats"].items():
                    bmax += val
                # If there were any NON skipped tests, we now calculate the percentage which
                # passed.
                if bmax:
                    percen = "{:.2f}".format(
                        (float(v["_stats"]["passed"]) + float(v["_stats"]["xfailed"]))
                        / float(bmax)
                        * 100
                    )
                    if float(percen) == 100.0:
                        level = "passed"
                    elif float(percen) > 80.0:
                        level = "failed"
                    else:
                        level = "error"
                    percenstring = '<span name="blab" class="label label-{}">{}%</span>'.format(
                        bimdict[level], percen
                    )
                modstring = '<span name="mod_lev" class="label label-primary">M</span>'
                pretty_time = str(datetime.timedelta(seconds=math.ceil(v["_duration"])))
                list_string += (
                    "<li>{} {}<span>&nbsp;</span>"
                    '{}{}<span style="color:#888888">&nbsp;<em>[{}]'
                    "</em></span></li>\n"
                ).format(k, modstring, str(percenstring), self.build_li(v), pretty_time)
        list_string += "</ul>\n"
        return list_string


class Reporter(ArtifactorBasePlugin, ReporterBase):
    def plugin_initialize(self):
        self.register_plugin_hook("report_test", self.report_test)
        self.register_plugin_hook("finish_session", self.run_report)
        self.register_plugin_hook("build_report", self.run_report)
        self.register_plugin_hook("start_test", self.start_test)
        self.register_plugin_hook("skip_test", self.skip_test)
        self.register_plugin_hook("finish_test", self.finish_test)
        self.register_plugin_hook("session_info", self.session_info)
        self.register_plugin_hook("composite_pump", self.composite_pump)
        self.register_plugin_hook("tb_info", self.tb_info)

    def configure(self):
        self.only_failed = self.data.get("only_failed", False)
        self.configured = True

    @ArtifactorBasePlugin.check_configured
    def composite_pump(self, old_artifacts):
        return None, {"old_artifacts": old_artifacts}

    @ArtifactorBasePlugin.check_configured
    def skip_test(self, test_location, test_name, skip_data):
        test_ident = "{}/{}".format(test_location, test_name)
        return None, {"artifacts": {test_ident: {"skipped": skip_data}}}

    @ArtifactorBasePlugin.check_configured
    def start_test(self, test_location, test_name, metadata=None, param_dict=None, slaveid=None):
        if not param_dict:
            param_dict = {}
        test_ident = "{}/{}".format(test_location, test_name)
        return (
            None,
            {
                "artifacts": {
                    test_ident: {
                        "start_time": time.time(),
                        "slaveid": slaveid,
                        "metadata": metadata,
                        "params": param_dict,
                        "test_module": test_location,
                        "test_name": test_name,
                    }
                }
            },
        )

    @ArtifactorBasePlugin.check_configured
    def finish_test(self, artifacts, test_location, test_name, slaveid=None):
        test_ident = "{}/{}".format(test_location, test_name)
        overall_status = overall_test_status(artifacts[test_ident]["statuses"])
        return (
            None,
            {
                "artifacts": {
                    test_ident: {
                        "finish_time": time.time(),
                        "slaveid": slaveid,
                        "statuses": {"overall": overall_status},
                    }
                }
            },
        )

    @ArtifactorBasePlugin.check_configured
    def report_test(
        self,
        artifacts,
        test_location,
        test_name,
        test_xfail,
        test_when,
        test_outcome,
        test_phase_duration,
    ):
        test_ident = "{}/{}".format(test_location, test_name)
        ret_dict = {
            "artifacts": {
                test_ident: {
                    "statuses": {test_when: (test_outcome, test_xfail)},
                    "durations": {test_when: test_phase_duration},
                }
            }
        }
        return None, ret_dict

    @ArtifactorBasePlugin.check_configured
    def session_info(self, version=None, build=None, stream=None, fw_version=None):
        return (
            None,
            {"build": build, "stream": stream, "version": version, "fw_version": fw_version},
        )

    @ArtifactorBasePlugin.check_configured
    def tb_info(self, test_location, test_name, exception, file_line, short_tb):
        test_ident = "{}/{}".format(test_location, test_name)
        return (
            None,
            {
                "artifacts": {
                    test_ident: {
                        "exception": {
                            "file_line": file_line,
                            "exception": exception,
                            "short_tb": short_tb,
                        }
                    }
                }
            },
        )

    @ArtifactorBasePlugin.check_configured
    def run_report(
        self, old_artifacts, artifact_dir, per_run, run_id, version=None, fw_version=None
    ):
        self._run_report(old_artifacts, artifact_dir, per_run, run_id, version, fw_version)