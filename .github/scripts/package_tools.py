"""Build a Windows folder package containing only runtime files and documentation."""
from pathlib import Path
import argparse
import subprocess
import sys
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('tool', choices=['EngineerHub', 'motor_selector'])
parser.add_argument('--output', type=Path, default=Path('release-packages'))
parser.add_argument('--build-root', type=Path, default=Path('build'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
source = root / 'tools' / args.tool
build_root = args.build_root.resolve() / args.tool
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
app_name = 'EngineerHub' if args.tool == 'EngineerHub' else '电机选型程序'
folder_name = 'EngineerHub' if args.tool == 'EngineerHub' else 'MotorSelector'
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
           '--windowed', '--name', app_name, '--distpath', str(build_root / 'dist'),
           '--workpath', str(build_root / 'work'), '--specpath', str(build_root),
           '--exclude-module', 'numpy', '--exclude-module', 'matplotlib',
           '--exclude-module', 'PIL', 'main.py']
build_root.mkdir(parents=True, exist_ok=True)
subprocess.run(command, cwd=source, check=True)
runtime = build_root / 'dist' / app_name
archive_path = output / f'{folder_name}-Windows-x64.zip'
with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    archive.write(runtime / f'{app_name}.exe', f'{folder_name}/{app_name}.exe')
    for item in sorted((runtime / '_internal').rglob('*')):
        if item.is_file():
            archive.write(item, f'{folder_name}/' + item.relative_to(runtime).as_posix())
    archive.write(source / 'README.md', f'{folder_name}/使用说明.md')
    if args.tool == 'motor_selector':
        archive.write(source / '如何添加电机和减速机数据.md', f'{folder_name}/如何添加电机和减速机数据.md')
with zipfile.ZipFile(archive_path) as archive:
    assert archive.testzip() is None
    assert not any('EngineerHubLibrary' in name or '/userdata/' in name or
                   'settings.json' in name for name in archive.namelist())
print(f'Created {archive_path.name}: {archive_path.stat().st_size} bytes')
