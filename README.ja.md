# Echo（エコー）

**ローカルで完結する、すぐに使えるリアルタイム音声 AI アシスタント** —— 全二重音声チャット、TTS、ボイスクローン、リアルタイム文字起こしをひとつのアプリで。

[English](README_EN.md) | [简体中文](README.md) | 日本語

---

## これは何？

Echo は**エンドユーザー向け**の音声 AI デスクトップアプリです（FastAPI + React、ブラウザまたはデスクトップウィンドウで動作）。

GitHub の [LiveKit Agents](https://github.com/livekit/agents)、[Pipecat](https://github.com/pipecat-ai/pipecat)、[TEN Framework](https://github.com/TEN-framework/ten-framework) も優れていますが、これらは**開発者向けフレームワーク**です。積み木が渡されて、Agent や連携、UI は自分でコードを書いて組み立てる必要があります。

**Echo は完成品**です。ダウンロードして、API キーを貼り付けて、話し始めるだけ。さらに中国国内の音声サービス（通義 Qwen-Omni、豆包（Doubao）全二重、小米（Xiaomi）、MiniMax など）にネイティブ対応しており、これは上記フレームワークがほとんどカバーしていない領域です。

## 機能

### 🎙️ リアルタイム全二重音声チャット
- 話しながら聞けて、いつでも割り込み（barge-in）可能。VAD 無音検出 + スマートな割り込み判定
- プロバイダー：OpenAI Realtime · Google Gemini Live · 通義 Qwen-Omni / Qwen-Audio · 豆包全二重 · GLM-4 Voice · Cartesia · Gradium · PersonaPlex（ローカル英語スピーキング練習）
- 音声ツール呼び出し、EverMem 長期記憶、セッション設定のホットリロード

### 🔊 TTS（13 エンジン）
Edge TTS · Qwen TTS · MiniMax · OpenAI · ElevenLabs · ChatTTS · GPT-SoVITS · Xiaomi · Azure · Doubao · Cartesia · Gradium · Soniox —— コンテンツハッシュキャッシュにより、同じテキストは二度合成されません

### 🧬 ボイスセンター
ボイスデザイン（text-to-voice）、ボイスクローン（サンプルをアップロードするだけ）

### 📝 文字起こし
- 長時間音声/動画の文字起こし：ffmpeg による自動分割、動画からの音声トラック自動抽出で、単一ファイルの長さ制限なし
- リアルタイムマイク文字起こし（Qwen-Audio-3.0-ASR-Flash-Streaming / Fun-ASR-Realtime）
- 同期字幕プレーヤー、SRT/VTT エクスポート、一括管理、ワンクリックで記憶へ保存

### 🎧 その他
ポッドキャスト/複数話者対話生成 · 翻訳（リアルタイム双方向通訳を含む）· AI チャット（DeepSeek / OpenRouter / Groq / SiliconFlow / Google Gemini / 通義 Qwen / Ollama、カスタムプロバイダー対応）· PDF の読み上げと推敲 · Tavus によるリアルタイム映像ペルソナ対話

## クイックスタート

**必要環境**：Python 3.10+ · Node.js 20+（Vite 7 の要件は ≥ 20.19）· ffmpeg（音声処理）

```bash
# Windows ワンクリック起動（バックエンド + フロントエンド開発サーバー）
run_web.bat

# デスクトップモード（フロントエンドをビルド + pywebview ウィンドウ）
run_web_desktop.bat
```

手動起動（macOS / Linux でも同じ）：

```bash
# バックエンド
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# フロントエンド（別ターミナル）
cd frontend
npm install
npm run dev
```

初回起動時に `config.json` が自動生成されます。設定ページを開いて各プロバイダーの API キーを入力してください。

デスクトップモードのトラブルシューティング：`python run_web_desktop.py --check`

### オプション機能

```bash
# ローカルオープンソース TTS（ChatTTS / GPT-SoVITS クローン文字起こし）
pip install -r backend/requirements-local-tts.txt

# PersonaPlex リアルタイム英語練習プロバイダー（モデルは別プロセスの moshi.server で動作）
pip install -r backend/requirements-personaplex.txt
```

## アーキテクチャ

```
backend/    FastAPI · 14 ルーター · サービス層（リアルタイム音声 9 プロバイダー構成 / TTS 13 エンジン振り分け / マルチプロバイダー LLM）
frontend/   React 19 + Vite + TypeScript SPA（本番環境では FastAPI が dist/ を直接ホスト）
```

- **RealtimeVoiceService**：コンポジション設計。割り込み判定・ターン確定・ツールイベント配信を共有し、各プロバイダーはトランスポート層の差分だけを実装
- **TtsService**：エンジン振り分け + コンテンツハッシュキャッシュ（アトミック書き込み + 容量ベースの自動削除）
- **ConfigLoader**：JSON 設定を mtime ベースでホットリロード

## テスト

```bash
cd backend && python -m pytest tests/ -q
cd frontend && npm run test:run
```

## FAQ

**どの API キーが必要？**
機能によります。テキストチャット + Edge TTS ならキーなしで始められます。リアルタイム音声やクローンには、選択したプロバイダーのキーが必要です。すべてローカルの `config.json` に保存されます。

**macOS / Linux で動く？**
はい。手動起動のコマンドはクロスプラットフォームで、`.bat` スクリプトは Windows 用のショートカットにすぎません。

**データは外部に送られる？**
いいえ。設定・セッション履歴・文字起こし結果はすべてローカル（SQLite + ローカルファイル）に保存されます。あなたが呼び出したクラウド API だけがリクエスト内容を見られます。

## Roadmap

- [ ] 意味ベースの発話区間・割り込み判定（SmartTurn 相当）
- [ ] リアルタイムプロバイダーの追加
- [ ] ワンクリックインストーラー

## License

[MIT](LICENSE)

---

> 名前の由来：Echo は DOTA2 の Earthshaker のアルティメット「Echo Slam（回音撃）」でもあります —— 敵が多いほど、反響は大きくなる。🎯
