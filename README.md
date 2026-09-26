# Mikage PromptTable

AI 画廊与提示词注释工作台 —— 一个用于整理、对比和标注 AI 绘图提示词的 Windows 桌面应用。

针对「同一个 Tag 在不同角色/动作上效果如何」「同一条提示词在不同模型上差别多大」这类
对比实验而设计：把图片、提示词、模型和注释放在一起管理，并且支持一个条目挂多张图做并排比较。

---

## 功能

### 画廊

- **瀑布流视图**：自适应列数（2–6 列），横图竖图都按原始比例展示，窗口变窄时自动减少列数
- **表格视图**：经典四列布局（人物 / Prompt / 预览图 / 推荐备注），方便批量浏览
- **分区管理**：自定义分区（人物、服饰、画风…），支持拖拽归类、双击重命名
- **幻灯片连播**：多图条目按顺序 / 倒序 / 随机播放，可选自动连播或点击切换

### 注释与对比

一个条目可以挂多张图，两种对比模式：

| | 模型 | 提示词 |
|---|---|---|
| **Tag 对比** | 全部图片共用一批（挂在条目上） | 每张图独立 |
| **模型对比** | 每张图独立 | 全部图片共用一段 |

- **标注类 Tag**：记录本次实验对比的变量（如 `harem outfit`），自动从提示词中剔除后得到「细分提示词」
- **一键应用到全部**：44 张图只有人物不同时，标注一张即可覆盖全部
- **模型列表**：底模 + 多个 LoRA 自由增删，自动识别类型并支持跳转 Civitai
- **Tag 完整显示**：可选在卡片上展示完整标注文字而非截断

### 模型库

- 扫描 ComfyUI / SD WebUI 的 `checkpoints`、`diffusion_models`、`loras` 目录
- **自动读取 Lora-Manager 的 `*.metadata.json` 与预览图**，无需联网即可显示封面
- 计算 SHA256 并按哈希同步 Civitai 元数据（名称、Base Model、触发词、封面）
- 按目录树分类浏览，右键即可同步 / 打开 / 编辑

### 媒体支持

- 图片：PNG / JPG / WEBP / BMP；动图：GIF / WEBP / APNG（原图直接播放）
- 视频：MP4 / WEBM / MOV（内置播放器，支持进度拖动）
- **自动解析内嵌元数据**：ComfyUI / SD WebUI / NovelAI 的 Prompt、模型名与 LoRA 权重
- 视频同样支持元数据解析（ComfyUI 会把工作流写进 MP4 元数据）

### 其他

- 导入 / 导出 Excel（`.xlsx`，含内嵌缩略图，导出后可在其他机器还原）
- 数据与程序分离存放于 `data\`，升级或替换 exe 不会丢失数据
- 拖拽图片进窗口即可导入，自动解析元数据并生成缩略图
- 无边框毛玻璃界面，窗口可自由拖动与缩放

---

## 安装

### 安装程序（推荐）

下载 `MikagePromptTable-Setup-<版本>.exe` 运行即可。安装过程可选择：

- 创建桌面快捷方式
- **注册到 Windows 搜索 / 启动器**（让任务栏搜索、uTools、ZTools 等能检索到）

安装目录下的 `data\` 保存全部用户数据，**卸载时默认保留**。

### 免安装

直接运行 `MikagePromptTable.exe` 即可，数据会保存在 exe 同级的 `data\` 目录。

要让 Windows 搜索和启动器能检索到，可以：

- 点应用内「⋮」菜单 →「注册到搜索 / 启动器」
- 或命令行执行 `MikagePromptTable.exe --register`（`--unregister` 取消）

命令行开关同样可以在你自己的安装脚本里调用。

---

## 使用提示

| 操作 | 说明 |
|---|---|
| 导入图片 | 拖拽进窗口，或点「导入图片」；自动解析内嵌提示词 |
| 切换视图 | 顶部「瀑布流 / 表格」 |
| 调整列数 | 顶部滑块（窗口过窄时会自动减少实际列数） |
| 选择条目 | 点卡片或表格行，右侧面板显示详情 |
| 编辑提示词 | 右侧面板直接编辑，自动保存 |
| 查看原图 | 点缩略图或卡片放大按钮 |
| 导出 | 「导出 Excel」生成带缩略图的表格 |

---

## 从源码构建

环境要求：Python 3.11+（开发时使用 3.13）、Windows 10/11。

```bash
pip install pywebview openpyxl pillow numpy pyinstaller
python src/build.py
```

产物输出到 `dist\MikagePromptTable.exe`。

构建安装程序需要 [Inno Setup 6](https://jrsoftware.org/isinfo.php)：

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\MikagePromptTable.iss
```

---

## 目录结构

```
Mikage PromptTable/
├── src/
│   ├── app.py                      程序入口（含 --register / --unregister）
│   ├── build.py                    打包脚本
│   ├── backend/
│   │   ├── api.py                  前后端桥接接口
│   │   ├── storage.py              数据存储与迁移
│   │   ├── metadata.py             PNG / 视频元数据解析
│   │   ├── model_library.py        模型库扫描、哈希与 Civitai 同步
│   │   ├── server.py               本地资源服务（含 Range 支持）
│   │   ├── excel_io.py             Excel 导入导出
│   │   ├── shell_integration.py    开始菜单 / 搜索 / 启动器注册
│   │   └── win32utils.py           窗口拖拽、缩放、图标与圆角
│   ├── web/                        前端界面
│   └── assets/                     图标资源
├── installer/MikagePromptTable.iss       安装程序脚本
└── SHELL-INTEGRATION.md            壳集成与安装器集成说明
```

运行时数据（不纳入版本控制）：

```
data/
├── gallery_data.json     注释数据
├── model_library.json    模型库缓存
└── settings.json         界面设置
```

---

## 说明

- 元数据解析针对 ComfyUI 的工作流做通用节点扫描，因此不同模型家族（SD、Anima、
  Krea、MiniMax H3 等）都能识别出提示词与 LoRA 权重
- 模型库通过 SHA256 与 Civitai 匹配，需能访问 `civitai.com`
- 界面使用 WebView2 渲染，Windows 10/11 已内置

## 许可

[MIT](LICENSE)
