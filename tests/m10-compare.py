#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare retained M10 campaigns without pooling; optionally audit raw evidence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import runpy
import statistics as stats

ANALYZE = runpy.run_path(str(Path(__file__).with_name("m10-analyze.py")))


def audit(original, primary, confirmation):
    result = {}
    originals = {p.name: p.read_bytes() for p in (original / "fio").iterdir()}
    copies = {p.name: p.read_bytes() for p in (primary / "fio").iterdir()}
    assert originals == copies, "resumed I/O differs from original evidence"
    result["byte_identical_reused_io_files"] = len(originals)
    for label, directory in (("primary", primary), ("confirmation", confirmation)):
        params, rows, sources = ANALYZE["validate_io"](directory)
        with (directory / "raw-results.csv").open(newline="") as stream:
            retained = list(csv.DictReader(stream))
        assert retained == [{k: str(v) for k, v in row.items()} for row in rows], "CSV differs from raw JSON"
        manifest = json.loads((directory / "source-sha256.json").read_text())
        for name, digest in manifest.items():
            assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == digest
        ratios, sync_occupancy = [], []
        for path in sources:
            if not path.name.endswith(".meta.json"):
                continue
            meta = json.loads(path.read_text())
            raw = json.loads(path.with_name(path.name.replace(".meta.json", ".json")).read_text())
            command = meta["command"]
            expected = {
                "bs": meta["bs"], "numjobs": meta["jobs"], "iodepth": 1,
                "size": meta["region_bytes"] // meta["jobs"],
                "offset_increment": meta["region_bytes"] // meta["jobs"],
                "runtime": params["runtime_s"], "ramp_time": params["ramp_s"],
                "direct": int(meta["target"] == "secureram"),
                "randseed": 10000 + meta["trial"], "ioengine": "psync",
            }
            assert all(f"--{key}={value}" in command for key, value in expected.items())
            for job in raw["jobs"]:
                occupancy = 0
                for direction in ("read", "write"):
                    data = job[direction]
                    if not data["total_ios"]:
                        continue
                    assert data["io_bytes"] == data["total_ios"] * meta["bs"]
                    # fio JSON bw_bytes is integral, IOPS is printed to six decimals.
                    assert abs(data["bw_bytes"] - data["iops"] * meta["bs"]) < 2
                    assert abs(data["bw_bytes"] - data["io_bytes"] * 1000 / data["runtime"]) < 2
                    occupancy += data["iops"] * data["lat_ns"]["mean"] / 1e9
                sync_occupancy.append(occupancy)
            if meta["target"] == "secureram":
                assert meta["before_stats"]["integrity_failures"] == meta["after_stats"]["integrity_failures"] == 0
                for direction in ("read", "write"):
                    measured = sum(j[direction]["io_bytes"] for j in raw["jobs"])
                    delta = meta["after_stats"][direction + "_bytes"] - meta["before_stats"][direction + "_bytes"]
                    assert delta >= measured
                    if measured:
                        ratios.append(delta / measured)
        result[label] = dict(trials=len(rows), hashed_inputs=len(manifest),
                             driver_over_measured_bytes_min=min(ratios),
                             driver_over_measured_bytes_max=max(ratios),
                             synchronous_latency_occupancy_min=min(sync_occupancy),
                             synchronous_latency_occupancy_max=max(sync_occupancy),
                             result="PASS")
    return result


def compare(directory, make_plots=False):
    samples, summaries = {}, []
    for campaign, subdir in (("primary", directory), ("confirmation", directory / "confirmation")):
        with (subdir / "raw-results.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        for target in ("secureram", "tmpfs"):
            for jobs in (1, 2, 4):
                selected = [r for r in rows if r["target"] == target and r["rw"] == "randread"
                            and int(r["bs"]) == 4096 and int(r["region_bytes"]) == 67108864
                            and int(r["jobs"]) == jobs]
                values = [float(r["mib_s"]) for r in selected]
                assert len(values) == (5 if campaign == "primary" else 3)
                samples[campaign, target, jobs] = values
                summaries.append(dict(campaign=campaign, target=target, jobs=jobs,
                                      **ANALYZE["describe"](values),
                                      cv_percent=100 * stats.stdev(values) / stats.mean(values)))
    ANALYZE["write_csv"](directory / "confirmation-comparison.csv", summaries)
    lines = ["# Separate random-read confirmation", "",
             "4 KiB, 64 MiB aggregate, psync depth 1 per job. MiB/s; all samples retained.",
             "Primary: 5 trials, 5+1 seconds; confirmation: 3 trials, 10+2 seconds (measurement+warmup).",
             "Different windows are not pooled. SD is sample standard deviation, not a confidence interval.", "",
             "| Campaign | Target | Jobs | n | Mean | Median | Min | Max | SD | CV % |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summaries:
        lines.append(f"| {r['campaign']} | {r['target']} | {r['jobs']} | {r['n']} | "
                     + " | ".join(f"{r[k]:.2f}" for k in ("mean", "median", "minimum", "maximum", "stdev", "cv_percent")) + " |")
    lines += ["", "## Individual SecureRAM samples (trial order)", ""]
    for campaign in ("primary", "confirmation"):
        for jobs in (1, 2, 4):
            lines.append(f"- {campaign}, {jobs} jobs: " + ", ".join(f"{v:.4f}" for v in samples[campaign, "secureram", jobs]) + " MiB/s.")
    (directory / "confirmation-comparison.md").write_text("\n".join(lines) + "\n")
    if make_plots:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.7))
        for ax, target in zip(axes, ("secureram", "tmpfs")):
            for index, campaign in enumerate(("primary", "confirmation")):
                color = ("#2166ac", "#b35806")[index]
                shift = (-.07, .07)[index]
                selected = [r for r in summaries if r["campaign"] == campaign and r["target"] == target]
                ax.plot([r["jobs"] + shift for r in selected], [r["median"] for r in selected],
                        marker="D", color=color, label=f"{campaign} median")
                for r in selected:
                    values = samples[campaign, target, r["jobs"]]
                    ax.scatter([r["jobs"] + shift] * len(values), values, color=color, alpha=.6, s=24)
            ax.set(title=f"{target} ({'direct' if target == 'secureram' else 'buffered'})",
                   xlabel="Synchronous jobs", ylabel="Throughput (MiB/s)", ylim=(0, None), xticks=[1, 2, 4])
            ax.grid(alpha=.2)
            ax.legend()
        fig.suptitle("Random read: every trial and median; 4 KiB, 64 MiB aggregate\nPrimary n=5 (5+1 s); confirmation n=3 (10+2 s); separate target scales")
        fig.tight_layout()
        output = directory / "figures"
        output.mkdir(exist_ok=True)
        for extension in ("svg", "png"):
            fig.savefig(output / ("confirmation." + extension), dpi=160)
        svg = output / "confirmation.svg"
        svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n",
                       encoding="utf-8", newline="\n")
        plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="retained primary CSV directory with confirmation/ subdirectory")
    parser.add_argument("--plots", action="store_true")
    parser.add_argument("--audit", nargs=3, type=Path, metavar=("ORIGINAL", "PRIMARY", "CONFIRMATION"))
    args = parser.parse_args()
    if args.audit:
        result = audit(*args.audit)
        (args.directory / "raw-audit.json").write_text(json.dumps(result, indent=2) + "\n")
    compare(args.directory, args.plots)
    print("PASS: separate campaign comparison" + (" and raw evidence audit" if args.audit else ""))
