"""Tracking Marks reel pipeline.

  python -m pipeline reel   RAW.mp4 [--script script.txt]   transcribe, plan and render in one go
  python -m pipeline plan   RAW.mp4 [--script script.txt]   write RAW.plan.json for review
  python -m pipeline render PLAN.json                        render a (reviewed) plan

Exports land in <project>/exports when the raw clip sits in <project>/raw, otherwise next to the clip.
"""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python pipeline/main.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "pipeline"


def _project_dirs(raw: Path, name: str):
    root = raw.parent.parent if raw.parent.name.lower() == "raw" else raw.parent
    exports = root / "exports"
    return exports, exports / ".work" / name


def _plan_path(raw: Path, explicit):
    if explicit:
        return Path(explicit)
    exports, _ = _project_dirs(raw, raw.stem)
    return exports / f"{raw.stem}.plan.json"


def cmd_plan(args):
    from .planner import make_plan
    raw = Path(args.raw).resolve()
    script = Path(args.script).read_text(encoding="utf-8") if args.script else None
    plan = make_plan(raw, script=script, cta_text=args.cta_text, card=args.card, keep_outro=args.keep_outro, log=print)
    out = _plan_path(raw, args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"plan -> {out}")
    return out


def cmd_render(args):
    from .render import render
    plan_file = Path(args.plan).resolve()
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    raw = Path(plan["source"])
    exports, work = _project_dirs(raw, plan.get("name", raw.stem))
    if args.exports:
        exports = Path(args.exports)
        work = exports / ".work" / plan.get("name", raw.stem)
    return render(plan, work, exports)


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="pipeline", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "reel"):
        p = sub.add_parser(name)
        p.add_argument("raw", help="raw talking-head clip")
        p.add_argument("--script", help="text file with what you meant to say (improves spelling and keywords)")
        p.add_argument("--cta-text", help='text beside the CTA word, e.g. "for KCET + COMEDK"')
        p.add_argument("--card", help='full-screen card: "TITLE | ROW one | ROW two | ROW three"')
        p.add_argument("--keep-outro", action="store_true", help="keep sign-offs like 'milte hain' after the CTA")
        p.add_argument("--out", help="where to write the plan (default exports/<name>.plan.json)")
        p.add_argument("--exports", help="export folder (default <project>/exports)")
    r = sub.add_parser("render")
    r.add_argument("plan")
    r.add_argument("--exports")
    args = ap.parse_args(argv)
    if args.cmd == "plan":
        cmd_plan(args)
    elif args.cmd == "render":
        cmd_render(args)
    else:
        args.plan = str(cmd_plan(args))
        cmd_render(args)


if __name__ == "__main__":
    main()
