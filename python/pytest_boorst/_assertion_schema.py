"""Frozen CPython 3.14 AST metadata for guarded location updates."""

import _ast
import ast
from types import GenericAlias, UnionType

LOCATIONS = ("lineno", "col_offset", "end_lineno", "end_col_offset")
SPECIALS = (
    "__new__",
    "__init__",
    "__getattribute__",
    "__getattr__",
    "__setattr__",
    "__delattr__",
    "__dict__",
    "__class__",
    "__eq__",
    "__ne__",
    "__hash__",
    "__bool__",
    "__len__",
    "__del__",
    "__repr__",
    "__str__",
    "__format__",
    "__init_subclass__",
)
MISSING = object()
_ROWS = """
AST|||AST,object|
Add|||Add,operator,AST,object|
And|||And,boolop,AST,object|
AnnAssign|target,annotation,value,simple|lineno,col_offset,end_lineno,end_col_offset|AnnAssign,stmt,AST,object|value
Assert|test,msg|lineno,col_offset,end_lineno,end_col_offset|Assert,stmt,AST,object|msg
Assign|targets,value,type_comment|lineno,col_offset,end_lineno,end_col_offset|Assign,stmt,AST,object|type_comment
AsyncFor|target,iter,body,orelse,type_comment|lineno,col_offset,end_lineno,end_col_offset|AsyncFor,stmt,AST,object|type_comment
AsyncFunctionDef|name,args,body,decorator_list,returns,type_comment,type_params|lineno,col_offset,end_lineno,end_col_offset|AsyncFunctionDef,stmt,AST,object|returns,type_comment
AsyncWith|items,body,type_comment|lineno,col_offset,end_lineno,end_col_offset|AsyncWith,stmt,AST,object|type_comment
Attribute|value,attr,ctx|lineno,col_offset,end_lineno,end_col_offset|Attribute,expr,AST,object|
AugAssign|target,op,value|lineno,col_offset,end_lineno,end_col_offset|AugAssign,stmt,AST,object|
Await|value|lineno,col_offset,end_lineno,end_col_offset|Await,expr,AST,object|
BinOp|left,op,right|lineno,col_offset,end_lineno,end_col_offset|BinOp,expr,AST,object|
BitAnd|||BitAnd,operator,AST,object|
BitOr|||BitOr,operator,AST,object|
BitXor|||BitXor,operator,AST,object|
BoolOp|op,values|lineno,col_offset,end_lineno,end_col_offset|BoolOp,expr,AST,object|
Break||lineno,col_offset,end_lineno,end_col_offset|Break,stmt,AST,object|
Call|func,args,keywords|lineno,col_offset,end_lineno,end_col_offset|Call,expr,AST,object|
ClassDef|name,bases,keywords,body,decorator_list,type_params|lineno,col_offset,end_lineno,end_col_offset|ClassDef,stmt,AST,object|
Compare|left,ops,comparators|lineno,col_offset,end_lineno,end_col_offset|Compare,expr,AST,object|
Constant|value,kind|lineno,col_offset,end_lineno,end_col_offset|Constant,expr,AST,object|kind
Continue||lineno,col_offset,end_lineno,end_col_offset|Continue,stmt,AST,object|
Del|||Del,expr_context,AST,object|
Delete|targets|lineno,col_offset,end_lineno,end_col_offset|Delete,stmt,AST,object|
Dict|keys,values|lineno,col_offset,end_lineno,end_col_offset|Dict,expr,AST,object|
DictComp|key,value,generators|lineno,col_offset,end_lineno,end_col_offset|DictComp,expr,AST,object|
Div|||Div,operator,AST,object|
Eq|||Eq,cmpop,AST,object|
ExceptHandler|type,name,body|lineno,col_offset,end_lineno,end_col_offset|ExceptHandler,excepthandler,AST,object|type,name
Expr|value|lineno,col_offset,end_lineno,end_col_offset|Expr,stmt,AST,object|
Expression|body||Expression,mod,AST,object|
FloorDiv|||FloorDiv,operator,AST,object|
For|target,iter,body,orelse,type_comment|lineno,col_offset,end_lineno,end_col_offset|For,stmt,AST,object|type_comment
FormattedValue|value,conversion,format_spec|lineno,col_offset,end_lineno,end_col_offset|FormattedValue,expr,AST,object|format_spec
FunctionDef|name,args,body,decorator_list,returns,type_comment,type_params|lineno,col_offset,end_lineno,end_col_offset|FunctionDef,stmt,AST,object|returns,type_comment
FunctionType|argtypes,returns||FunctionType,mod,AST,object|
GeneratorExp|elt,generators|lineno,col_offset,end_lineno,end_col_offset|GeneratorExp,expr,AST,object|
Global|names|lineno,col_offset,end_lineno,end_col_offset|Global,stmt,AST,object|
Gt|||Gt,cmpop,AST,object|
GtE|||GtE,cmpop,AST,object|
If|test,body,orelse|lineno,col_offset,end_lineno,end_col_offset|If,stmt,AST,object|
IfExp|test,body,orelse|lineno,col_offset,end_lineno,end_col_offset|IfExp,expr,AST,object|
Import|names|lineno,col_offset,end_lineno,end_col_offset|Import,stmt,AST,object|
ImportFrom|module,names,level|lineno,col_offset,end_lineno,end_col_offset|ImportFrom,stmt,AST,object|module,level
In|||In,cmpop,AST,object|
Interactive|body||Interactive,mod,AST,object|
Interpolation|value,str,conversion,format_spec|lineno,col_offset,end_lineno,end_col_offset|Interpolation,expr,AST,object|format_spec
Invert|||Invert,unaryop,AST,object|
Is|||Is,cmpop,AST,object|
IsNot|||IsNot,cmpop,AST,object|
JoinedStr|values|lineno,col_offset,end_lineno,end_col_offset|JoinedStr,expr,AST,object|
LShift|||LShift,operator,AST,object|
Lambda|args,body|lineno,col_offset,end_lineno,end_col_offset|Lambda,expr,AST,object|
List|elts,ctx|lineno,col_offset,end_lineno,end_col_offset|List,expr,AST,object|
ListComp|elt,generators|lineno,col_offset,end_lineno,end_col_offset|ListComp,expr,AST,object|
Load|||Load,expr_context,AST,object|
Lt|||Lt,cmpop,AST,object|
LtE|||LtE,cmpop,AST,object|
MatMult|||MatMult,operator,AST,object|
Match|subject,cases|lineno,col_offset,end_lineno,end_col_offset|Match,stmt,AST,object|
MatchAs|pattern,name|lineno,col_offset,end_lineno,end_col_offset|MatchAs,pattern,AST,object|pattern,name
MatchClass|cls,patterns,kwd_attrs,kwd_patterns|lineno,col_offset,end_lineno,end_col_offset|MatchClass,pattern,AST,object|
MatchMapping|keys,patterns,rest|lineno,col_offset,end_lineno,end_col_offset|MatchMapping,pattern,AST,object|rest
MatchOr|patterns|lineno,col_offset,end_lineno,end_col_offset|MatchOr,pattern,AST,object|
MatchSequence|patterns|lineno,col_offset,end_lineno,end_col_offset|MatchSequence,pattern,AST,object|
MatchSingleton|value|lineno,col_offset,end_lineno,end_col_offset|MatchSingleton,pattern,AST,object|
MatchStar|name|lineno,col_offset,end_lineno,end_col_offset|MatchStar,pattern,AST,object|name
MatchValue|value|lineno,col_offset,end_lineno,end_col_offset|MatchValue,pattern,AST,object|
Mod|||Mod,operator,AST,object|
Module|body,type_ignores||Module,mod,AST,object|
Mult|||Mult,operator,AST,object|
Name|id,ctx|lineno,col_offset,end_lineno,end_col_offset|Name,expr,AST,object|
NamedExpr|target,value|lineno,col_offset,end_lineno,end_col_offset|NamedExpr,expr,AST,object|
Nonlocal|names|lineno,col_offset,end_lineno,end_col_offset|Nonlocal,stmt,AST,object|
Not|||Not,unaryop,AST,object|
NotEq|||NotEq,cmpop,AST,object|
NotIn|||NotIn,cmpop,AST,object|
Or|||Or,boolop,AST,object|
ParamSpec|name,default_value|lineno,col_offset,end_lineno,end_col_offset|ParamSpec,type_param,AST,object|default_value
Pass||lineno,col_offset,end_lineno,end_col_offset|Pass,stmt,AST,object|
Pow|||Pow,operator,AST,object|
RShift|||RShift,operator,AST,object|
Raise|exc,cause|lineno,col_offset,end_lineno,end_col_offset|Raise,stmt,AST,object|exc,cause
Return|value|lineno,col_offset,end_lineno,end_col_offset|Return,stmt,AST,object|value
Set|elts|lineno,col_offset,end_lineno,end_col_offset|Set,expr,AST,object|
SetComp|elt,generators|lineno,col_offset,end_lineno,end_col_offset|SetComp,expr,AST,object|
Slice|lower,upper,step|lineno,col_offset,end_lineno,end_col_offset|Slice,expr,AST,object|lower,upper,step
Starred|value,ctx|lineno,col_offset,end_lineno,end_col_offset|Starred,expr,AST,object|
Store|||Store,expr_context,AST,object|
Sub|||Sub,operator,AST,object|
Subscript|value,slice,ctx|lineno,col_offset,end_lineno,end_col_offset|Subscript,expr,AST,object|
TemplateStr|values|lineno,col_offset,end_lineno,end_col_offset|TemplateStr,expr,AST,object|
Try|body,handlers,orelse,finalbody|lineno,col_offset,end_lineno,end_col_offset|Try,stmt,AST,object|
TryStar|body,handlers,orelse,finalbody|lineno,col_offset,end_lineno,end_col_offset|TryStar,stmt,AST,object|
Tuple|elts,ctx|lineno,col_offset,end_lineno,end_col_offset|Tuple,expr,AST,object|
TypeAlias|name,type_params,value|lineno,col_offset,end_lineno,end_col_offset|TypeAlias,stmt,AST,object|
TypeIgnore|lineno,tag||TypeIgnore,type_ignore,AST,object|
TypeVar|name,bound,default_value|lineno,col_offset,end_lineno,end_col_offset|TypeVar,type_param,AST,object|bound,default_value
TypeVarTuple|name,default_value|lineno,col_offset,end_lineno,end_col_offset|TypeVarTuple,type_param,AST,object|default_value
UAdd|||UAdd,unaryop,AST,object|
USub|||USub,unaryop,AST,object|
UnaryOp|op,operand|lineno,col_offset,end_lineno,end_col_offset|UnaryOp,expr,AST,object|
While|test,body,orelse|lineno,col_offset,end_lineno,end_col_offset|While,stmt,AST,object|
With|items,body,type_comment|lineno,col_offset,end_lineno,end_col_offset|With,stmt,AST,object|type_comment
Yield|value|lineno,col_offset,end_lineno,end_col_offset|Yield,expr,AST,object|value
YieldFrom|value|lineno,col_offset,end_lineno,end_col_offset|YieldFrom,expr,AST,object|
alias|name,asname|lineno,col_offset,end_lineno,end_col_offset|alias,AST,object|asname,end_lineno,end_col_offset
arg|arg,annotation,type_comment|lineno,col_offset,end_lineno,end_col_offset|arg,AST,object|annotation,type_comment,end_lineno,end_col_offset
arguments|posonlyargs,args,vararg,kwonlyargs,kw_defaults,kwarg,defaults||arguments,AST,object|vararg,kwarg
boolop|||boolop,AST,object|
cmpop|||cmpop,AST,object|
comprehension|target,iter,ifs,is_async||comprehension,AST,object|
excepthandler||lineno,col_offset,end_lineno,end_col_offset|excepthandler,AST,object|end_lineno,end_col_offset
expr||lineno,col_offset,end_lineno,end_col_offset|expr,AST,object|end_lineno,end_col_offset
expr_context|||expr_context,AST,object|
keyword|arg,value|lineno,col_offset,end_lineno,end_col_offset|keyword,AST,object|arg,end_lineno,end_col_offset
match_case|pattern,guard,body||match_case,AST,object|guard
mod|||mod,AST,object|
operator|||operator,AST,object|
pattern||lineno,col_offset,end_lineno,end_col_offset|pattern,AST,object|
stmt||lineno,col_offset,end_lineno,end_col_offset|stmt,AST,object|end_lineno,end_col_offset
type_ignore|||type_ignore,AST,object|
type_param||lineno,col_offset,end_lineno,end_col_offset|type_param,AST,object|
unaryop|||unaryop,AST,object|
withitem|context_expr,optional_vars||withitem,AST,object|optional_vars
"""
_SLOTS = {
    "AST": {
        "__delattr__": ("wrapper_descriptor", "AST", "__delattr__", None),
        "__dict__": ("getset_descriptor", "AST", "__dict__", None),
        "__getattribute__": ("wrapper_descriptor", "AST", "__getattribute__", None),
        "__init__": ("wrapper_descriptor", "AST", "__init__", None),
        "__new__": ("builtin_function_or_method", None, "__new__", "AST"),
        "__repr__": ("wrapper_descriptor", "AST", "__repr__", None),
        "__setattr__": ("wrapper_descriptor", "AST", "__setattr__", None),
    }
}

