"""Math engine for the Calculator app: evaluates expressions, explains each step, solves equations.

Expressions are parsed with Python's ast module and walked by hand, so nothing the user
types is ever run as code. Every operation the walker performs can be recorded as a step
written in plain language.
"""

import ast
import math
import re

MAX_STEPS = 40
MAX_EXPONENT = 10_000
MAX_FACTORIAL = 170
MAX_LENGTH = 500


class MathError(ValueError):
    """A problem with the user's math, phrased so they can fix it."""


def fmt(value):
    """Show a number the way a person would write it."""
    if isinstance(value, bool):
        value = int(value)
    if isinstance(value, int):
        if abs(value) < 10**15:
            return str(value)
        if value.bit_length() > 1000:
            raise MathError("That number is too big to work with.")
        return f"{float(value):.12g}"
    if math.isnan(value):
        raise MathError("That calculation doesn't give a real number.")
    if math.isinf(value):
        raise MathError("That number is too big to work with.")
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.12g}"


def _clean(value):
    """Drop floating-point noise like 0.30000000000000004 or 1e-17."""
    if isinstance(value, float):
        if abs(value) < 1e-12:
            return 0.0
        rounded = round(value, 12)
        if abs(rounded - value) < 1e-12 * max(1.0, abs(value)):
            return rounded
    return value


# ---- Functions -------------------------------------------------------------
# Each entry: (minimum args, maximum args, group, signature, what it does, example).

def _need_whole(name, *values):
    for v in values:
        if v != int(v) or v < 0:
            raise MathError(f"{name} needs whole numbers that aren't negative.")
    return [int(v) for v in values]


def _sqrt(x):
    if x < 0:
        raise MathError(f"Negative numbers don't have a real square root, so √{fmt(x)} has no answer here.")
    return math.sqrt(x)


def _root(x, n):
    if n == 0:
        raise MathError("A 0th root isn't defined. Use a number like 2 for square root or 3 for cube root.")
    if x < 0:
        if n == int(n) and int(n) % 2 == 1:
            return -((-x) ** (1 / n))
        raise MathError(f"Negative numbers don't have a real root of order {fmt(n)}.")
    return x ** (1 / n)


def _log(x, base=10):
    if x <= 0:
        raise MathError(f"Logarithms only work for numbers above 0, and {fmt(x)} isn't.")
    if base <= 0 or base == 1:
        raise MathError("A logarithm's base has to be above 0 and not 1.")
    return math.log(x, base) if base != 10 else math.log10(x)


def _ln(x):
    if x <= 0:
        raise MathError(f"ln only works for numbers above 0, and {fmt(x)} isn't.")
    return math.log(x)


def _factorial(n):
    (n,) = _need_whole("Factorial", n)
    if n > MAX_FACTORIAL:
        raise MathError(f"Factorials above {MAX_FACTORIAL}! are too big to work with.")
    return math.factorial(n)


def _ncr(n, r):
    n, r = _need_whole("nCr", n, r)
    if r > n:
        return 0
    return math.comb(n, r)


def _npr(n, r):
    n, r = _need_whole("nPr", n, r)
    if r > n:
        return 0
    return math.perm(n, r)


def _gcd(*values):
    return math.gcd(*_need_whole("gcd", *values))


def _lcm(*values):
    return math.lcm(*_need_whole("lcm", *values))


def _mean(*values):
    return sum(values) / len(values)


