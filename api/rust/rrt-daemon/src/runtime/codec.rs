//! Encoding/decoding for yr cross-language serialized values plus kwargs parsing.
//! Single-value format: `[8B metadata][8B msgpack_size][msgpack_data][optional cloudpickle]`.
//! akernel method args/returns are simple values (str/int/dict/None), so they use msgpack.

use crate::posix::common::Arg;
use rmpv::Value;
use std::collections::BTreeMap;

/// Decode one yr-serialized value into a msgpack Value.
pub fn yr_deserialize(buf: &[u8]) -> Option<Value> {
    if buf.len() < 16 {
        return None;
    }
    // The Go libruntime path may wrap inline values as
    // [24B internal header][8B little-endian msgpack_size][msgpack_data].
    // This is the shape observed from frontend InvokeByInstanceId for sandbox
    // v1; accept it before trying the older cross-language header variants.
    if buf.len() >= 32 {
        let mut size_bytes = [0u8; 8];
        size_bytes.copy_from_slice(&buf[24..32]);
        let size = u64::from_le_bytes(size_bytes) as usize;
        if size > 0 {
            if let Some(data) = buf.get(32..32 + size) {
                if let Ok(value) = rmpv::decode::read_value(&mut &data[..]) {
                    return Some(value);
                }
            }
        }
    }
    // size is the msgpack int stored in header[8:16].
    let mut size_slice = &buf[8..16];
    if let Ok(size) = rmp::decode::read_int::<u64, _>(&mut size_slice) {
        let size = size as usize;
        if size > 0 {
            if let Some(data) = buf.get(16..16 + size) {
                if let Ok(value) = rmpv::decode::read_value(&mut &data[..]) {
                    return Some(value);
                }
            }
        }
    }

    // Some callers (notably libruntime's raw DataObject path) can already
    // strip or re-wrap the size header. Accept the cross-language form
    // `[16B zero header][msgpack]` and a bare msgpack value as fallbacks so
    // sandbox_invoke remains robust across frontend/runtime transport paths.
    rmpv::decode::read_value(&mut &buf[16..])
        .or_else(|_| rmpv::decode::read_value(&mut &buf[..]))
        .ok()
        .and_then(unwrap_msgpack_binary)
}

fn unwrap_msgpack_binary(value: Value) -> Option<Value> {
    match value {
        Value::Binary(bytes) => yr_deserialize(&bytes).or_else(|| {
            rmpv::decode::read_value(&mut &bytes[..])
                .ok()
                .and_then(unwrap_msgpack_binary)
        }),
        other => Some(other),
    }
}

/// Encode a msgpack Value into a yr-serialized value: `[16B zero header][msgpack]`.
/// split_buffer sees metadata=0 && size=0 and infers CROSS_LANGUAGE, with msgpack_data = buf[16:].
pub fn yr_serialize_value(v: &Value) -> Vec<u8> {
    let mut mp = Vec::new();
    let _ = rmpv::encode::write_value(&mut mp, v);
    let mut buf = vec![0u8; 16];
    buf.extend_from_slice(&mp);
    buf
}

/// Extract kwargs from a CallRequest arg list.
///
/// Runtime calls normally prepend protobuf MetaData at args[0], so akernel
/// method kwargs are encoded as alternating key/value entries in args[1:].
/// Some frontend/libruntime paths can pass only the user args, or a single map
/// value. Accept all three shapes so the HTTP sandbox v1 envelope can dispatch
/// to the same RRT primitives without depending on one exact transport wrapper.
pub fn parse_kwargs(args: &[Arg]) -> BTreeMap<String, Value> {
    parse_kwargs_from(args, 1)
        .or_else(|| parse_kwargs_from(args, 0))
        .unwrap_or_default()
}

fn parse_kwargs_from(args: &[Arg], start: usize) -> Option<BTreeMap<String, Value>> {
    if start >= args.len() {
        return None;
    }
    if let Some(Value::Map(kvs)) = yr_deserialize(&args[start].value) {
        let mut m = BTreeMap::new();
        for (k, v) in kvs {
            if let Some(key) = k.as_str() {
                m.insert(key.to_string(), v);
            }
        }
        if !m.is_empty() {
            return Some(m);
        }
    }

    let mut m = BTreeMap::new();
    let mut i = start;
    while i + 1 < args.len() {
        let key = yr_deserialize(&args[i].value).and_then(|v| v.as_str().map(String::from));
        let val = yr_deserialize(&args[i + 1].value);
        if let (Some(k), Some(v)) = (key, val) {
            m.insert(k, v);
        }
        i += 2;
    }
    if m.is_empty() {
        None
    } else {
        Some(m)
    }
}

/// Read a string from kwargs.
pub fn kw_str(kw: &BTreeMap<String, Value>, key: &str) -> Option<String> {
    kw.get(key).and_then(|v| v.as_str().map(String::from))
}

/// Build a return dict as a msgpack map.
pub fn map_value(pairs: Vec<(&str, Value)>) -> Value {
    Value::Map(
        pairs
            .into_iter()
            .map(|(k, v)| (Value::from(k), v))
            .collect(),
    )
}
