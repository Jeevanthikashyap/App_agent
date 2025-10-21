import argparse
import ast
import datetime
import json
import os
import re
import sys
import time
import subprocess
import voice_assistant
import prompts
from config import load_config
from and_controller import list_all_devices, AndroidController, traverse_tree
from model import parse_explore_rsp, parse_grid_rsp, OpenAIModel, QwenModel, GeminiModel
from utils import print_with_color, draw_bbox_multi, draw_grid

arg_desc = "AppAgent Executor"
parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=arg_desc)
parser.add_argument("--app")
parser.add_argument("--root_dir", default="./")
args = vars(parser.parse_args())

configs = load_config()

# ------------------ Voice Assistant ------------------
def call_voice_assistant():
    """
    Calls voice_assistant.py and returns the transcribed text in input.txt.
    """
    voice_assistant_script_path = os.path.join(os.path.dirname(__file__), "voice_assistant.py")
    try:
        print_with_color("--- Activating Voice Assistant ---", "magenta")
        subprocess.run(
            [sys.executable, voice_assistant_script_path],
            capture_output=True,
            text=True,
            check=True,
            encoding='utf-8'
        )
    except Exception as e:
        print_with_color(f"Voice assistant failed: {e}", "red")

# ------------------ Model Setup ------------------
if configs["MODEL"] == "OpenAI":
    mllm = OpenAIModel(base_url=configs["OPENAI_API_BASE"],
                       api_key=configs["OPENAI_API_KEY"],
                       model=configs["OPENAI_API_MODEL"],
                       temperature=configs["TEMPERATURE"],
                       max_completion_tokens=configs["MAX_COMPLETION_TOKENS"])
elif configs["MODEL"] == "Qwen":
    mllm = QwenModel(api_key=configs["DASHSCOPE_API_KEY"],
                     model=configs["QWEN_MODEL"])
elif configs["MODEL"] == "Gemini":
    mllm = GeminiModel(api_key=configs["GEMINI_API_KEY"],
                       model=configs["GEMINI_MODEL"],
                       temperature=configs["TEMPERATURE"],
                       max_completion_tokens=configs["MAX_COMPLETION_TOKENS"])
else:
    print_with_color(f"ERROR: Unsupported model type {configs['MODEL']}!", "red")
    sys.exit()

app = args["app"]
root_dir = args["root_dir"]

if not app:
    print_with_color("What is the name of the app you want me to operate?", "blue")
    app = input().replace(" ", "")

app_dir = os.path.join(os.path.join(root_dir, "apps"), app)
work_dir = os.path.join(root_dir, "tasks")
if not os.path.exists(work_dir):
    os.mkdir(work_dir)
auto_docs_dir = os.path.join(app_dir, "auto_docs")
demo_docs_dir = os.path.join(app_dir, "demo_docs")
task_timestamp = int(time.time())
dir_name = datetime.datetime.fromtimestamp(task_timestamp).strftime(f"task_{app}_%Y-%m-%d_%H-%M-%S")
task_dir = os.path.join(work_dir, dir_name)
os.mkdir(task_dir)
log_path = os.path.join(task_dir, f"log_{app}_{dir_name}.txt")

# ------------------ Documentation Selection ------------------
no_doc = False
if not os.path.exists(auto_docs_dir) and not os.path.exists(demo_docs_dir):
    print_with_color(f"No documentations found for the app {app}. Do you want to proceed with no docs? Enter y or n",
                     "red")
    user_input = ""
    while user_input != "y" and user_input != "n":
        user_input = input().lower()
    if user_input == "y":
        no_doc = True
    else:
        sys.exit()
elif os.path.exists(auto_docs_dir) and os.path.exists(demo_docs_dir):
    print_with_color(f"The app {app} has documentations generated from both autonomous exploration and human "
                     f"demonstration. Which one do you want to use? Type 1 or 2.\n1. Autonomous exploration\n2. Human "
                     f"Demonstration",
                     "blue")
    user_input = ""
    while user_input != "1" and user_input != "2":
        user_input = input()
    docs_dir = auto_docs_dir if user_input == "1" else demo_docs_dir
elif os.path.exists(auto_docs_dir):
    print_with_color(f"Documentations generated from autonomous exploration were found for the app {app}. The doc base "
                     f"is selected automatically.", "yellow")
    docs_dir = auto_docs_dir
else:
    print_with_color(f"Documentations generated from human demonstration were found for the app {app}. The doc base is "
                     f"selected automatically.", "yellow")
    docs_dir = demo_docs_dir

# ------------------ Device Setup ------------------
device_list = list_all_devices()
if not device_list:
    print_with_color("ERROR: No device found!", "red")
    sys.exit()
print_with_color(f"List of devices attached:\n{str(device_list)}", "yellow")
if len(device_list) == 1:
    device = device_list[0]
    print_with_color(f"Device selected: {device}", "yellow")
else:
    print_with_color("Please choose the Android device to start demo by entering its ID:", "blue")
    device = input()
controller = AndroidController(device)
width, height = controller.get_device_size()
if not width and not height:
    print_with_color("ERROR: Invalid device size!", "red")
    sys.exit()
print_with_color(f"Screen resolution of {device}: {width}x{height}", "yellow")

# ------------------ Greeting ------------------
greeting_text = "Hi, I am your app agent for L&T Finance - Planet App. How can I help you?"
print_with_color(greeting_text, "pink")
voice_assistant.speak_text(greeting_text)

STOP_WORDS = ["exit", "quit", "stop", "no", "no thanks", "all done", "you can exit now", "close"]

