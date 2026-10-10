"""Stand-in for `ssh Administrator@<machine> "<command line>"` on the cloud Windows runner
(scripts/ci/deploy_pkg_e2e.sh): runs the command line here, through cmd.exe, as Windows'
OpenSSH server does with its default shell. stdin passes through (the tar stream).
System32 first on PATH, as in an ssh session: `tar` there is Windows' bsdtar, not Git's."""
import os
import subprocess
import sys

env = dict(os.environ)
env["PATH"] = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32") + ";" + env.get("PATH", "")
sys.exit(subprocess.run(sys.argv[1], shell=True, env=env).returncode)