_FIELD_TYPES = """
Add|
And|
AnnAssign|target=expr;annotation=expr;value=union(expr,NoneType);simple=int
Assert|test=expr;msg=union(expr,NoneType)
Assign|targets=list(expr);value=expr;type_comment=union(str,NoneType)
AsyncFor|target=expr;iter=expr;body=list(stmt);orelse=list(stmt);type_comment=union(str,NoneType)
AsyncFunctionDef|name=str;args=arguments;body=list(stmt);decorator_list=list(expr);returns=union(expr,NoneType);type_comment=union(str,NoneType);type_params=list(type_param)
AsyncWith|items=list(withitem);body=list(stmt);type_comment=union(str,NoneType)
Attribute|value=expr;attr=str;ctx=expr_context
AugAssign|target=expr;op=operator;value=expr
Await|value=expr
BinOp|left=expr;op=operator;right=expr
BitAnd|
BitOr|
BitXor|
BoolOp|op=boolop;values=list(expr)
Break|
Call|func=expr;args=list(expr);keywords=list(keyword)
ClassDef|name=str;bases=list(expr);keywords=list(keyword);body=list(stmt);decorator_list=list(expr);type_params=list(type_param)
Compare|left=expr;ops=list(cmpop);comparators=list(expr)
Constant|value=object;kind=union(str,NoneType)
Continue|
Del|
Delete|targets=list(expr)
Dict|keys=list(expr);values=list(expr)
DictComp|key=expr;value=expr;generators=list(comprehension)
Div|
Eq|
ExceptHandler|type=union(expr,NoneType);name=union(str,NoneType);body=list(stmt)
Expr|value=expr
Expression|body=expr
FloorDiv|
For|target=expr;iter=expr;body=list(stmt);orelse=list(stmt);type_comment=union(str,NoneType)
FormattedValue|value=expr;conversion=int;format_spec=union(expr,NoneType)
FunctionDef|name=str;args=arguments;body=list(stmt);decorator_list=list(expr);returns=union(expr,NoneType);type_comment=union(str,NoneType);type_params=list(type_param)
FunctionType|argtypes=list(expr);returns=expr
GeneratorExp|elt=expr;generators=list(comprehension)
Global|names=list(str)
Gt|
GtE|
If|test=expr;body=list(stmt);orelse=list(stmt)
IfExp|test=expr;body=expr;orelse=expr
Import|names=list(alias)
ImportFrom|module=union(str,NoneType);names=list(alias);level=union(int,NoneType)
In|
Interactive|body=list(stmt)
Interpolation|value=expr;str=object;conversion=int;format_spec=union(expr,NoneType)
Invert|
Is|
IsNot|
JoinedStr|values=list(expr)
LShift|
Lambda|args=arguments;body=expr
List|elts=list(expr);ctx=expr_context
ListComp|elt=expr;generators=list(comprehension)
Load|
Lt|
LtE|
MatMult|
Match|subject=expr;cases=list(match_case)
MatchAs|pattern=union(pattern,NoneType);name=union(str,NoneType)
MatchClass|cls=expr;patterns=list(pattern);kwd_attrs=list(str);kwd_patterns=list(pattern)
MatchMapping|keys=list(expr);patterns=list(pattern);rest=union(str,NoneType)
MatchOr|patterns=list(pattern)
MatchSequence|patterns=list(pattern)
MatchSingleton|value=object
MatchStar|name=union(str,NoneType)
MatchValue|value=expr
Mod|
Module|body=list(stmt);type_ignores=list(type_ignore)
Mult|
Name|id=str;ctx=expr_context
NamedExpr|target=expr;value=expr
Nonlocal|names=list(str)
Not|
NotEq|
NotIn|
Or|
ParamSpec|name=str;default_value=union(expr,NoneType)
Pass|
Pow|
RShift|
Raise|exc=union(expr,NoneType);cause=union(expr,NoneType)
Return|value=union(expr,NoneType)
Set|elts=list(expr)
SetComp|elt=expr;generators=list(comprehension)
Slice|lower=union(expr,NoneType);upper=union(expr,NoneType);step=union(expr,NoneType)
Starred|value=expr;ctx=expr_context
Store|
Sub|
Subscript|value=expr;slice=expr;ctx=expr_context
TemplateStr|values=list(expr)
Try|body=list(stmt);handlers=list(excepthandler);orelse=list(stmt);finalbody=list(stmt)
TryStar|body=list(stmt);handlers=list(excepthandler);orelse=list(stmt);finalbody=list(stmt)
Tuple|elts=list(expr);ctx=expr_context
TypeAlias|name=expr;type_params=list(type_param);value=expr
TypeIgnore|lineno=int;tag=str
TypeVar|name=str;bound=union(expr,NoneType);default_value=union(expr,NoneType)
TypeVarTuple|name=str;default_value=union(expr,NoneType)
UAdd|
USub|
UnaryOp|op=unaryop;operand=expr
While|test=expr;body=list(stmt);orelse=list(stmt)
With|items=list(withitem);body=list(stmt);type_comment=union(str,NoneType)
Yield|value=union(expr,NoneType)
YieldFrom|value=expr
alias|name=str;asname=union(str,NoneType)
arg|arg=str;annotation=union(expr,NoneType);type_comment=union(str,NoneType)
arguments|posonlyargs=list(arg);args=list(arg);vararg=union(arg,NoneType);kwonlyargs=list(arg);kw_defaults=list(expr);kwarg=union(arg,NoneType);defaults=list(expr)
comprehension|target=expr;iter=expr;ifs=list(expr);is_async=int
keyword|arg=union(str,NoneType);value=expr
match_case|pattern=pattern;guard=union(expr,NoneType);body=list(stmt)
withitem|context_expr=expr;optional_vars=union(expr,NoneType)
"""