def _median(*values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


FUNCTIONS = {
    "sqrt": (_sqrt, 1, 1, "Powers and roots", "sqrt(x)", "Square root: the number that multiplied by itself gives x.", "sqrt(144)"),
    "cbrt": (lambda x: _root(x, 3), 1, 1, "Powers and roots", "cbrt(x)", "Cube root: the number that multiplied by itself three times gives x.", "cbrt(27)"),
    "root": (_root, 2, 2, "Powers and roots", "root(x, n)", "The nth root of x.", "root(81, 4)"),
    "exp": (math.exp, 1, 1, "Powers and roots", "exp(x)", "e raised to the power x.", "exp(1)"),
    "abs": (abs, 1, 1, "Basics", "abs(x)", "Distance from zero, so it's never negative.", "abs(-7)"),
    "round": (lambda x, n=0: round(x, int(n)), 1, 2, "Basics", "round(x, places)", "Round to a number of decimal places (0 if you leave it out).", "round(3.14159, 2)"),
    "floor": (math.floor, 1, 1, "Basics", "floor(x)", "Round down to a whole number.", "floor(4.8)"),
    "ceil": (math.ceil, 1, 1, "Basics", "ceil(x)", "Round up to a whole number.", "ceil(4.2)"),
    "sin": (None, 1, 1, "Trigonometry", "sin(angle)", "Sine: in a right triangle, opposite side ÷ longest side.", "sin(30)"),
    "cos": (None, 1, 1, "Trigonometry", "cos(angle)", "Cosine: adjacent side ÷ longest side.", "cos(60)"),
    "tan": (None, 1, 1, "Trigonometry", "tan(angle)", "Tangent: opposite side ÷ adjacent side.", "tan(45)"),
    "asin": (None, 1, 1, "Trigonometry", "asin(x)", "The angle whose sine is x.", "asin(0.5)"),
    "acos": (None, 1, 1, "Trigonometry", "acos(x)", "The angle whose cosine is x.", "acos(0.5)"),
    "atan": (None, 1, 1, "Trigonometry", "atan(x)", "The angle whose tangent is x.", "atan(1)"),
    "hypot": (math.hypot, 2, 2, "Trigonometry", "hypot(a, b)", "Longest side of a right triangle with sides a and b.", "hypot(3, 4)"),
    "log": (_log, 1, 2, "Logarithms", "log(x, base)", "What power of the base gives x. The base is 10 if you leave it out.", "log(1000)"),
    "ln": (_ln, 1, 1, "Logarithms", "ln(x)", "Natural logarithm: log with base e.", "ln(e^2)"),
    "log2": (lambda x: _log(x, 2), 1, 1, "Logarithms", "log2(x)", "Logarithm with base 2.", "log2(1024)"),
    "fact": (_factorial, 1, 1, "Counting", "n!", "Factorial: n × (n−1) × … × 1. Also written fact(n).", "5!"),
    "nCr": (_ncr, 2, 2, "Counting", "nCr(n, r)", "Ways to choose r things from n when order doesn't matter.", "nCr(10, 3)"),
    "nPr": (_npr, 2, 2, "Counting", "nPr(n, r)", "Ways to arrange r things from n when order matters.", "nPr(10, 3)"),
    "gcd": (_gcd, 2, 20, "Counting", "gcd(a, b)", "Greatest common divisor: the biggest number that divides all of them.", "gcd(48, 18)"),
    "lcm": (_lcm, 2, 20, "Counting", "lcm(a, b)", "Least common multiple: the smallest number they all divide into.", "lcm(4, 6)"),
    "mean": (_mean, 1, 100, "Statistics", "mean(a, b, …)", "The average: add them up and divide by how many there are.", "mean(4, 8, 15)"),
    "median": (_median, 1, 100, "Statistics", "median(a, b, …)", "The middle value once they're sorted.", "median(3, 9, 1, 7)"),
    "min": (min, 1, 100, "Statistics", "min(a, b, …)", "The smallest value.", "min(4, -2, 9)"),
    "max": (max, 1, 100, "Statistics", "max(a, b, …)", "The largest value.", "max(4, -2, 9)"),
}

CONSTANTS = {
    "pi": (math.pi, "π, the distance around a circle divided by the distance across it"),
    "e": (math.e, "e, the base of natural logarithms"),
    "tau": (math.tau, "τ, which is 2π"),
    "phi": ((1 + math.sqrt(5)) / 2, "φ, the golden ratio"),
}

GUIDE_EXTRAS = [
    ("Basics", "+  −  ×  ÷", "Add, subtract, multiply and divide. You can type * and / too.", "12 × (3 + 4)"),
    ("Basics", "x% of y", "Percentages. 15% on its own means 0.15.", "15% of 80"),
    ("Basics", "a mod b", "The remainder after dividing a by b.", "17 mod 5"),
    ("Powers and roots", "x^y", "x raised to the power y. You can also type x**y.", "2^10"),
    ("Equations", "solve with =", "Type an equation with one unknown letter and PyOS solves it.", "2x + 3 = 11"),
    ("Equations", "quadratics", "Equations with x² are solved with the quadratic formula, shown step by step.", "x^2 - 5x + 6 = 0"),
    ("Equations", "save a value", "Type a letter = a number to save it, then use the letter later. ans is the last answer.", "r = 4"),
]


def guide():
    """The function reference shown in the Calculator's guide panel."""
    entries = [{"group": g, "name": sig, "about": about, "example": ex} for g, sig, about, ex in GUIDE_EXTRAS]
    for _, _, _, group, sig, about, example in FUNCTIONS.values():
        entries.append({"group": group, "name": sig, "about": about, "example": example})
    for name, (_, about) in CONSTANTS.items():
        entries.append({"group": "Constants", "name": name, "about": about[0].upper() + about[1:] + ".", "example": f"2 * {name}"})
    order = ["Basics", "Powers and roots", "Equations", "Trigonometry", "Logarithms", "Counting", "Statistics", "Constants"]
    return sorted(entries, key=lambda e: order.index(e["group"]))


# ---- Parsing ---------------------------------------------------------------

def normalize(text):
    """Turn friendly math notation into something Python's parser accepts."""
    expr = text.strip()
    for friendly, plain in (("×", "*"), ("÷", "/"), ("−", "-"), ("–", "-"), ("√", "sqrt"), ("π", "pi"), ("²", "^2"), ("³", "^3")):
        expr = expr.replace(friendly, plain)
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\b", r"(\1/100)*", expr)
    expr = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", expr)
    expr = re.sub(r"\bmod\b", "%", expr)
    expr = _factorials(expr)
    expr = expr.replace("^", "**")
    # Implicit multiplication: 2x, 2(x+1), (a)(b), (a)x. Leave names like log2 and
    # scientific notation like 2e5 alone.
    expr = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?![eE][+-]?\d)([A-Za-z_(])", r"\1*\2", expr)
    # A space between a name and what follows means multiply too (pi r^2), except after a function name.
    expr = re.sub(r"\b([A-Za-z_]\w*)\s+(?=[A-Za-z_\d(])",
                  lambda m: m.group(1) + ("" if m.group(1) in FUNCTIONS else "*"), expr)
    expr = re.sub(r"\)\s*([A-Za-z_\d(])", r")*\1", expr)
    return expr


def _factorials(expr):
    """Rewrite n! as fact(n), including (expression)!. Leaves != alone."""
    out = expr
    while True:
        match = re.search(r"!(?!=)", out)
        if not match:
            return out
        end = match.start()
        start = end
        while start > 0 and out[start - 1] == " ":
            start -= 1
        if start > 0 and out[start - 1] == ")":
            depth, i = 0, start - 1
            while i >= 0:
                depth += {")": 1, "(": -1}.get(out[i], 0)
                if depth == 0:
                    break
                i -= 1
            if i < 0:
                raise MathError("The brackets don't match. There's a missing (.")
            begin = i
        else:
            token = re.search(r"(\d+(?:\.\d+)?|[A-Za-z_]\w*)$", out[:start])
            if not token:
                raise MathError("Put a number before ! to take its factorial, like 5!.")
            begin = token.start()
        out = f"{out[:begin]}fact({out[begin:start]}){out[end + 1:]}"


def parse(text):
    if len(text) > MAX_LENGTH:
        raise MathError(f"That's longer than {MAX_LENGTH} characters. Try splitting it up.")
    expr = normalize(text)
    if not expr:
        raise MathError("Type something to calculate, like 2 + 2.")
    if expr.count("(") != expr.count(")"):
        missing = "(" if expr.count("(") < expr.count(")") else ")"
        raise MathError(f"The brackets don't match. There's a missing {missing}.")
    try:
        return ast.parse(expr, mode="eval").body
    except SyntaxError:
        raise MathError("PyOS couldn't read that. Check for a missing number or operator.")


# ---- Evaluation ------------------------------------------------------------

OPS = {
    ast.Add: ("+", "add"), ast.Sub: ("−", "subtract"), ast.Mult: ("×", "multiply"),
    ast.Div: ("÷", "divide"), ast.Pow: ("^", "power"), ast.Mod: ("mod", "remainder"),
}


class Evaluator:
    def __init__(self, angle="deg", variables=None, record=True):
        self.angle = angle
        self.variables = dict(variables or {})
        self.record = record
        self.steps = []
        self.hidden_steps = 0

    def step(self, text):
        if not self.record:
            return
        if len(self.steps) < MAX_STEPS:
            self.steps.append(text)
        else:
            self.hidden_steps += 1

    def run(self, node):
        value = _clean(self.eval(node))
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            raise MathError("That number is too big to work with.")
        return value

    def eval(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name):
            return self.name(node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = self.eval(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return self.binop(node)
        if isinstance(node, ast.Call):
            return self.call(node)
        raise MathError("PyOS can do numbers, + − × ÷ ^, brackets and the functions in the guide.")

    def name(self, name):
        if name in self.variables:
            return self.variables[name]
        if name in CONSTANTS:
            return CONSTANTS[name][0]
        if name in FUNCTIONS:
            raise MathError(f"{name} is a function. Put a number in brackets after it, like {name}(2).")
        raise MathError(f"PyOS doesn't know what {name} is. Save it first with {name} = a number, or use = to solve for it.")

    def binop(self, node):
        left, right = self.eval(node.left), self.eval(node.right)
        symbol, kind = OPS[type(node.op)]
        try:
            if kind == "add":
                result = left + right
            elif kind == "subtract":
                result = left - right
            elif kind == "multiply":
                result = left * right
            elif kind == "divide":
                if right == 0:
                    raise MathError("Dividing by zero isn't defined, so this has no answer.")
                result = left / right
            elif kind == "remainder":
                if right == 0:
                    raise MathError("There's no remainder when dividing by zero.")
                result = left % right
            else:
                if abs(right) > MAX_EXPONENT:
                    raise MathError("That exponent is too big to work with.")
                if left < 0 and right != int(right):
                    raise MathError(f"A negative number to the power {fmt(right)} isn't a real number.")
                if left == 0 and right < 0:
                    raise MathError("0 to a negative power means dividing by zero, so it has no answer.")
                result = left ** right
        except OverflowError:
            raise MathError("That number is too big to work with.")
        if isinstance(result, int) and result.bit_length() > 1000:
            raise MathError("That number is too big to work with.")
        result = _clean(result)
        if kind == "power":
            self.step(f"{fmt(left)}^{fmt(right)} = {fmt(result)}" + self._power_note(left, right))
        elif kind == "remainder":
            self.step(f"{fmt(left)} mod {fmt(right)} = {fmt(result)}, the remainder after dividing {fmt(left)} by {fmt(right)}")
        else:
            self.step(f"{fmt(left)} {symbol} {fmt(right)} = {fmt(result)}")
        return result

    @staticmethod
    def _power_note(base, exponent):
        if exponent == int(exponent) and 2 <= exponent <= 5:
            return f", which is {' × '.join([fmt(base)] * int(exponent))}"
        if exponent == 0.5:
            return ", which is the same as a square root"
        if exponent < 0:
            return f", which is 1 ÷ {fmt(base)}^{fmt(-exponent)}"
        return ""

    def call(self, node):
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            name = node.func.id if isinstance(node.func, ast.Name) else "that"
            raise MathError(f"PyOS doesn't have a function called {name}. Open the guide to see what's available.")
        if node.keywords:
            raise MathError("Functions here take plain values separated by commas.")
        name = node.func.id
        func, low, high, _, signature, *_ = FUNCTIONS[name]
        if not low <= len(node.args) <= high:
            raise MathError(f"{name} is written {signature}.")
        args = [self.eval(a) for a in node.args]
        try:
            result = self.trig(name, args[0]) if func is None else func(*args)
        except (OverflowError, ValueError) as exc:
            if isinstance(exc, MathError):
                raise
            raise MathError(f"{name} can't work with {', '.join(fmt(a) for a in args)}.")
        result = _clean(result)
        self.step(self._explain(name, args, result))
        return result

    def trig(self, name, x):
        deg = self.angle == "deg"
        if name in ("sin", "cos", "tan"):
            if deg and x % 90 == 0:
                quarter = int(x // 90) % 4
                exact = {"sin": (0, 1, 0, -1), "cos": (1, 0, -1, 0), "tan": (0, None, 0, None)}[name][quarter]
                if exact is None:
                    raise MathError(f"tan({fmt(x)}°) is undefined, because cos({fmt(x)}°) is 0.")
                return exact
            return getattr(math, name)(math.radians(x) if deg else x)
        if name in ("asin", "acos") and not -1 <= x <= 1:
            raise MathError(f"{name} only works for numbers from −1 to 1.")
        angle = getattr(math, name)(x)
        return math.degrees(angle) if deg else angle

    def _explain(self, name, args, result):
        a = [fmt(v) for v in args]
        r = fmt(result)
        unit = "°" if self.angle == "deg" else " radians"
        if name == "sqrt":
            return f"√{a[0]} = {r}, because {r} × {r} = {a[0]}" if result == int(result) else f"√{a[0]} = {r}"
        if name == "cbrt":
            return f"∛{a[0]} = {r}" + (f", because {r} × {r} × {r} = {a[0]}" if result == int(result) else "")
        if name == "fact":
            n = int(args[0])
            chain = " × ".join(str(i) for i in range(n, 0, -1)) if 1 < n <= 8 else ""
            return f"{n}! = {chain + ' = ' if chain else ''}{r}"
        if name in ("sin", "cos", "tan"):
            return f"{name}({a[0]}{unit}) = {r}"
        if name in ("asin", "acos", "atan"):
            return f"{name}({a[0]}) = {r}{unit}"
        if name == "log":
            base = a[1] if len(a) > 1 else "10"
            return f"log base {base} of {a[0]} = {r}, because {base}^{r} = {a[0]}"
        if name == "ln":
            return f"ln({a[0]}) = {r}, because e^{r} = {a[0]}"
        if name == "nCr":
            return f"Choosing {a[1]} from {a[0]} when order doesn't matter: {r} ways"
        if name == "nPr":
            return f"Arranging {a[1]} from {a[0]} when order matters: {r} ways"
        if name == "mean":
            return f"Average of {', '.join(a)}: ({' + '.join(a)}) ÷ {len(a)} = {r}"
        return f"{name}({', '.join(a)}) = {r}"


# ---- Equations -------------------------------------------------------------

def _paren(value):
    """Wrap negative numbers in brackets inside a formula, like (−5)²."""
    text = fmt(value)
    return f"({text})" if value < 0 else text


def _signed(value):
    """Show '+ 3' or '− 3' for the next term of an expression."""
    return f"− {fmt(-value)}" if value < 0 else f"+ {fmt(value)}"


def _free_names(node, known):
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id not in known and sub.id not in FUNCTIONS:
            names.add(sub.id)
    return names


def _equation_sides(text):
    left, right = text.split("=", 1)
    if "=" in right:
        raise MathError("Use one = sign per equation.")
    if not left.strip() or not right.strip():
        raise MathError("Put something on both sides of the =.")
    return left, right


def solve(text, angle, variables):
    left_text, right_text = _equation_sides(text)
    left, right = parse(left_text), parse(right_text)
    known = set(variables) | set(CONSTANTS)
    unknowns = _free_names(left, known) | _free_names(right, known)
    if not unknowns:
        # An equation that only uses saved letters still means "solve", e.g. 2x + 3 = 11
        # after saving x earlier. Solve for x if it's there, or for the only saved letter used.
        used = (_free_names(left, set(CONSTANTS)) | _free_names(right, set(CONSTANTS))) - {"ans"}
        if "x" in used or len(used) == 1:
            unknowns = {"x"} if "x" in used else used
            variables = {k: v for k, v in variables.items() if k not in unknowns}
        else:
            return _check_equality(left, right, angle, variables, text)
    if len(unknowns) > 1:
        raise MathError(f"There's more than one unknown ({', '.join(sorted(unknowns))}). Save values for all but one first, like {sorted(unknowns)[0]} = 2.")
    var = unknowns.pop()

    def f(x):
        ev = Evaluator(angle, {**variables, var: x}, record=False)
        return ev.run(left) - ev.run(right)

    steps = [f"Move everything to one side: ({left_text.strip()}) − ({right_text.strip()}) = 0"]
    try:
        c = f(0)
        a = (f(1) + f(-1)) / 2 - c
        b = (f(1) - f(-1)) / 2
        is_quadratic = all(
            abs(f(t) - (a * t * t + b * t + c)) <= 1e-9 * (1 + abs(f(t))) for t in (2, -3, 0.5, 7, -11)
        )
    except MathError:
        is_quadratic = False
    a, b, c = (_clean(v) for v in (a, b, c)) if is_quadratic else (0, 0, 0)

    if is_quadratic and a == 0:
        if b == 0:
            if c == 0:
                return _solved(var, [], steps + ["Both sides are always equal, so every number works."], every=True)
            return _solved(var, [], steps + [f"That simplifies to {fmt(c)} = 0, which is never true, so there's no solution."])
        steps.append(f"This is a straight-line equation: {fmt(b)}{var} {_signed(c)} = 0")
        if c:
            action = f"Add {fmt(-c)} to" if c < 0 else f"Subtract {fmt(c)} from"
            steps.append(f"{action} both sides: {fmt(b)}{var} = {fmt(_clean(-c))}")
        root = _clean(-c / b)
        steps.append(f"Divide both sides by {fmt(b)}: {var} = {fmt(_clean(-c))} ÷ {_paren(b)} = {fmt(root)}")
        return _solved(var, [root], steps)

    if is_quadratic:
        steps.append(f"This is a quadratic: a{var}² + b{var} + c = 0 with a = {fmt(a)}, b = {fmt(b)}, c = {fmt(c)}")
        disc = _clean(b * b - 4 * a * c)
        steps.append(f"Discriminant b² − 4ac = {_paren(b)}² − 4 × {_paren(a)} × {_paren(c)} = {fmt(disc)}")
        if disc < 0:
            steps.append("The discriminant is negative, so there are no real solutions.")
            return _solved(var, [], steps)
        if disc == 0:
            root = _clean(-b / (2 * a))
            steps.append(f"The discriminant is 0, so there's one solution: {var} = −b ÷ 2a = {fmt(root)}")
            return _solved(var, [root], steps)
        sq = math.sqrt(disc)
        roots = sorted({_clean((-b - sq) / (2 * a)), _clean((-b + sq) / (2 * a))})
        steps.append(f"Quadratic formula: {var} = (−b ± √{fmt(disc)}) ÷ 2a = ({fmt(_clean(-b))} ± {fmt(_clean(sq))}) ÷ {_paren(2 * a)}")
        steps.append(f"So {var} = {fmt(roots[0])} or {var} = {fmt(roots[1])}")
        return _solved(var, roots, steps)

    steps.append(f"This isn't a straight-line or quadratic equation, so PyOS searches for values of {var} that make both sides equal.")
    roots = _numeric_roots(f)
    for r in roots:
        steps.append(f"Found {var} ≈ {fmt(r)} (both sides come out within 0.000000001 of each other)")
    if not roots:
        steps.append(f"No real solution turned up between −10000 and 10000.")
    return _solved(var, roots, steps, approximate=True)


def _numeric_roots(f, limit=10):
    points = sorted({0.0} | {s * m * 10.0**k for s in (1, -1) for k in range(-2, 4) for m in range(1, 10)} | {s * 10000.0 for s in (1, -1)})
    samples = []
    for x in points:
        try:
            samples.append((x, f(x)))
        except MathError:
            samples.append((x, None))
    roots = []
    for (x0, y0), (x1, y1) in zip(samples, samples[1:]):
        if y0 is None or y1 is None:
            continue
        if y0 == 0:
            roots.append(x0)
        elif y0 * y1 < 0:
            lo, hi, flo = x0, x1, y0
            for _ in range(200):
                mid = (lo + hi) / 2
                try:
                    fm = f(mid)
                except MathError:
                    break
                if fm == 0 or hi - lo < 1e-13 * max(1.0, abs(mid)):
                    break
                if (fm < 0) == (flo < 0):
                    lo, flo = mid, fm
                else:
                    hi = mid
            mid = (lo + hi) / 2
            try:
                if abs(f(mid)) < 1e-9 * max(1.0, abs(mid)):
                    roots.append(_clean(round(mid, 10)))
            except MathError:
                pass
    if samples and samples[-1][1] == 0:
        roots.append(samples[-1][0])
    unique = []
    for r in sorted(roots):
        if not unique or abs(r - unique[-1]) > 1e-8:
            unique.append(r)
    return unique[:limit]


def _solved(var, roots, steps, approximate=False, every=False):
    if every:
        result = "Every number works"
    elif not roots:
        result = "No real solution"
    else:
        sign = "≈" if approximate else "="
        result = " or ".join(f"{var} {sign} {fmt(r)}" for r in roots)
    return {"kind": "solve", "variable": var, "solutions": [float(r) for r in roots], "result": result, "steps": steps}


def _check_equality(left, right, angle, variables, text):
    ev = Evaluator(angle, variables)
    lv, rv = ev.run(left), ev.run(right)
    equal = abs(lv - rv) <= 1e-9 * max(1.0, abs(lv), abs(rv))
    steps = ev.steps + [f"Left side is {fmt(lv)} and right side is {fmt(rv)}"]
    return {"kind": "check", "result": "True" if equal else "False", "steps": steps}


# ---- Entry point -----------------------------------------------------------

NAME_RE = re.compile(r"^[A-Za-z_]\w{0,15}$")


def calculate(text, angle="deg", variables=None):
    """Work out one line from the Calculator. Returns a dict for the API."""
    if angle not in ("deg", "rad"):
        raise MathError("Angle mode must be deg or rad.")
    variables = {
        k: float(v) for k, v in (variables or {}).items()
        if isinstance(k, str) and NAME_RE.match(k) and isinstance(v, (int, float)) and not isinstance(v, bool)
        and k not in CONSTANTS and k not in FUNCTIONS
    }
    text = (text or "").strip()
    text = re.sub(r"^solve\s+", "", text, flags=re.IGNORECASE)

    if "=" in text:
        left, right = _equation_sides(text)
        name = left.strip()
        if NAME_RE.match(name) and name not in CONSTANTS and name not in FUNCTIONS and name not in _free_names(parse(right), set()):
            ev = Evaluator(angle, variables)
            value = ev.run(parse(right))
            ev.step(f"Saved {name} = {fmt(value)}. You can use {name} in later calculations.")
            return {"kind": "assign", "variable": name, "value": float(value), "result": f"{name} = {fmt(value)}", "steps": ev.steps}
        return solve(text, angle, variables)

    ev = Evaluator(angle, variables)
    value = ev.run(parse(text))
    steps = ev.steps
    if ev.hidden_steps:
        steps.append(f"…and {ev.hidden_steps} more steps")
    return {"kind": "value", "value": float(value), "result": fmt(value), "steps": steps}
