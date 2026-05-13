"""``jarvis`` command-line interface."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from jarvis.config import get_settings
from jarvis.utils.logging import configure_logging, get_logger

app = typer.Typer(
    name="jarvis",
    help="Local, autonomous, voice-driven AI assistant.",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
log = get_logger("cli")


# ---------------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------------- #


def _run(coro):
    try:
        return asyncio.run(coro)
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
        sys.exit(130)


# ---------------------------------------------------------------------- #
# commands
# ---------------------------------------------------------------------- #


@app.command()
def config() -> None:
    """Print the resolved settings (no secrets)."""
    settings = get_settings()
    table = Table(title="Jarvis configuration", show_header=True, header_style="bold")
    table.add_column("Key", style="cyan")
    table.add_column("Value")
    for k, v in settings.describe():
        table.add_row(k, str(v))
    console.print(table)


@app.command()
def ask(text: str = typer.Argument(..., help="Question or instruction.")) -> None:
    """One-shot text → answer (no audio)."""
    from jarvis.agent import AgentLoop, OllamaClient
    from jarvis.tools import build_default_registry

    settings = get_settings()
    configure_logging(settings.log_level)

    async def _go() -> None:
        async with OllamaClient(host=settings.ollama_host) as llm:
            agent = AgentLoop(llm=llm, tools=build_default_registry(), settings=settings)
            turn = await agent.run_turn(text, language=settings.language or "en")
            console.print(turn.assistant_text)

    _run(_go())


@app.command()
def say(
    text: str = typer.Argument(..., help="Text to speak."),
    language: str = typer.Option("en", "--lang", "-l"),
) -> None:
    """Speak *text* via the TTS engine."""
    from jarvis.audio import PiperEngine

    async def _go() -> None:
        engine = PiperEngine()
        await engine.speak(text, language=language)

    _run(_go())


@app.command()
def listen(seconds: float = typer.Option(15.0, "--max", help="Max seconds to listen.")) -> None:
    """Listen once, transcribe, exit."""
    from jarvis.audio import Transcriber
    from jarvis.audio.mic import record_utterance

    async def _go() -> None:
        console.print("[bold]Listening...[/bold] (speak now)")
        pcm = await record_utterance(max_seconds=seconds)
        if pcm.size == 0:
            console.print("[yellow]No speech detected.[/yellow]")
            return
        console.print(f"[dim]Captured {pcm.size / 16000:.1f}s of audio.[/dim]")
        transcript = await Transcriber().transcribe_array(pcm)
        console.print(f"[bold cyan]{transcript.language}[/bold cyan]: {transcript.text}")

    _run(_go())


@app.command()
def serve() -> None:
    """Run the core service in the foreground (for debugging)."""
    from jarvis.server.core import main as core_main

    core_main()


@app.command()
def hud() -> None:
    """Launch the floating PyQt HUD orb."""
    from jarvis.hud.orb import main as hud_main

    sys.exit(hud_main())


@app.command()
def status() -> None:
    """Show systemd status of the core service."""
    rc = subprocess.call(["systemctl", "--user", "status", "jarvis-core"])
    sys.exit(rc)


@app.command()
def logs(follow: bool = typer.Option(True, "--follow/--no-follow", "-f")) -> None:
    """Tail the core service journal."""
    args = ["journalctl", "--user", "-u", "jarvis-core"]
    if follow:
        args.append("-f")
    rc = subprocess.call(args)
    sys.exit(rc)


@app.command()
def audit() -> None:
    """Re-run the environment audit script."""
    script = Path(__file__).resolve().parents[2] / "scripts" / "audit.sh"
    if not script.exists():
        console.print("[red]audit.sh not found[/red]")
        sys.exit(1)
    sys.exit(subprocess.call(["/bin/bash", str(script)]))


@app.command("vault")
def vault_cmd(
    action: str = typer.Argument(..., help="init | set | get | delete | list"),
    name: str = typer.Argument(None),
    value: str = typer.Argument(None),
) -> None:
    """Manage the encrypted secrets vault."""
    from jarvis.vault import default_vault

    v = default_vault()
    if action == "init":
        recipient = v.init()
        console.print(f"Vault initialised. Public recipient: [bold]{recipient}[/bold]")
        return
    if action == "list":
        for k in v.keys():
            console.print(f"- {k}")
        return
    if not name:
        console.print("[red]name argument required[/red]")
        sys.exit(2)
    if action == "set":
        if value is None:
            import getpass

            value = getpass.getpass(f"value for {name}: ")
        v.set(name, value)
        console.print(f"stored [bold]{name}[/bold]")
        return
    if action == "get":
        val = v.get(name)
        if val is None:
            console.print(f"[yellow]no such key: {name}[/yellow]")
            sys.exit(1)
        console.print(val)
        return
    if action == "delete":
        if v.delete(name):
            console.print(f"deleted [bold]{name}[/bold]")
        else:
            console.print(f"[yellow]no such key: {name}[/yellow]")
        return
    console.print(f"[red]unknown action: {action}[/red]")
    sys.exit(2)


@app.command()
def doctor() -> None:
    """Quick health check: Ollama reachable, model present, tools registered."""
    import httpx

    settings = get_settings()
    console.print(f"[bold]Ollama:[/bold] {settings.ollama_host}")
    try:
        r = httpx.get(f"{settings.ollama_host}/api/tags", timeout=3.0)
        models = [m["name"] for m in r.json().get("models", [])]
        console.print(f"  models: {', '.join(models) or '(none)'}")
        ok = any(m.startswith(settings.model) for m in models)
        console.print(f"  has '{settings.model}': {'yes' if ok else 'NO'}")
    except Exception as exc:  # noqa: BLE001
        console.print(f"  [red]unreachable: {exc}[/red]")

    from jarvis.tools import build_default_registry

    reg = build_default_registry()
    console.print(f"[bold]Tools:[/bold] {', '.join(reg.names())}")

    sock = (
        Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "jarvis" / "core.sock"
    )
    console.print(f"[bold]Core socket:[/bold] {sock} {'(exists)' if sock.exists() else '(absent)'}")


if __name__ == "__main__":
    app()
