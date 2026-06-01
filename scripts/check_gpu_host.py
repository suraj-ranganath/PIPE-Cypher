#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser(description="Check ds-serv6 GPU availability")
    parser.add_argument("--host", default="suraj@ds-serv6.ucsd.edu")
    args = parser.parse_args()
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        args.host,
        "hostname; nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader,nounits; df -h / /data | sed -n '1,3p'",
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()

