use serde_json::Value;
use std::env;
use std::io::{self, Read, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::ExitCode;

const WINDOWED_APPS: [&str; 4] = ["brave-browser", "firefox", "chromium", "google-chrome"];

fn hyprland_socket() -> io::Result<PathBuf> {
    let runtime_dir = env::var_os("XDG_RUNTIME_DIR")
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "XDG_RUNTIME_DIR is not set"))?;
    let signature = env::var_os("HYPRLAND_INSTANCE_SIGNATURE").ok_or_else(|| {
        io::Error::new(
            io::ErrorKind::NotFound,
            "HYPRLAND_INSTANCE_SIGNATURE is not set",
        )
    })?;
    Ok(PathBuf::from(runtime_dir)
        .join("hypr")
        .join(signature)
        .join(".socket.sock"))
}

fn request(command: &str) -> io::Result<String> {
    let mut connection = UnixStream::connect(hyprland_socket()?)?;
    connection.write_all(command.as_bytes())?;
    let mut reply = String::new();
    connection.read_to_string(&mut reply)?;
    Ok(reply)
}

fn request_json(command: &str) -> io::Result<Value> {
    let reply = request(&format!("j/{command}"))?;
    if reply.trim().is_empty() {
        return Ok(Value::Object(Default::default()));
    }
    serde_json::from_str(&reply).map_err(io::Error::other)
}

fn dispatch(arguments: &str) -> io::Result<()> {
    request(&format!("dispatch {arguments}")).map(drop)
}

fn workspace_name(window: &Value) -> &str {
    window
        .pointer("/workspace/name")
        .and_then(Value::as_str)
        .unwrap_or_default()
}

fn list_windows() -> io::Result<Vec<Value>> {
    let Value::Array(clients) = request_json("clients")? else {
        return Ok(Vec::new());
    };
    let mut windows: Vec<Value> = clients
        .into_iter()
        .filter(|client| {
            client
                .get("mapped")
                .and_then(Value::as_bool)
                .unwrap_or(true)
        })
        .filter(|client| workspace_name(client) != "special:hidden")
        .collect();
    windows.sort_by_key(|window| {
        window
            .get("focusHistoryID")
            .and_then(Value::as_i64)
            .unwrap_or(i64::MAX)
    });
    Ok(windows)
}

fn active_window_address() -> io::Result<Option<String>> {
    Ok(request_json("activewindow")?
        .get("address")
        .and_then(Value::as_str)
        .map(str::to_owned))
}

fn switch_to_window(window: &Value) -> io::Result<()> {
    let address = window
        .get("address")
        .and_then(Value::as_str)
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "window has no address"))?;
    let target = format!("address:{address}");
    if workspace_name(window).starts_with("special:") {
        let current = request_json("activeworkspace")?
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_owned();
        dispatch(&format!(
            "hl.dsp.window.move({{ workspace = \"{current}\", window = \"{target}\", follow = false }})"
        ))?;
    }
    dispatch(&format!("hl.dsp.focus({{ window = \"{target}\" }})"))?;
    if active_window_address()?.as_deref() != Some(address) {
        return Ok(());
    }
    let fullscreen = match window.get("fullscreen") {
        Some(Value::Bool(state)) => *state,
        Some(Value::Number(state)) => state.as_i64().unwrap_or(0) != 0,
        _ => false,
    };
    let class = window
        .get("class")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_lowercase();
    if !fullscreen && !WINDOWED_APPS.contains(&class.as_str()) {
        dispatch("hl.dsp.window.fullscreen({ action = \"set\" })")?;
    }
    Ok(())
}

fn run(arguments: &[String]) -> io::Result<ExitCode> {
    match arguments {
        [command] if command == "clients" => {
            println!("{}", Value::Array(list_windows()?));
            Ok(ExitCode::SUCCESS)
        }
        [command, window] if command == "switch" => {
            let window: Value = serde_json::from_str(window)
                .map_err(|error| io::Error::new(io::ErrorKind::InvalidInput, error))?;
            switch_to_window(&window)?;
            Ok(ExitCode::SUCCESS)
        }
        _ => {
            eprintln!("usage: kewl-hypr clients | kewl-hypr switch <window-json>");
            Ok(ExitCode::from(2))
        }
    }
}

fn main() -> ExitCode {
    let arguments: Vec<String> = env::args().skip(1).collect();
    run(&arguments).unwrap_or_else(|error| {
        eprintln!("kewl-hypr: {error}");
        ExitCode::FAILURE
    })
}
