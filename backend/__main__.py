"""python -m backend [--source sim|replay|serial] [--file X.csv] [--port COM5] [--rpm 5000]"""
import argparse
import os

import uvicorn

ap = argparse.ArgumentParser(prog="python -m backend")
ap.add_argument("--source", choices=["sim", "replay", "serial"], default="sim")
ap.add_argument("--file", help="recording in data/sim/ for --source replay")
ap.add_argument("--port", help="serial port for --source serial, e.g. COM5")
ap.add_argument("--rpm", type=float, default=5000, help="simulator speed")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--http-port", type=int, default=8000)
args = ap.parse_args()

os.environ["INDUX_SOURCE"] = args.source
os.environ["INDUX_RPM"] = str(args.rpm)
if args.file:
    os.environ["INDUX_FILE"] = args.file
if args.port:
    os.environ["INDUX_PORT"] = args.port

uvicorn.run("backend.app:app", host=args.host, port=args.http_port, log_level="info")