def _type_name(value, known):
    if type(value) is type and value in known:
        return known[value]
    if (
        type(value) is GenericAlias
        and value.__origin__ is list
        and len(value.__args__) == 1
    ):
        return "list(" + _type_name(value.__args__[0], known) + ")"
    if type(value) is UnionType:
        return (
            "union("
            + ",".join(_type_name(item, known) for item in value.__args__)
            + ")"
        )
    raise ValueError("modified AST field type")


def schemas():
    standard = {}
    for row in _ROWS.strip().splitlines():
        name, *columns = row.split("|")
        standard[name] = tuple(
            tuple(part.split(",")) if part else () for part in columns
        )
    classes = {name: vars(_ast).get(name) for name in standard}
    for name, (fields, attributes, mro_names, defaults) in standard.items():
        cls = classes[name]
        if type(cls) is not type or vars(ast).get(name) is not cls:
            raise ValueError("modified AST class")
        expected_mro = tuple(
            object if base == "object" else classes[base] for base in mro_names
        )
        if cls.__mro__ != expected_mro:
            raise ValueError("modified AST inheritance")
        own = vars(cls)
        for key, expected in (
            ("_fields", fields),
            ("_attributes", attributes),
            ("__match_args__", fields),
        ):
            value = next(
                (vars(base)[key] for base in cls.__mro__ if key in vars(base)), MISSING
            )
            if (
                type(value) is not tuple
                or any(type(item) is not str for item in value)
                or value != expected
            ):
                raise ValueError("modified AST schema")
        for key in fields + LOCATIONS:
            if own.get(key, MISSING) is not (None if key in defaults else MISSING):
                raise ValueError("modified AST field descriptor")
        for key in SPECIALS:
            value = own.get(key, MISSING)
            expected = _SLOTS.get(name, {}).get(key)
            if expected is None:
                if value is not MISSING:
                    raise ValueError("modified AST method")
            else:
                actual = (
                    type(value).__name__,
                    getattr(getattr(value, "__objclass__", None), "__name__", None),
                    getattr(value, "__name__", None),
                    getattr(getattr(value, "__self__", None), "__name__", None),
                )
                if actual != expected:
                    raise ValueError("modified AST method")
    known = {value: name for name, value in classes.items()}
    known.update(
        {value: value.__name__ for value in (object, str, int, list, type(None))}
    )
    expected_types = dict(
        row.split("|", 1) for row in _FIELD_TYPES.strip().splitlines()
    )
    field_maps = []
    for name, cls in classes.items():
        mapping = vars(cls).get("_field_types", MISSING)
        expected = expected_types.get(name)
        if expected is None:
            if mapping is not MISSING:
                raise ValueError("modified AST field types")
        else:
            if type(mapping) is not dict or any(
                type(key) is not str for key in mapping
            ):
                raise ValueError("modified AST field types")
            actual = ";".join(
                key + "=" + _type_name(value, known) for key, value in mapping.items()
            )
            if actual != expected:
                raise ValueError("modified AST field types")
            field_maps.append((mapping, tuple(mapping.items())))
    rows = []
    for name, (fields, attributes, _, _) in standard.items():
        cls = classes[name]
        keys = tuple(
            dict.fromkeys(
                SPECIALS
                + ("_fields", "_attributes", "_field_types", "__match_args__")
                + fields
                + LOCATIONS
            )
        )
        checks = []
        for base in cls.__mro__:
            own = vars(base)
            defaults = () if base is object else standard[base.__name__][3]
            for key in fields + LOCATIONS:
                if own.get(key, MISSING) is not (None if key in defaults else MISSING):
                    raise ValueError("modified inherited AST field")
            for key in keys:
                value = own.get(key, MISSING)
                checks.append(
                    (
                        base,
                        key,
                        value is not MISSING,
                        None if value is MISSING else value,
                    )
                )

        def default(key, cls=cls):
            for base in cls.__mro__:
                if key in vars(base):
                    return True, vars(base)[key]
            return False, None

        rows.append(
            (
                cls,
                cls.__mro__,
                tuple(checks),
                tuple((field, *default(field)) for field in fields),
                tuple(key in attributes for key in LOCATIONS),
                tuple(default(key) for key in LOCATIONS),
            )
        )
    return tuple(rows), classes["Assert"], tuple(field_maps)
