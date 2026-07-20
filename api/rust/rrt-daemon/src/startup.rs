//! Runtime startup barrier used by fork-based warm starts.

use std::fs::File;
use std::io::{self, Read};
use std::path::Path;

const SEED_FILE_ENV: &str = "YR_SEED_FILE";
const ENV_FILE_ENV: &str = "YR_ENV_FILE";

/// Block on one read from a configured seed file, then refresh the process
/// environment before any runtime configuration or Tokio worker is created.
pub fn prepare_runtime_environment() -> io::Result<()> {
    wait_for_seed_file()?;

    if let Some(env_file) = std::env::var_os(ENV_FILE_ENV).filter(|value| !value.is_empty()) {
        refresh_environment_from_file(Path::new(&env_file));
    }
    Ok(())
}

fn wait_for_seed_file() -> io::Result<()> {
    let Some(seed_file) = std::env::var_os(SEED_FILE_ENV).filter(|value| !value.is_empty()) else {
        return Ok(());
    };
    let path = Path::new(&seed_file);
    println!("[rrt-runtime] begin reading seed file: {}", path.display());

    let mut file = File::open(path)?;
    let mut byte = [0_u8; 1];
    let bytes_read = file.read(&mut byte)?;

    println!(
        "[rrt-runtime] finished reading seed file: {}, bytes_read={bytes_read}",
        path.display(),
    );
    Ok(())
}

fn refresh_environment_from_file(path: &Path) {
    let content = match std::fs::read_to_string(path) {
        Ok(content) => content,
        Err(error) => {
            eprintln!(
                "[rrt-runtime] failed to load environment file {}: {error}",
                path.display()
            );
            return;
        }
    };

    for (index, raw_line) in content.lines().enumerate() {
        let line_number = index + 1;
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        let Some((raw_key, raw_value)) = line.split_once('=') else {
            eprintln!(
                "[rrt-runtime] invalid environment entry {}:{}: missing '='",
                path.display(),
                line_number
            );
            continue;
        };
        let key = raw_key.trim();
        let value = strip_quotes(raw_value.trim());
        if key.is_empty() || key.contains('\0') || value.contains('\0') {
            eprintln!(
                "[rrt-runtime] invalid environment entry {}:{}",
                path.display(),
                line_number
            );
            continue;
        }

        std::env::set_var(key, value);
    }
}

fn strip_quotes(value: &str) -> &str {
    if value.len() >= 2 {
        let bytes = value.as_bytes();
        if matches!(
            (bytes[0], bytes[bytes.len() - 1]),
            (b'"', b'"') | (b'\'', b'\'')
        ) {
            return &value[1..value.len() - 1];
        }
    }
    value
}

#[cfg(test)]
mod tests {
    use super::strip_quotes;

    #[test]
    fn strip_matching_quotes_only() {
        assert_eq!(strip_quotes("\"quoted value\""), "quoted value");
        assert_eq!(strip_quotes("'quoted value'"), "quoted value");
        assert_eq!(strip_quotes("\"unmatched'"), "\"unmatched'");
        assert_eq!(strip_quotes("plain"), "plain");
    }
}
