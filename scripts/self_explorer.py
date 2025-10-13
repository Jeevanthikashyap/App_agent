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
from utils import print_with_color, draw_bbox_multi

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

# ------------------ Continuous Task Loop ------------------
while True:
    # Ask for a new task
    print_with_color("\nDo you have a new task for me?", "blue")
    voice_assistant.speak_text("Do you have a new task for me?")
    input_file_path = "input.txt"
    open(input_file_path, "w").close()
    call_voice_assistant()

    # Read task description
    if os.path.exists(input_file_path) and os.path.getsize(input_file_path) > 0:
        with open(input_file_path, "r", encoding="utf-8") as f:
            task_desc = f.read().strip()
        open(input_file_path, "w").close()

        if task_desc.lower() in ["exit", "quit", "stop", "no"]:
            print_with_color("Goodbye! Exiting agent.", "red")
            voice_assistant.speak_text("Goodbye! Exiting now.")
            break

        print_with_color(f"Loaded task description: '{task_desc}'", "green")
    else:
        print_with_color("No new task detected. Exiting.", "red")
        break

    # Create a new demo directory for this task
    demo_dir = os.path.join(work_dir, "demos")
    os.makedirs(demo_dir, exist_ok=True)
    demo_timestamp = int(time.time())
    task_name = datetime.datetime.fromtimestamp(demo_timestamp).strftime("self_explore_%Y-%m-%d_%H-%M-%S")
    task_dir = os.path.join(demo_dir, task_name)
    os.mkdir(task_dir)
    explore_log_path = os.path.join(task_dir, f"log_explore_{task_name}.txt")
    reflect_log_path = os.path.join(task_dir, f"log_reflect_{task_name}.txt")

    # Initialize exploration state
    round_count = 0
    doc_count = 0
    useless_list = set()
    last_act = "None"
    task_complete = False

    # ------------------ Exploration Loop ------------------
    while round_count < configs["MAX_ROUNDS"]:
        round_count += 1
        print_with_color(f"Round {round_count}", "yellow")
        human_answer_context = ""
        if "human_input" in locals() and human_input:
            human_answer_context = f"You previously asked a question and the human responded with: '{human_input}'."
            human_input = ""

        screenshot_before = controller.get_screenshot(f"{round_count}_before", task_dir)
        xml_path = controller.get_xml(f"{round_count}", task_dir)
        if screenshot_before == "ERROR" or xml_path == "ERROR":
            break

        clickable_list = []
        focusable_list = []
        traverse_tree(xml_path, clickable_list, "clickable", True)
        traverse_tree(xml_path, focusable_list, "focusable", True)
        elem_list = []

        for elem in clickable_list:
            if elem.uid not in useless_list:
                elem_list.append(elem)
        for elem in focusable_list:
            if elem.uid not in useless_list:
                bbox = elem.bbox
                center = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
                close = False
                for e in clickable_list:
                    bbox = e.bbox
                    center_ = (bbox[0][0] + bbox[1][0]) // 2, (bbox[0][1] + bbox[1][1]) // 2
                    dist = ((center[0] - center_[0]) ** 2 + (center[1] - center_[1]) ** 2) ** 0.5
                    if dist <= configs["MIN_DIST"]:
                        close = True
                        break
                if not close:
                    elem_list.append(elem)

        draw_bbox_multi(
            screenshot_before,
            os.path.join(task_dir, f"{round_count}_before_labeled.png"),
            elem_list,
            dark_mode=configs["DARK_MODE"]
        )

        prompt = re.sub(r"<task_description>", task_desc, prompts.self_explore_task_template)
        prompt = re.sub(r"<last_act>", last_act, prompt)
        prompt = re.sub(r"<human_answer_context>", human_answer_context, prompt)
        base64_img_before = os.path.join(task_dir, f"{round_count}_before_labeled.png")

        print_with_color("Thinking about what to do in the next step...", "yellow")
        status, rsp = mllm.get_model_response(prompt, [base64_img_before])

        if not status:
            print_with_color(rsp, "red")
            break

        with open(explore_log_path, "a") as logfile:
            log_item = {"step": round_count, "prompt": prompt, "image": f"{round_count}_before_labeled.png", "response": rsp}
            logfile.write(json.dumps(log_item) + "\n")

        res = parse_explore_rsp(rsp)
        act_name = res[0]
        last_act = res[-1]
        res = res[:-1]

        if act_name == "FINISH":
            task_complete = True
            break
        elif act_name == "tap":
            _, area = res
            tl, br = elem_list[area - 1].bbox
            x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
            if controller.tap(x, y) == "ERROR":
                break
        elif act_name == "long_press":
            _, area = res
            tl, br = elem_list[area - 1].bbox
            x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
            if controller.long_press(x, y) == "ERROR":
                break
        elif act_name == "swipe":
            _, area, swipe_dir, dist = res
            tl, br = elem_list[area - 1].bbox
            x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
            if controller.swipe(x, y, swipe_dir, dist) == "ERROR":
                break
        elif act_name == "ask_human":
            _, question_to_ask = res
            print_with_color(f"AGENT REQUEST: {question_to_ask}", "green")
            input_file_path = "input.txt"
            open(input_file_path, "w").close()
            call_voice_assistant()

            if os.path.exists(input_file_path) and os.path.getsize(input_file_path) > 0:
                with open(input_file_path, "r", encoding="utf-8") as f:
                    human_input = f.read().strip()
                open(input_file_path, "w").close()
                print_with_color(f"Found response: '{human_input}'", "cyan")
            else:
                print_with_color("Waiting for your response (type or update input.txt)...", "yellow")
                human_input = input("Your response: ")
            print_with_color("Understood. Using this for next step.", "cyan")
            continue
        elif act_name == "text":
            _, area, input_str = res
            tl, br = elem_list[area - 1].bbox
            x, y = (tl[0] + br[0]) // 2, (tl[1] + br[1]) // 2
            print_with_color(f"Tapping element {area} to focus before typing.", "cyan")
            controller.tap(x, y)
            time.sleep(1.5)
            if controller.text(input_str) == "ERROR":
                break
        else:
            break

        time.sleep(configs["REQUEST_INTERVAL"])

        # Reflection phase
        screenshot_after = controller.get_screenshot(f"{round_count}_after", task_dir)
        if screenshot_after == "ERROR":
            break
        draw_bbox_multi(screenshot_after, os.path.join(task_dir, f"{round_count}_after_labeled.png"), elem_list, dark_mode=configs["DARK_MODE"])
        base64_img_after = os.path.join(task_dir, f"{round_count}_after_labeled.png")

        if act_name == "tap":
            prompt = re.sub(r"<action>", "tapping", prompts.self_explore_reflect_template)
        elif act_name == "long_press":
            prompt = re.sub(r"<action>", "long pressing", prompts.self_explore_reflect_template)
        elif act_name == "swipe":
            prompt = re.sub(r"<action>", "swiping", prompts.self_explore_reflect_template)
        else:
            continue

        prompt = re.sub(r"<ui_element>", str(area), prompt)
        prompt = re.sub(r"<task_desc>", task_desc, prompt)
        prompt = re.sub(r"<last_act>", last_act, prompt)

        print_with_color("Reflecting on my previous action...", "yellow")
        status, rsp = mllm.get_model_response(prompt, [base64_img_before, base64_img_after])
        if not status:
            break

        resource_id = elem_list[int(area) - 1].uid
        with open(reflect_log_path, "a") as logfile:
            log_item = {"step": round_count, "prompt": prompt, "response": rsp}
            logfile.write(json.dumps(log_item) + "\n")

        res = parse_reflect_rsp(rsp)
        decision = res[0]
        if decision == "INEFFECTIVE":
            useless_list.add(resource_id)
            last_act = "None"
        elif decision in ["BACK", "CONTINUE", "SUCCESS"]:
            if decision in ["BACK", "CONTINUE"]:
                useless_list.add(resource_id)
                last_act = "None"
                if decision == "BACK":
                    controller.back()
            doc = res[-1]
            doc_name = resource_id + ".txt"
            doc_path = os.path.join(docs_dir, doc_name)
            if os.path.exists(doc_path):
                doc_content = ast.literal_eval(open(doc_path).read())
            else:
                doc_content = {"tap": "", "text": "", "v_swipe": "", "h_swipe": "", "long_press": ""}
            doc_content[act_name] = doc
            with open(doc_path, "w") as outfile:
                outfile.write(str(doc_content))
            doc_count += 1
            print_with_color(f"Documentation saved to {doc_path}", "yellow")

        voice_assistant.speak_summary_only()
        time.sleep(configs["REQUEST_INTERVAL"])

    # ------------------ After Task Completion ------------------
    if task_complete:
        print_with_color(f"Task '{task_desc}' completed successfully. {doc_count} docs generated.", "yellow")
        voice_assistant.speak_text("Task completed successfully. Would you like me to do something else?")
    elif round_count == configs["MAX_ROUNDS"]:
        print_with_color(f"Task ended due to max rounds. {doc_count} docs generated.", "yellow")
        voice_assistant.speak_text("I reached the maximum rounds. Do you want to give me another task?")
    else:
        print_with_color(f"Task ended unexpectedly. {doc_count} docs generated.", "red")
        voice_assistant.speak_text("Something went wrong. Do you want to try another task?")

    print_with_color("Waiting for next command...", "blue")
    time.sleep(3)

voice_assistant.speak_text("Thank you! All tasks finished.")
open("output.txt", "w").close()
