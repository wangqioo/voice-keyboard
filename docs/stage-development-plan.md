# Voice Keyboard 阶段开发文档

更新时间：2026-06-17

本文记录 Voice Keyboard 当前阶段已经完成的工作、训练服务器现状、AI 指令纠错闭环状态，以及后续继续开发的优先级。

## 当前阶段结论

当前重点已经从“只搭建 AI 意图样本采集和上传能力”，推进到“Windows 客户端可用的 AI 指令纠错闭环 + 训练服务器已部署”。Windows 端现在具备从真实使用样本出发，进行本地诊断、人工纠错、本地覆盖规则、同步评测和本地模型训练的完整闭环。

需要明确的是：当前已经有本地轻量 JSON 意图模型和高阈值相似表达命中，但它还不是更强的语义分类器。现阶段正确率提升主要依赖三类机制：

- 本地硬规则和意图覆盖规则，直接减少明显误判。
- 带版本和回滚能力的本地轻量模型，减少重复 LLM 调用和常见变体误判。
- 持续收集带 `corrected_intent` 的真实样本，为后续训练语义分类器或小模型准备数据。

## 今天已完成

### Windows AI 指令纠错闭环

- Windows 主窗口已接入 AI 指令诊断入口。
- 支持按意图类型、复核状态筛选样本。
- 支持查看样本详情、预测意图、纠错结果和离线回放结果。
- 支持保存人工复核结果。
- 支持给错误样本填写 `corrected_intent`。
- 保存纠错后会写入本地覆盖规则。
- 本地意图判断会优先读取覆盖规则。
- 支持一键同步和评测。
- 未配置训练服务器时支持本地 only 模式：把本地已纠正样本同步成本地覆盖规则并立即评测。
- 已加入覆盖规则压缩，同一条文本只保留最新修正，避免覆盖文件无限增长。
- Windows UI 文案已优化为更清晰的中文展示。
- 已补充 Windows 主窗口相关测试。

### 训练服务器部署

训练服务器已部署到 4060Ti 机器，并通过 user systemd service 运行。

当前部署状态：

- 服务监听：`127.0.0.1:8010`
- 公网访问：通过 frp 暴露到 `6061`
- 服务方式：systemd user service
- 数据库：SQLite
- 鉴权：使用上传 token
- 后台页面：`/review`

真实 token 不写入仓库文档。客户端和命令行工具应继续通过本地配置、环境变量或安全的密钥管理方式注入 token。

### 训练服务端能力

- `training_server/` FastAPI 服务端模块已存在。
- 支持 JSONL 样本批量上传。
- 支持样本列表查询。
- 支持样本人工标注。
- 支持保存 `corrected_intent`。
- SQLite 支持 `corrected_intent_json` 自动迁移。
- 支持 `/v1/intent-samples/corrections` 拉取已纠正样本。
- 统计接口支持 `corrected_total` 和 `by_corrected_type`。
- 支持 token 鉴权。
- 内置 `/review` 网页标注后台。
- 支持高频短语聚合。
- 支持按相同文本批量复核并写入 `corrected_intent`。

## 当前如何使用

### Windows 本地闭环

常用流程：

1. 正常使用语音输入和 AI 指令。
2. 打开主窗口的 AI 指令诊断页面。
3. 过滤最近样本，找到判断错误的指令。
4. 填写复核结果和正确意图。
5. 保存反馈。
6. 点击同步评测。
7. 查看回放命中率和错例。

如果没有配置训练服务器，同步评测会走本地 only 模式：把本地样本里的 `corrected_intent` 同步成本地覆盖规则，然后立即做离线评测。

如果配置了训练服务器，同步评测会走远端闭环：上传本地样本，拉取远端已纠正样本，写入本地覆盖规则，然后离线评测。

### 客户端配置

客户端设置页支持配置：

- `instruction_mode.intent_training.server`
- `instruction_mode.intent_training.token`

未配置时，会回退读取环境变量。不要把真实 token 写进仓库。

### CLI 工具

离线评测本地样本：

