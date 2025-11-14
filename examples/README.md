# ProcessAudioTap サンプル集

ProcessAudioTapライブラリの使用例を提供するディレクトリです。

## 概要

このディレクトリには、ProcessAudioTapを使用したプロセス別音声キャプチャの実例が含まれています。各サンプルは、ライブラリの機能を実際に使用する方法を示しています。

## システム要件

- **OS**: Windows 10 (20H1以降) または Windows 11
- **Python**: 3.10以上
- **権限**: 管理者権限は不要

## 必要なライブラリ

### 必須

1. **ProcessAudioTap** (このパッケージ)
   - プロセス別音声キャプチャのコア機能
   - ソースからビルドする必要があります

2. **psutil**
   - プロセス名からPIDを検索するために使用
   - `pip install psutil` でインストール

### 標準ライブラリ (インストール不要)

- `wave`: WAVファイルの作成と書き込み
- `argparse`: コマンドライン引数の解析
- `sys`: システム操作

## インストール手順

### 1. ProcessAudioTapをビルド・インストール

リポジトリのルートディレクトリで実行:

```bash
# 開発モードでインストール (C++拡張をビルド)
pip install -e .

# または、開発用依存関係も含めてインストール
pip install -e ".[dev]"
```

**注意**: Visual Studio Build ToolsとWindows SDKが必要です。

### 2. psutilをインストール

```bash
pip install psutil
```

### 3. インストールの確認

```bash
python -c "from processaudiotap import ProcessAudioTap; print('インストール成功!')"
python -c "import psutil; print('psutilインストール成功!')"
```

---

## サンプル: record_proc_to_wav.py

### 説明

特定のプロセスから音声をキャプチャしてWAVファイルに保存するサンプルです。プロセスIDまたはプロセス名を指定して、そのプロセスが出力している音声を録音できます。

### 機能

- プロセスID (`--pid`) またはプロセス名 (`--name`) で対象プロセスを指定
- キャプチャした音声をWAVファイルに保存
- Enterキーまたは Ctrl+C で録音停止
- 44.1kHz、ステレオ、16ビットPCM形式で録音

### 使用方法

#### 基本構文

```bash
python examples/record_proc_to_wav.py [--pid PID | --name PROCESS_NAME] [--output OUTPUT_FILE]
```

#### オプション

| オプション | 型 | 必須 | 説明 |
|-----------|-----|------|------|
| `--pid` | 整数 | はい* | キャプチャするプロセスのID |
| `--name` | 文字列 | はい* | キャプチャするプロセスの名前 (例: "VRChat.exe" または "VRChat") |
| `--output` | 文字列 | いいえ | 出力WAVファイルのパス (デフォルト: "output.wav") |

\* `--pid` または `--name` のいずれか一方が必須です。

### 実行例

#### 1. プロセス名で録音 (推奨)

```bash
# VRChatの音声を録音
python examples/record_proc_to_wav.py --name "VRChat.exe" --output vrchat_audio.wav

# Discordの音声を録音 (.exe拡張子なしでも可)
python examples/record_proc_to_wav.py --name "Discord" --output discord_audio.wav

# デフォルトの出力ファイル名 (output.wav)
python examples/record_proc_to_wav.py --name "spotify.exe"
```

#### 2. プロセスIDで録音

```bash
# PID 1234のプロセスから録音
python examples/record_proc_to_wav.py --pid 1234 --output audio.wav
```

### プロセスIDの確認方法

#### 方法1: タスクマネージャー

1. `Ctrl + Shift + Esc` でタスクマネージャーを開く
2. 「詳細」タブをクリック
3. 「PID」列で対象プロセスのIDを確認

#### 方法2: tasklistコマンド

```bash
# すべてのプロセスを表示
tasklist

# 特定のプロセス名で検索
tasklist | findstr "VRChat"
```

#### 方法3: プロセス名を使用 (最も簡単)

`--name` オプションを使えば、PIDを調べる必要はありません。

### 出力ファイル形式

録音されたWAVファイルの仕様:

- **フォーマット**: WAV (PCM)
- **サンプルレート**: 44,100 Hz (CD品質)
- **チャンネル数**: 2 (ステレオ)
- **ビット深度**: 16-bit
- **エンコーディング**: リニアPCM

### 録音の停止

録音を停止するには:

- **Enterキーを押す**、または
- **Ctrl + C** を押す

録音が停止すると、WAVファイルが保存されます。

---

## トラブルシューティング

### エラー: `ModuleNotFoundError: No module named 'processaudiotap'`

**原因**: ProcessAudioTapがインストールされていません。

**解決策**:
```bash
cd /path/to/ProcessAudioTap
pip install -e .
```

### エラー: `ModuleNotFoundError: No module named 'psutil'`

**原因**: psutilがインストールされていません。

**解決策**:
```bash
pip install psutil
```

### エラー: `Process 'ProcessName' not found`

**原因**: 指定したプロセス名が実行されていません。

**解決策**:
1. プロセス名が正しいか確認
2. アプリケーションが実行中か確認
3. `tasklist` コマンドで正確なプロセス名を確認

### エラー: `ImportError: Native extension (_native) could not be imported`

**原因**: C++拡張がビルドされていません。

**解決策**:
```bash
# C++拡張を再ビルド
pip install -e . --force-reinstall --no-deps
```

**注意**: ProcessAudioTapはネイティブC++拡張が必須です。Visual Studio Build ToolsとWindows SDKがインストールされていることを確認してください。

### 音声がキャプチャされない

**確認事項**:
1. 対象プロセスが実際に音声を再生しているか
2. Windows 10が20H1以降であるか (`winver` コマンドで確認)
3. プロセスIDまたは名前が正しいか

---

## 追加情報

### 対応する音声アプリケーション例

- ゲーム: VRChat、Discord、ゲーム全般
- メディアプレーヤー: Spotify、foobar2000、MusicBee
- 通信アプリ: Discord、Zoom、Teams
- ブラウザ: Chrome、Firefox、Edge (各タブごとのプロセス)

### プロセス別キャプチャの利点

- システム全体ではなく、特定のアプリケーションの音声のみをキャプチャ
- 複数のアプリケーションが音声を再生していても、目的のものだけを録音可能
- 管理者権限不要

### 制限事項

- **Windows専用**: macOSやLinuxでは動作しません
- **Windows 10 20H1以降**: プロセス別キャプチャには新しいWASAPI機能が必要
- **Python 3.10以降**: 型ヒントの機能を使用しているため

---

## サポート

- **バグ報告**: [GitHub Issues](https://github.com/m96-chan/ProcessAudioTap/issues)
- **ドキュメント**: プロジェクトルートの [README.md](../README.md)
- **API詳細**: [CLAUDE.md](../CLAUDE.md)
