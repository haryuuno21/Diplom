from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable


class BasicRuntimeError(Exception):
    pass


class BasicSyntaxError(BasicRuntimeError):
    pass


class BasicExecutionLimitError(BasicRuntimeError):
    pass


class BasicScriptCancelledError(BasicRuntimeError):
    pass


AsyncCallable = Callable[..., Awaitable[object]]

ASYNC_BUILTINS = (
    "MOVE",
    "TURN",
    "HEAL",
    "GET_ROBOT_COORDINATES",
    "GET_ROBOT_LOCATION",
    "GET_BLOCK",
    "DEPTH",
    "ADDTREE",
    "PRINT",
)


@dataclass
class ScriptRunResult:
    success: bool
    logs: list[str] = field(default_factory=list)
    error: str | None = None


class BasicExecutionContext:
    def __init__(
        self,
        callbacks: dict[str, AsyncCallable],
        max_loop_iterations: int = 1000,
        cancel_requested: Callable[[], bool] | None = None,
    ):
        self.callbacks = callbacks
        self.logs: list[str] = []
        self.loop_iterations = 0
        self.max_loop_iterations = max_loop_iterations
        self.cancel_requested = cancel_requested or (lambda: False)

    async def guard_loop(self) -> None:
        self.raise_if_cancelled()
        self.loop_iterations += 1
        if self.loop_iterations > self.max_loop_iterations:
            raise BasicExecutionLimitError("Program exceeded loop iteration limit")
        await asyncio.sleep(0)
        self.raise_if_cancelled()

    def raise_if_cancelled(self) -> None:
        if self.cancel_requested():
            raise BasicScriptCancelledError("Script stopped by user")

    async def PRINT(self, *values) -> None:
        text = " ".join(str(value) for value in values)
        self.logs.append(text)


