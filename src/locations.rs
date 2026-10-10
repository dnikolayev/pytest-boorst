//! Atomic, module-batched AST location updates for guarded CPython 3.14 trees.
use pyo3::PyTypeInfo;
use pyo3::exceptions::PyValueError;
use pyo3::ffi;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyInt, PyList, PyMappingProxy, PyString, PyTuple, PyType};
use std::collections::{HashMap, HashSet};

const LOCATIONS: [&str; 4] = ["lineno", "col_offset", "end_lineno", "end_col_offset"];
const MAX_DEPTH: usize = 64;
const MAX_VISITS: usize = 100_000;
const MAX_BATCH_VISITS: usize = 1_000_000;

struct Check {
    index: usize,
    owner: Py<PyType>,
    key: Py<PyString>,
    expected: Option<Py<PyAny>>,
}

type NodeValues<'py> = (
    Vec<Option<Bound<'py, PyAny>>>,
    [Option<Bound<'py, PyAny>>; 4],
);
type GuardMap = HashMap<(usize, String), (usize, Option<Py<PyAny>>)>;

struct Field {
    default: Option<Py<PyAny>>,
}

struct FieldMap {
    mapping: Py<PyDict>,
    items: Vec<(Py<PyString>, Py<PyAny>)>,
}

impl FieldMap {
    fn valid(&self, py: Python<'_>) -> bool {
        let mapping = self.mapping.bind(py);
        mapping.len() == self.items.len()
            && mapping.iter().zip(&self.items).all(
                |((key, value), (expected_key, expected_value))| {
                    key.is(expected_key.bind(py)) && value.is(expected_value.bind(py))
                },
            )
    }
}

struct Schema {
    ty: Py<PyType>,
    mro: Py<PyTuple>,
    checks: Vec<Check>,
    fields: Vec<Field>,
    field_indices: HashMap<String, usize>,
    attributes: [bool; 4],
    location_defaults: [Option<Py<PyAny>>; 4],
}

#[pyclass(frozen)]
pub struct LocationPlan {
    guard_count: usize,
    schemas: Vec<Schema>,
    indices: HashMap<usize, usize>,
    scalars: HashSet<usize>,
    assert_index: usize,
    keys: [Py<PyString>; 4],
    field_maps: Vec<FieldMap>,
}

// Call only for exact AST instances after validating their stock dictionary
// descriptor. GenericGetDict must never be used on class objects.
fn dictionary<'py>(
    py: Python<'py>,
    value: &Bound<'py, PyAny>,
) -> PyResult<Option<Bound<'py, PyDict>>> {
    let raw = unsafe { ffi::PyObject_GenericGetDict(value.as_ptr(), std::ptr::null_mut()) };
    let result = unsafe { Bound::from_owned_ptr_or_err(py, raw)? };
    if !result.is_exact_instance_of::<PyDict>() {
        return Ok(None);
    }
    Ok(Some(result.cast_into::<PyDict>()?))
}

fn class_dictionary<'py>(owner: &Bound<'py, PyType>) -> PyResult<Option<Bound<'py, PyDict>>> {
    let proxy = owner.getattr("__dict__")?;
    if !proxy.is_exact_instance_of::<PyMappingProxy>() {
        return Ok(None);
    }
    let copy = proxy.call_method0("copy")?;
    if !copy.is_exact_instance_of::<PyDict>() {
        return Ok(None);
    }
    Ok(Some(copy.cast_into::<PyDict>()?))
}

fn same_optional(value: Option<&Bound<'_, PyAny>>, expected: Option<&Bound<'_, PyAny>>) -> bool {
    match (value, expected) {
        (None, None) => true,
        (Some(value), Some(expected)) => value.is(expected),
        _ => false,
    }
}

fn coordinate(value: &Bound<'_, PyAny>) -> bool {
    value.is_none() || value.is_exact_instance_of::<PyInt>()
}

