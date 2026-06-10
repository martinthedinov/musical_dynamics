"""Command-line interface:  python -m stego <command> ...

  embed     hide a file inside a music file
  extract   recover a hidden file
  capacity  report how much a music file can hold

Examples:
  python -m stego embed song.flac secret.zip -o stego.flac --redundancy 4 --password hunter2
  python -m stego embed song.wav  secret.zip --adaptive            # psychoacoustic: more data, less audible
  python -m stego embed voice.wav secret.txt --adaptive --profile speech   # speech-safe (skips silence)
  python -m stego extract stego.flac -o ./out --password hunter2   # auto-detects uniform vs adaptive
  python -m stego capacity song.wav --adaptive
"""
import argparse, os, sys
from .carriers import embed_file, extract_file, capacity
from .pipeline import PipelineError
from .crypto import CryptoError

def _default_out(in_path, suffix="_stego"):
    root, ext = os.path.splitext(in_path)
    return root + suffix + ext

def _add_method_flags(ps):
    ps.add_argument("--adaptive", action="store_true",
                    help="psychoacoustic adaptive bit-allocation (more capacity, less audible, "
                         "lossless WAV/FLAC/AIFF only)")
    ps.add_argument("--profile", choices=("music", "speech"), default="music",
                    help="adaptive profile: 'music' (max capacity) or 'speech' (skips silence, "
                         "gentler — keeps speech natural)")

def main(argv=None):
    p = argparse.ArgumentParser(prog="stego", description="Hide arbitrary files inside music, with fountain-coded redundancy.")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("embed", help="hide a file inside a music file")
    e.add_argument("carrier"); e.add_argument("payload")
    e.add_argument("-o", "--out", help="output carrier (default: <carrier>_stego.<ext>)")
    e.add_argument("--password"); e.add_argument("--redundancy", type=float, default=None,
                   help="target N/K (default: fill carrier = max redundancy)")
    e.add_argument("--n-lsb", type=int, default=1, help="uniform mode: bit-planes to use (1=stealthiest)")
    _add_method_flags(e)

    x = sub.add_parser("extract", help="recover a hidden file (auto-detects uniform vs adaptive)")
    x.add_argument("carrier"); x.add_argument("-o", "--out", default=".", help="output directory")
    x.add_argument("--password")

    c = sub.add_parser("capacity", help="report capacity of a music file")
    c.add_argument("carrier"); c.add_argument("--n-lsb", type=int, default=1)
    _add_method_flags(c)

    a = p.parse_args(argv)
    method = "adaptive" if getattr(a, "adaptive", False) else "uniform"
    try:
        if a.cmd == "embed":
            out = a.out or _default_out(a.carrier)
            info = embed_file(a.carrier, out, a.payload, password=a.password, redundancy=a.redundancy,
                              n_lsb=a.n_lsb, method=method, profile=a.profile)
            print("embedded %s (%d bytes) -> %s" % (os.path.basename(a.payload), info["payload_bytes"], out))
            tag = ("adaptive/%s" % a.profile) if method == "adaptive" else ("uniform n_lsb=%d" % info["n_lsb"])
            print("  %s · redundancy %sx · tolerates losing %s of the carrier · %s symbols%s"
                  % (tag, info["redundancy"], info["tolerates_symbol_loss"], info["n_symbols"],
                     " · AES-GCM" if a.password else ""))
        elif a.cmd == "extract":
            out_path, hdr = extract_file(a.carrier, a.out, password=a.password)
            how = hdr.get("method", "uniform")
            how = ("adaptive/%s" % hdr.get("profile", "?")) if how == "adaptive" else how
            print("recovered -> %s  (%s, redundancy was %.1fx%s)"
                  % (out_path, how, hdr["n_sym"] / max(1, hdr["K"]), ", encrypted" if hdr["flags"] & 2 else ""))
        elif a.cmd == "capacity":
            print(capacity(a.carrier, n_lsb=a.n_lsb, method=method, profile=a.profile))
    except (PipelineError, CryptoError, ValueError, NotImplementedError, FileNotFoundError) as err:
        print("error: %s" % err, file=sys.stderr); return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
