<div align="center">
<h1>📣 kanban-home-subscribe — Hermes Kanban 主页频道自动订阅</h1>

<p>
  <img src="https://img.shields.io/badge/version-0.1.0-blue.svg" alt="version">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue.svg" alt="python">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="license">
  <img src="https://img.shields.io/badge/Hermes-Plugin-purple.svg" alt="hermes-plugin">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome">
</p>

<p>
  <b>让 <a href="https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban">Hermes Kanban</a> 上的每一张卡片，自动订阅每一已配置的 home channel。</b><br>
  无需逐卡点击 · 幂等 · 被动通知不唤醒 agent · 首次回填不重放历史
</p>

<p>
  <a href="#-解决什么问题">解决什么问题</a> ·
  <a href="#-安装">安装</a> ·
  <a href="#-工作原理">工作原理</a> ·
  <a href="#-配置">配置</a> ·
  <a href="#-开发">开发</a>
</p>
</div>

---

## 💡 解决什么问题

Hermes Kanban 有一个 dashboard 开关 **“Notify home channels”**：打开后，某张卡片到达终态
（`completed` / `blocked` / `gave_up` / `crashed` / `timed_out` …）时，会把通知发到该平台的
home channel。

问题是它是**逐卡、逐平台**的手动开关，而且还存在两处官方机制都无法覆盖的缺口：

| 机制 | 实际行为 |
|---|---|
| `kanban.auto_subscribe_on_create`（默认 `true`） | 订阅的是**发起创建的那个会话**（platform + chat_id + thread_id），**不是** home channel。而且只在持久化的 gateway/TUI 会话里生效——CLI / cron 调用直接跳过。 |
| `/kanban create` 的自动订阅 | 同样订阅**当前聊天**，且固定为 `notify+wake`（会唤醒 agent），不受 `auto_subscribe_on_create` 控制。 |
| dashboard “Notify home channels” | 行为正确，但**每张新卡都要手动点一次**。 |

仓库里没有任何 `notify_home_on_create` 之类的配置项，所以“新建卡默认订阅 home channel”无法靠改配置实现。
本插件补上这一环：**每张卡片，自动订阅每个 home channel。**

---

## 📥 安装

```bash
hermes plugins install metaone01/hermes-kanban-home-subscribe
hermes plugins enable kanban-home-subscribe
```

> 插件是 opt-in 的（`plugins.enabled` 白名单），安装后必须 `enable`。
> 插件不会申请任何 capability——它只读写 Kanban 自己的订阅表。

安装后需要**重启 gateway**，插件才会加载：

```bash
systemctl --user restart hermes-gateway     # Linux
```

