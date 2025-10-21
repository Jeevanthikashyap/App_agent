import argparse
import ast
import datetime
import json
import os
import re
import sys
import time
import prompts
import subprocess
import voice_assistant
from gtts import gTTS
from playsound import playsound
from logger import setup_logger
from config import load_config
from and_controller import list_all_devices, AndroidController, traverse_tree
from model import parse_explore_rsp, parse_reflect_rsp, OpenAIModel, QwenModel, GeminiModel
from utils import print_with_color, draw_bbox_multi, draw_grid

# Initialize logging
setup_logger()

# ------------------ Basic Definitions ------------------
arg_desc = "AppAgent - Autonomous Exploration"
parser = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter, description=arg_desc)
parser.add_argument("--app")
parser.add_argument("--root_dir", default="./")
args = vars(parser.parse_args())

# ------------------ Voice Assistant ------------------
def call_voice_assistant():
    """
    Calls voice_assistant.py and returns the transcribed text.
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
configs = load_config()
if configs["MODEL"] == "OpenAI":
    mllm = OpenAIModel(
        base_url=configs["OPENAI_API_BASE"],
        api_key=configs["OPENAI_API_KEY"],
        model=configs["OPENAI_API_MODEL"],
        temperature=configs["TEMPERATURE"],
        max_completion_tokens=configs["MAX_COMPLETION_TOKENS"]
    )
elif configs["MODEL"] == "Qwen":
    mllm = QwenModel(api_key=configs["DASHSCOPE_API_KEY"], model=configs["QWEN_MODEL"])
elif configs["MODEL"] == "Gemini":
    mllm = GeminiModel(
        api_key=configs["GEMINI_API_KEY"],
        model=configs["GEMINI_MODEL"],
        temperature=configs["TEMPERATURE"],
        max_completion_tokens=configs["MAX_COMPLETION_TOKENS"]
    )
else:
    print_with_color(f"ERROR: Unsupported model type {configs['MODEL']}!", "red")
    sys.exit()

# ------------------ App Setup ------------------
app = args["app"]
root_dir = args["root_dir"]

if not app:
    print_with_color("What is the name of the target app?", "blue")
    app = input().replace(" ", "")

work_dir = os.path.join(root_dir, "apps")
os.makedirs(work_dir, exist_ok=True)
work_dir = os.path.join(work_dir, app)
os.makedirs(work_dir, exist_ok=True)
docs_dir = os.path.join(work_dir, "auto_docs")
os.makedirs(docs_dir, exist_ok=True)

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

# ------------------ Stop Words ------------------
STOP_WORDS = ["exit", "quit", "stop", "no", "no thanks", "all done", "you can exit now", "close"]

# ------------------ Grid Mode Setup ------------------
grid_on = True  # Force grid mode ON
rows, cols = 0, 0

def area_to_xy(area, subarea):
    global rows, cols
    if rows == 0 or cols == 0:
        rows, cols = 3, 3  # default grid
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

# ------------------ Continuous Task Loop ------------------
while True:
    print_with_color("\nDo you have a new task for me?", "blue")
    voice_assistant.speak_text("Do you have a new task for me?")
    input_file_path = "input.txt"
    open(input_file_path, "w").close()
    call_voice_assistant()

    if os.path.exists(input_file_path) and os.path.getsize(input_file_path) > 0:
        with open(input_file_path, "r", encoding="utf-8") as f:
            task_desc = f.read().strip().lower()
        open(input_file_path, "w").close()
        if any(stop_word in task_desc for stop_word in STOP_WORDS):
            print_with_color("Goodbye! Exiting agent.", "green")
            voice_assistant.speak_text("Goodbye! Exiting now.")
            break
        print_with_color(f"Loaded task description: '{task_desc}'", "green")
    else:
        print_with_color("No new task detected. Exiting.", "red")
        break

    demo_dir = os.path.join(work_dir, "demos")
    os.makedirs(demo_dir, exist_ok=True)
    demo_timestamp = int(time.time())
    task_name = datetime.datetime.fromtimestamp(demo_timestamp).strftime("self_explore_%Y-%m-%d_%H-%M-%S")
    task_dir = os.path.join(demo_dir, task_name)
    os.mkdir(task_dir)
    explore_log_path = os.path.join(task_dir, f"log_explore_{task_name}.txt")
    reflect_log_path = os.path.join(task_dir, f"log_reflect_{task_name}.txt")

    round_count = 0
    task_complete = False
    last_act = "None"
    doc_count = 0
    useless_list = set()

    # ------------------ Exploration Loop ------------------
    while round_count < configs["MAX_ROUNDS"]:
        round_count += 1
        print_with_color(f"Round {round_count}", "yellow")
        human_answer_context = ""

        screenshot_before = controller.get_screenshot(f"{round_count}_before", task_dir)

        # ------------------ XML Parsing (Commented for Grid Only) ------------------
        # xml_path = controller.get_xml(f"{round_count}", task_dir)
        # clickable_list = []
        # focusable_list = []
        # traverse_tree(xml_path, clickable_list, "clickable", True)
        # traverse_tree(xml_path, focusable_list, "focusable", True)
        # elem_list = []
        # for elem in clickable_list + focusable_list:
        #     if elem.uid not in useless_list:
        #         elem_list.append(elem)
        # draw_bbox_multi(screenshot_before, os.path.join(task_dir, f"{round_count}_before_labeled.png"), elem_list, dark_mode=configs["DARK_MODE"])

        # ------------------ Grid Drawing ------------------
        if grid_on:
            rows, cols = draw_grid(screenshot_before, os.path.join(task_dir, f"{round_count}_before_grid.png"))
            image = os.path.join(task_dir, f"{round_count}_before_grid.png")
            prompt = prompts.self_explore_task_template
            prompt = re.sub(r"<task_description>", task_desc, prompt)
            prompt = re.sub(r"<last_act>", last_act, prompt)
            prompt = re.sub(r"<human_answer_context>", human_answer_context, prompt)

            print_with_color("Thinking about what to do in the next step...", "yellow")
            status, rsp = mllm.get_model_response(prompt, [image])

            if not status:
                print_with_color(rsp, "red")
                break

            with open(explore_log_path, "a") as logfile:
                log_item = {"step": round_count, "prompt": prompt, "image": f"{round_count}_before_grid.png", "response": rsp}
                logfile.write(json.dumps(log_item) + "\n")

            res = parse_explore_rsp(rsp)
            act_name = res[0]
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
                        break
                elif act_name == "swipe_grid":
                    _, start_area, start_subarea, end_area, end_subarea = res
                    start_x, start_y = area_to_xy(start_area, start_subarea)
                    end_x, end_y = area_to_xy(end_area, end_subarea)
                    ret = controller.swipe_precise((start_x, start_y), (end_x, end_y))
                    if ret == "ERROR":
                        break
            except Exception as e:
                print_with_color(f"ERROR: Exception while executing grid action - {e}", "red")
                break

            time.sleep(configs["REQUEST_INTERVAL"])

    if task_complete:
        print_with_color(f"Task '{task_desc}' completed successfully. {doc_count} docs generated.", "yellow")
        voice_assistant.speak_text("Task completed successfully. Would you like me to do something else?")
    else:
        print_with_color(f"Task ended. {doc_count} docs generated.", "yellow")
        voice_assistant.speak_text("Task finished. Do you want to give me another task?")

voice_assistant.speak_text("Thank you! All tasks finished.")
open("output.txt", "w").close()
