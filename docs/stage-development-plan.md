# Voice Keyboard 阶段性开发文档

更新时间：2026-06-09

本文档用于记录 Voice Keyboard 当前阶段已经完成的工作、现在的使用方式、AI 意图训练闭环的状态，以及后续继续开发的路线。

## 当前阶段结论

当前开发方向已经从先做 Windows 转为 Mac 优先。Windows 端之前已经完成了客户端核心体验、托盘和主窗口配置入口、AI 意图诊断反馈、训练服务基础框架；本阶段新增重点是 Mac 本地可用的 AI 意图纠错闭环。

现在已经完成的是“真实使用样本 -> 本地诊断 -> 人工纠错 -> 本地覆盖规则 -> 离线回放评测 -> 本地/远端同步 -> 覆盖规则压缩 -> 本地模型训练 -> 模型评测 -> 版本回滚”的 Mac 本地闭环。这个闭环能立刻提升常见错误指令的正确率，因为用户纠正过的同一句或同类文本会优先走本地覆盖规则；同时可以把已纠正样本训练成本地轻量模型，并用固定评测报告观察效果。

需要明确的是：当前已经有本地轻量 JSON 意图模型和高阈值相似表达命中，但还不是更强的语义分类模型。现阶段提升正确率靠三类机制：

- 本地硬规则和意图覆盖规则，直接减少明显错判。
- 带版本和回滚能力的本地轻量模型，减少重复 LLM 调用和常见变体误判。
- 收集带 `corrected_intent` 的真实样本，为后续训练语义分类器或小模型准备数据。

## 已完成的主要能力

### Windows 客户端

- 支持语音转文字。
- 支持原文模式和微润色模式。
- 支持 AI 指令模式。
- 支持托盘菜单。
- 支持中文/英文界面切换。
- 支持托盘菜单语言随界面语言切换。
- 支持主窗口配置。
- 支持历史记录、记忆库、快捷键等配置入口。
- 支持开机自启动注册和取消。
- 支持托盘提示框反馈操作结果。
- 支持语音转文字热键和 AI 功能热键配置。

### Mac 本地运行基础

- 修复了源码方式运行时的权限检查稳定性。
- 麦克风权限请求改为更稳的 `sd.RawInputStream(... dtype="int16")`。
- Input Monitoring 权限请求后会重新检查状态。
- 源码运行时避免不必要的 AppKit 激活，减少权限提示异常。
- `scripts/run-local.sh` 改为更适合本地调试的非缓冲日志和进程匹配方式。

### AI 意图识别和反馈

- AI 指令会先经过本地快速判断。
- 对明确的本地快捷键、文本操作、记忆库操作等，优先走本地逻辑。
- 本地无法确定时，再进入 LLM 判断。
- AI 处理过程中会显示更细的状态，而不是只显示“AI 处理中”。
- 已加入意图诊断信息，便于后续分析判断是否正确。
- 已加入本地意图样本收集，为后续训练做准备。

### Mac AI 意图诊断闭环

- Mac 主窗口新增“意图诊断”入口。
- 支持按意图类型筛选样本。
- 支持按是否已复核筛选样本。
- 支持保存样本复核结果。
- 支持给错误样本填写 `corrected_intent`。
- 支持纠正为快捷键、删除、记忆库保存、记忆库读取、聊天等意图。
- 保存纠正后会写入本地覆盖规则。
- 本地覆盖规则默认保存到 `~/.voice-keyboard/intent_overrides.jsonl`。
- 本地意图判断会优先读取覆盖规则。
- 覆盖规则会校验快捷键、记忆库等能力是否存在，避免写入明显无效的修正。
- 诊断页显示总样本数、已复核数、正确数、错误数、已纠正数、覆盖命中数。
- 诊断页显示错误意图分布。
- 诊断页显示离线回放命中率。
- 诊断页支持查看错例详情。
- 诊断页支持一键同步和评测。
- 未配置训练服务器时，也支持本地-only 同步：直接把本地 `corrected_intent` 样本转成本地覆盖规则。
- 同步时会压缩覆盖规则，同一条文本只保留最新修正，避免覆盖文件无限重复增长。

### 训练闭环基础设施