```bash
.venv/bin/python tools/evaluate_intent_samples.py
```

生成去重后的固定评测集：

```bash
.venv/bin/python tools/evaluate_intent_samples.py \
  --dataset-output tmp/intent-eval-dataset.jsonl
```

生成版本化评测报告：

```bash
.venv/bin/python tools/evaluate_intent_samples.py \
  --report-dir tmp/intent-eval-reports \
  --version baseline
```

只把本地已纠正样本同步成本地覆盖规则：

```bash
.venv/bin/python tools/sync_intent_corrections.py --local-only
```

从训练服务器拉取已纠正样本并同步成本地覆盖规则：

```bash
.venv/bin/python tools/sync_intent_corrections.py --server http://SERVER:8000 --token change-me
```

执行完整闭环：

```bash
.venv/bin/python tools/run_intent_training_loop.py --server http://SERVER:8000 --token change-me
```

训练本地轻量意图模型：

```bash
.venv/bin/python tools/train_intent_model.py \
  --input ~/.voice-keyboard/intent_samples.jsonl \
  --output ~/.voice-keyboard/intent_models/current.json \
  --registry-dir ~/.voice-keyboard/intent_models \
  --version baseline
```

管理本地模型版本：

```bash
.venv/bin/python tools/manage_intent_model.py --registry-dir ~/.voice-keyboard/intent_models list
.venv/bin/python tools/manage_intent_model.py --registry-dir ~/.voice-keyboard/intent_models rollback
```

### 训练服务器

安装服务端依赖：

```bash
pip install -r requirements-server.txt
```

启动服务：

```bash
export INTENT_TRAINING_DATABASE_URL="sqlite:///./intent_training.db"
export INTENT_TRAINING_UPLOAD_TOKEN="change-me"
uvicorn training_server.api:app --host 0.0.0.0 --port 8000
```

上传本地样本：

```bash
.venv/bin/python tools/upload_intent_samples.py --server http://SERVER:8000 --token change-me
```

只检查本地样本数量，不上传：

```bash
.venv/bin/python tools/upload_intent_samples.py --dry-run
```

打开网页标注后台：

```text
http://SERVER:8000/review
```

使用 `INTENT_TRAINING_UPLOAD_TOKEN` 作为页面 Token。

## 数据训练闭环

当前已经完成的即时闭环：

1. 用户正常使用客户端。
2. 客户端记录意图判断样本。
3. 用户在诊断页复核样本。
4. 用户给错误样本填写正确意图。
5. 本地写入 `corrected_intent`。
6. 同步工具把已纠正样本写入本地覆盖规则。
7. 客户端下次判断时优先使用本地覆盖规则。
8. 离线评测工具回放已纠正样本。
9. 诊断页展示命中率和错例。
10. 同步时压缩覆盖规则，只保留每条文本最新修正。

远端服务闭环：

1. 客户端或工具上传样本。
2. 训练服务器保存样本。
3. 用户或开发者标注样本并填写 `corrected_intent`。
4. 客户端或工具拉取已纠正样本。
5. 本地同步成覆盖规则。
6. 本地离线回放评测。

模型增强闭环已经具备基础设施：

1. 积累真实纠正样本。
2. 维护固定评测集和版本化评测报告。
3. 训练本地轻量 JSON 模型。
4. 输出模型版本和评估报告。
5. 通过 `current.json` 激活当前模型。
6. 支持回滚到上一版本。
7. 用户继续纠错，样本继续回流。

### Memo Library Intent Reliability

