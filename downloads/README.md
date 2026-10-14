# Windows 工具下载

支持 Windows 10/11 64 位，无需安装 Python。

- **图纸管理**：[EngineerHub-Windows-x64.zip](https://github.com/fengs26-sketch/blog/releases/latest/download/EngineerHub-Windows-x64.zip)。完整解压，进入 `EngineerHub` 文件夹，双击 `EngineerHub.exe`。保留 `_internal/` 文件夹。
- **电机选型**：[MotorSelector-Windows-x64.zip](https://github.com/fengs26-sketch/blog/releases/latest/download/MotorSelector-Windows-x64.zip)。完整解压，进入 `MotorSelector` 文件夹，双击 `电机选型程序.exe`。保留 `_internal/` 文件夹。

请解压到可写目录。工程库、设置和个人选型数据在首次运行后保存在本机；下载包中不包含个人工程资料。
使用细节见包内 `使用说明.md` 和仓库的 `tools/` 目录。

校验：`Get-FileHash .\EngineerHub-Windows-x64.zip -Algorithm SHA256`，与 [SHA256SUMS.txt](https://github.com/fengs26-sketch/blog/releases/latest/download/SHA256SUMS.txt) 对照。
