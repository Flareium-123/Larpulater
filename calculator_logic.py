# calculator_logic.py - Pure math evaluation (safe)
import math
import random
import re


def safe_eval(expr: str) -> float:
    """Evaluate a math expression string safely. Returns float result."""
    # Replace display symbols with Python equivalents
    expr = expr.replace("×", "*").replace("÷", "/").replace("−", "-")
    expr = expr.replace("π", str(math.pi)).replace("e", str(math.e))
    expr = expr.replace("^", "**")
    expr = expr.replace("√(", "math.sqrt(").replace("√", "math.sqrt(")

    # Replace trig/log functions
    expr = re.sub(r'\bsin\b', 'math.sin', expr)
    expr = re.sub(r'\bcos\b', 'math.cos', expr)
    expr = re.sub(r'\btan\b', 'math.tan', expr)
    expr = re.sub(r'\bln\b',  'math.log', expr)
    expr = re.sub(r'\blog\b', 'math.log10', expr)
    expr = re.sub(r'\babs\b', 'abs', expr)
    expr = re.sub(r'\bfloor\b', 'math.floor', expr)
    expr = re.sub(r'\bceil\b', 'math.ceil', expr)

    allowed_names = {
        "__builtins__": {},
        "math": math,
        "abs": abs,
        "round": round,
    }
    result = eval(expr, allowed_names)  # noqa: S307
    return float(result)


def format_number(n: float) -> str:
    """Format a number nicely."""
    if n == int(n) and abs(n) < 1e15:
        return str(int(n))
    # up to 10 sig figs, strip trailing zeros
    formatted = f"{n:.10g}"
    return formatted


def generate_distractors(true_val: float) -> list[str]:
    """Generate 2 plausible wrong answers near the true value."""
    distractors = set()
    attempts = 0
    while len(distractors) < 2 and attempts < 50:
        attempts += 1
        strategy = random.randint(0, 4)
        if strategy == 0:
            # small additive noise
            noise = random.uniform(-abs(true_val) * 0.3 - 1, abs(true_val) * 0.3 + 1)
            cand = true_val + noise
        elif strategy == 1:
            # multiply by near-1
            cand = true_val * random.uniform(0.7, 1.3)
        elif strategy == 2:
            # round to fewer sig figs
            if true_val != 0:
                mag = 10 ** (len(str(int(abs(true_val)))) - 1)
                cand = round(true_val / mag) * mag + random.choice([-1, 1]) * mag * 0.5
            else:
                cand = random.uniform(-5, 5)
        elif strategy == 3:
            # negate or reciprocal variant
            cand = -true_val if true_val != 0 else random.uniform(1, 10)
        else:
            # integer neighbor
            cand = int(true_val) + random.choice([-2, -1, 1, 2])

        cand = round(cand, 10)
        cand_str = format_number(cand)
        true_str = format_number(true_val)
        if cand_str != true_str:
            distractors.add(cand_str)

    result = list(distractors)[:2]
    while len(result) < 2:
        result.append(format_number(true_val + random.randint(1, 9)))
    return result


def build_choices(true_val: float) -> list[dict]:
    """
    Build 4 multiple-choice entries.
    Returns list of dicts: {label, text, is_correct}
    Shuffled so the correct answer is at a random position (never D).
    D is always 'None of the above'.
    """
    true_str = format_number(true_val)
    distractors = generate_distractors(true_val)

    # Slots A, B, C: shuffle correct + 2 distractors
    slot_values = [true_str] + distractors
    random.shuffle(slot_values)

    labels = ["A", "B", "C"]
    choices = []
    for lbl, val in zip(labels, slot_values):
        choices.append({
            "label": lbl,
            "text": val,
            "is_correct": (val == true_str),
        })
    # D is always "None of the above" (never correct)
    choices.append({
        "label": "D",
        "text": "None of the above",
        "is_correct": False,
    })
    return choices
