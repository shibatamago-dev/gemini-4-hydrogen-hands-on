"""Standalone reproduction: Gemini 4 Hydrogen vs Gemini 3.8 Flash.

Same tasks, prompts, scoring harness and retry logic as the run recorded in
results.json, but the API key comes from the GEMINI_API_KEY environment
variable so anyone can run it outside Muse.

Usage:
  export GEMINI_API_KEY="your key"   # PowerShell: $env:GEMINI_API_KEY = "your key"
  python3 standalone_compare.py

Writes results.json and raw/<run>.txt next to this script (fresh run each
time; rename the bundled results.json first if you want to keep it).

Note: the free tier for gemini-3.8-flash allows only 20 requests/day, and
retries count too. If you hit HTTP 429, wait for the quota to recover.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


API_KEY = os.environ.get("GEMINI_API_KEY", "")


def read_response_body(response, chunk_size=65536):
    chunks = []
    while True:
        chunk = response.read(chunk_size)
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "raw")
RESULTS_PATH = os.path.join(BASE_DIR, "results.json")

MODELS = ["gemini-4-hydrogen", "gemini-3.8-flash"]
VARIANTS = {
    "gemini-4-hydrogen": ["gemini-4-hydrogen-preview"],
    "gemini-3.8-flash": ["gemini-3.8-flash-preview"],
}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise RuntimeError("redirect refused, verify the endpoint")


def call_generate(model, prompt, generation_config):
    """One logical API call with retries. Returns a record dict.

    wall_seconds covers all attempts and inter-attempt sleeps.
    stall_retry is True when any retry was caused by a timeout/URLError stall
    or a 5xx response.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": generation_config,
    }
    payload = json.dumps(body).encode("utf-8")
    start = time.time()
    attempts = 0
    stall_retry = False
    stall_notes = []
    last_error = None
    last_status = None
    raw_text = None
    parsed = None
    for attempt in range(4):
        attempts += 1
        request = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY},
            method="POST",
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
                last_status = response.status
                raw_bytes = read_response_body(response)
                raw_text = raw_bytes.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw_text)
                except json.JSONDecodeError:
                    parsed = None
                return {
                    "http_status": last_status,
                    "error": None,
                    "raw_text": raw_text,
                    "parsed": parsed,
                    "attempts": attempts,
                    "wall_seconds": round(time.time() - start, 3),
                    "stall_retry": stall_retry,
                    "stall_notes": stall_notes,
                }
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_status = exc.code
            last_error = f"HTTP {exc.code}: {detail}"
            raw_text = detail
            if exc.code >= 500:
                stall_retry = True
                stall_notes.append(f"attempt {attempt + 1}: HTTP {exc.code} (5xx), retried")
            if exc.code < 500 or attempt == 3:
                break
            time.sleep(5)
        except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            stall_retry = True
            stall_notes.append(f"attempt {attempt + 1}: stall/timeout ({last_error}), retried")
            if attempt == 3:
                break
            time.sleep(5)
    return {
        "http_status": last_status,
        "error": last_error,
        "raw_text": raw_text,
        "parsed": parsed,
        "attempts": attempts,
        "wall_seconds": round(time.time() - start, 3),
        "stall_retry": stall_retry,
        "stall_notes": stall_notes,
    }


def extract_text(parsed):
    if not parsed:
        return ""
    try:
        parts = parsed["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)
    except (KeyError, IndexError, TypeError):
        return ""


def extract_usage(parsed):
    if not parsed:
        return None
    um = parsed.get("usageMetadata")
    if not um:
        return None
    return {
        "promptTokenCount": um.get("promptTokenCount"),
        "candidatesTokenCount": um.get("candidatesTokenCount"),
        "thoughtsTokenCount": um.get("thoughtsTokenCount"),
        "totalTokenCount": um.get("totalTokenCount"),
    }


def save_raw(name, text):
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text is not None else "")
    return name


