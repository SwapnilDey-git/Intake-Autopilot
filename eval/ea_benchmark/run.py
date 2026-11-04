"""EA benchmark: score the whole pipeline (classify -> extract -> merge) against
the practice's own EA sheets, line by line, and compare with the previous run.

    python3 eval/ea_benchmark/run.py --corpus "<folder of client folders>" --label qwen-baseline
    python3 eval/ea_benchmark/run.py --corpus ... --folders 2,7,12 --label quick
    python3 eval/ea_benchmark/run.py --score-only --label rescore   # re-score what's loaded
    python3 eval/ea_benchmark/run.py --corpus ... --extra "<client folder or .zip>" --label x
    python3 eval/ea_benchmark/run.py --pin "<key>|2025" --fields name,stnr,hometown [--from-client 80]

Each client folder is imported as "BENCH <idx>-<hash>" (never its real name) and
removed again at the start of the next run -- real clients are never touched.
The answer keys (practice EA lines per folder+year) are FROZEN in labels.json on
the first run, so later runs are scored against the same truth even if the
classifier changes; --rebuild-labels refreshes them. labels.json and runs/ hold
real values and are gitignored; the console output is counts only.
"""
import argparse, base64, collections, datetime, hashlib, importlib.util, json, os, subprocess, sys, time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_DATA = os.environ.get("EA_BENCH_DATA") or (
    "/storage/ea_benchmark" if os.path.exists("/.dockerenv") and os.path.isdir("/storage") else HERE)
LABELS = os.path.join(_DATA, "labels.json")
# Person-checked answers for any EA-record field, per (folder key, year), plus the
# local paths of client folders that are not in the corpus (see helper.pinscore).
PINS = os.path.join(_DATA, "pins.json")
RUNS = os.path.join(_DATA, "runs")
BACKEND = os.environ.get("BACKEND_URL", "http://localhost:8080")
CONTAINER = "intake-backend"
# Inside the backend container (e.g. a Windows box with no host Python): run the
# helper directly instead of through docker. Corpus must then be under /storage.
IN_CONTAINER = os.path.exists("/.dockerenv") and os.path.isdir("/app")
LINES = ["Leistungserloese", "SV 9225", "Kleinmaterial 9100", "Provisionen 9190",
         "Abschreibung 9130", "Sonstiger Aufwand 9230", "Reisekosten 9160"]
STATUSES = ["match", "near", "wrong", "missing", "extra", "both_blank"]


