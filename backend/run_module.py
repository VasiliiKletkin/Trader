import os
import runpy
import sys
from pathlib import Path

import django

file_path = Path(sys.argv[1]).resolve()
backend_dir = Path(__file__).resolve().parent
module_name = (
    str(file_path.relative_to(backend_dir)).replace(os.sep, ".").removesuffix(".py")
)

sys.argv = sys.argv[1:]

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

runpy.run_module(module_name, run_name="__main__", alter_sys=True)