- Memo 保存已收紧为必须依赖 Explicit Selection；选中文本作为 value，语音只用于提炼 key。
- `instruction_mode.intent_fallbacks.memo_triggers` 已支持配置保存、查询、唤醒和删除触发词。
- Windows 主窗口 Memo Library 页已加入触发词配置入口，并可保存后刷新运行时配置。
- Memo Store 已支持已有实例感知外部文件变化，主窗口可轮询刷新记忆库列表。
- AIHandler 已加入保存兜底：有 Explicit Selection 且语音像 memo-save 时，即使分类器返回 chat，也会转成 `memo_save`。
- Memo 查询已支持 `查一下我的手机号`、`查一下我家地址`、`调出我的地址` 这类不带“记忆库/备忘录”的自然说法。
- 已避免 `查找` 这类精确 Shortcut Catalog 动作被 memo 查询触发词误伤。
- 状态栏/HUD 保持原语音转文字的小胶囊样式；AI 指令期间显示“我听到 + 进展/结果”，避免进展提示覆盖识别文本，指令结束后按最终提示计时隐藏。
### Intent Accuracy Guard And Reporting

- 已加入 baseline/candidate 评测报告对比 helper，输出准确率、正确数、错误数和错例数量差异，并标记 candidate 是否回退。
- 训练闭环结果已包含 `model_activation` 决策。
- `tools/run_intent_training_loop.py` 现在先注册 candidate 模型版本，再使用 candidate 版本路径生成评测报告；只有 candidate 不低于 baseline 时才激活为 `current.json`。
- 如果没有提供 `--model-report-dir`，训练闭环会保留 candidate 版本但不会激活，避免未评测模型覆盖当前模型。
- Mac 主窗口意图诊断页的模型状态会显示最新模型评测准确率和错例数。
- 训练服务 review 页面已增加 Export Evaluation Dataset、Model Reports、Sync Status 三个静态入口。
- Windows 当前无 Bash，`scripts/test-local.sh` 未直接执行；等价验证已用 unittest 全量、compileall 和 `git diff --check` 完成。

### Memo Metadata And Local Risk Policy

- Memo Store 已支持旧版 flat JSON 和新版 record JSON；`get/save/delete/keys` 保持兼容。
- 新保存的 Memo 会写成 `{value, aliases, value_type, sensitive}` record 形态，并保留已有别名和 metadata。
- Memo resolver 会优先使用 record 上显式保存的 `value_type`，再回退到 key/value 推断。
- `ai_intent.memo_records()` 会优先读取 store 的 `records()`，旧 store 仍可通过 `keys/get` 回退。
- 已新增本地高风险操作策略模块：普通 Shortcut Invocation 直接执行，高风险单操作需要确认，高风险操作在 Atomic Operation Stack 中 fail closed。
- Instruction Mode executor 现在记录 `operation_risk`、`confirmation_triggered`、`user_cancelled`，训练样本也会写入这些字段。
- Windows runtime 已接入高风险操作确认 adapter，通过原生确认弹窗执行；无确认 adapter 的运行路径继续 fail closed。

## 仍未完成

- 服务器端尚未真正训练语义分类器或小模型。
- 服务器端尚未形成模型版本发布机制。
- 客户端尚未实现从服务器拉取发布模型。
- 评测集规模还不足，需要真实样本继续积累。
- 高风险操作确认策略还需要在真实 Windows 使用中验证，并继续和模型置信度、误触发指标关联。
- Memo alias metadata 已有存储层，主窗口暂未提供 alias 编辑入口。

## 后续优先级

### P0：积累真实样本

- 用真实日常指令持续采集样本。
- 优先补充高频误判的 `corrected_intent`。
- 至少积累 50 条已纠正样本后，再判断模型训练收益。
- 记录每次模型版本、覆盖规则版本和评测报告路径。

### P1：固定评测集和模型激活保护

- 生成固定评测集，比较 `baseline`、`model-exact`、`model-0.8`。
- 训练新版本后自动生成 baseline/candidate 对比摘要。
- 如果新模型准确率低于当前 baseline，训练闭环会标记 `model_activation.should_activate=false`，并保持当前 `current.json` 不变。
- 如果错例数量增加，提示人工检查。
- 在 UI 显示最新模型报告准确率和错例数量；报告路径由 helper 返回，后续可在 UI 展开显示。
- 保留一键回滚入口。

### P2：服务器端模型训练和发布

- 在 4060Ti 服务器上训练真正的语义分类器或小模型。
- 服务端保存模型版本、训练数据版本和评测报告。
- 只发布通过评测 guard 的 candidate。
- 客户端按版本拉取已发布模型。
- 客户端保留本地回滚能力。

