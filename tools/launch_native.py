"""Validate and launch the selected native candidate; never build or use Tk."""
import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys


class LaunchError(ValueError):
    """The requested candidate cannot be launched safely."""


@dataclass(frozen=True)
class LaunchPlan:
    app: Path
    binary: Path
    python: Path
    save_file: Path
    version: str
    isolated: bool


def resolve_launch(root, save_file=None):
    """Read only candidate metadata and executable attributes, never save data."""
    root = Path(root).resolve()
    try:
        with (root / '当前原生候选.json').open(encoding='utf-8') as stream:
            record = json.load(stream)
    except (OSError, ValueError) as error:
        raise LaunchError('当前原生候选清单缺失或无法读取，请先完成候选构建核验。') from error
    if not isinstance(record, dict) or record.get('status') not in ('candidate', 'release'):
        raise LaunchError('当前清单没有指定可用的原生候选。')
    name, version = record.get('app'), record.get('version')
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise LaunchError('候选应用必须使用工程内的相对路径。')
    if not isinstance(version, str) or not version.strip():
        raise LaunchError('候选清单缺少版本号。')
    app = (root / name).resolve()
    if not app.is_relative_to(root) or app.suffix != '.app' or not app.is_dir():
        raise LaunchError('候选应用不存在、不是 .app，或位于工程之外。')
    try:
        with (app / 'Contents' / 'Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
    except (OSError, ValueError, plistlib.InvalidFileException) as error:
        raise LaunchError('候选应用的信息文件无法读取。') from error
    if not isinstance(info, dict) or any(info.get(key) != value for key, value in {
        'CFBundleExecutable': 'Tianmu',
        'CFBundleIdentifier': 'local.tianmu.garden',
        'CFBundleShortVersionString': version,
    }.items()):
        raise LaunchError('候选应用的身份或版本与清单不一致。')
    binary = (app / 'Contents' / 'MacOS' / 'Tianmu').resolve()
    if not binary.is_relative_to(app) or not binary.is_file() or not os.access(binary, os.X_OK):
        raise LaunchError('候选应用缺少可执行的 Tianmu 程序。')
    runtime = info.get('TianmuPythonExecutable')
    if not isinstance(runtime, str) or not runtime:
        raise LaunchError('候选应用没有记录有效的 Python 运行环境。')
    if Path(runtime).is_absolute():
        python = Path(runtime)
    else:
        resources = app / 'Contents' / 'Resources'
        python = (resources / runtime).resolve()
        if info.get('TianmuEmbeddedPython') is not True or not python.is_relative_to(resources):
            raise LaunchError('内置运行环境必须完整位于应用内。')
    if not python.is_file() or not os.access(python, os.X_OK):
        raise LaunchError('候选应用记录的 Python 运行环境不存在或不可执行。')
    selected_save = (app.parent / '体验存档' / 'state.json') if save_file is None else Path(save_file).expanduser().absolute()
    return LaunchPlan(app, binary, python, selected_save, version, save_file is None)


def execute_launch(plan, *, check_only=False, process_runner=subprocess.run,
                   exec_fn=os.execv, printer=print):
    """The process boundary is injectable so tests never launch or query apps."""
    printer(f'灶神原生候选：{plan.version}')
    printer(f'{"隔离体验存档" if plan.isolated else "显式指定存档"}：{plan.save_file}')
    printer(f'原生程序：{plan.binary}')
    if check_only:
        printer('仅检查启动计划；未启动游戏、创建目录或读取存档。')
        return
    try:
        running = process_runner(['/usr/bin/pgrep', '-x', 'Tianmu'],
                                 capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LaunchError('无法确认是否已有灶神运行，已停止启动。') from error
    if running.returncode == 0:
        raise LaunchError('已有灶神正在运行。请返回现有游戏；本次没有启动第二个实例。')
    if running.returncode != 1:
        raise LaunchError('运行状态检查失败，已停止启动。')
    sys.stdout.flush()
    exec_fn(str(plan.binary), [str(plan.binary), '--save-file', str(plan.save_file)])


def main(argv=None):
    parser = argparse.ArgumentParser(description='启动已核验的灶神原生候选')
    parser.add_argument('--save-file', type=Path, help='显式选择存档；默认使用候选旁的体验存档')
    parser.add_argument('--check-only', action='store_true', help='只检查并打印启动计划')
    args = parser.parse_args(argv)
    try:
        plan = resolve_launch(Path(__file__).resolve().parents[1], args.save_file)
        execute_launch(plan, check_only=args.check_only)
    except (LaunchError, OSError) as error:
        print(f'未启动：{error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
