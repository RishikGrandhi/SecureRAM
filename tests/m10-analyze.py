#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Recompute M10 statistics from every raw trial; optional matplotlib figures."""
import argparse
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics as stats

MIB = 1048576
KEYS = ("target", "rw", "bs", "region_bytes", "jobs")
METRICS = ("mib_s", "iops", "latency_us", "fio_cpu_core_pct", "guest_busy_pct", "guest_steal_pct", "elapsed_s")


def describe(values):
    return dict(n=len(values), mean=stats.mean(values), median=stats.median(values),
                minimum=min(values), maximum=max(values), stdev=stats.stdev(values) if len(values) > 1 else 0)


def parse_trial(meta, result):
    assert meta["status"] == "PASS", "incomplete/failed trial retained; cannot report acceptance"
    jobs = result["jobs"]
    assert len(jobs) == meta["jobs"] and all(j["error"] == 0 for j in jobs)
    row = {key: meta[key] for key in (*KEYS, "trial")}
    directions = [j[d] for j in jobs for d in ("read", "write") if j[d]["total_ios"]]
    count = sum(d["total_ios"] for d in directions)
    assert count > 0
    row.update(mib_s=sum(d["bw_bytes"] for d in directions) / MIB,
               iops=sum(d["iops"] for d in directions),
               latency_us=sum(d["lat_ns"]["mean"] * d["total_ios"] for d in directions) / count / 1000,
               fio_cpu_core_pct=sum(j["usr_cpu"] + j["sys_cpu"] for j in jobs),
               elapsed_s=(meta["after"]["monotonic_ns"] - meta["before"]["monotonic_ns"]) / 1e9)
    cpu = [b - a for a, b in zip(meta["before"]["cpu"], meta["after"]["cpu"])]
    total = sum(cpu)
    assert total > 0
    row["guest_busy_pct"] = 100 * sum(cpu[i] for i in (0, 1, 2, 5, 6)) / total
    row["guest_steal_pct"] = 100 * cpu[7] / total
    assert all(meta["after"][k] == meta["before"][k] for k in ("pswpin", "pswpout"))
    return row


def write_csv(path, rows):
    assert rows
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_io(directory):
    params = json.loads((directory / "parameters.json").read_text())
    rows, sources = [], []
    for path in sorted((directory / "fio").glob("*.meta.json")):
        data = path.with_name(path.name.replace(".meta.json", ".json"))
        rows.append(parse_trial(json.loads(path.read_text()), json.loads(data.read_text())))
        sources.extend((path, data))
    expected = {(target, *case, trial) for case in params["configurations"]
                for target in ("secureram", "tmpfs") for trial in range(1, params["trials"] + 1)}
    actual = [tuple(row[k] for k in (*KEYS, "trial")) for row in rows]
    assert len(actual) == len(set(actual)) and set(actual) == expected, "missing/duplicate/unplanned trials"
    return params, rows, sources