impl Schema {
    fn valid<'py>(
        &self,
        py: Python<'py>,
        dictionaries: &mut HashMap<usize, Bound<'py, PyDict>>,
        checked: &mut [bool],
    ) -> PyResult<bool> {
        let ty = self.ty.bind(py);
        if !ty.get_type().is(PyType::type_object(py)) {
            return Ok(false);
        }
        if !ty.getattr("__mro__")?.is(self.mro.bind(py)) {
            return Ok(false);
        }
        // Each exact class mappingproxy is copied once per call, shared across
        // encountered schemas. Keep snapshots local so later mutations are live.
        for check in &self.checks {
            if checked[check.index] {
                continue;
            }
            let owner = check.owner.bind(py);
            let pointer = owner.as_ptr() as usize;
            if let std::collections::hash_map::Entry::Vacant(entry) = dictionaries.entry(pointer) {
                if !owner.get_type().is(PyType::type_object(py)) {
                    return Ok(false);
                }
                let Some(current) = class_dictionary(owner)? else {
                    return Ok(false);
                };
                entry.insert(current);
            }
            let value = dictionaries
                .get(&pointer)
                .unwrap()
                .get_item(check.key.bind(py))?;
            if !same_optional(
                value.as_ref(),
                check.expected.as_ref().map(|value| value.bind(py)),
            ) {
                return Ok(false);
            }
            checked[check.index] = true;
        }
        Ok(true)
    }

    fn values<'py>(&self, py: Python<'py>, dict: &Bound<'py, PyDict>) -> Option<NodeValues<'py>> {
        let mut fields: Vec<_> = self
            .fields
            .iter()
            .map(|field| field.default.as_ref().map(|value| value.bind(py).clone()))
            .collect();
        let mut locations = std::array::from_fn(|i| {
            self.location_defaults[i]
                .as_ref()
                .map(|value| value.bind(py).clone())
        });
        // Iteration does not hash keys or invoke their equality methods. A later
        // direct dict write is safe only after every stored key is an exact str.
        for (key, value) in dict.iter() {
            if !key.is_exact_instance_of::<PyString>() {
                return None;
            }
            let Ok(key) = key.cast::<PyString>() else {
                return None;
            };
            let Ok(name) = key.to_str() else {
                return None;
            };
            if name == "_fields" || name == "_attributes" {
                return None;
            }
            if let Some(&index) = self.field_indices.get(name) {
                fields[index] = Some(value.clone());
            }
            if let Some(index) = LOCATIONS.iter().position(|candidate| *candidate == name) {
                locations[index] = Some(value);
            }
        }
        Some((fields, locations))
    }
}

enum Work<'py> {
    Visit(Bound<'py, PyAny>, usize),
    Exit(usize),
}

struct Write<'py> {
    dictionary: Bound<'py, PyDict>,
    source: usize,
    mask: u8,
}

#[pymethods]
impl LocationPlan {
    fn valid_classes(&self, py: Python<'_>) -> PyResult<bool> {
        if !self.field_maps.iter().all(|mapping| mapping.valid(py)) {
            return Ok(false);
        }
        let mut dictionaries = HashMap::new();
        let mut checked = vec![false; self.guard_count];
        for schema in &self.schemas {
            if !schema.valid(py, &mut dictionaries, &mut checked)? {
                return Ok(false);
            }
        }
        Ok(true)
    }

