# 壳集成 / 安装程序集成说明

Mikage PromptTable 可以被 Windows 任务栏搜索、uTools、ZTools 等启动器检索并调用。
原理很简单：这些都是**枚举开始菜单快捷方式**的，把快捷方式放对位置即可。

## 一、已实现的机制

### 1. 开始菜单快捷方式（搜索可见的关键）

写入位置：

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Mikage PromptTable.lnk
```

- Windows 搜索（任务栏搜索框、Win+S）会索引该目录
- uTools / ZTools / Everything / Listary 等启动器同样枚举它

实测快捷方式内容：

```
目标    : <安装目录>\MikagePromptTable.exe
工作目录: <安装目录>
图标    : <安装目录>\assets\app.ico,0
描述    : Mikage PromptTable - AI 画廊与提示词注释工作台
```

### 2. App Paths 注册表项（可按名称启动）

```
HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\App Paths\MikagePromptTable.exe
```

- 让 Win+R 直接输入 `Mikage PromptTable` 即可启动
- 部分启动器也用它解析可执行文件
- 写在 **HKCU** 下，**不需要管理员权限**

### 3. 命令行开关

程序内置两个开关，安装程序可以直接调用：

```bat
:: 注册（创建快捷方式 + 写注册表）
MikagePromptTable.exe --register

:: 取消注册（删除快捷方式 + 清注册表）
MikagePromptTable.exe --unregister
```

两者都是**静默执行后立即退出**（不启动主界面），完成后弹一个提示框。
PowerShell 调用示例：

```powershell
Start-Process -FilePath "C:\Path\MikagePromptTable.exe" -ArgumentList "--register" -Wait
```

## 二、在安装程序里怎么接

本仓库自带 Inno Setup 脚本 `installer/MikagePromptTable.iss`，已配置好全部流程：

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/MikagePromptTable.iss
```

产物为 `dist\MikagePromptTable-Setup-<版本>.exe`。

关键配置：

```ini
[Tasks]
Name: "register"; Description: "注册到 Windows 搜索 / 启动器 (uTools、ZTools 等)"; ...

[Run]
Filename: "{app}\MikagePromptTable.exe"; Parameters: "--register"; \
         Flags: runhidden waituntilterminated; Tasks: register

[UninstallRun]
Filename: "{app}\MikagePromptTable.exe"; Parameters: "--unregister"; \
         Flags: runhidden waituntilterminated; RunOnceId: "UnregisterShell"
```

### 其他安装器

NSIS：

```nsis
CreateShortcut "$SMPROGRAMS\Mikage PromptTable.lnk" "$INSTDIR\MikagePromptTable.exe" "" \
               "$INSTDIR\assets\app.ico" 0
ExecWait '"$INSTDIR\MikagePromptTable.exe" --register'
```

### 绿色版 / 手动注册

双击 `MikagePromptTable.exe`，点右上角「⋮」菜单里的 **「注册到搜索 / 启动器」**，
勾号出现即注册成功。再次点击即可取消。

## 三、注意事项

1. **不需要管理员权限**：全部写在 HKCU 和用户自己的开始菜单目录下。

2. **uTools / ZTools 可能需要重建索引**：它们扫描开始菜单后，若没立刻看到条目，
   重启一次该应用或手动触发「重建索引」。

3. **数据与程序分离**：`data\` 保存注释记录、模型库缓存与界面设置。
   安装 / 升级时**不要删除或覆盖 `data\`**。
   安装程序已配置为卸载时询问用户是否保留数据。

4. **图标缓存**：如果替换了 `assets\app.ico`，Windows 可能仍显示旧图标
   （Explorer 会缓存）。重新登录或刷新图标缓存即可。
