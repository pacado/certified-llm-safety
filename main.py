import torch
import transformers
from transformers import AutoTokenizer

import os
import time
import json
import random
import argparse

from defenses import erase_and_check, is_harmful, progress_bar, erase_and_check_contiguous, erase_and_check_subsets

parser = argparse.ArgumentParser(description='Check safety of prompts.')
parser.add_argument('--num_prompts', type=int, default=2,
                    help='number of prompts to check')
parser.add_argument('--mode', type=str, default="suffix", choices=["suffix", "subset", "contiguous"],
                    help='attack mode to defend against')
parser.add_argument('--eval_type', type=str, default="safe", choices=["safe", "harmful"],
                    help='type of prompts to evaluate')
parser.add_argument('--max_erase', type=int, default=20,
                    help='maximum number of tokens to erase')
parser.add_argument('--num_adv', type=int, default=2,
                    help='number of adversarial prompts to defend against (contiguous mode only)')
parser.add_argument('--results_dir', type=str, default="results",
                    help='directory to save results')
args = parser.parse_args()

num_prompts = args.num_prompts
mode = args.mode
eval_type = args.eval_type
max_erase = args.max_erase
num_adv = args.num_adv
results_dir = args.results_dir

print("Evaluation type: " + eval_type)
print("Number of prompts to check: " + str(num_prompts))
if eval_type == "safe":
    print("Mode: " + mode)
    print("Maximum tokens to erase: " + str(max_erase))
    if mode == "contiguous":
        print("Number of adversarial prompts to defend against: " + str(num_adv))

# Create results directory if it doesn't exist
if not os.path.exists(results_dir):
    os.makedirs(results_dir)

# Create results file
if eval_type == "safe":
    results_file = os.path.join(results_dir, f"{eval_type}_{mode}_{num_prompts}.json")
elif eval_type == "harmful":
    results_file = os.path.join(results_dir, f"{eval_type}_{num_prompts}.json")

# Load results if they exist
if os.path.exists(results_file):
    with open(results_file, "r") as f:
        results = json.load(f)
else:
    results = {}

# print(results)

# Load model and tokenizer
model = "meta-llama/Llama-2-7b-chat-hf"
print(f'Loading model {model}...')
tokenizer = AutoTokenizer.from_pretrained(model)
pipeline = transformers.pipeline(
    "text-generation",
    model=model,
    torch_dtype=torch.float16,
    device_map="auto",
)

if eval_type == "safe":
    # Safe prompts
    print("Evaluating safe prompts:")
    # Load prompts from text file
    with open("data/safe_prompts.txt", "r") as f:
        prompts = f.readlines()
        prompts = [prompt.strip() for prompt in prompts]

    # Sample a random subset of the prompts
    prompts = random.sample(prompts, num_prompts)

    # Check if the prompts are harmful
    count_safe = 0
    start_time = time.time()
    for i in range(num_prompts):
        prompt = prompts[i]
        if mode == "suffix":
            harmful = erase_and_check(prompt, pipeline, tokenizer, max_erase=max_erase)
        elif mode == "subset":
            harmful = erase_and_check_subsets(prompt, pipeline, tokenizer, max_erase=max_erase)
        elif mode == "contiguous":
            harmful = erase_and_check_contiguous(prompt, pipeline, tokenizer, max_erase=max_erase, num_adv=num_adv)
        if not harmful:
            count_safe += 1

        current_time = time.time()
        elapsed_time = current_time - start_time
        time_per_prompt = elapsed_time / (i + 1)
        percent_safe = count_safe / (i + 1) * 100
        print("    Checking safety... " + progress_bar((i + 1) / num_prompts) \
            + f' Detected safe = {percent_safe:5.1f}%' \
            + f' Time/prompt = {time_per_prompt:5.1f}s', end="\r")
        
    # Save results
    if mode == "contiguous":
        if str(dict(num_adv = num_adv)) not in results:
            results[str(dict(num_adv = num_adv))] = {}
        results[str(dict(num_adv = num_adv))][str(dict(max_erase = max_erase))] = dict(percent_safe = percent_safe, time_per_prompt = time_per_prompt)
    else:
        results[str(dict(max_erase = max_erase))] = dict(percent_safe = percent_safe, time_per_prompt = time_per_prompt)
    # print(results)

elif eval_type == "harmful":
    # Harmful prompts
    print("Evaluating harmful prompts:")
    # Load prompts from text file
    with open("data/harmful_prompts.txt", "r") as f:
        prompts = f.readlines()
        prompts = [prompt.strip() for prompt in prompts]

    # Sample a random subset of the prompts
    prompts = random.sample(prompts, num_prompts)

    # Check if the prompts are harmful
    count_harmful = 0
    batch_size = 10
    start_time = time.time()
    for i in range(0, num_prompts, batch_size):
        batch = prompts[i:i+batch_size]
        # Evaluating the safety filter gives us certifed safety guarantees on
        # erase_and_check for harmful prompts (from construction).
        harmful = is_harmful(batch, pipeline, tokenizer)
        count_harmful += sum(harmful)

        current_time = time.time()
        elapsed_time = current_time - start_time
        time_per_prompt = elapsed_time / (i + batch_size)
        num_done = i + batch_size
        percent_harmful = count_harmful / num_done * 100
        print("    Checking safety... " + progress_bar(num_done / num_prompts) \
            + f' Detected harmful = {percent_harmful:5.1f}%' \
            + f' Time/prompt = {time_per_prompt:5.1f}s', end="\r")
        
    # Save results
    results["percent_harmful"] = percent_harmful

print("")

# Save results
print("Saving results to " + results_file)
with open(results_file, "w") as f:
    json.dump(results, f, indent=2)