    fn fill_batches<'py>(&self, py: Python<'py>, batches: &Bound<'py, PyAny>) -> PyResult<bool> {
        let version = py.version_info();
        if version.major != 3 || version.minor != 14 || !batches.is_exact_instance_of::<PyList>() {
            return Ok(false);
        }
        if !self.field_maps.iter().all(|mapping| mapping.valid(py)) {
            return Ok(false);
        }
        let source_schema = &self.schemas[self.assert_index];
        let mut class_dictionaries = HashMap::new();
        let mut checked = vec![false; self.guard_count];
        let mut validated = HashSet::new();
        let mut filled_lineno = HashSet::new();
        let mut plan = Vec::<Write<'py>>::new();
        let mut sources = Vec::new();
        let mut leaf_nodes = HashSet::new();
        let mut batch_visits = 0usize;
        for batch in batches.cast::<PyList>()?.iter() {
            if !batch.is_exact_instance_of::<PyTuple>() {
                return Ok(false);
            }
            let batch = batch.cast::<PyTuple>()?;
            if batch.len() != 2 {
                return Ok(false);
            }
            let roots = batch.get_item(0)?;
            let source = batch.get_item(1)?;
            if !roots.is_exact_instance_of::<PyList>()
                || !source.get_type().is(source_schema.ty.bind(py))
            {
                return Ok(false);
            }
            if validated.insert(self.assert_index)
                && !source_schema.valid(py, &mut class_dictionaries, &mut checked)?
            {
                return Ok(false);
            }
            let Some(source_dict) = dictionary(py, &source)? else {
                return Ok(false);
            };
            let Some((_, source_locations)) = source_schema.values(py, &source_dict) else {
                return Ok(false);
            };
            if source_locations
                .iter()
                .flatten()
                .any(|value| !coordinate(value))
            {
                return Ok(false);
            }
            let source_index = sources.len();
            sources.push(source_locations);
            let source_locations = &sources[source_index];
            let roots = roots.cast::<PyList>()?;
            let mut stack: Vec<_> = roots
                .iter()
                .rev()
                .map(|node| Work::Visit(node, 0))
                .collect();
            let mut active = HashSet::new();
            let mut visits = 0usize;

            while let Some(work) = stack.pop() {
                let (node, depth) = match work {
                    Work::Exit(pointer) => {
                        active.remove(&pointer);
                        continue;
                    }
                    Work::Visit(node, depth) => (node, depth),
                };
                visits += 1;
                batch_visits += 1;
                let pointer = node.as_ptr() as usize;
                if depth > MAX_DEPTH
                    || visits > MAX_VISITS
                    || batch_visits > MAX_BATCH_VISITS
                    || !active.insert(pointer)
                {
                    return Ok(false);
                }
                let Some(&index) = self.indices.get(&(node.get_type_ptr() as usize)) else {
                    return Ok(false);
                };
                // Source assertions cannot also be targets: earlier writes would
                // change the coordinates copied by a later forest.
                if index == self.assert_index {
                    return Ok(false);
                }
                let schema = &self.schemas[index];
                if validated.insert(index)
                    && !schema.valid(py, &mut class_dictionaries, &mut checked)?
                {
                    return Ok(false);
                }
                if leaf_nodes.contains(&pointer) {
                    active.remove(&pointer);
                    continue;
                }
                let Some(dict) = dictionary(py, &node)? else {
                    return Ok(false);
                };
                let Some((fields, locations)) = schema.values(py, &dict) else {
                    return Ok(false);
                };
                if schema.fields.is_empty() && !schema.attributes.iter().any(|present| *present) {
                    leaf_nodes.insert(pointer);
                    active.remove(&pointer);
                    continue;
                }
                let mut mask = 0u8;
                if !filled_lineno.contains(&pointer)
                    && locations[0].as_ref().is_none_or(|value| value.is_none())
                {
                    for i in 0..4 {
                        if !schema.attributes[i] || !source_schema.attributes[i] {
                            continue;
                        }
                        let Some(value) = &source_locations[i] else {
                            continue;
                        };
                        if value.is_none() && i < 2 {
                            continue;
                        }
                        if locations[i].as_ref().is_some_and(|old| !coordinate(old)) {
                            return Ok(false);
                        }
                        mask |= 1 << i;
                        if i == 0 && !value.is_none() {
                            filled_lineno.insert(pointer);
                        }
                    }
                }

                if mask != 0 {
                    plan.push(Write {
                        dictionary: dict,
                        source: source_index,
                        mask,
                    });
                }

                // All callbacks remain on the stock fallback path. Do not suppress
                // arbitrary objects' __class__ behavior during stock isinstance.
                let mut children = Vec::new();
                for value in fields.into_iter().flatten() {
                    if self.indices.contains_key(&(value.get_type_ptr() as usize)) {
                        children.push(value);
                    } else if value.is_exact_instance_of::<PyList>() {
                        for child in value.cast::<PyList>()?.iter() {
                            if self.indices.contains_key(&(child.get_type_ptr() as usize)) {
                                children.push(child);
                            } else if !self.scalars.contains(&(child.get_type_ptr() as usize)) {
                                return Ok(false);
                            }
                        }
                    } else if !self.scalars.contains(&(value.get_type_ptr() as usize)) {
                        return Ok(false);
                    }
                }
                stack.push(Work::Exit(pointer));
                stack.extend(
                    children
                        .into_iter()
                        .rev()
                        .map(|child| Work::Visit(child, depth + 1)),
                );
            }
        }

        // Nothing that can invoke ordinary Python callbacks is intentionally
        // called after preflight. Dict failures propagate rather than retrying
        // stock against a partially modified graph.
        for write in plan {
            for (i, value) in sources[write.source].iter().enumerate() {
                if write.mask & (1 << i) != 0 {
                    write
                        .dictionary
                        .set_item(self.keys[i].bind(py), value.as_ref().unwrap())?;
                }
            }
        }
        Ok(true)
    }
}

