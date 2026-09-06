"""Build the HVQM4 movie helper:  python native/build_hvqm4.py

Compiles native/hvqm4/hvqm4dec.c into native/bin/hvqm4dec(.exe) with the
first C compiler found: clang or gcc on PATH, or the clang that ships with
Visual Studio (located through vswhere). The sources use GCC extensions, so
plain MSVC cl.exe is not enough.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "hvqm4" / "hvqm4dec.c"
OUT = HERE / "bin" / ("hvqm4dec.exe" if sys.platform == "win32" else "hvqm4dec")
FLAGS = ["-O2", "-DNATIVE=1", "-D_CRT_SECURE_NO_WARNINGS", "-Wno-everything"]


def vs_clang() -> tuple[Path, Path] | None:
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return None
    try:
        root = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if not root:
        return None
    for rel in ("VC/Tools/Llvm/x64/bin/clang.exe", "VC/Tools/Llvm/bin/clang.exe"):
        clang = Path(root) / rel
        vcvars = Path(root) / "VC/Auxiliary/Build/vcvars64.bat"
        if clang.exists() and vcvars.exists():
            return clang, vcvars
    return None


def main() -> int:
    OUT.parent.mkdir(exist_ok=True)
    for name in ("clang", "gcc", "cc"):
        exe = shutil.which(name)
        if exe:
            cmd = [exe, *FLAGS, str(SRC), "-o", str(OUT)] + ([] if sys.platform == "win32" else ["-lm"])
            print(" ".join(cmd))
            return subprocess.call(cmd)
    if sys.platform == "win32":
        found = vs_clang()
        if found:
            clang, vcvars = found
            # import the MSVC environment (headers, libs) that clang needs, then call clang directly
            import tempfile
            with tempfile.NamedTemporaryFile("w", suffix=".cmd", delete=False) as f:
                f.write("@echo off\r\ncall \"" + str(vcvars) + "\" >nul 2>&1\r\nset\r\n")
                script = f.name
            try:
                dump = subprocess.check_output(["cmd", "/c", script], text=True)
            finally:
                os.unlink(script)
            env = dict(os.environ)
            for line in dump.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k] = v
            cmd = [str(clang), *FLAGS, str(SRC), "-o", str(OUT)]
            print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
            return subprocess.call(cmd, env=env)
    print("no C compiler found (need clang or gcc; on Windows the LLVM component of Visual Studio works)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