# ---------------------------------------------------------------- prompts

T1_BUGGY = '''def moving_average(xs, k):
    if k <= 0:
        raise ValueError("k must be positive")
    if not xs or k > len(xs):
        return []
    out = []
    for i in range(len(xs) - k):
        window = xs[i:i + k]
        out.append(sum(window) / len(xs))
    return out'''

T1_PROMPT = f"""The following Python function is buggy:

```python
{T1_BUGGY}
```

Specification for `moving_average(xs, k)`:
- Returns a list of float averages, one for each full window of length k, in order.
- Returns [] if xs is empty or k > len(xs).
- Raises ValueError if k <= 0.

Reply with the corrected full function in a single python code block and nothing else."""

T2_PROMPT = """Implement a Python function `parse_duration(s)` that converts a duration string to total seconds (int).

Rules:
- Units: d = days, h = hours, m = minutes, s = seconds.
- Examples: "1h30m" -> 5400, "45s" -> 45, "2d 3h" -> 183600, "90m" -> 5400.
- Spaces between components are allowed.
- Raise ValueError on an unknown unit or on an empty string.

Reply with the function in a single python code block and nothing else."""

T3_MEMO = """Project update memo

Project Aurora will move into its second phase next month. The approved budget
is 12500000 JPY. The delivery deadline is 2027-03-15. The project owner is
Yuki Tanaka. Separately, the Vendor X pilot rollout has been cancelled and
will not proceed."""

T3_PROMPT = f"""Read this memo:

{T3_MEMO}

Reply with JSON only (no code fence, no extra text) with exactly these keys:
"project" (project name), "budget_jpy" (budget as a number, JPY),
"deadline" (date string), "owner" (owner name),
"cancelled_items" (array of strings naming items described as cancelled)."""

T3_TRUTH = {
    "project": "Project Aurora",
    "budget_jpy": 12500000,
    "deadline": "2027-03-15",
    "owner": "Yuki Tanaka",
    "cancelled_marker": "Vendor X",
}

T4_TEXT = """The TrailLite Backpack is a lightweight pack for day hikes. It has a 20L
capacity and a waterproof shell. It also has padded shoulder straps for
comfort on longer walks."""

T4_PROMPT = f"""Read this product description:

{T4_TEXT}

Reply in exactly this format and nothing else:
Line 1: NAME: <product name from the text>
Line 2: PRICE: not stated   (use exactly this if the text gives no price; do not invent a price)
Then exactly 3 bullet lines, each starting with "- ", listing features that appear in the text."""

# ---------------------------------------------------------------- harness

def extract_code(text):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1)
    return text


def check(fn):
    try:
        return bool(fn())
    except Exception:
        return False


