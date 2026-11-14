"""logcanary command line.

  logcanary lab-up                 build the host image, start the lab, install the ES template
  logcanary lab-down               stop and remove the lab containers (volumes kept)
  logcanary run COND [-n N]        run N repeats of one condition (resumes)
  logcanary matrix [--group G]     run every condition (default set first, then tuned)
  logcanary reconcile              re-query Elasticsearch for every run and recompute results
  logcanary report                 aggregate results into results/*.csv and results/table.md
  logcanary figures                draw docs/img/*.png
  logcanary summary                write results/summary.json
  logcanary list                   show the matrix and how many repeats are done
"""

from __future__ import annotations

import argparse
import os
import sys


def lab_up() -> None:
    from logcanary import lab

    build = ["docker", "build", "-q", "--network", "host", "-t", "logcanary-host:noble"]
    if os.environ.get("https_proxy"):
        build += ["--build-arg", f"https_proxy={os.environ['https_proxy']}"]
    lab.sh(*build, str(lab.LAB / "host"), timeout=1800)
    lab.compose("up", "-d", "es")
    lab.es_up()
    lab.install_es_assets()
    lab.compose("up", "-d", "host")
    lab.compose("up", "-d", "filebeat", "fluentbit", "vector", env={"SHIPPER_SET": "default"})
    print("lab up")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="logcanary", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lab-up")
    sub.add_parser("lab-down")
    r = sub.add_parser("run")
    r.add_argument("cond")
    r.add_argument("-n", "--repeats", type=int)
    m = sub.add_parser("matrix")
    m.add_argument("--group")
    sub.add_parser("reconcile")
    sub.add_parser("report")
    sub.add_parser("figures")
    sub.add_parser("summary")
    sub.add_parser("list")
    a = ap.parse_args(argv)

    if a.cmd == "lab-up":
        lab_up()
    elif a.cmd == "lab-down":
        from logcanary import lab

        lab.compose("down")
    elif a.cmd == "run":
        from logcanary import runner
        from logcanary.conditions import ALL

        runner.run_condition(ALL[a.cond], a.repeats)
    elif a.cmd == "matrix":
        from logcanary import runner
        from logcanary.conditions import MATRIX, TUNED

        for c in MATRIX + TUNED:
            if a.group is None or c.group == a.group:
                runner.run_condition(c)
    elif a.cmd == "reconcile":
        from logcanary import report

        report.reconcile_all()
    elif a.cmd == "report":
        from logcanary import report

        report.main()
    elif a.cmd == "figures":
        from logcanary import figures

        figures.main()
    elif a.cmd == "summary":
        from logcanary import summary

        summary.main()
    elif a.cmd == "list":
        from logcanary import runner
        from logcanary.conditions import MATRIX, TUNED

        for c in MATRIX + TUNED:
            print(f"{c.name:24} {runner.done_repeats(c)}/{c.repeats}  {c.title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