### P3：增强网页标注后台

- 展示最近一次同步状态。
- 展示纠正样本是否已被本地覆盖规则吸收。
- 增加导出评测集入口。
- 增加模型评测报告入口。
- 按语义相似度聚合同类表达，而不只是相同文本。

### P4：高风险操作策略

- 发送、删除、关闭窗口、提交表单等操作继续保留确认策略。
- 本地模型命中但属于高风险操作时，不直接绕过确认。
- 样本已开始记录是否触发确认、用户是否取消。
- 下一步把“误触发高风险操作”作为单独评测指标，并在诊断页展示。

## 关键风险

### 样本质量

如果没有人工标注，只靠自动采集，很难训练出可靠模型。后续必须持续做标注和纠错。

### 过拟合到单句覆盖

当前覆盖规则能快速修正重复误判，但它更接近“纠错记忆”，不是泛化模型。后续要靠训练集和评测集解决泛化问题。

### 企业电脑限制

当前电脑无法运行未授信 EXE，因此后续 Windows 测试和发布要区分：

- 源码启动。
- 本地开发构建。
- 企业可信发布。
- GitHub 发布产物。

### API-Key 安全

仓库不能提交真实 API-Key 或训练服务器 token。后续所有密钥都应通过环境变量、本地配置文件或企业密钥管理系统注入。

### 高风险操作

发送、删除、关闭窗口、提交表单等操作需要持续保留风险策略。不能因为本地模型判断更快，就直接跳过确认。

## 建议下一步

1. 在 Windows 上继续真实使用，积累至少 50 条已纠正样本。
2. 用固定评测集比较 baseline 和候选模型。
3. 在 Windows 上真实验证高风险确认弹窗，确认 `发送/提交/关闭/删除` 类操作不会误触发。
4. 给 Memo Library 增加 alias 编辑入口。
5. 在服务器上做第一版语义分类器或小模型训练实验。
6. 建立服务端模型版本发布接口。
7. 让客户端拉取服务器发布模型，并保留本地回滚。
8. 把高风险操作确认策略纳入评测指标。

## 当前仓库状态备注

截至 2026-06-17，模型激活 guard、Memo metadata、本地高风险策略和 Windows 高风险确认 adapter 已提交到本地 `main`，尚未推送远端。

已验证：

- `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_ai_intent.py" -v`
- `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_intent_evaluation.py" -v`
- `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_ai_handler_runtime.py" -v`
- `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_windows_main_window.py" -v`
- `.\.venv\Scripts\python.exe -m unittest discover -s test -p "test_runtime_composition.py" -v`
- `.\.venv\Scripts\python.exe -m unittest discover -s test -v`：342 tests, 5 skipped
- `.\.venv\Scripts\python.exe -m compileall -q agent test training_server tools`
- `git diff --check`
- `/Users/wq/voice-keyboard/.venv/bin/python -m unittest discover -s test -p "test_intent_loop.py" -v`
- `/Users/wq/voice-keyboard/.venv/bin/python -m unittest discover -s test -p "test_memo_store.py" -v`
- `/Users/wq/voice-keyboard/.venv/bin/python -m unittest discover -s test -p "test_instruction_executor.py" -v`
- `/Users/wq/voice-keyboard/.venv/bin/python -m unittest discover -s test -p "test_operation_confirmation.py" -v`
- `/Users/wq/voice-keyboard/.venv/bin/python -m unittest discover -s test -p "test_runtime_composition.py" -v`
- `/Users/wq/voice-keyboard/.venv/bin/python -m unittest discover -s test -p "test_ai_handler_runtime.py" -v`
- `/Users/wq/voice-keyboard/.venv/bin/python -m compileall -q agent training_server tools test`
- `git diff --check`

Windows 当前没有 Bash，因此 `test_run_local_script.py` 的 shell 脚本执行测试会跳过；在 Git Bash、WSL、macOS 或 Linux 环境下仍会实际运行。
