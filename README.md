# Echooo

一个以**用户自定义领域和明确委托权限**为核心的个人语音助手。你可以让它整理自己的信息，也可以授权它与指定的人交流；每次会话分别确定读取、披露、行动和记忆写入范围。

领域由你创建、命名、修改和删除，没有预设的“生活 / 工作 / 项目 A”分类。新工作区是空的。

## 这一版可以做什么

- 创建私人工作区，登录后管理任意领域。
- 在指定领域录入记忆或导入 TXT、Markdown、CSV、JSON、PDF、DOCX。原始资料提取为待审核建议；不会直接变成对外可用知识。
- 给记忆设置“仅本人 / 可授权披露”、交流对象限制、有效期，查看来源和版本，修订或恢复旧版本。
- 创建私人交流，或一次有明确对象、期限、目标、知识范围和写入领域的委托。
- 邀请一位参与者与 AI 助手交流。本人可实时旁听、保存私人笔记、确认新承诺、结束或撤销授权。
- 以文字或麦克风交流。外部回复完成检查后才发给浏览器和语音合成；支持打断。
- 会后查看归属到说话者的陈述、确认记录和记忆建议。编辑后新增或替换**指定写入领域**中的记忆，也可以拒绝。
- 导出工作区数据，删除领域、来源及依赖内容。撤销、资料变更和到期会使相关会话失效。

**当前定位：可运行的个人助手 MVP。** 一次委托支持一位受邀参与者和本人监督；暂未接入会议平台、电话、日历、邮箱或支付工具。“批准”表示批准向对方发送的确切表述，不执行外部交易。浏览器会明确显示对方正在与 AI 交流。

## 本地运行

要求 Python 3.11+，支持 AudioWorklet 的现代浏览器。文本演示不需要模型密钥。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
# 首次运行且没有 .env 时复制；已有配置请对照示例更新。
cp .env.mock.example .env
python -m echooo
```

打开 [本地工作区](http://127.0.0.1:8000)，创建用户名和至少 10 位密码。数据默认保存到 `data/echooo.db`，重启后保留。不要在首次设置完成前向公网开放服务。

如果包镜像缺包，可在本次安装中指定官方源：

```bash
python -m pip install --index-url https://pypi.org/simple -e '.[dev]'
```

推荐第一次体验：

1. 创建你自己的领域，例如“北极星产品研究”。
2. 录入两条记忆：一条内部安排设为“仅本人”；一条进度设为“可授权披露”，对象填“客户”。
3. 创建委托，对象填“客户”，选择领域，并**单独勾选**进度的“披露”。
4. 创建邀请，在另一个浏览器或无痕窗口打开链接并加入。本人页留作监督。
5. 询问进度与内部安排，再要求助手作出新承诺，观察披露范围与确认流程。
6. 结束会话，在“待审核”中确认、编辑或拒绝更新。

演示模式使用确定性的授权事实匹配，不代表真实模型的对话能力。麦克风在 mock STT 下不可用；“朗读回复”是可选的浏览器语音。邀请码只能兑换一次，新邀请会撤销原访客凭证。

## 接入真实语音与模型

对照 [.env.example](.env.example) 修改 `.env`，重启服务：

| 能力 | 配置 | 说明 |
| --- | --- | --- |
| 语音识别 | `STT_PROVIDER=assemblyai`，填写 `ASSEMBLYAI_API_KEY` | AssemblyAI v3 WebSocket，浏览器输入为 16 kHz 单声道 PCM16 |
| 理解与回复 | `LLM_PROVIDER=openai_compatible`，填写 URL、模型和密钥 | 流式 `/chat/completions`；需要稳定遵循 JSON 输出指令 |
| 语音播放 | `TTS_PROVIDER=browser` | 浏览器朗读，优先本地声音；设备可能使用云端语音 |
| 自托管语音合成 | `TTS_PROVIDER=cosyvoice` | 官方 FastAPI 协议；此版房间使用预设说话人，须有匹配的 SFT 模型和 speaker ID |

真实 LLM 的对外回复经过“结构化草稿 → 独立检查 → 发布”。这会增加首句延迟，是当前版本的明确取舍。所有知识筛选先在服务端完成；不把完整个人资料交给模型后再要求它保密。

无论选择哪种 STT / LLM / TTS，都不能绕过应用的授权和记忆写入层。这是 Echooo 的核心价值，语音 API 是可替换的基础服务。

- [AssemblyAI Streaming 文档](https://www.assemblyai.com/docs/streaming)
- [CosyVoice 仓库](https://github.com/FunAudioLLM/CosyVoice)
- 模型行为配置：[config/prompts.toml](config/prompts.toml)

## PostgreSQL 与部署

本地 SQLite 方便体验；部署推荐 PostgreSQL。已实现并在真实 PostgreSQL 上验证 owner 级 RLS。域与披露权限仍由应用服务层检查，不能把 RLS 理解为模型安全保证。

提供可选的本地数据库服务：在 `.env` 设置 `POSTGRES_PASSWORD`，然后执行：

```bash
docker compose up -d db
```

将 `DATABASE_URL` 改为 `postgresql+psycopg://echooo:URL_ENCODED_PASSWORD@127.0.0.1:5433/echooo` 后重启应用。SQLite 与 PostgreSQL 是不同数据源，**切换连接不会自动迁移已有资料**。

详见 [运行与部署](docs/OPERATIONS.md)。本版房间和取消任务在一个进程内协调，必须使用 **一个应用 worker**。公网访问需要 HTTPS、正确的 `PUBLIC_ORIGIN` 和 `COOKIE_SECURE=true`。

## 测试

```bash
STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser python -m pytest -q
python -m compileall -q src tests
node --check web/app.js
node --check web/voice.js
```

PostgreSQL 集成测试需要独立的 `echooo_test*` 数据库，测试会清空其中的应用表；不要指向工作数据库：

```bash
ECHO_TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST/echooo_test' \
STT_PROVIDER=mock LLM_PROVIDER=mock TTS_PROVIDER=browser \
python -m pytest tests/test_product.py -q
```

测试涵盖跨领域隔离、独立披露授权、一次性邀请、凭证与会话撤销、生成过程中撤销、私人笔记隔离、承诺确认、记忆归属与版本冲突、删除传播、STT 到已检查语音输出、打断、重启持久化及 PostgreSQL RLS。真实服务的识别率、音质与网络延迟需要使用你的服务配置进一步验收。

## 文档与方向

- [架构和信息边界](docs/ARCHITECTURE.md)
- [运行、配置、删除与备份](docs/OPERATIONS.md)
- [后续路线与验收标准](docs/ROADMAP.md)
- [实现范围和验证记录](docs/IMPLEMENTATION.md)

旧版无登录 `/ws` 语音演示、未核验文本直出和声音样本上传流程已移除。新的入口是有身份与范围检查的 `/ws/sessions/{id}`。不要把旧前端与新服务混用。