def harness_t1(text):
    code = extract_code(text)
    ns = {}
    try:
        exec(code, ns)  # noqa: S102 - harness for generated code, local only
        f = ns["moving_average"]
    except Exception as exc:
        return 0, 5, {"exec_error": f"{type(exc).__name__}: {exc}"}
    checks = {
        "normal_window": check(lambda: f([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]),
        "k_equals_1": check(lambda: f([1, 2, 3], 1) == [1.0, 2.0, 3.0]),
        "empty_input": check(lambda: f([], 2) == []),
        "k_greater_than_len": check(lambda: f([1, 2], 5) == []),
        "value_error_k0": check(lambda: _raises_value_error(lambda: f([1, 2], 0))),
    }
    return sum(checks.values()), len(checks), checks


def _raises_value_error(fn):
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def harness_t2(text):
    code = extract_code(text)
    ns = {}
    try:
        exec(code, ns)  # noqa: S102
        f = ns["parse_duration"]
    except Exception as exc:
        return 0, 8, {"exec_error": f"{type(exc).__name__}: {exc}"}
    checks = {
        "1h30m": check(lambda: f("1h30m") == 5400),
        "45s": check(lambda: f("45s") == 45),
        "2d_3h": check(lambda: f("2d 3h") == 183600),
        "90m": check(lambda: f("90m") == 5400),
        "1h_only": check(lambda: f("1h") == 3600),
        "30m30s": check(lambda: f("30m30s") == 1830),
        "empty_raises": check(lambda: _raises_value_error(lambda: f(""))),
        "unknown_unit_raises": check(lambda: _raises_value_error(lambda: f("5x"))),
    }
    return sum(checks.values()), len(checks), checks


def harness_t3(text):
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
    except Exception as exc:
        return 0, 5, {"json_error": f"{type(exc).__name__}: {exc}"}
    checks = {
        "project": check(lambda: obj.get("project") == T3_TRUTH["project"]),
        "budget_jpy": check(lambda: obj.get("budget_jpy") == T3_TRUTH["budget_jpy"]),
        "deadline": check(lambda: obj.get("deadline") == T3_TRUTH["deadline"]),
        "owner": check(lambda: obj.get("owner") == T3_TRUTH["owner"]),
        "cancelled_items": check(
            lambda: isinstance(obj.get("cancelled_items"), list)
            and any(T3_TRUTH["cancelled_marker"] in str(x) for x in obj["cancelled_items"])
        ),
    }
    return sum(checks.values()), len(checks), checks


def harness_t4(text):
    lines = [ln for ln in text.strip().splitlines() if ln.strip() != ""]
    bullets = [ln for ln in lines if ln.lstrip().startswith("- ")]
    allowed_keywords = ["20l", "capacity", "waterproof", "shell", "padded",
                        "shoulder", "straps", "lightweight", "day hike"]
    forbidden = ["$", "¥", "warranty", "guarantee", "leather", "solar", "usb"]
    line1_ok = len(lines) >= 1 and lines[0].strip() == "NAME: TrailLite Backpack"
    line2 = lines[1].strip() if len(lines) >= 2 else ""
    line2_ok = line2 == "PRICE: not stated" and not any(ch.isdigit() for ch in line2)
    bullets_count_ok = len(bullets) == 3
    def bullets_clean():
        if not bullets:
            return False
        for b in bullets:
            low = b.lower()
            if any(fb in low for fb in forbidden):
                return False
            if not any(kw in low for kw in allowed_keywords):
                return False
        return True
    checks = {
        "line1_name": line1_ok,
        "line2_not_stated_no_number": bool(line2_ok),
        "exactly_3_bullets": bullets_count_ok,
        "bullets_only_text_features": check(bullets_clean),
    }
    return sum(checks.values()), len(checks), checks


HARNESS = {"T1": harness_t1, "T2": harness_t2, "T3": harness_t3, "T4": harness_t4}
PROMPTS = {"T1": T1_PROMPT, "T2": T2_PROMPT, "T3": T3_PROMPT, "T4": T4_PROMPT}

# ---------------------------------------------------------------- runner

results = {"probe": [], "runs": [], "notes": []}
# Per-model state: resolved model id and whether thinkingConfig must be omitted.
model_state = {}


def persist():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)


def probe_model(model):
    gen = {"maxOutputTokens": 256, "temperature": 0}
    tried = [model] + VARIANTS.get(model, [])
    for idx, candidate in enumerate(tried):
        res = call_generate(candidate, "Reply with exactly: OK", gen)
        raw_name = save_raw(f"probe_{candidate}.txt",
                             res["raw_text"] if res["raw_text"] is not None else (res["error"] or ""))
        rec = {
            "model_requested": model,
            "model_tried": candidate,
            "http_status": res["http_status"],
            "error": res["error"],
            "attempts": res["attempts"],
            "wall_seconds": res["wall_seconds"],
            "stall_retry": res["stall_retry"],
            "stall_notes": res["stall_notes"],
            "response_text": extract_text(res["parsed"]),
            "usage": extract_usage(res["parsed"]),
            "raw_file": raw_name,
        }
        results["probe"].append(rec)
        persist()
        print(f"[probe] {candidate}: HTTP {res['http_status']} attempts={res['attempts']} "
              f"wall={res['wall_seconds']}s text={rec['response_text']!r} err={res['error']}", flush=True)
        if res["http_status"] == 200:
            model_state[model] = {"model_used": candidate, "thinking_omitted": False,
                                  "thinking_error": None}
            if idx > 0:
                results["notes"].append(
                    f"{model}: original model ID failed; variant {candidate} succeeded and is used for all runs.")
                persist()
            return True
        # Only try a variant on 404/400 style failures, per spec.
        if res["http_status"] not in (400, 404):
            break
    return False


