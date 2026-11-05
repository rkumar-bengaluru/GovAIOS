"""usage: .venv/bin/python run.py flows/<flow>.yaml"""
import sys

from desktop import get_desktop
from engine import Runner, Stop

try:
    Runner(sys.argv[1], get_desktop()).run()
except Stop as e:
    sys.exit(f"STOPPED: {e}")
