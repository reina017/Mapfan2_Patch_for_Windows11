# GitHubでの公開手順

このフォルダーだけをGitHubのリポジトリにします。親の作業フォルダーや旧試作ZIPは公開対象にしません。

## 公開前

1. READMEの対応版・必要環境・確認範囲を確認します。
2. `py -3 test_public.py` と `py -3 test_uninstall.py` を実行します。
3. `py -3 build_release.py` で、ランチャー・アンインストーラー同梱ZIPと単独アンインストーラーZIPを作ります。
4. 手元のCDによる統合テスト: `py -3 test_public.py --media D:\`。このテストは一時フォルダーへ導入してアンインストールまで実行し、実ユーザーのINI・レジストリは変更しません。
5. `py -3 build_release.py --audit` を実行し、Gitの追跡対象も確認します。
6. 別PCと物理CDで試験できるまでは、GitHub Releaseを **pre-release** として公開することを推奨します。

## ソースを登録

GitHub上で空のリポジトリを作成します。名前の例は `mapfan2-win11-patch`。
このフォルダー内で初回に実行するコマンド例（URLは自分の公開先に置き換えます）:

```bat
git init -b main
git add .
py -3 build_release.py --audit
git diff --cached --stat
git commit -m "Prepare patch-only beta release"
git remote add origin https://github.com/YOUR_ACCOUNT/mapfan2-win11-patch.git
git push -u origin main
git tag v1.1.0-beta.5
git push origin v1.1.0-beta.5
```

親フォルダーのISO、media、unpacked、_test、元DLL、地図データを追加しないでください。
`.gitignore` だけでなくビルド時の許可リストでも確認します。

## Releaseに添付

GitHubのReleasesで `v1.1.0-beta.5` のpre-releaseを作成し、`dist` 内の以下を添付します。

- `mapfan2-win11-patch-1.1.0-beta.5.zip`
- `mapfan2-win11-patch-1.1.0-beta.5.zip.sha256`
- `mapfan2-win11-uninstaller-1.1.0-beta.5.zip`
- `mapfan2-win11-uninstaller-1.1.0-beta.5.zip.sha256`

このZIPには、独自コード・ランチャー・ライセンス表記とハッシュ一覧のみが入ります。
単独アンインストーラーZIPには独自コード・説明書・ライセンスだけを入れます。旧版への追加と保守モードの制限はUNINSTALL.mdに記載しています。
GitHubが自動生成するSource code ZIPにはビルド済みランチャーが入らないため、利用者には上記の配布ZIPを案内します。

案内文の例:

> MapFan II for Windows 95（1996年7月版）のCD-ROM所有者向け非公式Windows 11互換パッチです。製品本体・地図・付属DLLは含みません。CDから利用者のPC内で必要なファイルを展開し、互換パッチを適用します。Python 3.11以降が必要です。確認済み機能と未検証事項はREADMEをご覧ください。

GitHub側へのリポジトリ作成・push・Release公開は、このフォルダーの準備だけでは実行されません。