class BasicScriptRuntime:
    def __init__(self, max_loop_iterations: int = 1000):
        self.max_loop_iterations = max_loop_iterations

    async def execute(
        self,
        program_text: str,
        callbacks: dict[str, AsyncCallable],
        *,
        cancel_requested: Callable[[], bool] | None = None,
    ) -> ScriptRunResult:
        try:
            python_source = self._translate_program(program_text)
        except BasicRuntimeError as exc:
            return ScriptRunResult(success=False, logs=[], error=str(exc))

        context = BasicExecutionContext(
            callbacks,
            self.max_loop_iterations,
            cancel_requested=cancel_requested,
        )

        namespace = {
            "__builtins__": {},
            "BasicExecutionLimitError": BasicExecutionLimitError,
            "PRINT": context.PRINT,
            "range": range,
            "int": int,
            "abs": abs,
            "min": min,
            "max": max,
        }
        for name, callback in callbacks.items():
            namespace[name] = callback

        try:
            exec(python_source, namespace)
            program = namespace["__basic_program"]
            context.raise_if_cancelled()
            await program(context)
        except SyntaxError as exc:
            return ScriptRunResult(
                success=False,
                logs=context.logs,
                error=f"Syntax error: {exc.msg}",
            )
        except BasicRuntimeError as exc:
            return ScriptRunResult(success=False, logs=context.logs, error=str(exc))
        except Exception as exc:
            return ScriptRunResult(success=False, logs=context.logs, error=f"Runtime error: {exc}")
        return ScriptRunResult(success=True, logs=context.logs)

    def _translate_program(self, program_text: str) -> str:
        lines = ["async def __basic_program(__ctx):"]

        indent = 1
        block_stack: list[str] = []

        for raw_line in program_text.splitlines():
            line = self._strip_comment(raw_line).strip()
            if not line:
                continue

            upper = line.upper()

            if upper in ("END WHILE", "WEND", "END IF", "END FOR"):
                if not block_stack:
                    raise BasicSyntaxError(f"Unexpected block terminator: {line}")
                indent -= 1
                block_stack.pop()
                continue

            if upper.startswith("NEXT"):
                if not block_stack or block_stack[-1] != "for":
                    raise BasicSyntaxError("NEXT without FOR")
                indent -= 1
                block_stack.pop()
                continue

            if upper.startswith("ELSEIF "):
                if not block_stack or block_stack[-1] != "if":
                    raise BasicSyntaxError("ELSEIF without IF")
                indent -= 1
                condition = line[7:].strip()
                if condition.upper().endswith("THEN"):
                    condition = condition[:-4].strip()
                lines.append(f"{'    ' * indent}elif {self._translate_expression(condition)}:")
                indent += 1
                continue

            if upper == "ELSE":
                if not block_stack or block_stack[-1] != "if":
                    raise BasicSyntaxError("ELSE without IF")
                indent -= 1
                lines.append(f"{'    ' * indent}else:")
                indent += 1
                continue

            if upper.startswith("WHILE"):
                condition = line[5:].strip()
                lines.append(f"{'    ' * indent}while {self._translate_expression(condition)}:")
                block_stack.append("while")
                indent += 1
                lines.append(f"{'    ' * indent}await __ctx.guard_loop()")
                continue

            if upper.startswith("IF "):
                if not upper.endswith("THEN"):
                    raise BasicSyntaxError("IF statement must end with THEN")
                condition = line[2:-4].strip()
                lines.append(f"{'    ' * indent}if {self._translate_expression(condition)}:")
                block_stack.append("if")
                indent += 1
                continue

            if upper.startswith("FOR "):
                translated = self._translate_for(line)
                lines.append(f"{'    ' * indent}{translated}")
                block_stack.append("for")
                indent += 1
                lines.append(f"{'    ' * indent}await __ctx.guard_loop()")
                continue

            translated = self._translate_statement(line)
            lines.append(f"{'    ' * indent}{translated}")

        if block_stack:
            raise BasicSyntaxError("Program ended before all blocks were closed")

        if len(lines) == 2:
            lines.append("    return None")
        return "\n".join(lines)

    def _translate_for(self, line: str) -> str:
        match = re.fullmatch(
            r"FOR\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s+TO\s+(.+?)(?:\s+STEP\s+(.+))?$",
            line,
            re.IGNORECASE,
        )
        if not match:
            raise BasicSyntaxError(f"Unsupported FOR syntax: {line}")
        variable, start, end, step = match.groups()
        start_expr = self._translate_expression(start)
        end_expr = self._translate_expression(end)
        step_expr = self._translate_expression(step) if step else "1"
        return (
            f"for {variable} in range(int({start_expr}), int({end_expr}) + "
            f"(1 if int({step_expr}) > 0 else -1), int({step_expr})):"
        )

    def _translate_statement(self, line: str) -> str:
        normalized = line.strip()
        if normalized.upper() == "HEAL":
            normalized = "HEAL()"

        assignment = re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*(.+)", normalized)
        if assignment:
            variable, expr = assignment.groups()
            return f"{variable} = {self._translate_expression(expr)}"

        translated = self._translate_expression(normalized)
        if not translated.startswith("await "):
            return translated
        return translated

    def _translate_expression(self, expression: str) -> str:
        expr = expression.strip()
        expr = self._unwrap_outer_parentheses(expr)
        expr = self._replace_comparison_operators(expr)
        expr = re.sub(r"\bAND\b", "and", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bOR\b", "or", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bNOT\b", "not", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bTRUE\b", "True", expr, flags=re.IGNORECASE)
        expr = re.sub(r"\bFALSE\b", "False", expr, flags=re.IGNORECASE)

        for name in ASYNC_BUILTINS:
            expr = re.sub(
                rf"\b{name}\s*\(",
                f"await {name}(",
                expr,
                flags=re.IGNORECASE,
            )
        return expr

    def _replace_comparison_operators(self, expression: str) -> str:
        chars: list[str] = []
        in_string = False
        index = 0
        while index < len(expression):
            char = expression[index]
            if char == '"':
                in_string = not in_string
                chars.append(char)
                index += 1
                continue

            if not in_string and char == "<" and index + 1 < len(expression) and expression[index + 1] == ">":
                chars.append("!=")
                index += 2
                continue

            if not in_string and char == "=":
                previous = expression[index - 1] if index > 0 else ""
                next_char = expression[index + 1] if index + 1 < len(expression) else ""
                if previous not in ("<", ">", "!", "=") and next_char != "=":
                    chars.append("==")
                    index += 1
                    continue

            chars.append(char)
            index += 1
        return "".join(chars)

    def _strip_comment(self, line: str) -> str:
        result: list[str] = []
        in_string = False
        for char in line:
            if char == '"':
                in_string = not in_string
                result.append(char)
                continue
            if char == "'" and not in_string:
                break
            result.append(char)
        return "".join(result)

    def _unwrap_outer_parentheses(self, expression: str) -> str:
        expr = expression.strip()
        while expr.startswith("(") and expr.endswith(")") and self._parentheses_balanced(expr[1:-1]):
            expr = expr[1:-1].strip()
        return expr

    def _parentheses_balanced(self, expression: str) -> bool:
        depth = 0
        in_string = False
        for char in expression:
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0