def run_task(task_id, model_requested, thinking_level):
    state = model_state[model_requested]
    model_used = state["model_used"]
    prompt = PROMPTS[task_id]
    gen = {"maxOutputTokens": 8192, "temperature": 0}
    thinking_omitted = state["thinking_omitted"]
    thinking_error = state["thinking_error"]
    effective_level = None
    if not thinking_omitted and thinking_level:
        gen["thinkingConfig"] = {"thinkingLevel": thinking_level}
        effective_level = thinking_level
    res = call_generate(model_used, prompt, gen)
    total_attempts = res["attempts"]
    total_wall = res["wall_seconds"]
    stall_retry = res["stall_retry"]
    stall_notes = list(res["stall_notes"])
    # Step E: thinkingConfig caused a 400 -> retry this model's runs without it.
    if res["http_status"] == 400 and effective_level and not thinking_omitted:
        thinking_error = res["error"]
        thinking_omitted = True
        state["thinking_omitted"] = True
        state["thinking_error"] = thinking_error
        gen2 = {"maxOutputTokens": 8192, "temperature": 0}
        res2 = call_generate(model_used, prompt, gen2)
        total_attempts += res2["attempts"]
        total_wall = round(total_wall + res2["wall_seconds"], 3)
        stall_retry = stall_retry or res2["stall_retry"]
        stall_notes += res2["stall_notes"]
        res = res2
        effective_level = None
        results["notes"].append(
            f"{model_requested}: thinkingConfig caused HTTP 400 ({thinking_error}); "
            f"retried without thinkingConfig and thinking is omitted for this model's runs.")
        persist()
    suffix = f"_{thinking_level}" if thinking_level else ""
    if thinking_omitted:
        suffix = "_nothinking"
    elif task_id == "T2" and thinking_level == "xhigh":
        suffix = "_xhigh"
    raw_name = save_raw(f"{task_id}_{model_used}{suffix}.txt",
                        res["raw_text"] if res["raw_text"] is not None else (res["error"] or ""))
    text = extract_text(res["parsed"])
    passed = total = None
    details = None
    if res["http_status"] == 200 and text:
        passed, total, details = HARNESS[task_id](text)
    else:
        passed, total, details = 0, {"T1": 5, "T2": 8, "T3": 5, "T4": 4}[task_id], {"no_response": True}
    rec = {
        "task": task_id,
        "model_requested": model_requested,
        "model": model_used,
        "thinking_requested": thinking_level,
        "thinking_level": effective_level,
        "thinking_omitted": thinking_omitted,
        "thinking_omitted_reason": thinking_error if thinking_omitted else None,
        "http_status": res["http_status"],
        "error": res["error"],
        "wall_seconds": total_wall,
        "attempts": total_attempts,
        "stall_retry": stall_retry,
        "stall_notes": stall_notes,
        "usage": extract_usage(res["parsed"]),
        "score_passed": passed,
        "score_total": total,
        "score": (passed / total) if total else None,
        "harness_details": details,
        "response_text": text,
        "raw_file": raw_name,
    }
    results["runs"].append(rec)
    persist()
    print(f"[{task_id}] {model_used} level={effective_level} HTTP {res['http_status']} "
          f"score={passed}/{total} wall={total_wall}s attempts={total_attempts} "
          f"stall_retry={stall_retry} err={res['error']}", flush=True)
    return rec