# ------------------ Continuous Task Loop ------------------
while True:
    task_desc = ""
    print_with_color("Do you have a new task for me?", "blue")
    voice_assistant.speak_text("Do you have a new task for me?")

    # Clear input file and call voice assistant
    input_file_path = "input.txt"
    open(input_file_path, "w").close()
    call_voice_assistant()

    # Read task description from voice input
    if os.path.exists(input_file_path) and os.path.getsize(input_file_path) > 0:
        with open(input_file_path, "r", encoding="utf-8") as f:
            task_desc = f.read().strip().lower()
        open(input_file_path, "w").close()
    else:
        print_with_color("No new task detected. Please try again.", "red")
        continue

    # Stop words check
    if any(stop_word in task_desc for stop_word in STOP_WORDS):
        print_with_color("Goodbye! Exiting agent.", "green")
        voice_assistant.speak_text("Goodbye! Exiting now.")
        break

    print_with_color(f"Loaded task description: '{task_desc}'", "green")

    # ------------------ Task Execution Variables ------------------
    round_count = 0
    last_act = "None"
    task_complete = False

    # Force grid mode ON
    grid_on = True
    rows, cols = 0, 0

    def area_to_xy(area, subarea):
        global rows, cols
        if rows == 0 or cols == 0:
            rows, cols = 3, 3  # default grid if not drawn yet
        area = max(1, area) - 1
        row, col = divmod(area, cols)
        row = min(row, rows - 1)
        col = min(col, cols - 1)
        x_0, y_0 = col * (width // cols), row * (height // rows)
        if subarea == "top-left":
            x, y = x_0 + (width // cols) // 4, y_0 + (height // rows) // 4
        elif subarea == "top":
            x, y = x_0 + (width // cols) // 2, y_0 + (height // rows) // 4
        elif subarea == "top-right":
            x, y = x_0 + (width // cols) * 3 // 4, y_0 + (height // rows) // 4
        elif subarea == "left":
            x, y = x_0 + (width // cols) // 4, y_0 + (height // rows) // 2
        elif subarea == "right":
            x, y = x_0 + (width // cols) * 3 // 4, y_0 + (height // rows) // 2
        elif subarea == "bottom-left":
            x, y = x_0 + (width // cols) // 4, y_0 + (height // rows) * 3 // 4
        elif subarea == "bottom":
            x, y = x_0 + (width // cols) // 2, y_0 + (height // rows) * 3 // 4
        elif subarea == "bottom-right":
            x, y = x_0 + (width // cols) * 3 // 4, y_0 + (height // rows) * 3 // 4
        else:
            x, y = x_0 + (width // cols) // 2, y_0 + (height // rows) // 2
        return x, y

    # ------------------ Task Execution Loop ------------------
    while round_count < configs["MAX_ROUNDS"]:
        round_count += 1
        print_with_color(f"Round {round_count}", "yellow")

        screenshot_path = controller.get_screenshot(f"{dir_name}_{round_count}", task_dir)
        #     xml_path = controller.get_xml(f"{dir_name}_{round_count}", task_dir)
        #     if screenshot_path == "ERROR" or xml_path == "ERROR":
        #         break

        # Always draw grid
        rows, cols = draw_grid(screenshot_path, os.path.join(task_dir, f"{dir_name}_{round_count}_grid.png"))
        image = os.path.join(task_dir, f"{dir_name}_{round_count}_grid.png")
        prompt = prompts.task_template_grid

        prompt = re.sub(r"<task_description>", task_desc, prompt)
        prompt = re.sub(r"<last_act>", last_act, prompt)

        print_with_color("Thinking about what to do in the next step...", "yellow")
        status, rsp = mllm.get_model_response(prompt, [image])

        if status:
            with open(log_path, "a") as logfile:
                log_item = {"step": round_count, "prompt": prompt, "image": f"{dir_name}_{round_count}_grid.png",
                            "response": rsp}
                logfile.write(json.dumps(log_item) + "\n")

            # Only grid parsing now
            res = parse_grid_rsp(rsp)
            act_name = res[0]

            if act_name == "FINISH":
                task_complete = True
                break
            if act_name == "ERROR":
                break

            last_act = res[-1]
            res = res[:-1]

            try:
                if act_name == "tap_grid" or act_name == "long_press_grid":
                    _, area, subarea = res
                    x, y = area_to_xy(area, subarea)
                    if act_name == "tap_grid":
                        ret = controller.tap(x, y)
                    else:
                        ret = controller.long_press(x, y)
                    if ret == "ERROR":
                        print_with_color("ERROR: tap execution failed", "red")
                        break
                elif act_name == "swipe_grid":
                    _, start_area, start_subarea, end_area, end_subarea = res
                    start_x, start_y = area_to_xy(start_area, start_subarea)
                    end_x, end_y = area_to_xy(end_area, end_subarea)
                    ret = controller.swipe_precise((start_x, start_y), (end_x, end_y))
                    if ret == "ERROR":
                        print_with_color("ERROR: swipe execution failed", "red")
                        break
            except Exception as e:
                print_with_color(f"ERROR: Exception while executing grid action - {e}", "red")
                break

            time.sleep(configs["REQUEST_INTERVAL"])
        else:
            print_with_color(rsp, "red")
            break

    if task_complete:
        print_with_color("Task completed successfully", "yellow")
        voice_assistant.speak_text("Task completed successfully.")
    elif round_count == configs["MAX_ROUNDS"]:
        print_with_color("Task finished due to reaching max rounds", "yellow")
        voice_assistant.speak_text("Task finished due to reaching maximum rounds.")
    else:
        print_with_color("Task finished unexpectedly", "red")
        voice_assistant.speak_text("Task finished unexpectedly.")
