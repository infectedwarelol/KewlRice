use std::env;
use std::io::Write;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Command, ExitCode, Stdio};
use std::time::Duration;

const SOCKET_TIMEOUT: Duration = Duration::from_millis(300);

fn runtime_dir() -> PathBuf {
    env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"))
}

fn send_to_daemon(popup: &str) -> std::io::Result<()> {
    let mut connection = UnixStream::connect(runtime_dir().join("kewl-ui.sock"))?;
    connection.set_write_timeout(Some(SOCKET_TIMEOUT))?;
    connection.write_all(format!("popup {popup}").as_bytes())
}

fn launch_standalone(popup: &str) {
    let popups_script = env::current_exe()
        .ok()
        .and_then(|executable| {
            executable
                .parent()
                .map(|directory| directory.join("popups.py"))
        })
        .unwrap_or_else(|| PathBuf::from("popups.py"));
    let _ = Command::new("python3")
        .arg(popups_script)
        .arg(popup)
        .stdin(Stdio::null())
        .process_group(0)
        .spawn();
}

fn main() -> ExitCode {
    let arguments: Vec<String> = env::args().skip(1).collect();
    let [popup] = arguments.as_slice() else {
        return ExitCode::from(2);
    };
    if send_to_daemon(popup).is_err() {
        launch_standalone(popup);
    }
    ExitCode::SUCCESS
}
