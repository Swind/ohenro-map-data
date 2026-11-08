"""Reconstruct static route literals from Blutter's annotated ARM64 assembly.

Only the straight-line list initializer is interpreted, never executable APK code.
The returned paths preserve the Dart outer-list order, including singleton paths.
"""

import math
from pathlib import Path
import re


_METHOD = re.compile(r"^  static (List<List<List<double>>>|List<List<double>>) \w+\(\) \{")
# Match semantic annotations, not the duplicate native instructions below them.
_INSTRUCTION = re.compile(r"^    // 0x[0-9a-f]+: (.*)")
_ASSIGN = re.compile(r"r(\d+) = (.*)")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")
_LITERAL = re.compile(r"_GrowableList\._literal(\d*)\(\)$")
_MOVE = re.compile(r"mov\s+(x\d+|lr), (x\d+|lr)$")
_MEMORY = re.compile(r"(ldur|stur|str)\s+(x\d+|lr), \[(fp|SP)(?:, #(-?(?:0x[0-9a-f]+|\d+)))?\]$")
_PAIR = re.compile(r"stp\s+(x\d+|lr), (x\d+|lr), \[SP(?:, #(0x[0-9a-f]+|\d+))?\]$")
_FIELD = re.compile(r"StoreField: r(\d+)->field_([0-9a-f]+) = r(\d+)$")
_STORE = re.compile(r"ArrayStore: r(\d+)\[(r\d+|\d+)\] = r(\d+)\s+; List_4$")
_ARGUMENT_REGISTERS = ("x2", "x3", "x5", "x6", "x7")
_MISSING = object()


class _Array:
    __slots__ = ("values", "element_type")

    def __init__(self, length, element_type):
        self.values = [_MISSING] * length
        self.element_type = element_type


def parse_layer(path: Path) -> tuple[list[list[list[float]]], int]:
    """Return (paths, reference_constructor_count) from one route source file.

    A flat List<List<double>> initializer (ConnectionPoints) returns one path;
    callers retain responsibility for its lat/lon swap and Point export. Numbered
    constructors of point-reference paths are counted, including literal1; outer
    route-list constructors are not. Unknown instructions or incomplete literals
    fail with source location rather than dropping geometry.
    """
    path = Path(path)
    registers = {}
    memory = {}
    active = False
    return_type = None
    references = 0
    line_number = 0

    def fail(message):
        raise ValueError(f"{path}:{line_number}: {message}")

    def register(name):
        if name not in registers:
            fail(f"unresolved register {name}")
        return registers[name]

    def slot(base, offset):
        key = (base, offset)
        if key not in memory:
            fail(f"unresolved stack slot {base}{offset:+#x}")
        return memory[key]

    def element_type(value):
        if value not in ("double", "List<double>", "List<List<double>>"):
            fail(f"unsupported list element type {value!r}")
        return value

    def check_elements(values, kind):
        if any(value is _MISSING for value in values):
            fail("incomplete array literal")
        if kind == "double":
            if not all(type(value) in (int, float) and math.isfinite(value) for value in values):
                fail("non-numeric point coordinate")
            if len(values) not in (2, 3):
                fail(f"unsupported point dimension {len(values)}")
        elif not all(isinstance(value, list) for value in values):
            fail(f"non-list element in {kind} literal")

    def tagged_index(value):
        if type(value) is not int or value < 0 or value % 2:
            fail(f"invalid tagged array size/index {value!r}")
        return value // 2

    def store(array, index, value):
        if not isinstance(array, _Array):
            fail("array store target is not an allocated array")
        if not 0 <= index < len(array.values):
            fail(f"array store index {index} outside length {len(array.values)}")
        if array.values[index] is not _MISSING:
            fail(f"duplicate array store at index {index}")
        array.values[index] = value

    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not active:
                method = _METHOD.match(line)
                if not method:
                    continue
                return_type = method[1]
                active = True
                continue
            instruction = _INSTRUCTION.match(line)
            if not instruction:
                if line.strip() == "}":
                    fail("initializer ended without a return")
                continue
            text = instruction[1]
            assignment = _ASSIGN.fullmatch(text)
            if assignment:
                destination = "x" + assignment[1]
                value = assignment[2]
                if _NUMBER.fullmatch(value):
                    registers[destination] = float(value) if any(c in value for c in ".eE") else int(value)
                elif value.startswith("<") and value.endswith(">"):
                    registers[destination] = element_type(value[1:-1])
                elif value == "AllocateArray()":
                    registers[destination] = _Array(tagged_index(register("x2")), element_type(register("x1")))
                else:
                    literal = _LITERAL.fullmatch(value)
                    if not literal:
                        fail(f"unsupported assignment {text}")
                    if literal[1]:
                        count = int(literal[1])
                        if not 1 <= count <= 8:
                            fail(f"unsupported numbered literal size {count}")
                        kind = element_type(register("x1"))
                        values = [register(name) for name in _ARGUMENT_REGISTERS[:count]]
                        values.extend(slot("SP", offset * 8) for offset in range(count - 6, -1, -1))
                        if kind == "List<double>":
                            references += 1
                    else:
                        array = slot("SP", 0)
                        kind = element_type(slot("SP", 8))
                        if not isinstance(array, _Array) or array.element_type != kind:
                            fail("generic literal has incompatible backing array/type")
                        values = array.values
                    check_elements(values, kind)
                    # Calls clobber argument registers; only explicit reloads may reuse them.
                    registers.clear()
                    registers[destination] = values
                continue
            move = _MOVE.fullmatch(text)
            if move:
                registers[move[1]] = register(move[2])
                continue
            memory_op = _MEMORY.fullmatch(text)
            if memory_op:
                operation, name, base, offset = memory_op.groups()
                offset = int(offset or "0", 0)
                if operation == "ldur":
                    registers[name] = slot(base, offset)
                else:
                    memory[base, offset] = register(name)
                continue
            pair = _PAIR.fullmatch(text)
            if pair:
                offset = int(pair[3] or "0", 0)
                memory["SP", offset] = register(pair[1])
                memory["SP", offset + 8] = register(pair[2])
                continue
            field = _FIELD.fullmatch(text)
            if field:
                offset = int(field[2], 16) - 15
                if offset < 0 or offset % 4:
                    fail(f"unsupported array field offset {field[2]}")
                store(register("x" + field[1]), offset // 4, register("x" + field[3]))
                continue
            array_store = _STORE.fullmatch(text)
            if array_store:
                index = array_store[2]
                index = tagged_index(register("x" + index[1:])) if index.startswith("r") else int(index)
                store(register("x" + array_store[1]), index, register("x" + array_store[3]))
                continue
            if text == "ret":
                result = register("x0")
                if not isinstance(result, list):
                    fail("initializer did not return a list")
                paths = [result] if return_type == "List<List<double>>" else result
                for points in paths:
                    if not isinstance(points, list) or not points:
                        fail("empty or invalid route path")
                    for point in points:
                        if not isinstance(point, list):
                            fail("route point is not a coordinate list")
                        check_elements(point, "double")
                return paths, references
            if text in ("EnterFrame", "CheckStackOverflow", "LeaveFrame") or re.fullmatch(r"AllocStack\(0x[0-9a-f]+\)", text):
                continue
            fail(f"unsupported initializer instruction {text}")
    fail("no complete static route literal initializer")