首次生效时，会对每个板做一次全量回填（见下方 [工作原理](#-工作原理)）。

### 手动安装

```bash
git clone https://github.com/metaone01/hermes-kanban-home-subscribe.git
cp -r hermes-kanban-home-subscribe ~/.hermes/plugins/
hermes plugins enable kanban-home-subscribe
```

---

## ⚙️ 工作原理

插件挂在 `on_kanban_dispatch_tick` 钩子上。gateway 内嵌的 dispatcher 每
`kanban.dispatch_interval_seconds`（默认 60 秒）**逐板**触发一次，插件在每次 tick 里：

1. 取出该板上**所有非 `archived`** 的卡片；
2. 找出还没被本插件订阅过的 (卡片, 平台) 组合；
3. 用与 dashboard 开关**完全相同**的调用写入订阅行。

订阅行的形态：

```
task_id | platform | chat_id | thread_id | chat_type | delivery_mode | notifier_profile
t_xxxx  | qqbot    | <home>  |           | dm        | notify        | <active profile>
```

`hermes kanban notify-list` 会显示这些行，与手动订阅的完全一致。

### 三条关键设计

**1. 被动通知，不唤醒 agent。**
使用默认的 `notify` 投递模式：只发一条消息，不会让目标 agent 额外跑一轮。
（`/kanban create` 的自动订阅用的是 `notify+wake`，本插件刻意不这么做——
对所有卡片都唤醒 agent 会带来意料之外的 token 消耗。）

**2. 首次回填不会重放历史。**
`add_notify_sub` 会把 `last_event_id` 播种为“当前最大事件 id”，
所以插件第一次启用时，不会把每张卡的历史事件当作新通知全部推给你。

**3. 订阅一次，不再复活。**
插件在自己的 state 库（`~/.hermes/plugin-data/kanban-home-subscribe/data.db`）里记录
哪些 (board, task, platform) 是它写的，**永不重新添加**一个之后被删除的订阅。这一点很重要：

- 你在 dashboard 上**主动取消**了某张卡的通知 → 插件不会把它加回来；
- gateway notifier 在一次网络故障后，连续 12 次发送失败会**丢弃**该订阅（判定为死频道）
  → 插件也不会把它加回来，否则会对着一个死掉的聊天窗口每 60 秒空转一次。

如果某张卡归档后又回到活跃状态，插件会忘记它曾订阅过，于是重新订阅——这是符合预期的。

---

## 🔧 配置

插件设置写在 `~/.hermes/config.yaml` 的 `plugins.entries.kanban-home-subscribe.settings` 下：

```yaml
plugins:
  entries:
    kanban-home-subscribe:
      settings:
        enabled: true        # 总开关，默认 true
        max_per_tick: 500    # 每个板每次 tick 最多处理的卡片数，默认 500
        dry_run: false       # 只演练不写库，默认 false
```

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 设为 `false` 暂停本插件（不卸载）。 |
| `max_per_tick` | `500` | 每个板每次 tick 的写入上限，避免大板一次性占用 dispatcher 线程过久。上限之外的卡片会在后续 tick 里继续处理。 |
| `dry_run` | `false` | 只统计将要写入的订阅、不真正落库。适合在正式启用前评估影响面。 |

### 想先看看会写多少？

把 `dry_run` 设为 `true` 并重启 gateway，然后看日志：

```bash
grep kanban-home-subscribe ~/.hermes/logs/gateway.log
```

```
kanban-home-subscribe: board agent-unified — 191 card(s) / 191 subscription(s) [dry-run] on qqbot (state pruned 0)
```

### 依赖

- Hermes Agent（含 Kanban 功能）
- 至少一个平台配置了 home channel——通过 `/sethome` 或
  `<PLATFORM>_HOME_CHANNEL` 环境变量（如 `QQBOT_HOME_CHANNEL`）

没有配置 home channel 时，插件每个 tick 都安静地什么都不做。

### 兼容性

Hermes 后来把 Kanban 的连接与通知辅助函数拆成了独立模块
（`hermes_cli.kanban_db_connect`、`hermes_cli.kanban_db_notify`），并新增
`plugins.plugin_storage` 存放插件状态。本插件在运行时自动适配两种布局，
因此在旧版本上同样可用：缺少 `plugin_storage` 时，回退到私有的 `plugin-data/` 状态库。

实测环境：

| Hermes 版本 | 结果 |
|---|---|
| 本地 git 构建 0.21.3 | 15/15 测试通过 |
| PyPI 发布版 0.19.0（早于模块拆分） | 15/15 测试通过 |

在拆分前的版本上，订阅行没有 `delivery_mode` 列——这是 schema 差异，不是行为差异。

### 验证安装

```bash
hermes plugins list | grep kanban-home-subscribe   # 应为 enabled
grep kanban-home-subscribe ~/.hermes/logs/gateway.log
```

---

## 🧪 开发

```bash
git clone https://github.com/metaone01/hermes-kanban-home-subscribe.git
cd hermes-kanban-home-subscribe
pip install pytest hermes-agent            # hermes-agent 提供 Kanban 模块
python -m pytest tests/ -v
```

测试分两层：

- `tests/test_unit.py` —— 不依赖 Hermes：设置解析、home channel 缓存与容错。
- `tests/test_integration.py` —— 针对**临时**的 board DB 真跑一遍订阅逻辑（用
  `HERMES_KANBAN_HOME` 隔离，不碰你的真实看板），覆盖首次订阅、幂等、归档跳过、
  手动取消不复活、新卡捕获、`dry_run` 零写入、`max_per_tick` 上限等。

---

## 📄 License

[MIT](LICENSE) © 2026 metaone01
