"""A small shell that works inside the PyOS home folder."""

import ast
import datetime
import math
import operator
import posixpath
import shlex

from .storage import SandboxError

HELP = """\
help              show this list
ls [folder]       list a folder
cd [folder]       change folder (cd with no folder goes home)
pwd               show the current folder
cat <file>        print a text file
mkdir <name>      make a folder
touch <name>      make an empty file
rm <path>         delete a file or folder
mv <path> <name>  rename a file or folder
echo <text>       print text; echo <text> > <file> writes it to a file
calc <expr>       do arithmetic, like calc sqrt(2) * 10
date              show the date and time
whoami            show your user name
clear             clear the screen"""

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {name: getattr(math, name) for name in (
    "sqrt", "sin", "cos", "tan", "log", "log10", "exp", "floor", "ceil", "factorial",
)}
_FUNCS.update(abs=abs, round=round, min=min, max=max)
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_eval(expr):
    """Evaluate arithmetic without handing the expression to Python's eval."""

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("That exponent is too large.")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCS and not node.keywords):
            return _FUNCS[node.func.id](*(walk(a) for a in node.args))
        raise ValueError("calc understands numbers, + - * / // % **, and math functions.")

    return walk(ast.parse(expr, mode="eval"))


class Terminal:
    def __init__(self, storage):
        self.storage = storage

    def _join(self, cwd, path):
        """Combine the current folder with a user-typed path, home-relative."""
        if path.startswith("~"):
            path = path[1:]
            combined = path.lstrip("/")
        elif path.startswith("/"):
            combined = path.lstrip("/")
        else:
            combined = posixpath.join(cwd, path)
        normal = posixpath.normpath("/" + combined).lstrip("/")
        return "" if normal == "." else normal

    def run(self, cwd, line, user_name="Guest"):
        """Run one command line. Returns (output, new_cwd, clear_screen)."""
        cwd = self.storage.relative(self.storage.resolve(cwd))
        redirect = None
        if line.strip().startswith("echo") and ">" in line:
            line, _, redirect = line.partition(">")
            redirect = redirect.strip()
        try:
            parts = shlex.split(line)
        except ValueError as exc:
            return f"Couldn't read that command: {exc}", cwd, False
        if not parts:
            return "", cwd, False
        cmd, args = parts[0], parts[1:]

        try:
            if cmd == "help":
                return HELP, cwd, False
            if cmd == "clear":
                return "", cwd, True
            if cmd == "pwd":
                return "~/" + cwd, cwd, False
            if cmd == "whoami":
                return user_name, cwd, False
            if cmd == "date":
                return datetime.datetime.now().strftime("%A %d %B %Y, %H:%M:%S"), cwd, False
            if cmd == "ls":
                listing = self.storage.list_dir(self._join(cwd, args[0] if args else ""))
                names = [e["name"] + ("/" if e["is_dir"] else "") for e in listing["entries"]]
                return ("\n".join(names) or "This folder is empty."), cwd, False
            if cmd == "cd":
                target = self._join(cwd, args[0]) if args else ""
                if not self.storage.resolve(target).is_dir():
                    return f"cd: {args[0]} isn't a folder.", cwd, False
                return "", target, False
            if cmd == "cat":
                self._need(args, 1, "cat <file>")
                return self.storage.read_text(self._join(cwd, args[0])).rstrip("\n"), cwd, False
            if cmd == "mkdir":
                self._need(args, 1, "mkdir <name>")
                for name in args:
                    self.storage.make_folder(cwd, name)
                return "", cwd, False
            if cmd == "touch":
                self._need(args, 1, "touch <name>")
                for name in args:
                    path = self._join(cwd, name)
                    if not self.storage.resolve(path).exists():
                        self.storage.save_text(path, "")
                return "", cwd, False
            if cmd == "rm":
                self._need(args, 1, "rm <path>")
                for name in args:
                    self.storage.delete(self._join(cwd, name))
                return "", cwd, False
            if cmd == "mv":
                self._need(args, 2, "mv <path> <new name>")
                self.storage.rename(self._join(cwd, args[0]), args[1])
                return "", cwd, False
            if cmd == "echo":
                text = " ".join(args)
                if redirect:
                    self.storage.save_text(self._join(cwd, redirect), text + "\n")
                    return "", cwd, False
                return text, cwd, False
            if cmd == "calc":
                self._need(args, 1, "calc <expression>")
                result = safe_eval(" ".join(args))
                if isinstance(result, float) and result.is_integer() and abs(result) < 1e15:
                    result = int(result)
                return str(result), cwd, False
        except (SandboxError, ValueError, ZeroDivisionError, OverflowError, SyntaxError) as exc:
            return f"{cmd}: {exc}", cwd, False

        return f"{cmd} isn't a command here. Type help to see the list.", cwd, False

    @staticmethod
    def _need(args, count, usage):
        if len(args) < count:
            raise ValueError(f"usage is {usage}")
