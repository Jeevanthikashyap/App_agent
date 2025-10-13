import argparse
import datetime
import os
import time

from scripts.utils import print_with_color

arg_desc = "AppAgent - exploration phase"
parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=arg_desc)
parser.add_argument("--app")
parser.add_argument("--root_dir", default="./")
args = vars(parser.parse_args())

app = args["app"]
root_dir = args["root_dir"]


print_with_color("Welcome to your app agent", "yellow")
print_with_color("Press 1 to continue", "blue")
user_input = ""
while user_input != "1" and user_input != "2":
    user_input = input()

if not app:
    print_with_color("What is the name of the target app?", "blue")
    app = input()
    app = app.replace(" ", "")

if user_input == "1":
    os.system(f"python scripts/self_explorer.py --app {app} --root_dir {root_dir}")
else:
    print_with_color("Wrong key pressed","red")