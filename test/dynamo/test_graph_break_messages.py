# Owner(s): ["module: dynamo"]

import re
import unittest
import warnings

import torch
import torch._dynamo
import torch._dynamo.config
import torch._dynamo.test_case
import torch.utils._pytree as python_pytree
from torch._dynamo.exc import Unsupported
from torch._dynamo.utils import counters
from torch.testing._internal.common_utils import IS_FBCODE, scoped_load_inline


"""
NOTE Adding tests to this file:

It is good practice to add a minimal repro for each graph break site (i.e. `unimplemented()` call
to make sure that there aren't any errors that occur when generating graph break messages.

If a graph break message test fails because the graph break no longer repros,
it is good practice to find a new minimal repro that causes the graph break.
If this is too much work, it is likely safe to skip/remove the test, assuming
it was previously passing and the graph break message is not changed.
However, if you add a new graph break or modify a graph break message, you should
make sure that there is a test for it.
"""


class GraphBreakMessagesTest(torch._dynamo.test_case.TestCase):
    maxDiff = None

    def test_dynamic_shape_operator(self):
        def fn():
            return torch.nonzero(torch.rand([10, 10]))

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Dynamic shape operator
  Explanation: Operator `aten.nonzero.default`'s output shape depends on input Tensor data.
  Hint: Enable tracing of dynamic shape operators with `torch._dynamo.config.capture_dynamic_output_shape_ops = True`

  Developer debug context: aten.nonzero.default


from user code:
   File "test_graph_break_messages.py", line N, in fn
    return torch.nonzero(torch.rand([10, 10]))""",
        )

    def test_dynamic_shape_operator_no_meta_kernel(self):
        def fn():
            return torch.linalg.lstsq(torch.rand(10, 10), torch.rand(10, 10))

        with torch._dynamo.config.patch(capture_dynamic_output_shape_ops=True):
            self.assertExpectedInlineMunged(
                Unsupported,
                lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
                """\
Dynamic shape operator (no meta kernel)
  Explanation: Operator `aten.linalg_lstsq.default` does not have a meta kernel that supports dynamic output shapes
  Hint: Please report an issue to PyTorch

  Developer debug context: aten.linalg_lstsq.default


from user code:
   File "test_graph_break_messages.py", line N, in fn
    return torch.linalg.lstsq(torch.rand(10, 10), torch.rand(10, 10))""",
            )

    def test_data_dependent_operator(self):
        def fn(x):
            return x.item()

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(
                torch.Tensor([1])
            ),
            """\
Tensor.item

from user code:
   File "test_graph_break_messages.py", line N, in fn
    return x.item()""",
        )

    def test_data_dependent_operator2(self):
        def fn(x):
            return torch.equal(x, x)

        with torch._dynamo.config.patch(capture_scalar_outputs=True):
            self.assertExpectedInlineMunged(
                Unsupported,
                lambda: torch.compile(fn, backend="eager", fullgraph=True)(
                    torch.ones(3)
                ),
                """\
Data dependent operator
  Explanation: Operator `aten.equal.default` has a non-Tensor output whose value is dependent on the data of Tensor inputs.
  Hint: Consider wrapping the operator into a PyTorch-understood custom operator (see https:/pytorch.org/tutorials/advanced/custom_ops_landing_page.html)

  Developer debug context: aten.equal.default


from user code:
   File "test_graph_break_messages.py", line N, in fn
    return torch.equal(x, x)""",
            )

    def test_super_call_method(self):
        def fn(it):
            return [x + 1 for x in it]

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(
                zip(range(5), range(10))
            ),
            """\
Unsupported method call
  Explanation: Dynamo does not know how to trace method `__iter__` of class `zip`
  Hint: Avoid calling `zip.__iter__` in your code.
  Hint: Please report an issue to PyTorch.
  Hint: Dynamo does not fully support tracing builtin iterators (e.g. `map`, `zip`, `enumerate`) passed in from uncompiled to compiled regions (e.g. `torch.compile(fn)(enumerate(...))`). This can happen unintentionally if a previous graph break happens with a builtin iterator in the local scope.

  Developer debug context: call_method UserDefinedObjectVariable(zip) __iter__ () {}


from user code:
   File "test_graph_break_messages.py", line N, in fn
    return [x + 1 for x in it]""",
        )

    def test_super_call_function(self):
        def fn(it):
            return [x + 1 for x in it()]

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(
                zip(range(5), range(10))
            ),
            """\
Unsupported function call
  Explanation: Dynamo does not know how to trace the function `UserDefinedObjectVariable(zip)`
  Hint: Avoid calling `UserDefinedObjectVariable(zip)` in your code.
  Hint: Please report an issue to PyTorch.

  Developer debug context: call_function UserDefinedObjectVariable(zip) [] {}


from user code:
   File "test_graph_break_messages.py", line N, in fn
    return [x + 1 for x in it()]""",
        )

    def test_unsupported_context(self):
        def fn(obj):
            with obj:
                return 1

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(3),
            """\