def analyze(directory, io_only=False):
    params, rows, sources = validate_io(directory)
    write_csv(directory / "raw-results.csv", rows)
    groups = defaultdict(list)
    for row in rows:
        groups[tuple(row[k] for k in KEYS)].append(row)
    summaries = []
    for key, group in sorted(groups.items()):
        for metric in METRICS:
            summaries.append(dict(zip(KEYS, key), metric=metric, **describe([r[metric] for r in group])))
    write_csv(directory / "summary.csv", summaries)
    life = []
    for path in sorted(directory.glob("lifecycle-*.json")):
        sources.append(path)
        records = json.loads(path.read_text())
        assert len(records) == params["trials"] and all(r["status"] == "PASS" for r in records)
        assert {r["trial"] for r in records} == set(range(1, params["trials"] + 1))
        life.extend(records)
    if not io_only:
        assert {r["capacity_bytes"] for r in life} == {params["capacity_mib"] * MIB // 4, params["capacity_mib"] * MIB}
    if life:
        write_csv(directory / "lifecycle-raw.csv", life)
    life_summary = []
    for capacity in sorted({r["capacity_bytes"] for r in life}):
        for metric in ("load_cli_ms", "create_ms", "restore_ms", "delete_ms", "destroy_with_snapshot_ms", "lock_unlock_pair_ms"):
            life_summary.append(dict(capacity_bytes=capacity, metric=metric,
                                     **describe([r[metric] for r in life if r["capacity_bytes"] == capacity])))
    if life_summary:
        write_csv(directory / "lifecycle-summary.csv", life_summary)
    # One paired ratio per matching trial, not a ratio of differently weighted samples.
    lookup = {tuple(r[k] for k in (*KEYS, "trial")): r for r in rows}
    ratios = []
    for case in params["configurations"]:
        values = [lookup[("tmpfs", *case, trial)]["mib_s"] / lookup[("secureram", *case, trial)]["mib_s"]
                  for trial in range(1, params["trials"] + 1)]
        ratios.append(dict(zip(KEYS[1:], case), metric="tmpfs_over_secureram_throughput_ratio", **describe(values)))
    write_csv(directory / "comparison.csv", ratios)
    memory = []
    for capacity in sorted({r["capacity_bytes"] for r in life}):
        memory.append(dict(capacity_bytes=capacity, tag_bytes=capacity // 128,
                           staging_bytes=8192, live_payload_bytes=capacity + capacity // 128 + 8192,
                           snapshot_payload_bytes=2 * (capacity + capacity // 128) + 8192))
    if memory:
        write_csv(directory / "memory.csv", memory)
    throughput = [r for r in summaries if r["metric"] == "mib_s" and r["target"] == "secureram"]
    fastest, slowest = max(throughput, key=lambda r: r["mean"]), min(throughput, key=lambda r: r["mean"])
    lines = ["# M10 machine-derived results", "", f"{len(rows)} I/O trials; {params['trials']} per configuration. All retained.",
             "", "Means below use sample standard deviation; no exclusions. MiB = 1048576 bytes.", ""]
    for label, row in (("Fastest SecureRAM", fastest), ("Slowest SecureRAM", slowest)):
        lines.append(f"{label}: {row['rw']}, {row['bs']//1024} KiB, {row['region_bytes']//MIB} MiB region, {row['jobs']} jobs: {row['mean']:.2f} MiB/s (SD {row['stdev']:.2f}).")
    lines += ["", "| Target | Workload | KiB | Region MiB | Jobs | Mean MiB/s | SD | Mean us | Guest busy % |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    smap = {(tuple(r[k] for k in KEYS), r["metric"]): r for r in summaries}
    for key in sorted(groups):
        r = smap[(key, "mib_s")]
        lines.append(f"| {key[0]} | {key[1]} | {key[2]//1024} | {key[3]//MIB} | {key[4]} | {r['mean']:.2f} | {r['stdev']:.2f} | {smap[(key,'latency_us')]['mean']:.2f} | {smap[(key,'guest_busy_pct')]['mean']:.2f} |")
    lines += ["", "## Comparison and scaling", "", "Paired tmpfs/SecureRAM throughput ratios include filesystem/direct-mode and block-stack differences. They do not isolate encryption or HMAC."]
    for row in ratios:
        lines.append(f"- {row['rw']} {row['bs']//1024} KiB / {row['region_bytes']//MIB} MiB / {row['jobs']} jobs: {row['mean']:.2f}x (SD {row['stdev']:.2f}).")
    capacity = params["capacity_mib"] * MIB
    for rw in ("randread", "randwrite"):
        scale = [(key[4], smap[(key, "mib_s")]["mean"]) for key in groups if key[:4] == ("secureram", rw, 4096, capacity)]
        scale.sort()
        if not scale:
            continue
        best = max(scale, key=lambda pair: pair[1])
        lines.append(f"{rw}: " + ", ".join(f"{jobs} jobs {rate:.2f} MiB/s ({rate/scale[0][1]:.2f}x 1-job)" for jobs, rate in scale) + f". Highest observed mean at {best[0]} jobs; this is not a proven global saturation point.")
    lines += ["", "## Lifecycle (milliseconds)", "", "| Capacity MiB | Operation | n | Mean | Median | Min | Max | SD |", "|---:|---|---:|---:|---:|---:|---:|---:|"]
    for row in life_summary:
        lines.append(f"| {row['capacity_bytes']//MIB} | {row['metric']} | {row['n']} | {row['mean']:.4f} | {row['median']:.4f} | {row['minimum']:.4f} | {row['maximum']:.4f} | {row['stdev']:.4f} |")
    lines += ["", "## Variability and limitations", "", "Throughput CV >10% configurations (retained, no exclusions):"]
    noisy = [r for r in summaries if r["metric"] == "mib_s" and r["stdev"] / r["mean"] > .1]
    lines += [f"- {r['target']} {r['rw']} {r['bs']} bytes, region {r['region_bytes']}, {r['jobs']} jobs: CV {100*r['stdev']/r['mean']:.1f}%" for r in noisy] or ["None."]
    lines += ["", "Snapshot create allocates/copies the whole ciphertext/tag pair; restore copies it; delete wipes/frees it. Load includes CLI startup, protected randomness, key setup and whole-medium authenticated-zero initialization. Destroy timing includes a populated snapshot. Lock/unlock is a batch mean for a pair, not isolated syscall latency.",
              "", "Guest CPU uses /proc/stat deltas over fio startup, ramp and measurement, excluding later validation. It includes kernel worker and unrelated guest work. fio CPU excludes the asynchronous kernel worker. No per-crypto CPU attribution is supported. Guest steal may underreport host contention in VirtualBox. No swap deltas were accepted. Host observations and short virtualized windows limit precision.",
              "", "Memory CSV accounts ciphertext, tags, snapshot and two staging buffers only; kernel metadata, provider context, allocator rounding and page tables are extra. No exact resident memory claim is made.",
              "", "Sequential IOPS are retained in CSV but throughput is the primary interpretation. Mean latency is weighted by operation counts, not an average of percentiles. Timed loops reuse initialized regions; working-set size is distinct from total bytes transferred. All security guarantees remain those of M9."]
    (directory / "analysis.md").write_text("\n".join(lines) + "\n")
    manifest = {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    (directory / "source-sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return summaries, life_summary, params


def plots(directory, summaries, life, params):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    output = directory / "figures"
    output.mkdir(exist_ok=True)
    cap = params["capacity_mib"] * MIB
    def finish(fig, name):
        fig.tight_layout()
        fig.savefig(output / (name + ".svg"))
        fig.savefig(output / (name + ".png"), dpi=160)
        plt.close(fig)
    def series(ax, target, rw, bs, field, metric, label):
        rows = [r for r in summaries if r["target"] == target and r["rw"] == rw and r["bs"] == bs and r["metric"] == metric
                and (r["jobs"] == 1 if field == "region_bytes" else r["region_bytes"] == cap)]
        rows.sort(key=lambda r: r[field])
        ax.errorbar([r[field]/MIB if field == "region_bytes" else r[field] for r in rows],
                    [r["mean"] for r in rows], yerr=[r["stdev"] for r in rows], marker="o", capsize=4, label=label)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, rw in zip(axes, ("read", "write")):
        for bs in (4096, 131072):
            series(ax, "secureram", rw, bs, "region_bytes", "mib_s", f"{bs//1024} KiB request")
        ax.set(title=f"SecureRAM sequential {rw}", xlabel="Working region (MiB)", ylabel="Throughput (MiB/s)", ylim=(0, None))
        ax.legend(); ax.grid(alpha=.2)
    fig.suptitle(f"Raw direct I/O, 1 psync job; mean ± sample SD, n={params['trials']}")
    finish(fig, "sequential")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for row_axes, target in zip(axes, ("secureram", "tmpfs")):
        for ax, rw in zip(row_axes, ("randread", "randwrite")):
            series(ax, target, rw, 4096, "jobs", "mib_s", target)
            ax.set(title=f"{target}: {rw}", xlabel="Synchronous jobs (depth 1 each)", ylabel="Throughput (MiB/s)", ylim=(0, None))
            ax.legend(); ax.grid(alpha=.2)
    fig.suptitle(f"4 KiB, {cap//MIB} MiB aggregate; SecureRAM direct vs tmpfs buffered; mean ± SD")
    finish(fig, "concurrency-baseline")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, metric, title in zip(axes, ("mib_s", "guest_busy_pct"), ("Throughput (MiB/s)", "Whole guest busy (%)")):
        workloads = ("read", "write", "randread", "randwrite", "randrw")
        for index, target in enumerate(("secureram", "tmpfs")):
            rows = [next(r for r in summaries if r["target"] == target and r["rw"] == rw and r["bs"] == (131072 if rw in ("read", "write") else 4096)
                         and r["region_bytes"] == cap and r["jobs"] == 1 and r["metric"] == metric) for rw in workloads]
            ax.bar([x + (index-.5)*.36 for x in range(5)], [r["mean"] for r in rows], .36, yerr=[r["stdev"] for r in rows], capsize=3, label=target)
        ax.set_xticks(range(5), workloads, rotation=20)
        ax.set(ylabel=title, ylim=(0, 100 if metric == "guest_busy_pct" else None))
        ax.legend(); ax.grid(axis="y", alpha=.2)
    fig.suptitle(f"1 job, {cap//MIB} MiB; sequential 128 KiB / random 4 KiB / mixed 70% read")
    finish(fig, "baseline-cpu")
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for ax, metrics in zip(axes, (("create_ms", "restore_ms", "delete_ms"), ("load_cli_ms", "destroy_with_snapshot_ms"))):
        for metric in metrics:
            rows = sorted((r for r in life if r["metric"] == metric), key=lambda r: r["capacity_bytes"])
            ax.errorbar([r["capacity_bytes"]/MIB for r in rows], [r["mean"] for r in rows], yerr=[r["stdev"] for r in rows], marker="o", capsize=4, label=metric)
        ax.set(xlabel="Configured capacity (MiB)", ylabel="Elapsed time (ms)", ylim=(0, None))
        ax.legend(); ax.grid(alpha=.2)
    fig.suptitle(f"Full ciphertext/tag snapshot and key lifecycle; mean ± sample SD, n={params['trials']}")
    finish(fig, "lifecycle")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--plots", action="store_true", help="render SVG/PNG using installed matplotlib")
    parser.add_argument("--plot-csv", action="store_true", help="render retained summary CSV without the bulk raw archive")
    parser.add_argument("--io-only", action="store_true", help="analyze the separate random-read confirmation only")
    args = parser.parse_args()
    if args.plot_csv:
        def table(name):
            with (args.directory / name).open(newline="") as stream:
                rows = list(csv.DictReader(stream))
            for row in rows:
                for key, value in row.items():
                    if key not in ("target", "rw", "metric"):
                        row[key] = float(value) if key in ("mean", "median", "minimum", "maximum", "stdev") else int(value)
            return rows
        result = (table("summary.csv"), table("lifecycle-summary.csv"),
                  json.loads((args.directory / "parameters.json").read_text()))
    else:
        result = analyze(args.directory, io_only=args.io_only)
    if args.plots or args.plot_csv:
        plots(args.directory, *result)
    print("PASS: retained CSV figures regenerated" if args.plot_csv else
          "PASS: raw trial completeness, statistics and requested outputs")
