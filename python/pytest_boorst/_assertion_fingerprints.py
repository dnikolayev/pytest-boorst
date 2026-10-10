"""Recognized source and metadata for pytest 9.1.1 and CPython 3.14."""

REWRITE_SHA256 = "17f1eefbd1c2fe5326cb7592ff3af92a773582cf9d01727b09d3ab864906ee50"

AST_SHA256 = "5ea9a796353544bea0d706153516f04ef3d92be305d15a73238403837d77e34c"

REWRITER_KEYS = (
    "__module__",
    "__firstlineno__",
    "__doc__",
    "__init__",
    "run",
    "is_rewrite_disabled",
    "variable",
    "assign",
    "display",
    "helper",
    "builtin",
    "explanation_param",
    "push_format_context",
    "pop_format_context",
    "generic_visit",
    "visit_Assert",
    "visit_NamedExpr",
    "visit_Name",
    "visit_BoolOp",
    "visit_UnaryOp",
    "visit_BinOp",
    "visit_Call",
    "visit_Starred",
    "visit_Attribute",
    "visit_Compare",
    "__static_attributes__",
)

VISITOR_KEYS = (
    "__module__",
    "__firstlineno__",
    "__doc__",
    "visit",
    "generic_visit",
    "__static_attributes__",
    "__dict__",
    "__weakref__",
)

SENTINEL_KEYS = (
    "__module__",
    "__firstlineno__",
    "__static_attributes__",
    "__dict__",
    "__weakref__",
    "__doc__",
)

BINOPS = (
    ("BitOr", "|"),
    ("BitXor", "^"),
    ("BitAnd", "&"),
    ("LShift", "<<"),
    ("RShift", ">>"),
    ("Add", "+"),
    ("Sub", "-"),
    ("Mult", "*"),
    ("Div", "/"),
    ("FloorDiv", "//"),
    ("Mod", "%%"),
    ("Eq", "=="),
    ("NotEq", "!="),
    ("Lt", "<"),
    ("LtE", "<="),
    ("Gt", ">"),
    ("GtE", ">="),
    ("Pow", "**"),
    ("Is", "is"),
    ("IsNot", "is not"),
    ("In", "in"),
    ("NotIn", "not in"),
    ("MatMult", "@"),
)

UNARYOPS = (("Not", "not %s"), ("Invert", "~%s"), ("USub", "-%s"), ("UAdd", "+%s"))

CONFIG_SHA256 = "98b05c2c37d09e1d5c05975efc2d9af98d4aff6ea47de410a8e93956420873c1"

PARSER_FLAGS = (
    ("PyCF_ONLY_AST", 1024),
    ("PyCF_OPTIMIZED_AST", 33792),
    ("PyCF_TYPE_COMMENTS", 4096),
)

THREAD_COUNT_SHA256 = "f2c620120676505999343b160fbacceeb2d9a0d97253e92ba8234f945a253fb5"