def load_existing():
    """Standalone version: no resume. Every run starts fresh."""
    return
    # --- original resume logic kept unreachable for reference ---
    if not os.path.exists(RESULTS_PATH):
        return
    try:
        with open(RESULTS_PATH, encoding="utf-8") as f:
            prev = json.load(f)
    except Exception:
        return
    results["probe"] = prev.get("probe", [])
    results["runs"] = prev.get("runs", [])
    results["notes"] = prev.get("notes", [])
    for rec in results["probe"]:
        if rec.get("http_status") == 200:
            model_state[rec["model_requested"]] = {
                "model_used": rec["model_tried"], "thinking_omitted": False,
                "thinking_error": None}
    # If any earlier run had thinking omitted for a model, keep omitting it.
    for rec in results["runs"]:
        if rec.get("thinking_omitted") and rec["model_requested"] in model_state:
            model_state[rec["model_requested"]]["thinking_omitted"] = True
            model_state[rec["model_requested"]]["thinking_error"] = rec.get("thinking_omitted_reason")


def already_ran(task_id, model_requested, thinking_level):
    for rec in results["runs"]:
        if rec.get("task") != task_id or rec.get("model_requested") != model_requested:
            continue
        req = rec.get("thinking_requested", rec.get("thinking_level"))
        if req == thinking_level:
            return True
    return False


def main():
    if not API_KEY:
        print("GEMINI_API_KEY is not set. Get a key at https://aistudio.google.com/apikey "
              "and set it in the environment (never in this file).", file=sys.stderr)
        return 2
    os.makedirs(RAW_DIR, exist_ok=True)
    load_existing()
    if results["probe"] or results["runs"]:
        results["notes"].append("Resumed: reused earlier probe/run records from results.json.")
        persist()
    ok = {}
    for model in MODELS:
        if model in model_state:
            ok[model] = True
            print(f"[probe] {model}: already probed OK in an earlier invocation, skipping", flush=True)
            continue
        # Probe cycles: a 5xx / network failure is transient (Google's 503 says
        # "try again later"), so wait 60s and re-probe, up to 3 cycles total.
        # A 404/400 after variants are exhausted stops immediately (spec step A).
        success = False
        for cycle in range(3):
            if probe_model(model):
                success = True
                break
            last = [r for r in results["probe"] if r["model_requested"] == model]
            last_status = last[-1]["http_status"] if last else None
            if last_status in (400, 404) or cycle == 2:
                break
            print(f"[probe] {model}: transient failure (HTTP {last_status}), "
                  f"waiting 60s before probe cycle {cycle + 2}/3", flush=True)
            results["notes"].append(
                f"{model}: probe cycle {cycle + 1} failed with HTTP {last_status}; retrying probe after 60s (transient 5xx).")
            persist()
            time.sleep(60)
        ok[model] = success
    failed = [m for m, v in ok.items() if not v]
    if failed:
        results["notes"].append(
            f"STOPPED: probe failed for {failed}; main runs not executed. See probe records for verbatim errors and variants tried.")
        persist()
        print(f"STOPPED: probe failed for {failed}", flush=True)
        return 1
    for task_id in ["T1", "T2", "T3", "T4"]:
        for model in MODELS:
            if already_ran(task_id, model, "high"):
                print(f"[{task_id}] {model}: already ran in an earlier invocation, skipping", flush=True)
                continue
            run_task(task_id, model, "high")
    # Extra: T2 with Hydrogen at xhigh.
    if not already_ran("T2", "gemini-4-hydrogen", "xhigh"):
        run_task("T2", "gemini-4-hydrogen", "xhigh")
    persist()
    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
