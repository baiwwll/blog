# 个人博客与工程工具

博客站点：<https://fengs26-sketch.github.io/blog/>

## 工具下载

| 工具 | Windows 10/11 64 位下载 | 源码与说明 |
| --- | --- | --- |
| 图纸与工程项目管理 EngineerHub | [下载 ZIP](https://github.com/fengs26-sketch/blog/releases/latest/download/EngineerHub-Windows-x64.zip) | [使用说明](tools/EngineerHub/README.md) |
| 电机选型计算程序 | [下载 ZIP](https://github.com/fengs26-sketch/blog/releases/latest/download/MotorSelector-Windows-x64.zip) | [使用说明](tools/motor_selector/README.md) |

下载后完整解压到可写目录再运行，无需安装 Python。两个下载包均为文件夹版，需要保留整个程序目录及 `_internal/`。
下载包的 SHA-256 见 [校验文件](https://github.com/fengs26-sketch/blog/releases/latest/download/SHA256SUMS.txt)。

源码位于 `tools/`。两个程序的运行依赖均为 Python 标准库及 tkinter；打包时需要 PyInstaller。
图纸库、程序设置、用户型号库、个人方案和报告由程序首次运行时创建，并保存在本机。

电机选型内置型号为典型参数，正式选型应导入厂家数据并复核。

## 构建与发布

更新 `tools/` 源码后，GitHub Actions 自动测试、打包，并在 [Releases](https://github.com/fengs26-sketch/blog/releases) 发布 Windows 下载包。
也可在 Actions 中手动运行 `Build Windows tools`。构建脚本只收集程序运行依赖和说明文件。