- 新增 `training_server/` 服务端模块。
- 新增 FastAPI API。
- 新增 SQLite 存储，适合开发阶段和小规模部署。
- 支持 JSONL 样本批量上传。
- 支持样本列表查询。
- 支持样本人工标注。
- 支持保存 `corrected_intent`。
- 服务端 SQLite 支持 `corrected_intent_json` 自动迁移。
- 支持 `/v1/intent-samples/corrections` 拉取已纠正样本。
- 统计接口支持 `corrected_total` 和 `by_corrected_type`。
- 支持 token 鉴权。
- 支持内置 `/review` 网页标注后台。
- 支持高频短语聚合。
- 支持按相同文本批量复核和写入 `corrected_intent`。
- 新增 `tools/upload_intent_samples.py` 上传工具。
- 新增 `tools/evaluate_intent_samples.py` 离线评测工具。
- 支持从已纠正样本生成去重固定评测集。
- 支持输出版本化 JSON 评测报告。
- 支持训练本地轻量意图模型 JSON。
- 支持客户端在 LLM 之前使用本地意图模型精确命中。
- 支持可配置的高阈值相似表达命中，默认仍为精确命中。
- 支持离线评测报告接入本地意图模型和相似阈值，便于比较 `baseline` 与模型版本。
- 支持本地意图模型版本 registry、版本列表、激活指定版本和回滚上一版本。
- 一键训练闭环支持同步纠错后训练模型版本，并写出对应模型评测报告。
- Mac 意图诊断页支持查看当前模型版本、训练模型并回滚到上一版本。
- 新增 `tools/sync_intent_corrections.py` 纠错同步工具。
- 新增 `tools/run_intent_training_loop.py` 一键训练闭环工具。
- 新增 `docs/intent-training-server.md` 服务端使用说明。
- 新增相关单元测试。

## 当前如何使用

### Mac 本地闭环

当前 Mac 开发阶段优先使用源码方式运行。

常用流程：

1. 正常使用语音输入和 AI 指令。
2. 打开主窗口的“意图诊断”。
3. 过滤最近样本，找到判断错误的指令。
4. 填写复核结果和正确意图。
5. 保存反馈。
6. 点击“同步评测”。
7. 查看回放命中率和错例。

如果没有配置训练服务器，“同步评测”会走本地-only 模式：把本地样本里的 `corrected_intent` 同步成本地覆盖规则，然后立即做离线评测。

如果配置了训练服务器，“同步评测”会走远端闭环：上传本地样本，拉取远端已纠正样本，写入本地覆盖规则，然后离线评测。

### Mac 训练服务器配置

Mac 主窗口设置页支持配置：

- `instruction_mode.intent_training.server`
- `instruction_mode.intent_training.token`

未配置时，会回退读取环境变量。

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

执行完整闭环并训练/评测一个本地模型版本：

```bash
.venv/bin/python tools/run_intent_training_loop.py \
  --server http://SERVER:8000 \
  --token change-me \
  --model-registry-dir ~/.voice-keyboard/intent_models \
  --model-version model-0.8 \
  --model-report-dir ~/.voice-keyboard/intent_eval_reports \
  --model-min-similarity 0.8
```

### 训练服务

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

使用 `INTENT_TRAINING_UPLOAD_TOKEN` 作为页面 Token。后台支持查看统计、筛选样本、高频短语聚合、按相同文本批量复核、保存复核标签、备注和 `corrected_intent`。

## 数据训练闭环

当前已经完成的即时闭环是：

1. 用户正常使用客户端。
2. 客户端记录意图判断样本。
3. 用户在 Mac 意图诊断页复核样本。
4. 用户给错误样本填写正确意图。
5. 本地写入 `corrected_intent`。
6. 同步工具把已纠正样本写入本地覆盖规则。
7. 客户端下次判断时优先使用本地覆盖规则。
8. 离线评测工具回放已纠正样本。
9. 诊断页展示命中率和错例。
10. 同步时压缩覆盖规则，只保留每条文本最新修正。

远端服务闭环是：

1. 客户端或工具上传样本。
2. 训练服务器保存样本。
3. 用户或开发者标注样本并填写 `corrected_intent`。
4. 客户端或工具拉取已纠正样本。
5. 本地同步成覆盖规则。
6. 本地离线回放评测。

当前模型增强闭环已经具备：

1. 积累真实纠正样本。
2. 维护固定评测集和版本化评测报告。
3. 训练本地轻量 JSON 模型。
4. 输出模型版本和评估报告。
5. 通过 `current.json` 激活当前模型。
6. 支持回滚到上一版本。
7. 用户继续纠错，样本继续回流。

后续模型增强方向是从字符相似和精确命中，升级到语义相似或小分类器；但必须先用真实样本评测证明它比当前规则和轻量模型更稳。

## 后续优先级

### P0：真实样本正确率验证

- 用真实日常指令持续采集样本。
- 继续补充高频误判的 `corrected_intent`。
- 生成固定评测集，比较 `baseline`、`model-exact`、`model-0.8`。
- 记录每次模型版本、覆盖规则版本、评测报告路径。
- 观察覆盖规则和本地模型是否真的减少重复错判。
- 验证 Mac 权限、热键、HUD、AI 指令执行在长时间使用下稳定。
- 达到可量化目标后再扩大自动执行范围。

### P1：模型评测和激活策略

当前模型可以训练、评测、激活和回滚。下一步要让激活更安全：

- 训练新版本后自动生成 baseline/model 对比摘要。
- 如果新模型准确率低于当前 baseline，不自动激活。
- 如果错例数量增加，提示需要人工检查。
- 在 Mac UI 显示最新模型报告路径、准确率、错例数量。
- 保留一键回滚入口。

### P2：增强网页标注后台

当前已经有内置 `/review` 基础网页标注后台、短语聚合和键盘快捷键。下一步建议继续增强：

