"""Find a tool this server installs: PATH first, then ~/.local/bin.

A chat or worker often runs with a PATH that leaves out ~/.local/bin (VSTA-234), so a
bare `yeo-key` or `hypertask` call raised FileNotFoundError. Every script asks this one
module instead of naming the tool and hoping PATH carries it.
"""
import os
import shutil
from pathlib import Path


def local_bin(home=None):
    return Path(home or Path.home()) / '.local' / 'bin'


def find(name, home=None):
    """`name` on PATH, else this server's copy in ~/.local/bin, else None."""
    found = shutil.which(name)
    if found:
        return found
    local = local_bin(home) / name
    return str(local) if local.is_file() else None


def hypertask(home=None):
    return find('hypertask', home)


def yeo_key(home=None):
    return find('yeo-key', home)
