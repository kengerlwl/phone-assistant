# Phone Assistant

手机主动连接、可随时停止的自托管 Android 助手。仓库包含 Android App、Python/WSS 桥接服务、Docker Compose 部署工具和标准 SSH 控制客户端。Android 11+，不需要 Root、ADB、USB 激活或同一 Wi-Fi；手机仍需移动数据或 Wi-Fi 网络。

本项目是 [Mobilerun Portal](https://github.com/droidrun/mobilerun-portal) v0.7.25 的衍生版，基于提交 `d4cb7d6657385488239812e776df584f890e32fd`，修改日期 2026-10-16。保留上游作者 Niels Schmidt 的版权与 [AGPL-3.0-or-later 许可证](LICENSE)。这不是上游官方发行版，也不是无人值守或隐蔽远控工具。

## 相比上游，改了什么

无障碍控件读取、手势和反向 WebSocket 是上游已有能力。Phone Assistant 围绕个人自托管场景收敛：单设备桥接、一次性配对码、手机端连接/断开入口、不自动批准系统权限、不依赖云平台账户或计费流程。1.1.0 增加通用部署初始化、自检、配对链接预填和无需私有工具的标准 SSH 客户端。

截图可在手机端压缩为 JPEG/PNG 或按设备坐标裁剪，返回尺寸、缩放、偏移、旋转和捕获时间。命令有截止时间，手势等待完成回调，动作结果与页面回读分开；断线不排队、不重放。上层 AI 可以结合控件树、截图和外部 OCR，但 App 本身没有更强的视觉模型，也不内置 LLM。

这是一种更窄、更可控的使用方式，不是上游全部功能的增强版。文件访问、APK 自动安装、通知/SMS 采集、触发器、连续视频、局域网 HTTP/WS 控制入口均未开放。部分上游源码和依赖仍保留，APK 尚未专门瘦身。`docs/`、`agent-test-flows/` 中的上游历史资料不是本版的能力承诺；本 README 和实际白名单为准。

## 快速开始：服务端

需要一台 Linux 服务器、Python 3.10+、Docker Engine 与 Compose v2、可解析的域名和手机系统信任的 TLS 证书。以下示例使用公网 TCP 8443；防火墙仅对手机开放这个业务端口，SSH 另按运维需求限制。不要开放控制端口 18766。

将仓库放在服务器 `/opt/phone-assistant`，在仓库根目录执行以下命令。将示例域名与证书位置替换为自己的配置；证书完整链与私钥需在同一目录且可被容器读取。若证书系统使用跨目录符号链接，先用续期部署钩子同步到专用目录，不要把其他站点私钥一起挂入容器。

```bash
python3 deploy/setup.py \
  --server wss://phone.example.com:8443/device \
  --cert /opt/phone-assistant-tls/fullchain.pem \
  --key /opt/phone-assistant-tls/privkey.pem
docker compose -f deploy/compose.yaml up -d --build
python3 deploy/manage.py doctor
python3 deploy/manage.py pair
```

初始化会生成权限为 0600 的 `deploy/.env` 和私有状态目录，不覆盖已有凭据。Compose 使用 Linux host network，公网只提供 `POST /pair` 和 `GET /device`，控制 API 固定绑定 `127.0.0.1`。容器启用只读根文件系统、cap-drop、资源与日志限制。不要将 Compose 当作跨平台 Docker Desktop 部署承诺。

`pair` 输出 8 位配对码和 `phoneassistant://pair?...` 链接。链接是短期凭据，不应发布到 Issue、日志或公共聊天；十分钟过期、单次消费、最多二十次尝试。当前手机在线时不可重新配对。需要更换手机时先从旧手机主动断开，再生成新码；新配对将替换旧设备凭据。普通重连不需要新码。

证书应由自己的 ACME/证书系统定期续期。服务每五分钟检查证书更新；保留证书路径并原子更新文件。控制令牌不在 APK 内，服务端只保存设备令牌的 SHA256 摘要。服务端能处理明文指令和截图，因此它必须可信；本方案不是手机到客户端的端到端加密。

查看状态与日志可使用 `python3 deploy/manage.py status` 和 `docker compose -f deploy/compose.yaml logs --tail 50`。停止服务使用 `docker compose -f deploy/compose.yaml down`，数据仍保留。升级前备份私密的 `.env` 与 `deploy/data/`，不要将它们提交到 Git。`doctor` 检查本机控制接口和证书，不替代从外部主机验证 18766 不可达。

## 手机端

安装自己构建的 APK，或使用本仓库 Releases 提供的签名 APK（如该版本已发布）。系统安装许可、受限设置及无障碍授权由手机主人手动确认；不自动绕过安全提示。开启系统设置中名为 Phone Assistant 的无障碍服务，并允许连接状态通知以方便查看与停止。

把服务器输出的配对链接复制到手机，打开 App 点“粘贴配对链接”，或者通过支持自定义协议的应用打开链接。也可手填 WSS 地址和配对码。导入只预填，不自动连接或申请权限；核对域名后点“连接我的助手”。连接页本身禁止远程读取/控制，连接完成后离开连接页，或打开内置“操作测试页”。

点击 App 或通知中的“立即断开”即可停止会话。锁屏拒绝控制，不提供远程解锁。设计上的重启恢复流程为：解锁手机、打开 App、确认无障碍就绪、点连接；保存的配对凭据可复用。系统可能关闭无障碍或限制后台运行，必要时由用户手动恢复。并不承诺静默开机、永久在线或所有厂商兼容。

## 电脑端与日常控制

电脑需要 Python 3.10+ 和 OpenSSH，不需要安装手机驱动或私有远程工具。配置一个可免交互连接且已核验主机指纹的 SSH 别名，例如 `phone-server`；客户端不会跳过主机密钥检查。服务器上的 SSH 用户需要运行控制脚本并读取部署 `.env` 的权限，仅授予可信操作者。

客户端优先读取 `PHONE_ASSISTANT_CONFIG` 指向的 JSON，默认是仓库 `.private/client.json`。可按 `bridge/client.example.json` 创建自己的私密配置，不要将真实配置提交到 Git。SSH 端口、IdentityFile 和代理等在自己的 SSH config 中配置。也可仅使用环境变量：

```bash
export PHONE_ASSISTANT_SSH_HOST=phone-server
export PHONE_ASSISTANT_CONTROL=/opt/phone-assistant/bridge/control.py
python3 bridge/phone_client.py status
python3 bridge/phone_client.py fg
python3 bridge/phone_client.py ui --filter 搜索
python3 bridge/phone_client.py shot
python3 bridge/phone_client.py tap --text 搜索
python3 bridge/phone_client.py text '你好，Phone Assistant'
python3 bridge/phone_client.py scroll --dir down
python3 bridge/phone_client.py key back
```

无参数和 `--help` 只显示帮助，不访问手机。`tap` 可按唯一 text、desc、id 或 `--xy x,y` 定位；歧义会拒绝，不猜测。文本默认替换当前焦点的非密码输入框，可用 `--append` 插入，不自动发送，不自动切换输入法。`app 包名` 请求启动后回读，未确认前台时明确给出警告。返回、主页、最近应用和通知栏分别为 `key back/home/recent/notifications`。

截图默认保存到仓库 `output/`，图片与 JSON sidecar 均为私密文件；可用 `--out` 指定仓库内不存在的文件。`--format png --max-edge 0` 获取原尺寸，`--crop x,y,width,height` 以设备坐标裁剪。截图包含可能敏感的屏幕内容，默认不上传；使用者需自行设置保留和清理策略。

```bash
python3 bridge/phone_client.py shot --format png --max-edge 0
python3 bridge/phone_client.py shot --crop 20,400,900,500
python3 bridge/phone_client.py swipe --xy 500,1600 --to 500,700
```

OCR 是可选外部适配，不随本仓库附带平台私有实现。设置 `PHONE_OCR_BINARY` 为可执行文件，客户端以 `[binary, imagePath, minConfidence]` 调用，要求 stdout 返回如下 JSON，文字框为图片像素坐标、原点在左上：

```json
{"width":100,"height":50,"lines":[{"text":"示例","conf":0.95,"x":10,"y":5,"w":60,"h":20}]}
```

随后可运行 `python3 bridge/phone_client.py ocr --filter 示例`，或 `ocr --path output/已有图片.jpg`。没有 sidecar 的外部图只返回图片坐标；有 sidecar 时校验 SHA256 和尺寸后映射到设备坐标。转换公式为 `deviceX = offsetX + imageX * scaleX`、`deviceY = offsetY + imageY * scaleY`。导航、滚动或旋转后必须重新观察，不能沿用旧坐标。

## AI 与工具集成接口

公开接入点是本仓库 CLI 和 stdin RPC，不绑定任何 Agent 平台。仓库不包含现有平台的受保护 Skill、提示词或私有包装器；使用者可以根据这里的公开接口在自己的工具框架中注册能力。

CLI 成功输出 `{"ok":true,"elapsedMs":123,"data":{...}}`，失败输出 `{"ok":false,"error":"..."}` 并以非零状态退出。动作已经成功而后续观察失败时，`data` 保留动作回执并包含 `observationError` 与禁止重放的 `warning`。`online:true` 仅表示 WSS 会话在线，不等于手机已解锁、权限就绪或动作已完成。

服务端 `python3 bridge/control.py rpc` 从 stdin 读取单个 JSON 对象，通过回环 API 发送一次请求，将响应 JSON 写到 stdout。请求不放在远程 shell 命令参数里。以下是 Python 调用方式，完整输入校验和 SSH 传输也可直接复用 `bridge/phone_client.py`：

```python
import json
import subprocess

request = {"action": "command", "method": "state", "params": {"filter": False}}
reply = subprocess.run(
    ["ssh", "-o", "BatchMode=yes", "phone-server",
     "python3 /opt/phone-assistant/bridge/control.py rpc"],
    input=json.dumps(request), capture_output=True, text=True, timeout=35,
)
result = json.loads(reply.stdout)
# Nonzero exit or status:error means inspect the error; do not blindly replay actions.
```

RPC action 为 `status`、`pair` 或 `command`。command 的 method 白名单为 `state`、`capture`、`screenshot`、`tap`、`swipe`、`global`、`app`、`keyboard/input`、`keyboard/clear`、`keyboard/key`、`version`、`time`、`packages`；参数实现见 `PersonalControlPolicy.kt` 和 CLI。截图建议使用带元数据的 `capture`。手机只接受当前连接上的未过期命令，桥接仅允许一条在途；失败、超时、断线可能意味着结果未知，必须先观察，不能自动重放写操作。

## 构建与验证

Android 使用 JDK 17、Android SDK 34、AGP 8.11.0、Gradle wrapper 8.13。发布包 applicationId 为 `work.kenger.phoneassistant`，与 1.0.0 相同，升级需使用同一签名。Debug 包不要覆盖已安装的 Release；测试时使用独立设备或自行配置不同 applicationId。

```bash
./gradlew :app:assembleDebug :app:testDebugUnitTest --no-daemon
python3 -m venv .venv
.venv/bin/python -m pip install -r bridge/requirements.txt
.venv/bin/python -m unittest discover -s bridge -p 'test_*.py' -v
```

Release 签名沿用上游环境变量 `DROIDRUN_KEYSTORE_PATH`、`DROIDRUN_KEYSTORE_PASSWORD`、`DROIDRUN_KEYSTORE_KEY_ALIAS`、`DROIDRUN_KEYSTORE_KEY_PASSWORD`。通过私有环境或密钥管理器提供，不写进源码，再运行 `./gradlew :app:assembleRelease :app:testDebugUnitTest` 和 `python3 scripts/package_personal_release.py`。脚本输出签名 APK、对应源码 ZIP、SHA256 和清单；源码包不含构建缓存、真实配置、私钥或手机截图。向他人分发 APK 时，同时提供对应源码和许可证。

当前发布授权不包含 GitHub `workflow` scope，因此云端 CI 尚未启用；配置作为 `.github/phone-assistant-checks.yml.example` 保留。具备相应权限后，可将其放入 `.github/workflows/` 启用 Debug 构建、Android/桥接/客户端测试；配置不持有发布签名，也不会仅因标签自动上传 Release。历史上游测试仍保留，其中非本版开放的功能测试仅验证相关代码，不代表它们可远程调用。

1.0.0 已在 vivo X200 Ultra / Android 16 验证截图、局部图片、中文输入、点击、滚动、横屏、停止控制和短时断连恢复。真实手机重启后仅手机端恢复、长期待机、多设备和全应用兼容仍未完整验收。1.1.0 的新增流程应以该版本实际测试记录为准，不能用旧版真机结果替代。
