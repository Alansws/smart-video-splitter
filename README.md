# Smart Video Splitter

中文简介：一个面向 macOS 的桌面视频分割工具，核心目标是把单个视频拆分为多个不超过指定体积的分片，适合 Telegram 等对单文件大小有限制的上传场景。

English summary: A macOS desktop video splitting tool for cutting large videos into upload-ready parts with an exact size limit, designed for workflows like Telegram uploads.

## Why This Project

很多视频分割工具只能按时长切片，遇到变码率视频时容易出现“某一段仍然超出上传平台大小限制”的问题。`Smart Video Splitter` 重点解决的是“按大小上限交付可上传分片”这件事，而不是单纯做一个时间切刀。

## Key Features

- 精确输入分片上限，支持 `MB` / `GB` 单位和如 `1999.5` 这样的手动值
- `严格不超限` 模式：每个分片输出后都会校验实际体积，必要时缩短片段或重编码兜底
- `极速无损` 模式：优先使用 `ffmpeg -c copy`，速度快并尽可能保留原始编码
- 支持单文件或文件夹批量处理
- 支持可选递归扫描子文件夹
- 支持双击 `.command` 启动源码版
- 支持打包为 macOS `.app`

## Use Cases

- 上传视频到 Telegram、Discord、Slack 等对单文件大小有限制的平台
- 批量整理课程录像、录屏、播客视频或直播回放
- 在尽量保留原始编码的前提下快速切分大文件

## Requirements

- macOS
- Python 3.10+
- `ffmpeg` and `ffprobe`

安装 ffmpeg：

```bash
brew install ffmpeg
```

## Run

源码启动：

```bash
python3 smart_video_splitter.py
```

双击启动：

- 直接双击 `launch_smart_video_splitter.command`

## Build macOS App

如果本机还没有 PyInstaller：

```bash
python3 -m pip install pyinstaller
```

然后执行：

```bash
./build_macos_app.sh
```

生成产物：

- `dist/SmartVideoSplitter.app`

## How It Works

### Strict Mode

`严格不超限` 是默认模式，适合“每段必须能上传”的场景。

- 先用流复制尝试切段
- 如果输出仍超限，会自动缩短该段时长并重试
- 如果流复制仍无法稳定压到限制以内，会切换到重编码兜底

这意味着速度可能更慢，但目标是让每个最终分片都不超过你设置的上限。

### Fast Mode

`极速无损` 模式优先速度与原始编码保留：

- 使用 `ffmpeg -c copy`
- 每段输出后仍会校验体积
- 如果某个分片超限，只会记录告警，不承诺严格满足上限

如果你的目标是“尽快切完”，而不是“绝不超限”，这个模式更适合。

## Notes

- 当前支持格式：`.mp4`、`.mov`、`.mkv`
- 输出文件默认保存在原视频所在目录
- 建议在首次批量处理前先用单个文件验证你的目标上传平台限制

## Project Positioning

这是一个实用型桌面工具项目，聚焦单文件大小受限的视频上传工作流。仓库默认只发布源码、启动脚本和打包脚本，不包含本机构建产物。

## License

MIT
