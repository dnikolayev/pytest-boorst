use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::collections::HashMap;

fn make_unique(mut ids: Vec<String>) -> Result<Vec<String>, &'static str> {
    if ids.iter().any(|id| !id.is_ascii()) {
        return Err("unique_ids only supports ASCII strings");
    }

    let mut original_counts = HashMap::new();
    for id in &ids {
        *original_counts.entry(id.clone()).or_insert(0usize) += 1;
    }
    if original_counts.len() == ids.len() {
        return Ok(ids);
    }

    let mut occupied = original_counts.clone();
    let mut suffixes = HashMap::new();
    for id in &mut ids {
        if original_counts[id.as_str()] == 1 {
            continue;
        }
        let separator = if id.as_bytes().last().is_some_and(u8::is_ascii_digit) {
            "_"
        } else {
            ""
        };
        let next = suffixes.entry(id.clone()).or_insert(0usize);
        let replacement = loop {
            let candidate = format!("{id}{separator}{next}");
            *next += 1;
            if !occupied.contains_key(&candidate) {
                break candidate;
            }
        };

        // Replacing the last occurrence frees its name for later suffixes.
        let remaining = occupied.get_mut(id.as_str()).unwrap();
        *remaining -= 1;
        if *remaining == 0 {
            occupied.remove(id.as_str());
        }
        occupied.insert(replacement.clone(), 1);
        *id = replacement;
    }
    Ok(ids)
}

#[pyfunction]
fn unique_ids(ids: Vec<String>) -> PyResult<Vec<String>> {
    make_unique(ids).map_err(PyValueError::new_err)
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(unique_ids, module)?)
}

#[cfg(test)]
mod tests {
    use super::make_unique;

    #[test]
    fn preserves_pytest_suffixes_and_live_occupancy() {
        for (input, expected) in [
            (vec![], vec![]),
            (vec!["a", "b", ""], vec!["a", "b", ""]),
            (vec!["a", "a", "a0"], vec!["a1", "a2", "a0"]),
            (vec!["1", "1", "1_0"], vec!["1_1", "1_2", "1_0"]),
            (vec!["", "", "0"], vec!["1", "2", "0"]),
            (vec!["a0", "a0", "a", "a"], vec!["a0_0", "a0_1", "a0", "a1"]),
            (vec!["a", "a0", "a", "a0"], vec!["a1", "a0_0", "a2", "a0_1"]),
        ] {
            let input = input.into_iter().map(str::to_owned).collect();
            assert_eq!(make_unique(input).unwrap(), expected);
        }
    }

    #[test]
    fn rejects_unicode_before_processing() {
        for input in [vec!["\u{00e9}"], vec!["a", "a", "\u{00b2}"]] {
            assert!(make_unique(input.into_iter().map(str::to_owned).collect()).is_err());
        }
    }
}