Unsupported context manager
  Explanation: Dynamo does not know how to enter a `int` context manager.
  Hint: Avoid using the unsupported context manager.
  Hint: File an issue to PyTorch. Simple context managers can potentially be supported, but note that context managers can't be supported in general

  Developer debug context: Attempted SETUP_WITH/BEFORE_WITH on ConstantVariable(int: 3)


from user code:
   File "test_graph_break_messages.py", line N, in fn
    with obj:""",
        )

    def test_backend_fake_tensor_exc(self):
        def bad_backend(gm, ex):
            raise torch._subclasses.fake_tensor.UnsupportedFakeTensorException("test")

        def fn(x):
            return x + 1

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend=bad_backend, fullgraph=True)(
                torch.ones(3, 3)
            ),
            """\
Backend compiler exception
  Explanation: Backend compiler `bad_backend` failed with test. Adding a graph break.
  Hint: Report an issue to the backend compiler repo.

  Developer debug context: Backend: bad_backend
Exception:test
Traceback:
  File "test_graph_break_messages.py", line N, in fn
    return x + 1""",
        )

    def test_unsupported_builtin(self):
        def fn():
            print("abc")

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Failed to trace builtin operator
  Explanation: Dynamo does not know how to trace builtin operator `print` with argument types ['str'] (has_kwargs False)
  Hint: Avoid calling builtin `print` with argument types ['str']. Consider using an equivalent alternative function/method to `print`.
  Hint: If you are attempting to call a logging function (e.g. `print`), you can try adding it to `torch._dynamo.config.reorderable_logging_functions`.
  Hint: Please report an issue to PyTorch.

  Developer debug context: builtin print [<class 'torch._dynamo.variables.constant.ConstantVariable'>] False


from user code:
   File "test_graph_break_messages.py", line N, in fn
    print("abc")""",
        )

    def test_skipfile_call(self):
        def fn():
            return unittest.skip("test")

        def post_munge(s):
            return re.sub(r"file `.*case\.py`", "file `case.py`", s)

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Attempted to call function marked as skipped
  Explanation: Dynamo developers have intentionally marked that the function `skip` in file `case.py` should not be traced.
  Hint: Avoid calling the function `skip`.
  Hint: Remove the function `skip` or the file `case.py` from torch/_dynamo/trace_rules.py. More graph breaks may occur as a result of attempting to trace into the function.
  Hint: Please file an issue to PyTorch.

  Developer debug context: module: unittest.case, qualname: skip, skip reason: <missing reason>


from user code:
   File "test_graph_break_messages.py", line N, in fn
    return unittest.skip("test")""",
            post_munge=post_munge,
        )

    def test_skipfile_dynamo_call(self):
        def fn():
            torch._dynamo.disable()

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Attempted to call function marked as skipped
  Explanation: Dynamo developers have intentionally marked that the function `disable` in file `_dynamo/decorators.py` should not be traced.
  Hint: Avoid calling the function `disable`.

  Developer debug context: module: torch._dynamo.decorators, qualname: disable, skip reason: <missing reason>


from user code:
   File "test_graph_break_messages.py", line N, in fn
    torch._dynamo.disable()""",
        )

    def test_skipfile_inline(self):
        class Foo:
            fn = unittest.skip

        def fn():
            Foo().fn()

        def post_munge(s):
            return re.sub(r"`.*case\.py`", "`case.py`", s)

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Attempted to inline function marked as skipped
  Explanation: Dynamo developers have intentionally marked that the function `skip` should not be traced.
  Hint: Avoid calling the function `skip`.
  Hint: Remove the function `case.py` from torch/_dynamo/trace_rules.py. More graph breaks may occur as a result of attempting to trace into the function.
  Hint: Please file an issue to PyTorch.

  Developer debug context: qualname: skip, name: skip, filename: `case.py`, skip reason: skipped according trace_rules.lookup SKIP_DIRS


from user code:
   File "test_graph_break_messages.py", line N, in fn
    Foo().fn()""",
            post_munge=post_munge,
        )

    def test_disable(self):
        @torch.compiler.disable
        def inner():
            return 1

        def fn():
            return inner()

        def post_munge(s):
            return re.sub(
                r"<function GraphBreakMessagesTest\.test_disable\.<locals>\.inner at 0x[0-9A-Fa-f]+>",
                "<function inner>",
                s,
            )

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Skip calling `torch.compiler.disable()`d function
  Explanation: Skip calling function `<function inner>` since it was wrapped with `torch.compiler.disable`
  Hint: Remove the `torch.compiler.disable` call

  Developer debug context: <function inner>


from user code:
   File "test_graph_break_messages.py", line N, in fn
    return inner()""",
            post_munge=post_munge,
        )

    def test_dynamo_graph_break_fn(self):
        def fn():
            torch._dynamo.graph_break()

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Call to `torch._dynamo.graph_break()`
  Explanation: User-inserted graph break. Message: None
  Hint: Remove the `torch._dynamo.graph_break()` call.

  Developer debug context: Called `torch._dynamo.graph_break()` with args `[]`, kwargs `{}`