def _importer():
    spec = importlib.util.spec_from_file_location("ipf", os.path.join(ROOT, "scripts", "import_person_folder.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def put_file(path, dest):
    """Make a host file visible to the helper at dest."""
    if IN_CONTAINER:
        import shutil
        shutil.copy(path, dest)
    else:
        subprocess.run(["docker", "cp", path, f"{CONTAINER}:{dest}"], check=True, capture_output=True)


def put_labels(path):
    put_file(path, "/tmp/ea_labels.json")


def helper(*args):
    """Run the in-container helper; return its JSON (the last JSON line -- some
    libraries print warnings to stdout)."""
    if IN_CONTAINER:
        cmd = [sys.executable, os.path.join(HERE, "helper.py"), *args]
    else:
        subprocess.run(["docker", "cp", os.path.join(HERE, "helper.py"), f"{CONTAINER}:/tmp/ea_bench_helper.py"],
                       check=True, capture_output=True)
        cmd = ["docker", "exec", CONTAINER, "python", "/tmp/ea_bench_helper.py", *args]
    out = subprocess.run(cmd, capture_output=True, text=True)
    lines = [l for l in out.stdout.splitlines() if l.startswith("{")]
    if out.returncode or not lines:
        sys.exit(f"helper {args[0]} failed: {out.stderr.strip()[-400:]}")
    return json.loads(lines[-1])


def load_pins():
    d = json.load(open(PINS)) if os.path.exists(PINS) else {}
    return {"sources": d.get("sources", {}), "pins": d.get("pins", {})}


def save_pins(d):
    os.makedirs(_DATA, exist_ok=True)
    with open(PINS, "w") as fh:
        json.dump(d, fh, indent=1, ensure_ascii=False)


def extra_key(path):
    """Key of a client folder/zip outside the corpus: 'x' + a path hash."""
    return "x" + hashlib.sha1(os.path.abspath(path).encode("utf-8")).hexdigest()[:7]


def collect_any(path):
    """A client folder, or a .zip of one read in memory (never extracted to disk)."""
    if os.path.isdir(path):
        return _importer().collect(path)
    import zipfile
    ipf, files = _importer(), []
    with zipfile.ZipFile(path) as zf:
        for n in zf.namelist():
            name = os.path.basename(n)
            if n.endswith("/") or not name or ipf._is_junk(name):
                continue
            files.append({"filename": name, "content_base64": base64.b64encode(zf.read(n)).decode("ascii")})
    return files


def post_case(key, files):
    payload = {"source": "folder-import", "external_ref": f"bench::{key}", "client_name": f"BENCH {key}",
               "subject": f"Benchmark {key}", "files": files}
    req = urllib.request.Request(BACKEND + "/api/intake/case", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        res = json.load(r)
    print(f"  imported {key}: {res.get('documents')} docs, {res.get('primaries')} to extract")


def in_scope(key, only):
    """A subset run scores only the corpus folders it loaded; extras always."""
    return key.startswith("x") or only is None or int(key[:2]) in only


def folders(corpus, only):
    subs = sorted(d for d in os.listdir(corpus) if os.path.isdir(os.path.join(corpus, d)))
    for i, d in enumerate(subs):
        if only is None or i in only:
            yield i, d, f"{i:02d}-{hashlib.sha1(d.encode('utf-8')).hexdigest()[:8]}"


def import_all(corpus, only, extras):
    ipf = _importer()
    if corpus:
        for i, d, key in folders(corpus, only):
            post_case(key, ipf.collect(os.path.join(corpus, d)))
    for key, path in extras.items():
        if not os.path.exists(path):
            print(f"  {key}: source missing on this machine -- skipped")
            continue
        post_case(key, collect_any(path))


def wait(stall_min):
    start = time.time()
    while True:
        s = helper("status")
        age = s["last_event_age_s"]
        print(f"  [{int(time.time() - start) // 60:3d} min] pending={s['pending']} extracted={s['extracted']} "
              f"failed={sum(s['failed'].values())}", flush=True)
        if s["pending"] == 0:
            return s, True
        quiet = age if age is not None else time.time() - start
        if quiet > stall_min * 60:
            print(f"  no extraction for {stall_min} min -- scoring what finished (run marked INCOMPLETE)")
            return s, False
        time.sleep(30)


def summarise(results):
    tally = {ln: collections.Counter() for ln in LINES}
    by_src = collections.Counter()
    no_source = []
    for r in results:
        if not r["has_source"]:
            no_source.append(r["key"])
            continue
        for ln in LINES:
            L = r["lines"][ln]
            tally[ln][L["status"]] += 1
            if L["status"] not in ("match", "both_blank"):
                by_src[(ln, L["status"], L["src"])] += 1
    acc = {}
    for ln in LINES:
        n = sum(tally[ln].values())
        acc[ln] = (tally[ln]["match"] + tally[ln]["both_blank"]) / n if n else None
    tot = sum(sum(t.values()) for t in tally.values())
    ok = sum(t["match"] + t["both_blank"] for t in tally.values())
    return {"tally": {k: dict(v) for k, v in tally.items()}, "accuracy": acc,
            "overall": ok / tot if tot else None, "scored_years": len(results) - len(no_source),
            "no_source_years": no_source,
            "non_matches": [[ln, st, src, n] for (ln, st, src), n in by_src.most_common()]}


def summarise_pins(results):
    tally = collections.defaultdict(collections.Counter)
    for r in results:
        for path, f in r["fields"].items():
            tally[path][f["status"]] += 1
    n = sum(sum(t.values()) for t in tally.values())
    ok = sum(t["match"] for t in tally.values())
    return {"tally": {k: dict(v) for k, v in sorted(tally.items())}, "overall": ok / n if n else None,
            "years": len(results)}


def statuses(run):
    """{(key, line_or_field): status} of a stored run, for the regression diff."""
    out = {}
    for r in run.get("results") or []:
        if r.get("has_source"):
            for ln, L in r["lines"].items():
                out[(r["key"], ln)] = L["status"]
    for r in run.get("pin_results") or []:
        for path, f in r["fields"].items():
            out[(r["key"], "pin:" + path)] = f["status"]
    return out


def regressions(prev_run, run):
    good = ("match", "both_blank")
    a, b = statuses(prev_run), statuses(run)
    worse = sorted(k for k in a.keys() & b.keys() if a[k] in good and b[k] not in good)
    better = sorted(k for k in a.keys() & b.keys() if a[k] not in good and b[k] in good)
    return worse, better, {k: (a[k], b[k]) for k in worse}


def show_pins(ps, prev):
    if not ps["years"]:
        return
    print(f"\npinned fields (person-checked answers), client-years: {ps['years']}")
    print(f"{'field':28s}{'match':>8s}{'wrong':>8s}{'missing':>9s}")
    for path, t in ps["tally"].items():
        print(f"{path:28s}{t.get('match', 0):>8d}{t.get('wrong', 0):>8d}{t.get('missing', 0):>9d}")
    o, po = ps["overall"], (prev or {}).get("overall")
    if o is not None:
        print(f"{'PINNED OVERALL':28s}{o:>8.0%}" + (f"   {(o - po) * 100:+.0f} pt" if po is not None else ""))


def show(summary, prev):
    print(f"\nscored client-years: {summary['scored_years']}   "
          f"(skipped, no source docs for that year: {len(summary['no_source_years'])})")
    print(f"{'line':24s}" + "".join(f"{s:>11s}" for s in STATUSES) + "   accuracy   vs prev")
    for ln in LINES:
        t, a = summary["tally"][ln], summary["accuracy"][ln]
        pa = (prev or {}).get("accuracy", {}).get(ln)
        delta = f"{(a - pa) * 100:+6.0f} pt" if a is not None and pa is not None else ""
        print(f"{ln:24s}" + "".join(f"{t.get(s, 0):>11d}" for s in STATUSES)
              + (f"   {a:7.0%}" if a is not None else "        -") + f"   {delta}")
    o, po = summary["overall"], (prev or {}).get("overall")
    print(f"{'OVERALL':24s}" + " " * 66 + (f"   {o:7.0%}" if o is not None else "")
          + (f"   {(o - po) * 100:+6.0f} pt" if o is not None and po is not None else ""))
    if summary["non_matches"]:
        print("\nnon-matches by (line, status, our source doc type):")
        for ln, st, src, n in summary["non_matches"]:
            print(f"  {n:3d}  {ln:24s} {st:8s} src={src}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", help="folder whose sub-folders are one client each")
    ap.add_argument("--folders", help="comma-separated folder indexes (default: all)")
    ap.add_argument("--label", default="run", help="name for this run, e.g. the model or prompt change")
    ap.add_argument("--stall-min", type=float, default=15, help="give up waiting after N quiet minutes")
    ap.add_argument("--rebuild-labels", action="store_true", help="re-freeze answer keys from the sheets")
    ap.add_argument("--score-only", action="store_true", help="don't import; score what's loaded")
    ap.add_argument("--extra", action="append", default=[],
                    help="a client folder or .zip outside the corpus (remembered in pins.json)")
    ap.add_argument("--no-extras", action="store_true", help="skip the remembered extra folders")
    ap.add_argument("--pin", help="'<key>|<year>': freeze the current values of --fields as checked answers")
    ap.add_argument("--fields", help="comma-separated EA fields for --pin (e.g. name,stnr,reisekosten.km_note)")
    ap.add_argument("--from-client", type=int, help="with --pin: read the values off this client id "
                    "instead of the BENCH client of that key")
    a = ap.parse_args()
    only = {int(x) for x in a.folders.split(",")} if a.folders else None

    pins = load_pins()
    for path in a.extra:
        if not os.path.exists(path):
            sys.exit(f"--extra {path!r} does not exist")
        pins["sources"][extra_key(path)] = os.path.abspath(path)
    if a.extra:
        save_pins(pins)

    if a.pin:
        return pin(a, pins)

    complete, status = True, None
    if not a.score_only:
        if a.corpus and not os.path.isdir(a.corpus):
            sys.exit("--corpus must be the folder that holds the client folders")
        if not a.corpus and (a.no_extras or not pins["sources"]):
            sys.exit("nothing to import: give --corpus and/or --extra")
        print("cleanup of previous benchmark data:", helper("cleanup"))
        print("importing:")
        import_all(a.corpus, only, {} if a.no_extras else pins["sources"])
        print("waiting for extraction:")
        status, complete = wait(a.stall_min)

    labels = {} if a.rebuild_labels or not os.path.exists(LABELS) else json.load(open(LABELS))
    os.makedirs(RUNS, exist_ok=True)  # also creates _DATA
    empty = os.path.join(RUNS, ".empty_labels.json")
    with open(empty, "w") as fh:
        fh.write("{}")
    put_labels(LABELS if labels else empty)
    first = helper("score", "/tmp/ea_labels.json")
    new = {k: v for k, v in first["built_labels"].items() if k not in labels}
    if new:
        labels.update(new)
        with open(LABELS, "w") as fh:
            json.dump(labels, fh, indent=1, ensure_ascii=False)
        print(f"\nfroze {len(new)} new answer key(s) into labels.json ({len(labels)} total)")
        put_labels(LABELS)
        first = helper("score", "/tmp/ea_labels.json")
    first["results"] = [r for r in first["results"] if in_scope(r["key"].split("|")[0], only)]

    pin_file = os.path.join(RUNS, ".pins_only.json")
    with open(pin_file, "w") as fh:
        json.dump(pins["pins"], fh, ensure_ascii=False)
    put_file(pin_file, "/tmp/ea_pins.json")
    os.remove(pin_file)
    pin_results = [r for r in helper("pinscore", "/tmp/ea_pins.json")["results"]
                   if in_scope(r["key"].split("|")[0], only)]
    pin_summary = summarise_pins(pin_results)

    summary = summarise(first["results"])
    os.makedirs(RUNS, exist_ok=True)
    # Compare with the last run over the SAME folders -- a subset run against a
    # full run would read every unloaded folder as a change.
    scope = sorted(only) if only else "all"
    extras = [] if a.no_extras else sorted(pins["sources"])
    prev_run, prev_desc = None, None
    for f in sorted((f for f in os.listdir(RUNS) if f.endswith(".json")), reverse=True):
        old = json.load(open(os.path.join(RUNS, f)))
        if old.get("folders") == scope and old.get("extras", []) == extras:
            prev_run, prev_desc = old, f
            break
    prev = (prev_run or {}).get("summary")
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run = {"label": a.label, "at": ts, "complete": complete, "folders": scope, "extras": extras,
           "status": status, "summary": summary, "results": first["results"],
           "pin_summary": pin_summary, "pin_results": pin_results}
    path = os.path.join(RUNS, f"{ts}_{a.label}.json")
    with open(path, "w") as fh:
        json.dump(run, fh, indent=1, ensure_ascii=False, default=str)
    show(summary, prev)
    show_pins(pin_summary, (prev_run or {}).get("pin_summary"))
    worse = []
    if prev_run:
        print(f"\n(compared with {prev_desc})")
        worse, better, how = regressions(prev_run, run)
        for k in better:
            print(f"  fixed      {k[0]:22s} {k[1]}")
        for k in worse:
            print(f"  REGRESSED  {k[0]:22s} {k[1]}  ({how[k][0]} -> {how[k][1]})")
        if not worse and not better:
            print("  no line changed status")
    else:
        print("\n(no earlier run over the same folders -- this one is the baseline)")
    if not complete:
        print("\nINCOMPLETE run: some documents were still unread -- treat the numbers as a lower bound.")
    print(f"\nfull run with values (gitignored): {os.path.relpath(path, ROOT)}")
    if worse and complete:
        sys.exit(2)  # a change that breaks a line that used to match does not ship


def pin(a, pins):
    """Freeze checked values as answers. Values go straight into the gitignored
    pins.json; the console shows only which fields were pinned."""
    if "|" not in a.pin or not a.fields:
        sys.exit("--pin needs '<key>|<year>' and --fields")
    key, year = a.pin.split("|")
    cid = a.from_client
    if cid is None:
        cid = helper("benchclient", key).get("client_id")
        if cid is None:
            sys.exit(f"no BENCH client for {key} -- run the benchmark first or pass --from-client")
    got = helper("pinseed", str(cid), year, a.fields)
    if got["absent"]:
        print("not pinned (no value on the record -- check it, then fill it in the dashboard first):",
              ", ".join(got["absent"]))
    pins["pins"].setdefault(f"{key}|{year}", {}).update(got["pins"])
    save_pins(pins)
    print(f"pinned {len(got['pins'])} field(s) for {key}|{year}: {', '.join(got['pins'])}")


if __name__ == "__main__":
    main()
