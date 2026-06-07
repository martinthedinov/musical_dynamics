"""Command-line interface:  python -m stego <command> ...

  embed     hide a file inside a music file
  extract   recover a hidden file
  capacity  report how much a music file can hold

Examples:
  python -m stego embed song.flac secret.zip -o stego.flac --redundancy 4 --password hunter2
  python -m stego extract stego.flac -o ./out --password hunter2
  python -m stego capacity song.wav
"""
import argparse, os, sys
from .carriers import embed_file, extract_file, capacity
from .pipeline import PipelineError
from .crypto import CryptoError

def _default_out(in_path, suffix="_stego"):
    root, ext = os.path.splitext(in_path)
    return root + suffix + ext

def main(argv=None):
    p = argparse.ArgumentParser(prog="stego", description="Hide arbitrary files inside music, with fountain-coded redundancy.")
    sub = p.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("embed", help="hide a file inside a music file")
    e.add_argument("carrier"); e.add_argument("payload")
    e.add_argument("-o", "--out", help="output carrier (default: <carrier>_stego.<ext>)")
    e.add_argument("--password"); e.add_argument("--redundancy", type=float, default=None,
                   help="target N/K (default: fill carrier = max redundancy)")
    e.add_argument("--n-lsb", type=int, default=1, help="bit-planes to use (1=stealthiest)")

    x = sub.add_parser("extract", help="recover a hidden file")
    x.add_argument("carrier"); x.add_argument("-o", "--out", default=".", help="output directory")
    x.add_argument("--password")

    c = sub.add_parser("capacity", help="report capacity of a music file")
    c.add_argument("carrier"); c.add_argument("--n-lsb", type=int, default=1)

    a = p.parse_args(argv)
    try:
        if a.cmd == "embed":
            out = a.out or _default_out(a.carrier)
            info = embed_file(a.carrier, out, a.payload, password=a.password,
                              redundancy=a.redundancy, n_lsb=a.n_lsb)
            print("embedded %s (%d bytes) -> %s" % (os.path.basename(a.payload), info["payload_bytes"], out))
            print("  redundancy %sx · tolerates losing %s of the carrier · %s symbols · n_lsb=%d%s"
                  % (info["redundancy"], info["tolerates_symbol_loss"], info["n_symbols"], info["n_lsb"],
                     " · AES-GCM" if a.password else ""))
        elif a.cmd == "extract":
            out_path, hdr = extract_file(a.carrier, a.out, password=a.password)
            print("recovered -> %s  (redundancy was %.1fx, n_lsb=%d%s)"
                  % (out_path, hdr["n_sym"] / max(1, hdr["K"]), hdr["n_lsb"], ", encrypted" if hdr["flags"] & 2 else ""))
        elif a.cmd == "capacity":
            print(capacity(a.carrier, n_lsb=a.n_lsb))
    except (PipelineError, CryptoError, ValueError, NotImplementedError, FileNotFoundError) as err:
        print("error: %s" % err, file=sys.stderr); return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