// Rows: (type, mro, checks, fields, attribute-mask, location-defaults).
// Checks: (owner-type, key, present, expected). Fields/defaults: (key,present,value).
#[pyfunction]
pub fn location_plan(
    py: Python<'_>,
    rows: &Bound<'_, PyTuple>,
    scalar_types: &Bound<'_, PyTuple>,
    assert_type: &Bound<'_, PyType>,
    field_type_maps: &Bound<'_, PyTuple>,
) -> PyResult<LocationPlan> {
    let version = py.version_info();
    if version.major != 3 || version.minor != 14 {
        return Err(PyValueError::new_err(
            "AST location batches require CPython 3.14",
        ));
    }
    let mut schemas = Vec::new();
    let mut indices = HashMap::new();
    let mut guards = GuardMap::new();
    for row in rows.iter() {
        let row = row.cast::<PyTuple>()?;
        let ty = row.get_item(0)?.cast_into::<PyType>()?;
        let mro = row.get_item(1)?.cast_into::<PyTuple>()?;
        let mut checks = Vec::new();
        for check in row.get_item(2)?.cast::<PyTuple>()?.iter() {
            let check = check.cast::<PyTuple>()?;
            let owner = check.get_item(0)?.cast_into::<PyType>()?;
            let key = check.get_item(1)?.cast_into::<PyString>()?;
            let token = (owner.as_ptr() as usize, key.to_str()?.to_owned());
            let expected = if check.get_item(2)?.extract::<bool>()? {
                Some(check.get_item(3)?)
            } else {
                None
            };
            let index = if let Some((index, prior)) = guards.get(&token) {
                if !same_optional(
                    expected.as_ref(),
                    prior.as_ref().map(|value| value.bind(py)),
                ) {
                    return Err(PyValueError::new_err(
                        "conflicting class guard expectations",
                    ));
                }
                *index
            } else {
                let index = guards.len();
                guards.insert(
                    token,
                    (index, expected.as_ref().map(|value| value.clone().unbind())),
                );
                index
            };
            checks.push(Check {
                index,
                owner: owner.unbind(),
                key: key.unbind(),
                expected: expected.map(|value| value.unbind()),
            });
        }
        let mut fields = Vec::new();
        let mut field_indices = HashMap::new();
        for field in row.get_item(3)?.cast::<PyTuple>()?.iter() {
            let field = field.cast::<PyTuple>()?;
            let name = field.get_item(0)?.extract::<String>()?;
            field_indices.insert(name.clone(), fields.len());
            fields.push(Field {
                default: if field.get_item(1)?.extract::<bool>()? {
                    Some(field.get_item(2)?.unbind())
                } else {
                    None
                },
            });
        }
        let attributes: [bool; 4] = row.get_item(4)?.extract()?;
        let defaults = row.get_item(5)?.cast_into::<PyTuple>()?;
        let mut location_defaults = std::array::from_fn(|_| None);
        for (i, destination) in location_defaults.iter_mut().enumerate() {
            let default = defaults.get_item(i)?.cast_into::<PyTuple>()?;
            if default.get_item(0)?.extract::<bool>()? {
                *destination = Some(default.get_item(1)?.unbind());
            }
        }
        indices.insert(ty.as_ptr() as usize, schemas.len());
        schemas.push(Schema {
            ty: ty.unbind(),
            mro: mro.unbind(),
            checks,
            fields,
            field_indices,
            attributes,
            location_defaults,
        });
    }
    let assert_index = *indices
        .get(&(assert_type.as_ptr() as usize))
        .ok_or_else(|| PyValueError::new_err("missing Assert schema"))?;
    let mut scalars = HashSet::new();
    for ty in scalar_types.iter() {
        scalars.insert(ty.cast::<PyType>()?.as_ptr() as usize);
    }
    let mut field_maps = Vec::new();
    for item in field_type_maps.iter() {
        let item = item.cast::<PyTuple>()?;
        let mapping = item.get_item(0)?.cast_into::<PyDict>()?;
        if !mapping.is_exact_instance_of::<PyDict>() {
            return Err(PyValueError::new_err(
                "field types must be plain dictionaries",
            ));
        }
        let mut items = Vec::new();
        for entry in item.get_item(1)?.cast::<PyTuple>()?.iter() {
            let entry = entry.cast::<PyTuple>()?;
            let key = entry.get_item(0)?.cast_into::<PyString>()?;
            if !key.is_exact_instance_of::<PyString>() {
                return Err(PyValueError::new_err(
                    "field type keys must be plain strings",
                ));
            }
            items.push((key.unbind(), entry.get_item(1)?.unbind()));
        }
        field_maps.push(FieldMap {
            mapping: mapping.unbind(),
            items,
        });
    }
    Ok(LocationPlan {
        guard_count: guards.len(),
        schemas,
        indices,
        scalars,
        assert_index,
        keys: std::array::from_fn(|i| PyString::new(py, LOCATIONS[i]).unbind()),
        field_maps,
    })
}
