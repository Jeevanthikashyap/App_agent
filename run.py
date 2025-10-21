import argparse
import os
import time
from scripts.utils import print_with_color

arg_desc = "AppAgent - deployment phase"
parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=arg_desc)
parser.add_argument("--app")
parser.add_argument("--root_dir", default="./")
args = vars(parser.parse_args())

app = args["app"]
root_dir = args["root_dir"]

print_with_color("Welcome to your App Agent!", "yellow")

# if not app:
#     print_with_color("What is the name of the target app?", "blue")
#     app = input()
#     app = app.replace(" ", "")

os.system(f"python scripts/task_executor.py --app {app} --root_dir {root_dir}")
