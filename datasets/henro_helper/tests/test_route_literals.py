from pathlib import Path
import tempfile
import unittest

from datasets.henro_helper.route_literals import parse_layer


class RouteLiteralTests(unittest.TestCase):
    def parse(self, instructions, *, flat=False, preamble=""):
        kind = "List<List<double>>" if flat else "List<List<List<double>>>"
        assembly = preamble + f"  static {kind} routes() {{\n"
        assembly += "".join(f"    // 0x{index * 4 + 256:x}: {text}\n" for index, text in enumerate(instructions.strip().splitlines()))
        assembly += "  }\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "Routes.dart")
            path.write_text(assembly, encoding="utf-8")
            return parse_layer(path)

    def test_hoisted_points_reconstruct_connector_and_preserve_outer_order(self):
        paths, references = self.parse('''r1 = <double>
r2 = 134.1
r3 = 34.1
r5 = 12.5
r0 = _GrowableList._literal3()
stur x0, [fp, #-8]
r1 = <double>
r2 = 134.2
r3 = 34.2
r5 = 13.5
r0 = _GrowableList._literal3()
stur x0, [fp, #-0x10]
ldur x2, [fp, #-8]
mov x3, x0
r1 = <List<double>>
r0 = _GrowableList._literal2()
stur x0, [fp, #-0x18]
ldur x2, [fp, #-0x10]
ldur x3, [fp, #-8]
ldur x5, [fp, #-0x10]
r1 = <List<double>>
r0 = _GrowableList._literal3()
mov x2, x0
ldur x3, [fp, #-0x18]
r1 = <List<List<double>>>
r0 = _GrowableList._literal2()
ret''')
        a, b = [134.1, 34.1, 12.5], [134.2, 34.2, 13.5]
        self.assertEqual(paths, [[b, a, b], [a, b]])
        self.assertEqual(references, 2)

    def test_flat_connection_array_stores_and_tagged_register_index(self):
        paths, references = self.parse('''r1 = <double>
r2 = 34.051980
r3 = 134.349080
r0 = _GrowableList._literal2()
stur x0, [fp, #-8]
r1 = <List<double>>
r2 = 6
r0 = AllocateArray()
mov x4, x0
ldur x0, [fp, #-8]
stur x4, [fp, #-0x10]
StoreField: r4->field_f = r0
r1 = <double>
r2 = 33.989120
r3 = 134.323310
r0 = _GrowableList._literal2()
ldur x1, [fp, #-0x10]
ArrayStore: r1[1] = r0  ; List_4
ldur x0, [fp, #-8]
r4 = 4
ArrayStore: r1[r4] = r0  ; List_4
r16 = <List<double>>
ldur lr, [fp, #-0x10]
stp lr, x16, [SP]
r0 = _GrowableList._literal()
LeaveFrame
ret''', flat=True, preamble='''  static _ unrelated() {
    // 0x10: r0 = UnsupportedUnrelatedCall()
  }
''')
        first = [34.05198, 134.34908]
        self.assertEqual(paths, [[first, [33.98912, 134.32331], first]])
        self.assertEqual(references, 0)

    def test_real_black_singleton_literals_are_not_merged_or_padded(self):
        paths, references = self.parse('''r1 = <double>
r2 = 133.568230
r3 = 33.972380
r5 = 103.050000
r0 = _GrowableList._literal3()
mov x2, x0
r1 = <List<double>>
r0 = _GrowableList._literal1()
stur x0, [fp, #-8]
r1 = <double>
r2 = 133.571920
r3 = 33.972780
r5 = 122.920000
r0 = _GrowableList._literal3()
mov x2, x0
r1 = <List<double>>
r0 = _GrowableList._literal1()
mov x3, x0
ldur x2, [fp, #-8]
r1 = <List<List<double>>>
r0 = _GrowableList._literal2()
ret''')
        self.assertEqual(paths, [[[133.56823, 33.97238, 103.05]], [[133.57192, 33.97278, 122.92]]])
        self.assertEqual(references, 2)

    def test_numbered_literals_six_through_eight_use_reversed_stack_arguments(self):
        for count in (6, 7, 8):
            with self.subTest(count=count):
                instructions = []
                expected = []
                for index in range(count):
                    expected.append([134.0 + index / 100, 34.0 + index / 100])
                    instructions.extend([
                        "r1 = <double>", f"r2 = {expected[-1][0]}", f"r3 = {expected[-1][1]}",
                        "r0 = _GrowableList._literal2()", f"stur x0, [fp, #-{(index + 1) * 8}]",
                    ])
                for index, register in enumerate((2, 3, 5, 6, 7)):
                    instructions.append(f"ldur x{register}, [fp, #-{(index + 1) * 8}]")
                for index in range(5, count):
                    instructions.extend([
                        f"ldur x16, [fp, #-{(index + 1) * 8}]",
                        f"str x16, [SP, #{(count - index - 1) * 8}]",
                    ])
                instructions.extend([
                    "r1 = <List<double>>", f"r0 = _GrowableList._literal{count}()",
                    "mov x2, x0", "r1 = <List<List<double>>>", "r0 = _GrowableList._literal1()", "ret",
                ])
                self.assertEqual(self.parse("\n".join(instructions)), ([expected], 1))

    def test_numbered_outer_list_eight_preserves_paths_not_point_construction_order(self):
        instructions = []
        expected = []
        for index in range(8):
            point = [134.0 + index / 100, 34.0]
            expected.append([point])
            instructions.extend([
                "r1 = <double>", f"r2 = {point[0]}", f"r3 = {point[1]}",
                "r0 = _GrowableList._literal2()", "mov x2, x0", "r1 = <List<double>>",
                "r0 = _GrowableList._literal1()", f"stur x0, [fp, #-{(index + 1) * 8}]",
            ])
        instructions.extend([
            "ldur x16, [fp, #-48]", "ldur lr, [fp, #-56]", "stp lr, x16, [SP, #8]",
            "ldur x0, [fp, #-64]", "str x0, [SP]", "ldur x2, [fp, #-8]",
            "ldur x3, [fp, #-16]", "ldur x5, [fp, #-24]", "ldur x6, [fp, #-32]",
            "ldur x7, [fp, #-40]", "r1 = <List<List<double>>>", "r0 = _GrowableList._literal8()", "ret",
        ])
        self.assertEqual(self.parse("\n".join(instructions)), (expected, 8))

    def test_unsupported_or_incomplete_geometry_fails_instead_of_dropping_it(self):
        cases = [
            ("r0 = UnknownCall()", "unsupported assignment"),
            ("ArrayLoad: r0 = r1[0]", "unsupported initializer instruction"),
            ("r1 = <double>\nr2 = 134.0\nr0 = _GrowableList._literal2()", "unresolved register x3"),
            ("r1 = <List<double>>\nr2 = 3\nr0 = AllocateArray()", "invalid tagged array"),
            ("r1 = <List<double>>\nr2 = 4\nr0 = AllocateArray()\nr16 = <List<double>>\nstp x0, x16, [SP]\nr0 = _GrowableList._literal()", "incomplete array literal"),
            ("r0 = _GrowableList._literal()", "unresolved stack slot"),
            ("r1 = <double>\nr0 = _GrowableList._literal9()", "unsupported numbered literal size"),
            ("EnterFrame", "initializer ended without a return"),
        ]
        for instructions, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    self.parse(instructions)

    def test_call_does_not_reuse_stale_argument_registers(self):
        with self.assertRaisesRegex(ValueError, "unresolved register x2"):
            self.parse('''r1 = <double>
r2 = 134.1
r3 = 34.1
r0 = _GrowableList._literal2()
r1 = <double>
r0 = _GrowableList._literal2()
ret''')


if __name__ == "__main__":
    unittest.main()