from user code:
   File "test_graph_break_messages.py", line N, in fn
    torch._dynamo.graph_break()""",
        )

    def test_dynamo_graph_break_fn_with_msg(self):
        def fn():
            torch._dynamo.graph_break(msg="test graph break")

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Call to `torch._dynamo.graph_break()`
  Explanation: User-inserted graph break. Message: test graph break
  Hint: Remove the `torch._dynamo.graph_break()` call.

  Developer debug context: Called `torch._dynamo.graph_break()` with args `[]`, kwargs `{'msg': ConstantVariable(str: 'test graph break')}`


from user code:
   File "test_graph_break_messages.py", line N, in fn
    torch._dynamo.graph_break(msg="test graph break")""",
        )

    def test_warnings(self):
        def fn():
            warnings.warn("test")

        self.assertExpectedInlineMunged(
            Unsupported,
            lambda: torch.compile(fn, backend="eager", fullgraph=True)(),
            """\
Attempted to call function marked as skipped
  Explanation: Dynamo does not know how to trace the Python builtin `_warnings.warn`.
  Hint: If you are attempting to call a logging function (e.g. `_warnings.warn`), you can try adding it to `torch._dynamo.config.reorderable_logging_functions`.
  Hint: Please file an issue on GitHub so the PyTorch team can add support for it.

  Developer debug context: module: _warnings, qualname: warn, skip reason: <missing reason>


from user code:
   File "test_graph_break_messages.py", line N, in fn
    warnings.warn("test")""",
        )

    @unittest.skipIf(not python_pytree._cxx_pytree_exists, "missing optree package")
    def test_optree_graph_break_message(self):
        import optree

        @torch.compile(backend="eager")
        def fn(x):
            d = {"a": 1}
            optree.tree_flatten(d)
            return torch.sin(x)

        fn(torch.randn(4))
        self.assertEqual(len(counters["graph_break"]), 1)
        first_graph_break = next(iter(counters["graph_break"].keys()))
        self.assertExpectedInline(
            first_graph_break,
            """\
Attempted to call function marked as skipped
  Explanation: Dynamo cannot trace optree C/C++ function optree._C.PyCapsule.flatten.
  Hint:  Consider using torch.utils._pytree - https://github.com/pytorch/pytorch/blob/main/torch/utils/_pytree.py

  Developer debug context: module: optree._C, qualname: PyCapsule.flatten, skip reason: <missing reason>
""",
        )

    @scoped_load_inline
    @torch._dynamo.config.patch(inline_inbuilt_nn_modules=False)
    @unittest.skipIf(IS_FBCODE, "inline cpp_extension doesn't work in fbcode")
    def test_cpp_extension_recommends_custom_ops(self, load_inline):
        cpp_source = """
        #include <torch/extension.h>
        at::Tensor foobar(const at::Tensor& x) {
            return x.clone();
        }
        """
        module = load_inline(
            name="mylib",
            cpp_sources=cpp_source,
            functions="foobar",
            verbose=True,
        )

        x = torch.ones(2, 2, requires_grad=True)
        counters.clear()

        @torch.compile(backend="eager")
        def f(x):
            return module.foobar(x)

        with self.assertWarnsOnceRegex(
            UserWarning,
            "(?s).*https://pytorch.org/tutorials/advanced/custom_ops_landing_page.html.*",
        ):
            f(x)
        self.assertEqual(len(counters["graph_break"]), 1)
        first_graph_break = next(iter(counters["graph_break"].keys()))

        first_graph_break = re.sub(r"mylib(_v\d+)?", "mylib", first_graph_break)

        self.assertExpectedInline(
            first_graph_break,
            """\
Attempted to call function marked as skipped
  Explanation: Dynamo does not know how to trace the builtin `mylib.PyCapsule.foobar.` This function is either a Python builtin (e.g. _warnings.warn) or a third-party C/C++ Python extension (perhaps created with pybind).
  Hint: If it is a Python builtin, please file an issue on GitHub so the PyTorch team can add support for it and see the next case for a workaround.
  Hint: If it is a third-party C/C++ Python extension, please either wrap it into a PyTorch-understood custom operator (see https://pytorch.org/tutorials/advanced/custom_ops_landing_page.html for more details) or, if it is traceable, use `torch.compiler.allow_in_graph`.

  Developer debug context: module: mylib, qualname: PyCapsule.foobar, skip reason: <missing reason>
""",
        )

        cpp_source = """
        #include <torch/extension.h>
        at::Tensor baz(const at::Tensor& x) {
            return x.clone();
        }
        """
        module2 = load_inline(
            name="mylib2",
            cpp_sources=cpp_source,
            functions="baz",
            verbose=True,
        )

        torch._dynamo.reset()

        # Test that each warning only happens once
        @torch.compile(backend="eager")
        def f(x):
            module2.baz(x)
            module.foobar(x)
            module.foobar(x)
            module2.baz(x)
            module.foobar(x)
            module2.baz(x)
            return x.clone()

        with warnings.catch_warnings(record=True) as ws:
            warnings.simplefilter("always")
            f(x)
            f(x)
        self.assertEqual(len(ws), 2)


if __name__ == "__main__":
    from torch._dynamo.test_case import run_tests

    run_tests()
