# EngineerHub v0.1

Windows 本机工程项目中心。提供整机 / 零部件入口、项目管理、SQLite 文件索引、工程扫描分类、系统默认应用打开文件。

## 启动

Windows 下载版：[EngineerHub-Windows-x64.zip](https://github.com/baiwwll/ai-tools/releases/latest/download/EngineerHub-Windows-x64.zip)。完整解压，进入 `EngineerHub` 文件夹后双击 `EngineerHub.exe`，保留 `_internal/`。

双击 `启动 EngineerHub.cmd` 或 `dist\EngineerHub\EngineerHub.exe`。文件夹版包含 Python 运行环境，无需安装 Python。移动程序时请保留 `dist\EngineerHub` 整个文件夹，包含 `_internal`。

没有打包文件时，`启动 EngineerHub.cmd` 会使用本机 Python 运行源码。

源码运行：`python main.py`。运行时只使用 Python 标准库，不需要安装第三方依赖。文件夹打开调用 Windows Shell 原生接口，兼容中文路径。

默认工程库：程序旁的 `EngineerHubLibrary`。设置保存到同目录的 `EngineerHub.settings.json`，采用便携式布局，请把程序放在可读写的目录中。界面左下角“选择工程库…”可以选择其他磁盘位置或打开已有工程库。程序记住最后使用的位置。选择工程库不会搬迁已有库；搬迁时请在程序关闭后完整复制工程库目录，再选择新位置。

也可以运行 `python main.py --library "D:\EngineerHubLibrary"`，临时指定工程库而不改变保存的设置。

## 使用流程

1. 进入“整机设计”或“零部件设计”，新建项目。程序自动分配 `P000001` 这样的编号并创建 `Workspace`。
2. 或点击“导入现有工程”，选择完整工程文件夹，填写名称和类型，扫描预览分类后确认导入。
3. 默认“复制到工程库”，完整保留源目录结构和原文件。也可选择“保留原位置”，只记录索引。
4. 双击项目查看文件，按 CAD / 工程图 / CAE / 计算 / 资料 / 其他筛选，支持文件名和相对路径搜索。
5. 双击文件或点击“打开选中文件”，通过 Windows 已配置的默认应用打开。SolidWorks 原生文档优先通过 Unicode Windows DDE 文件打开命令复用已运行的 SolidWorks，避免中文路径被文件启动器错误处理；没有运行实例时仍使用系统默认应用。“定位文件”直接打开所选文件所在的文件夹。
6. 把新文件保存到 Workspace 后，进入项目时扫描；项目详情停留期间默认每 30 秒后台刷新，也可以取消“自动刷新”并手动扫描。
7. 编辑项目可修改名称、类型和说明；项目文件夹不随名称重命名。“移除登记”清理索引，保留工程文件。

## 工程库结构

```text
EngineerHubLibrary/
  engineerhub.db
  Projects/
    P000001_升降平台/
      project.json
      Workspace/
        总装.SLDASM
        Parts/零件.SLDPRT
        ANSYS/模型.wbpj
        计算/负载计算.xlsx
```

SQLite 保存项目信息、文件相对路径、分类、大小、修改时间和丢失标记；工程文件本体不存入数据库。工程库中的托管项目使用相对路径，整个工程库可以整体搬迁。原位置索引项目使用绝对路径，原目录搬迁后需要重新导入。

`project.json` 是托管项目的基础信息副本。v0.1 未提供自动重建整个数据库的入口；数据库丢失后工程文件仍可访问，重新导入 Workspace 可恢复文件索引。备份请在程序关闭后备份整个工程库，而不只备份数据库。

## 分类规则

| 分类 | 常见扩展名 |
|---|---|
| CAD 模型 | SLDASM / SLDPRT / STEP / STP / IGES / PRT / ASM / IPT / IAM / STL 等 |
| 工程图 | SLDDRW / DWG / DXF / IDW 等 |
| CAE 分析 | WBPJ / WBPZ / MECHDB / MECHDAT / CAS.H5 / DAT.H5 / MSH / RST / INP / ODB / K 等 |
| 计算文件 | XLSX / XLS / XLSM / CSV / MCDX / IPYNB 等 |
| 项目资料 | PDF / DOCX / PPTX / TXT / MD / 图片等 |
| 其他文件 | 未识别类型，保留并索引 |

分类仅依据扩展名，不读取 CAD 模型内容，也不自动解析装配引用。扫描跳过常见锁文件、版本工具内部目录和符号链接 / Windows junction。完整复制保留普通文件和空目录；遇到链接或无法读取的内容时不允许复制导入，可修复源目录或使用原位置索引。扫描读取失败时保留此前索引，不把无法访问的文件误标为丢失。完整扫描发现消失的文件会保留索引并标记“丢失”；文件恢复后自动恢复“可用”。

## 当前边界

- 文件打开依赖本机已安装的软件和 Windows 文件关联。没有配置默认应用时，按错误提示在 Windows 中设置。
- 完整保留相对目录并不保证引用到源文件夹之外的 CAD / CAE 文件可用。导入前需要确认工程文件夹包含所有配套内容，或自行使用 CAD 软件提供的工程打包工具。
- 复制是当前文件的复制，不是版本快照。建议源工程处于保存、关闭状态再导入；正在写入的文件可能在复制时继续变化。
- 不提供版本控制、SolidWorks API、装配依赖分析、缩略图、云同步或多人协作。
- 自动刷新只扫描当前打开的项目，不监视整个磁盘。大型仿真目录可关闭自动刷新。
- 导入中断时保留已复制的内容及项目登记，并在说明中标记未完成；可以移除登记后重新导入。源文件不删除。

## 开发验证

```powershell
python -m unittest discover -s tests -v
python tests/gui_smoke.py
```

打包依赖 PyInstaller。运行 `build.ps1` 会创建独立构建环境并生成 `dist\EngineerHub\EngineerHub.exe` 和运行依赖。

如果输出目录中已有工程库或设置，构建脚本会停止，避免重建时覆盖用户数据。先备份并移走整个旧程序文件夹，再重新构建。