- 展示最近一次同步状态。
- 展示纠正样本是否已被本地覆盖规则吸收。
- 增加导出评测集入口。
- 增加模型评测报告入口。
- 按语义相似度聚合同类表达，而不仅是相同文本。
- 查看纠正样本同步状态。

这个后台会直接决定后续训练数据质量，但在 Mac 本地-only 闭环已经可用之后，它不是阻塞项。

### P3：更强语义意图模型

当前第一版本地意图模型已经可以从 `corrected_intent` 样本生成 JSON 模型，并在 LLM 之前做精确文本命中；也支持通过 `intent_model_min_similarity` 打开保守的高阈值相似表达命中。模型可以注册成多个本地版本，并通过 `current.json` 激活或回滚。下一步目标是从字符相似增强到真正可评测、可回滚的可控泛化：

- 输入：用户语音识别后的文本、当前应用、是否有选中文本、历史上下文摘要。
- 输出：意图类型、目标对象、动作参数、置信度。
- 目标：减少 LLM 调用次数，提高常见指令的响应速度和正确率。
- 当前可先用 `0.8` 阈值验证轻微前后缀和口语变体，但必须配合固定评测集观察误命中。
- 只有在真实样本评测集上明显优于当前轻量模型时，才接入运行时。

第一版可以优先覆盖：

- 纯语音转文字。
- 微润色。
- 常用快捷键。
- 文本替换。
- 文本删除。
- 文本续写。
- 记忆库读取。
- 记忆库保存。
- 和 AI 聊天。

### P4：风险策略和高风险操作确认

客户端当前接入方式是分层判断：

1. 本地硬规则命中，直接执行。
2. 本地覆盖规则命中，直接执行或按风险策略确认。
3. 本地训练模型高置信度命中，直接执行或低风险执行。
4. 本地训练模型低置信度，进入 LLM。
5. 高风险操作需要确认。
6. 失败或用户纠正时继续记录样本。

下一步需要把风险策略和模型置信度关联起来：

- 发送、删除、关闭窗口、提交表单等操作继续保留确认策略。
- 本地模型命中但属于高风险操作时，不直接绕过确认。
- 在样本中记录是否触发确认、用户是否取消。
- 把“误触发高风险操作”作为单独评测指标。

### P5：Windows 同步实现 Mac 新能力

明天回到 Windows 时，建议把 Mac 已完成的闭环能力同步过去：

- 意图诊断 UI。
- 筛选和复核。
- `corrected_intent` 编辑。
- 本地覆盖规则。
- 同步评测。
- 查看错例。
- 训练服务器配置入口。
- 本地-only 同步。
- 覆盖规则压缩。
- 本地模型训练、评测、版本和回滚。

## 关键风险

### 样本质量

如果没有人工标注，只靠自动采集，很难训练出可靠模型。后续必须持续做标注和纠错。

### 过拟合到单句覆盖

当前覆盖规则能快速修正重复错判，但它更接近“纠错记忆”，不是泛化模型。后续要靠训练集和评测集解决泛化问题。

### 企业电脑限制

当前电脑无法运行未授信 EXE，因此后续 Windows 测试和发布要区分：

- 源码启动。
- 本地开发构建。
- 企业可信发布。
- GitHub 发布产物。

### API-Key 安全

仓库不能提交真实 API-Key。后续所有密钥都应该通过环境变量、本地配置文件或企业密钥管理系统注入。

### 高风险操作

发送、删除、关闭窗口、提交表单等操作需要持续保留风险策略。不能因为本地模型判断更快，就直接跳过确认。

## 后续开发建议顺序

建议下一阶段按这个顺序做：

1. 在 Mac 上继续真实使用，积累至少 50 条已纠正样本。
2. 用固定评测集比较 `baseline`、`model-exact`、`model-0.8`。
3. 在 Mac UI 显示最新模型报告摘要和错例数量。
4. 增加模型自动激活保护：新模型低于 baseline 时不激活。
5. 增强网页标注后台的导出评测集、同步状态和模型报告入口。
6. 如果真实样本数量足够，再做语义相似或小分类器实验。
7. 明确高风险操作确认策略和评测指标。
8. 把 Mac 闭环能力同步到 Windows。

## 当前仓库状态

当前最新提交已经推送到 GitHub `main` 分支。

最近关键提交：

- `ca0aaf9 Add Mac intent model controls`
- `25a5742 Train model in intent loop`
- `b9821bb Add intent model version rollback`
- `769a9e1 Evaluate local intent model reports`
- `33aa79a Add similar intent model matching`
- `d7322ac Add local intent model training`
- `cdba7b3 Add review console keyboard shortcuts`
- `bebde8f Add intent evaluation datasets and reports`
- `bf552de Add phrase grouping to intent review`
- `c250b6d Add intent review web console`
- `c9016a6 Update stage development plan for Mac intent loop`
- `e3122fc Compact intent overrides during sync`

这些提交把 AI 意图训练从“只有采集和上传”推进到“Mac 本地可以纠错、同步、评测、训练模型、比较模型版本并回滚”。下一步重点不是再加概念，而是用真实样本把正确率打上去，并让模型激活策略更安全。
